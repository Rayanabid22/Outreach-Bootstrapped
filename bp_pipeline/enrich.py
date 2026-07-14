"""Stage 6 — social enrichment + activity check for qualified companies.

Shared module — same logic and qualification bar as ic_pipeline/enrich.py in
the funded pipeline (Rayanabid22/IC-Outreach); only the framing of the prompt
differs (bootstrapped company, not recently funded).
"""

import config
from .claude_client import call_claude, parse_json_block
from .models import Lead, RunStats

_PROMPT_TEMPLATE = """Find the social profiles and contact info for this \
established bootstrapped software company. Use web search to verify.

Company: {company}
Website: {website}
Category: {category}
Context: {context}

Rules:
- x_active: true ONLY if the company's X (Twitter) account has posted within the \
last 30 days — verify via web search of the handle's recent posts. This is the \
priority signal; check it carefully.
- instagram: actively look for the company's Instagram account — it is a
co-equal qualification signal with X, not just a fallback.
- instagram_active: true if posted within the last 30 days; null if you cannot tell.
- linkedin_url: company page URL only — do NOT attempt to check LinkedIn activity.
- Founder fields are a bonus, never required. Bootstrapped founders are usually \
easy to find: the /about page, X bio, Indie Hackers profile, interviews. \
If not found after ~2 search attempts, leave blank and move on.
- email: a contact/hello email from the site or public pages; blank if not found.
- Leave any field you cannot find as "" (or null for instagram_active).
- x_handle should be the bare handle without the @ (e.g. "acmehq").

Respond with ONLY this JSON object, no prose:
{{
  "x_handle": "", "x_active": false,
  "linkedin_url": "",
  "instagram": "", "instagram_active": null,
  "discord": "",
  "email": "",
  "founder_name": "", "founder_title": "",
  "founder_x": "", "founder_linkedin": ""
}}"""


def enrich(lead: Lead, stats: RunStats) -> Lead:
    """Fill social/contact fields on the lead in place and return it."""
    context = f"bootstrapped/lightly funded, est. MRR {lead.mrr_range}"
    if lead.raw.evidence:
        context += f"; found via: {lead.raw.evidence}"
    prompt = _PROMPT_TEMPLATE.format(
        company=lead.company,
        website=lead.website or "unknown — find it",
        category=lead.category,
        context=context,
    )
    text = call_claude(prompt, stats, config.ENRICH_MAX_SEARCHES, "enrich")
    data = parse_json_block(text)
    if not isinstance(data, dict):
        print(f"    [enrich] could not parse JSON for {lead.company}")
        return lead

    lead.x_handle = str(data.get("x_handle") or "").lstrip("@")
    lead.x_active = bool(data.get("x_active"))
    lead.linkedin_url = str(data.get("linkedin_url") or "")
    lead.instagram = str(data.get("instagram") or "")
    ig_active = data.get("instagram_active")
    lead.instagram_active = bool(ig_active) if ig_active is not None else None
    lead.discord = str(data.get("discord") or "")
    lead.email = str(data.get("email") or "")
    lead.founder_name = str(data.get("founder_name") or "")
    lead.founder_title = str(data.get("founder_title") or "")
    lead.founder_x = str(data.get("founder_x") or "").lstrip("@")
    lead.founder_linkedin = str(data.get("founder_linkedin") or "")
    return lead


def is_qualified(lead: Lead) -> bool:
    """Qualification bar for social activity.

    When config.REQUIRE_ACTIVE_SOCIAL is True: at least one confirmed-active
    social. X is the priority signal — an active X alone qualifies. Instagram
    activity is the best-effort backup. A LinkedIn URL alone does NOT
    qualify (no activity check is possible).

    When False (Rayan's decision, 2026-07-14): social activity is recorded
    in the X Active / Instagram columns but no longer disqualifies a
    revenue-verified company — too many otherwise-perfect bootstrapped
    companies simply don't post.
    """
    if not config.REQUIRE_ACTIVE_SOCIAL:
        return True
    return lead.x_active or bool(lead.instagram_active)
