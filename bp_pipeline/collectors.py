"""Stage 1 — collect bootstrapped-company candidates.

Every source sits behind a common interface (name -> collector function) so
sources can be toggled in config or via --sources on the CLI.

Most hunting grounds (Indie Hackers, G2, Capterra, Chrome Web Store, Shopify,
acquire.com, Product Hunt) block or throttle raw scraping, so those sources
are collected with a Claude web-search call driven by the per-source
"hunting_ground" description in config.SEARCH_SOURCES. The WordPress plugin
directory has a free public JSON API, so it gets a real HTTP collector on
top of its search collector.
"""

import time

import requests

import config
from .claude_client import call_claude, parse_json_block
from .models import RawCandidate, RunStats

_session = requests.Session()

_PROMPT_TEMPLATE = """You are prospecting for Impact Creatives, a motion design \
studio selling launch videos, product explainers, and monthly content retainers \
to software companies. This pipeline hunts the QUIET PROFITABLE end of the \
market: established, revenue-generating software companies that are \
bootstrapped or lightly funded — roughly {mrr_bar}+ MRR, able to afford a \
premium creative studio, but with NO in-house creative team and NO recent VC \
money. The buyer is the founder.

ICP categories:
{niches}

Hunting ground for THIS collection run:
{hunting_ground}

Use web search to find up to {target} candidate companies from this hunting
ground. Prefer companies that look big enough to pay (real revenue/traction
signals) but small enough to have no agency or creative hires.

Do NOT include: obviously VC-backed companies (Series A or beyond), public
companies, agencies/consultancies, or anything in these excluded categories:
{exclusions}

Rules:
- Only list companies you actually found evidence for — never invent names.
- evidence: the concrete signal you saw, verbatim-ish (e.g. "IH: founder
  reports $45k MRR", "Chrome Web Store: 30,000 users", "G2: 180 reviews").
- source_url: where you saw it.

Respond with ONLY a JSON array, no prose:
[
  {{"company": "", "website": "", "source_url": "", "evidence": "", "category_hint": ""}}
]"""


def _collect_search(source_name: str, spec: dict, stats: RunStats) -> list[RawCandidate]:
    """Generic Claude-web-search collector for one hunting ground."""
    prompt = _PROMPT_TEMPLATE.format(
        mrr_bar=config.MRR_BAR,
        niches="\n".join(f"- {n}" for n in config.NICHES),
        hunting_ground=spec["hunting_ground"],
        target=config.CANDIDATES_PER_SOURCE,
        exclusions="\n".join(f"- {e}" for e in config.EXCLUSIONS),
    )
    text = call_claude(prompt, stats, config.COLLECT_MAX_SEARCHES,
                       f"collect_{source_name}")
    parsed = parse_json_block(text)
    if not isinstance(parsed, list):
        print(f"  [collect] {source_name}: could not parse JSON; skipping source")
        return []

    records = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("company", "")).strip()
        if not name:
            continue
        records.append(
            RawCandidate(
                company_name_raw=name,
                source=source_name,
                source_url=str(item.get("source_url", "")),
                website_hint=str(item.get("website", "")),
                category_hint=str(item.get("category_hint", "")),
                evidence=str(item.get("evidence", "")),
            )
        )
    print(f"  [collect] {source_name}: {len(records)} candidates")
    return records


# ---------------------------------------------------------------------------
# WordPress plugin directory — free public JSON API with active_installs.
# ---------------------------------------------------------------------------

_WP_API = "https://api.wordpress.org/plugins/info/1.2/"
_WP_QUERIES = ["forms", "seo", "email marketing", "membership", "backup",
               "analytics", "booking", "ecommerce"]


def _collect_wordpress_api(stats: RunStats) -> list[RawCandidate]:
    """Query the wordpress.org plugin API for popular ICP-relevant plugins
    whose active-install counts sit in the configured sweet spot."""
    lo, hi = config.INSTALL_RANGE
    records: list[RawCandidate] = []
    seen_slugs: set[str] = set()

    for query in _WP_QUERIES:
        time.sleep(config.REQUEST_DELAY_SECONDS)
        try:
            resp = _session.get(
                _WP_API,
                params={
                    "action": "query_plugins",
                    "request[search]": query,
                    "request[per_page]": 50,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"  [collect] wordpress-api HTTP {resp.status_code} for '{query}'")
                continue
            plugins = resp.json().get("plugins", [])
        except Exception as exc:
            print(f"  [collect] wordpress-api error for '{query}': {exc}")
            continue

        for p in plugins:
            slug = p.get("slug", "")
            installs = int(p.get("active_installs") or 0)
            if not slug or slug in seen_slugs or not (lo <= installs <= hi * 10):
                # allow up to 10x the top of the range — install counts on
                # WP skew high; the stage filter verifies the company anyway
                continue
            seen_slugs.add(slug)
            # The company behind the plugin is the lead, not the plugin.
            author = str(p.get("author", ""))
            # author comes as an HTML link — pull the display text
            name = author.split(">")[-2].split("<")[0].strip() if ">" in author else author
            homepage = str(p.get("homepage") or "")
            records.append(
                RawCandidate(
                    company_name_raw=name or str(p.get("name", "")),
                    source="wordpress",
                    source_url=f"https://wordpress.org/plugins/{slug}/",
                    website_hint=homepage,
                    category_hint="SaaS (WordPress plugin company)",
                    evidence=f"WordPress.org: {installs:,}+ active installs "
                             f"({p.get('name', slug)})",
                )
            )
    print(f"  [collect] wordpress (API): {len(records)} candidates")
    return records


# ---------------------------------------------------------------------------
# Entry point — common interface
# ---------------------------------------------------------------------------

def available_sources() -> list[str]:
    return list(config.SEARCH_SOURCES.keys())


def collect(source_names: list[str] | None, stats: RunStats) -> list[RawCandidate]:
    """Collect from the given sources (or all enabled ones) and dedup in-batch."""
    if source_names:
        unknown = [s for s in source_names if s not in config.SEARCH_SOURCES]
        if unknown:
            raise SystemExit(f"Unknown source(s): {', '.join(unknown)}. "
                             f"Available: {', '.join(available_sources())}")
        enabled = source_names
    else:
        enabled = [name for name, spec in config.SEARCH_SOURCES.items()
                   if spec.get("enabled", True)]

    print(f"[stage 1] Collecting from sources: {', '.join(enabled)}")
    records: list[RawCandidate] = []
    for name in enabled:
        if name == "wordpress":
            # Real API first, then the search collector tops it up.
            records.extend(_collect_wordpress_api(stats))
        records.extend(_collect_search(name, config.SEARCH_SOURCES[name], stats))

    # In-batch dedup by normalized name, keeping the first (strongest-evidence
    # sources should be listed first in config).
    unique: dict[str, RawCandidate] = {}
    for rec in records:
        key = rec.dedup_key
        if key and key not in unique:
            unique[key] = rec
    result = list(unique.values())
    for rec in result:
        stats.per_source[rec.source] = stats.per_source.get(rec.source, 0) + 1
    print(f"[stage 1] {len(records)} raw -> {len(result)} unique candidates")
    return result
