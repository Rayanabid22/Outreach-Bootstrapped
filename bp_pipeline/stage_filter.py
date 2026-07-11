"""Stage 3 + 5 — funding-profile, ICP, halal, and creative-team filter.

One Claude call per batch (merged into a single pass for token efficiency,
mirroring the funded pipeline's icp_filter). Outputs a JSON verdict with
reasoning per company; the code enforces the hard rules on top of the
model's verdict so nothing slips through on a soft "pass".
"""

import config
from .claude_client import call_claude, parse_json_block
from .dedup import normalize_name
from .models import RawCandidate, RunStats

_PROMPT_TEMPLATE = """You are qualifying software companies for Impact Creatives, \
a motion design studio (launch videos, product explainers, monthly content \
retainers) whose buyer is the founder. This pipeline hunts the OPPOSITE end of \
the market from funding news: quiet, profitable, established companies that \
are bootstrapped or lightly funded. For EACH company below, use web search to \
verify the facts — do not guess.

STEP A — resolve identity: confirm the real brand/product name and website. \
If you cannot confidently identify the company, verdict "reject" with \
reject_reason "could not resolve company".

STEP B — funding profile (the core filter). Search for "<company> funding", \
Crunchbase/press records, and the company's own about/blog pages.
- "bootstrapped": no institutional funding found anywhere. Absence of \
Crunchbase/press funding records after searching IS the bootstrapped signal.
- "lightly funded": accelerator-only (incl. TinySeed / Calm Company Fund), \
angel round, or total raised under ~${light_max}, AND no round in the last \
{quiet_months} months.
- "excluded": raised a Series A or beyond, OR raised more than ${hard_max} \
total, OR raised ANYTHING in the last {no_raise_months} months (the funded \
pipeline covers those), OR is a public company.

STEP C — ICP category. is_icp_fit true only if clearly one of:
{niches}

STEP D — hard exclusions. verdict "reject" with the reason if ANY apply:
{exclusions}

STEP E — in-house creative team check. Check the company's careers page and \
LinkedIn for roles like "video editor", "motion designer", "brand designer":
- "none": no such roles found
- "one": exactly one such person/role (lead is kept but deprioritized)
- "several": multiple creative hires -> verdict "reject"
- "unknown": could not check

STEP F — region: US | UK | Canada | Europe | Australia | Other. Record it; \
only reject on region if serving them is obviously impossible on timezone or \
payment grounds.

verdict is "pass" ONLY if: identity resolved AND funding_status is \
"bootstrapped" or "lightly funded" AND is_icp_fit AND no hard exclusion AND \
in_house_creative is not "several".

Companies to evaluate:
{companies}

Respond with ONLY a JSON array, one object per company, in the SAME ORDER as \
listed, using exactly this schema:
[
  {{
    "company": "<name as listed above>",
    "resolved_brand_name": "",
    "website": "",
    "verdict": "pass",
    "reject_reason": "",
    "funding_status": "bootstrapped | lightly funded (<detail>) | excluded (<detail>)",
    "raised_last_12mo": false,
    "is_icp_fit": true,
    "category": "SaaS | AI tools | Tech/Software | Fintech | Trading platform | Biotech (AI software)",
    "region": "US | UK | Canada | Europe | Australia | Other",
    "in_house_creative": "none | one | several | unknown",
    "reasoning_one_line": ""
  }}
]
No prose before or after the JSON."""


def filter_batch(batch: list[RawCandidate], stats: RunStats) -> list[dict]:
    """Return one result dict per input record (aligned by index)."""
    companies_text = "\n".join(
        f"{i + 1}. {rec.company_name_raw}"
        f" | source: {rec.source}"
        + (f" | website: {rec.website_hint}" if rec.website_hint else "")
        + (f" | evidence: {rec.evidence}" if rec.evidence else "")
        for i, rec in enumerate(batch)
    )
    prompt = _PROMPT_TEMPLATE.format(
        light_max=config.MAX_LIGHT_FUNDING_USD,
        hard_max=config.HARD_MAX_FUNDING_USD,
        no_raise_months=config.NO_RAISE_MONTHS,
        quiet_months=config.LIGHT_FUNDING_QUIET_MONTHS,
        niches="\n".join(f"- {n}" for n in config.NICHES),
        exclusions="\n".join(f"- {e}" for e in config.EXCLUSIONS),
        companies=companies_text,
    )

    text = call_claude(prompt, stats, config.STAGE_MAX_SEARCHES, "stage_filter")
    parsed = parse_json_block(text)
    if not isinstance(parsed, list):
        print("    [filter] could not parse JSON from model; skipping batch")
        parsed = []

    return _align(batch, parsed)


def is_pass(res: dict) -> tuple[bool, str]:
    """Enforce the hard rules in code on top of the model's verdict.

    Returns (passed, reject_reason).
    """
    reason = str(res.get("reject_reason") or res.get("reasoning_one_line") or "")
    if str(res.get("verdict", "")).lower() != "pass":
        return False, reason or "rejected by stage filter"
    funding = str(res.get("funding_status", "")).lower()
    if funding.startswith("excluded") or not (
        funding.startswith("bootstrapped") or funding.startswith("lightly")
    ):
        return False, f"funding profile out of scope: {res.get('funding_status')}"
    if res.get("raised_last_12mo"):
        return False, "raised in the last 12 months (funded pipeline's territory)"
    if not res.get("is_icp_fit"):
        return False, reason or "not ICP"
    if str(res.get("in_house_creative", "")).lower() == "several":
        return False, "several in-house creative hires"
    return True, ""


def _align(batch: list[RawCandidate], parsed: list) -> list[dict]:
    """Align model output to input records, by order and then by name."""
    fallback = {
        "verdict": "reject",
        "reject_reason": "no result returned by filter model",
        "resolved_brand_name": "",
        "website": "",
        "funding_status": "",
        "raised_last_12mo": False,
        "is_icp_fit": False,
        "category": "",
        "region": "",
        "in_house_creative": "unknown",
        "reasoning_one_line": "",
    }
    results: list[dict] = []
    by_name = {
        normalize_name(str(item.get("company", ""))): item
        for item in parsed
        if isinstance(item, dict)
    }
    for i, rec in enumerate(batch):
        item = parsed[i] if i < len(parsed) and isinstance(parsed[i], dict) else None
        if item is None or normalize_name(str(item.get("company", ""))) != rec.dedup_key:
            item = by_name.get(rec.dedup_key, item)
        results.append(dict(fallback, **item) if isinstance(item, dict) else dict(fallback))
    return results
