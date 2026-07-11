#!/usr/bin/env python3
"""IC Bootstrapped Leads Pipeline.

Usage:
    python bootstrapped_pipeline.py run [--target 100] [--dry-run] \
        [--sources indiehackers,g2,chrome]

Finds established, revenue-generating software companies that are bootstrapped
or lightly funded (~$80-150k+ MRR, no round in the last 12 months), estimates
their revenue from public proxy signals, verifies at least one social is
active (X priority), and appends qualified leads to the "Bootstrapped Leads"
tab of the Google Sheet. Dedups against BOTH this pipeline's and the funded
pipeline's processed lists — zero overlap by construction.

Companion to the funded pipeline in Rayanabid22/IC-Outreach: same output
format, sheet write pattern, dedup logic, and social qualification bar.
"""

import argparse
import os
import sys
from datetime import date, datetime
from urllib.parse import urlparse

import config
from bp_pipeline import revenue, stage_filter
from bp_pipeline.collectors import available_sources, collect
from bp_pipeline.dedup import (SeenStore, append_registry, load_funded_keys,
                               load_registry, normalize_name)
from bp_pipeline.enrich import enrich, is_qualified
from bp_pipeline.models import Lead, RunStats


class _Tee:
    """Mirror stdout into a run log file (logs/run_*.log)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)

    def flush(self):
        for s in self.streams:
            s.flush()


def _open_run_log():
    os.makedirs(config.LOG_DIR, exist_ok=True)
    path = os.path.join(
        config.LOG_DIR, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    fh = open(path, "a")
    sys.stdout = _Tee(sys.__stdout__, fh)
    print(f"[log] writing run log to {path}")
    return fh


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _domain(url: str) -> str:
    try:
        return (urlparse(url if "//" in url else f"https://{url}").netloc or "").lower()
    except ValueError:
        return ""


def run(target: int, dry_run: bool, sources: list[str] | None):
    if not config.ANTHROPIC_API_KEY:
        sys.exit("ANTHROPIC_API_KEY is not set — export it and re-run.")

    stats = RunStats()
    today = date.today().isoformat()

    # Sheet connection (skipped entirely in dry-run mode).
    writer = None
    if not dry_run:
        from bp_pipeline.sheets import SheetWriter

        writer = SheetWriter()

    # ------------------------------------------------------------------
    # Stage 2 prep — dedup store: local SQLite merged with this pipeline's
    # registry, the FUNDED pipeline's registry, and both Processed tabs.
    # ------------------------------------------------------------------
    seen = SeenStore(config.SEEN_DB)
    seen.import_keys(load_registry().keys(), "registry")
    seen.import_keys(load_funded_keys(), "funded-registry")
    if writer is not None:
        try:
            seen.import_keys(writer.load_processed_keys(), "from-sheet")
        except Exception as exc:
            print(f"[dedup] warning: could not read Processed tab: {exc}")
        try:
            seen.import_keys(writer.load_funded_processed_keys(), "funded-sheet")
        except Exception as exc:
            print(f"[dedup] warning: could not read funded Processed tab: {exc}")

    qualified: list[Lead] = []
    rejected_rows: list[list] = []
    processed_rows: list[list] = []
    processed_this_run: set[str] = set()

    # ------------------------------------------------------------------
    # Stage 1 — collect
    # ------------------------------------------------------------------
    raw = collect(sources, stats)
    stats.raw_collected = len(raw)

    # ------------------------------------------------------------------
    # Stage 2 — dedup (both pipelines)
    # ------------------------------------------------------------------
    fresh = [
        r for r in raw
        if r.dedup_key not in processed_this_run and not seen.is_seen(r.dedup_key)
    ]
    stats.after_dedup = len(fresh)
    print(f"[stage 2] {len(fresh)} candidates remain after cross-pipeline dedup")

    # ------------------------------------------------------------------
    # Stages 3-6 — filter, estimate revenue, enrich
    # ------------------------------------------------------------------
    for batch_num, batch in enumerate(_chunks(fresh, config.STAGE_BATCH_SIZE), 1):
        print(f"[stage 3] Stage/funding filter batch {batch_num} "
              f"({len(batch)} companies)...")
        results = stage_filter.filter_batch(batch, stats)

        for rec, res in zip(batch, results):
            key = rec.dedup_key
            processed_this_run.add(key)
            company = str(res.get("resolved_brand_name") or rec.company_name_raw)
            # Also block the resolved brand's key, so an alias and the real
            # name can't both get processed.
            resolved_key = normalize_name(company)
            if resolved_key and resolved_key != key:
                processed_this_run.add(resolved_key)
            website = str(res.get("website") or rec.website_hint or "")

            def mark(outcome, _k=key, _rk=resolved_key, _c=company, _d=_domain(website)):
                seen.mark(_k, _c, _d, outcome)
                if _rk and _rk != _k:
                    seen.mark(_rk, _c, _d, outcome)
                processed_rows.append([_k, _c, _d, today, outcome])

            passed, reject_reason = stage_filter.is_pass(res)
            if not passed:
                stats.rejected_stage += 1
                mark("rejected-stage")
                rejected_rows.append([today, company, rec.source, reject_reason])
                continue

            stats.stage_pass += 1
            lead = Lead(
                raw=rec,
                company=company,
                website=website,
                category=str(res.get("category") or ""),
                region=str(res.get("region") or ""),
                funding_status=str(res.get("funding_status") or ""),
                in_house_creative=str(res.get("in_house_creative") or "unknown"),
                fit_reasoning=str(res.get("reasoning_one_line") or ""),
            )

            print(f"[stage 4] Estimating revenue for {lead.company}...")
            revenue.estimate(lead, stats)
            meets, reason = revenue.meets_bar(lead)
            if not meets:
                stats.rejected_low_confidence += 1
                mark("low-confidence")
                rejected_rows.append([today, company, rec.source, reason])
                continue
            stats.revenue_pass += 1

            print(f"[stage 6] Enriching {lead.company} "
                  f"(est. {lead.mrr_range}, confidence {lead.revenue_confidence})...")
            enrich(lead, stats)

            if is_qualified(lead):
                qualified.append(lead)
                stats.qualified += 1
                stats.confidence_sum += lead.revenue_confidence
                if lead.founder_name:
                    stats.founders_found += 1
                mark("qualified")
                print(f"    -> QUALIFIED ({stats.qualified}/{target})"
                      + (f" X: @{lead.x_handle}" if lead.x_handle else ""))
            else:
                stats.rejected_no_socials += 1
                mark("no-active-socials")
                rejected_rows.append(
                    [today, company, rec.source,
                     "Passed all filters but no confirmed-active social found"])

            if stats.qualified >= target:
                break
        if stats.qualified >= target:
            break

    # Leads with one creative hire are kept but deprioritized: sort them last.
    qualified.sort(key=lambda l: l.in_house_creative.lower().startswith("one"))

    # ------------------------------------------------------------------
    # Stage 7 — write
    # ------------------------------------------------------------------
    lead_rows = [lead.to_sheet_row(today) for lead in qualified]
    if dry_run:
        print("\n[dry-run] Rows that WOULD be appended to the Bootstrapped Leads tab:")
        for row in lead_rows:
            print("  " + " | ".join(str(cell) for cell in row))
        print(f"\n[dry-run] {len(rejected_rows)} rows would go to Rejected, "
              f"{len(processed_rows)} to Processed.")
    else:
        print(f"[stage 7] Appending {len(lead_rows)} leads to the sheet...")
        writer.append_leads(lead_rows)
        writer.append_processed(processed_rows)
        writer.append_rejected(rejected_rows)
        # Keep the committed registry in sync with the sheet's Processed tab.
        append_registry([
            dict(zip(["key", "company", "domain", "date", "outcome"], row))
            for row in processed_rows
        ])

    seen.close()
    _print_summary(stats, target, len(lead_rows), dry_run)


def _print_summary(stats: RunStats, target: int, written: int, dry_run: bool):
    founder_rate = (
        f"{stats.founders_found / stats.qualified:.0%}" if stats.qualified else "n/a"
    )
    avg_conf = (
        f"{stats.confidence_sum / stats.qualified:.0f}" if stats.qualified else "n/a"
    )
    per_source = ", ".join(f"{s}: {n}" for s, n in sorted(stats.per_source.items()))
    print("\n" + "=" * 60)
    print("RUN SUMMARY")
    print("=" * 60)
    print(f"  Raw collected:            {stats.raw_collected}")
    if per_source:
        print(f"    per source:             {per_source}")
    print(f"  After dedup (both lists): {stats.after_dedup}")
    print(f"  Passed stage/ICP filter:  {stats.stage_pass}")
    print(f"  Passed revenue bar:       {stats.revenue_pass}")
    print(f"  Qualified (active social):{stats.qualified} (target was {target})")
    print(f"  Rejected (stage/ICP):     {stats.rejected_stage}")
    print(f"  Rejected (low confidence):{stats.rejected_low_confidence}")
    print(f"  Rejected (no socials):    {stats.rejected_no_socials}")
    print(f"  Written to sheet:         {written}"
          + (" (dry run — nothing written)" if dry_run else ""))
    print(f"  Avg revenue confidence:   {avg_conf}")
    print(f"  Founder found rate:       {founder_rate}")
    print(f"  API calls:                {stats.api_calls} "
          f"({stats.input_tokens:,} in / {stats.output_tokens:,} out tokens, "
          f"{stats.web_searches} web searches)")
    print(f"  Est. API cost:            ${stats.cost_estimate():.2f}")
    if stats.qualified < target:
        print(f"\n  NOTE: target of {target} not met — this segment moves "
              f"slowly; the run completed with the real count above "
              f"(no padding). Re-run next week; dedup keeps it fresh.")
    print("=" * 60)


def check_names(names: list[str]):
    """Dedup gate for candidate names (checks both pipelines' lists)."""
    seen = SeenStore(config.SEEN_DB)
    seen.import_keys(load_registry().keys(), "registry")
    seen.import_keys(load_funded_keys(), "funded-registry")
    for name in names:
        status = "SEEN" if seen.is_seen(normalize_name(name)) else "NEW"
        print(f"{status}\t{name}")
    seen.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="run the full pipeline")
    run_parser.add_argument("--target", type=int, default=config.TARGET_LEADS,
                            help=f"qualified-lead target (default {config.TARGET_LEADS})")
    run_parser.add_argument("--dry-run", action="store_true",
                            help="print results instead of writing to the sheet")
    run_parser.add_argument("--sources", type=str, default="",
                            help="comma-separated source list (default: all "
                                 f"enabled). Available: {', '.join(available_sources())}")

    check_parser = sub.add_parser("check", help="dedup-check company names")
    check_parser.add_argument("names", nargs="+", help="company names to check")

    args = parser.parse_args()

    if args.command == "run":
        log_fh = _open_run_log()
        started = datetime.now()
        sources = [s.strip() for s in args.sources.split(",") if s.strip()] or None
        try:
            run(args.target, args.dry_run, sources)
            print(f"Done in {(datetime.now() - started).total_seconds() / 60:.1f} min.")
        finally:
            sys.stdout = sys.__stdout__
            log_fh.close()
    elif args.command == "check":
        check_names(args.names)


if __name__ == "__main__":
    main()
