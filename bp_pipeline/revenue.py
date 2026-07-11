"""Stage 4 — revenue estimation from public proxy signals.

One Claude call per stage-filter-passing company. Active user counts are not
directly public, so revenue is estimated from whichever proxy signals are
findable, each cited by name — never fabricated. The pass bar (confidence >=
config.REVENUE_CONFIDENCE_BAR AND >= config.MIN_REVENUE_SIGNALS independent
signals) is enforced in code, not left to the model.
"""

import config
from .claude_client import call_claude, parse_json_block
from .models import Lead, RunStats

_PROMPT_TEMPLATE = """Estimate the monthly recurring revenue of this software \
company using ONLY verifiable public proxy signals found via web search. \
NEVER fabricate or assume a signal you did not actually find.

Company: {company}
Website: {website}
Category: {category}
Signal seen at collection time: {evidence}

Look for whichever of these you can find (each one found = one independent \
signal; report its concrete value):
1. SELF-REPORTED REVENUE — Indie Hackers product pages, founder interviews, \
Starter Story, MicroConf/TinySeed talks, founder tweets stating MRR/ARR. \
Strongest signal; take it at face value.
2. PUBLIC INSTALL/USER COUNTS — Chrome Web Store user count, Shopify App \
Store installs + reviews, WordPress plugin active installs, Slack App \
Directory installs.
3. REVIEW VOLUME — G2 / Capterra / Trustpilot review counts. {g2_lo}+ G2 \
reviews generally implies hundreds of paying customers. Combine with the \
pricing page's typical monthly price: MRR ~= reviews x 8-15 \
customers-per-review x monthly price.
4. APP STORE SIGNALS — iOS/Android review counts and rating volume.
5. TRAFFIC — free-tier estimated monthly visits; >= ~{traffic:,}/month is \
healthy for B2B SaaS. Do not use paid APIs.
6. TEAM SIZE — LinkedIn headcount. {team_lo}-{team_hi} people with no \
funding = likely default-alive revenue business; 1-2 people = probably too \
small. Report the count.
7. LONGEVITY — domain/product age >= {age} years (established, not a \
weekend project).

Then:
- est_mrr_range: your honest estimate, e.g. "$80k-150k" or "$20k-40k" or \
"unknown".
- revenue_confidence: 0-100 — how confident you are that MRR is AT LEAST \
{mrr_bar}, given the signals found. Zero signals = very low score.
- signals: list ONLY the signals you actually found, each as one short \
string naming the source and the value, e.g. "G2: 180 reviews", \
"Founder tweet (2024): $95k MRR", "LinkedIn: 14 employees". If you found \
fewer than {min_signals}, report what you found — the pipeline will mark \
the company LOW CONFIDENCE; do not pad the list.

Respond with ONLY this JSON object, no prose:
{{
  "est_mrr_range": "",
  "revenue_confidence": 0,
  "signals": [],
  "team_size": "",
  "reasoning_one_line": ""
}}"""


def estimate(lead: Lead, stats: RunStats) -> Lead:
    """Fill revenue fields on the lead in place and return it."""
    prompt = _PROMPT_TEMPLATE.format(
        company=lead.company,
        website=lead.website or "unknown — find it",
        category=lead.category,
        evidence=lead.raw.evidence or "none",
        g2_lo=config.G2_REVIEW_RANGE[0],
        traffic=config.MIN_MONTHLY_TRAFFIC,
        team_lo=config.TEAM_SIZE_RANGE[0],
        team_hi=config.TEAM_SIZE_RANGE[1],
        age=config.MIN_PRODUCT_AGE_YEARS,
        mrr_bar=config.MRR_BAR,
        min_signals=config.MIN_REVENUE_SIGNALS,
    )
    text = call_claude(prompt, stats, config.REVENUE_MAX_SEARCHES, "revenue")
    data = parse_json_block(text)
    if not isinstance(data, dict):
        print(f"    [revenue] could not parse JSON for {lead.company}")
        return lead

    lead.mrr_range = str(data.get("est_mrr_range") or "unknown")
    try:
        lead.revenue_confidence = max(0, min(100, int(data.get("revenue_confidence") or 0)))
    except (TypeError, ValueError):
        lead.revenue_confidence = 0
    signals = data.get("signals")
    lead.signals_used = [str(s) for s in signals if str(s).strip()] \
        if isinstance(signals, list) else []
    lead.team_size = str(data.get("team_size") or "")
    return lead


def meets_bar(lead: Lead) -> tuple[bool, str]:
    """Pass bar: confidence >= bar AND >= MIN_REVENUE_SIGNALS named signals.

    Returns (passed, reject_reason). Companies below the bar are marked LOW
    CONFIDENCE and never counted toward the target.
    """
    if len(lead.signals_used) < config.MIN_REVENUE_SIGNALS:
        return False, (f"LOW CONFIDENCE: only {len(lead.signals_used)} revenue "
                       f"signal(s) found (need {config.MIN_REVENUE_SIGNALS})")
    if lead.revenue_confidence < config.REVENUE_CONFIDENCE_BAR:
        return False, (f"LOW CONFIDENCE: revenue confidence "
                       f"{lead.revenue_confidence} < {config.REVENUE_CONFIDENCE_BAR} "
                       f"(est. {lead.mrr_range})")
    return True, ""
