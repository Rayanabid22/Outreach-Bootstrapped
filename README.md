# IC Bootstrapped Leads Pipeline

Finds **established, revenue-generating software companies** that are
**bootstrapped or lightly funded** — roughly $80–150k+ MRR, no round in the
last 12 months, no in-house creative team — estimates their revenue from
public proxy signals, verifies at least one social is active (X priority),
and appends qualified leads to the **Bootstrapped Leads** tab of the Google
Sheet.

This is the opposite end of the market from the funded pipeline in
[Rayanabid22/IC-Outreach](https://github.com/Rayanabid22/IC-Outreach): not
fresh raises, but quiet profitable companies. It reuses that pipeline's
architecture and shared modules (Claude client, dedup, sheet writer,
social-enrichment qualification bar) and **dedups against BOTH pipelines'
processed lists**, so the two never produce overlapping leads.

Target: 100–150 qualified per weekly run. No time-window concept — these
companies don't expire; dedup is what keeps runs fresh. The pipeline never
pads: every row has revenue confidence ≥ 60 with ≥ 2 named signals AND at
least one confirmed-active social. If only 60 qualify, the summary says 60.

## Quick start

```bash
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export SHEET_ID=<your google sheet id>

python bootstrapped_pipeline.py run
```

Optional flags:

| Flag | Effect |
|---|---|
| `--target 100` | Override the qualified-lead target (default 100) |
| `--dry-run` | Print results instead of writing to the sheet (no Google auth needed) |
| `--sources indiehackers,g2,chrome` | Run only the named sources (default: all enabled in config) |

There's also a dedup gate for manual research:

```bash
python bootstrapped_pipeline.py check "Acme" "Plausible Analytics"
```

## Google Sheets setup

**The live sheet already exists** — [IC Bootstrapped Leads](https://docs.google.com/spreadsheets/d/1CR0ZiaMhxAJDQYKMyJV_QDVwv-ygAQM8kxlIhTlLQTY/edit)
(owned by mrayanabid510@gmail.com), with the `Bootstrapped Leads` /
`Bootstrapped Processed` / `Bootstrapped Rejected` tabs and the first 22
leads loaded. `config.py` points at it by default, so every future run
appends to this same sheet — new leads land at the bottom of the Leads tab,
and the Processed tab keeps dedup in sync across machines.

To let the pipeline write to it (one-time, ~5 min), use the same
service-account pattern as the funded pipeline:

1. Google Cloud project → enable the **Google Sheets API**.
2. Create a **service account** → JSON key → save as `credentials.json` here
   (gitignored), or set `GOOGLE_CREDENTIALS_JSON` to the key's full contents.
3. Share the target sheet with the service account's email as **Editor**.
4. `export SHEET_ID=<the id between /d/ and /edit in the sheet URL>`.

The pipeline creates/maintains three tabs of its own (so it can share a
spreadsheet with the funded pipeline without colliding):

- **Bootstrapped Leads** — qualified leads, 22 columns: Date Added, Company,
  Website, Category, Region, Est. MRR Range, Revenue Confidence (0–100),
  Signals Used, Funding Status, Team Size, Source, X Handle, X Active,
  LinkedIn, Instagram, Discord, Email, Founder, Founder X, Founder LinkedIn,
  In-House Creative?, Fit Reasoning
- **Bootstrapped Processed** — every company ever evaluated (dedup)
- **Bootstrapped Rejected** — dropped companies with the reason logged

It also **reads** the funded pipeline's `Processed` tab (same spreadsheet by
default, or set `FUNDED_SHEET_ID`) and the funded repo's committed
`data/processed.csv` (local sibling checkout or raw GitHub URL) for
cross-pipeline dedup.

## How it works

1. **Collect** — each source sits behind a common toggleable interface:
   Indie Hackers, TinySeed / Calm Company Fund / MicroConf ecosystem,
   Chrome Web Store, Shopify App Store, WordPress plugin directory (real
   JSON API + search), Slack App Directory, G2, Capterra, Product Hunt
   archive (1–3-year-old survivors), founder revenue-bragging searches,
   and acquire.com public listings. Sources that block scraping are
   collected via Claude web search instead of raw requests; every candidate
   carries a source tag and the concrete evidence seen.
2. **Dedup** — normalized company name keyed in local SQLite (`seen.db`),
   merged with this repo's `data/processed.csv`, the funded pipeline's
   registry, and both sheets' Processed tabs. Same-day re-runs are
   idempotent; zero overlap with the funded pipeline's leads.
3. **Stage/funding + ICP + halal filter** — batched Claude calls with web
   search. Verifies: bootstrapped (no funding records found) or lightly
   funded (accelerator/angel/<$3M total, quiet 18 months); hard-excludes
   Series A+, >$5M total, any raise in the last 12 months, public
   companies, agencies, gambling, interest-based lending, alcohol/cannabis,
   adult content, dating apps, and Israeli companies; checks careers page /
   LinkedIn for in-house creative hires (several ⇒ excluded, one ⇒ kept but
   deprioritized). JSON verdict + reasoning; the hard rules are re-enforced
   in code.
4. **Revenue estimation** — one Claude call per surviving company. Gathers
   whichever proxy signals are findable — self-reported revenue (Indie
   Hackers / Starter Story / founder tweets), public install counts
   (Chrome / Shopify / WordPress / Slack), G2/Capterra/Trustpilot review
   volume × pricing-page ARPU, app-store reviews, traffic estimates,
   LinkedIn team size, product age — and outputs an MRR range plus a 0–100
   revenue-confidence score citing each signal used. **Pass bar: score ≥ 60
   AND ≥ 2 independent signals**; anything below is logged LOW CONFIDENCE
   and never counted toward the target. Nothing is ever fabricated: fewer
   signals ⇒ rejection, not padding.
5. **Social enrichment** — same module behavior as the funded pipeline: X
   handle + 30-day activity check (priority), LinkedIn URL (no activity
   check — no LinkedIn scraping, URLs only), Instagram + activity, Discord,
   email; founder name/title/personal X/LinkedIn as bonus, never blocking.
   Qualification bar: ≥ 1 confirmed-active social.
6. **Write** — qualified leads appended to `Bootstrapped Leads`; audit rows
   to `Bootstrapped Processed` / `Bootstrapped Rejected`; the committed
   registry stays in sync.
7. **Summary** — funnel counts per stage, per-source counts, average
   revenue confidence, founder-found rate, and an API cost estimate.

## Configuration

Everything editable lives in `config.py` — no code changes needed:

- `NICHES` / `EXCLUSIONS` — the ICP definition and halal gate
- `MRR_BAR`, `REVENUE_CONFIDENCE_BAR`, `MIN_REVENUE_SIGNALS`
- `INSTALL_RANGE`, `G2_REVIEW_RANGE`, `MIN_MONTHLY_TRAFFIC`,
  `TEAM_SIZE_RANGE`, `MIN_PRODUCT_AGE_YEARS`
- `MAX_LIGHT_FUNDING_USD`, `HARD_MAX_FUNDING_USD`, `NO_RAISE_MONTHS`,
  `LIGHT_FUNDING_QUIET_MONTHS`
- `SEARCH_SOURCES` — per-source `enabled` toggle and the hunting-ground
  description that drives each collection call
- `TARGET_LEADS`, batch sizes, per-stage web-search budgets
- `CLAUDE_MODEL` and pricing constants for the cost estimate
- `FUNDED_SHEET_ID` / `FUNDED_REGISTRY_PATHS` / `FUNDED_REGISTRY_URLS` —
  where the funded pipeline's processed lists live

## Operational notes

- Every Claude API response is logged to `logs/`, plus a per-run
  `logs/run_*.log` mirroring the console output.
- Raw HTTP (WordPress API, registry fetch) is rate-limited (~1–2 req/s)
  with polite delays; sources that block scraping are reached via Claude
  web search only.
- `seen.db` is the primary dedup store; delete it only if you also clear
  the `Bootstrapped Processed` tab (it re-syncs from the tabs and
  registries on each non-dry run).
- Explicit non-goals: no LinkedIn scraping (URLs only), no outreach sending
  (sheet output only), no paid data APIs.
