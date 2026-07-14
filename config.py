"""Configuration for the IC Bootstrapped Leads Pipeline.

Everything Rayan is likely to tweak lives here: niches, exclusions, the MRR
bar, install-count / review-count ranges, source toggles + hunting-ground
descriptions, targets, and batch sizes. Secrets (API key) come from the
environment; the Google Sheet ID can come from either.

This pipeline shares its architecture (and several modules) with the funded
pipeline in Rayanabid22/IC-Outreach — same Claude client, dedup logic, sheet
write pattern, and social-activity qualification bar.
"""

import os

# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"  # same model as the funded pipeline

# Rough pricing used only for the end-of-run cost estimate.
PRICE_INPUT_PER_MTOK = 3.00     # USD per 1M input tokens (claude-sonnet-4-6)
PRICE_OUTPUT_PER_MTOK = 15.00   # USD per 1M output tokens
PRICE_PER_1000_SEARCHES = 10.00 # USD per 1,000 web searches

# ---------------------------------------------------------------------------
# Google Sheet — SEPARATE tabs from the funded pipeline so both can live in
# the same spreadsheet without colliding.
# ---------------------------------------------------------------------------
# The live "IC Bootstrapped Leads" Google Sheet (owned by mrayanabid510@gmail.com):
# https://docs.google.com/spreadsheets/d/1CR0ZiaMhxAJDQYKMyJV_QDVwv-ygAQM8kxlIhTlLQTY/edit
# Every run appends to this same sheet. Override with the SHEET_ID env var.
SHEET_ID = os.environ.get("SHEET_ID", "") or "1CR0ZiaMhxAJDQYKMyJV_QDVwv-ygAQM8kxlIhTlLQTY"
CREDENTIALS_FILE = "credentials.json"      # service-account key (gitignored)
LEADS_TAB = "Bootstrapped Leads"
PROCESSED_TAB = "Bootstrapped Processed"
REJECTED_TAB = "Bootstrapped Rejected"

# The funded pipeline's Processed tab, read for cross-pipeline dedup.
# Defaults to the same spreadsheet; set FUNDED_SHEET_ID if it lives elsewhere.
FUNDED_SHEET_ID = os.environ.get("FUNDED_SHEET_ID", "") or SHEET_ID
FUNDED_PROCESSED_TAB = "Processed"

# The funded pipeline's committed dedup registry (cross-pipeline dedup even
# without sheet credentials). Local paths are tried first, then the raw URL.
FUNDED_REGISTRY_PATHS = [
    os.environ.get("FUNDED_REGISTRY_PATH", ""),
    "../IC-Outreach/data/processed.csv",
    "../ic-outreach/data/processed.csv",
]
FUNDED_REGISTRY_URLS = [
    # HEAD tracks the repo's default branch, whatever it's named.
    "https://raw.githubusercontent.com/Rayanabid22/IC-Outreach/HEAD/data/processed.csv",
]

# ---------------------------------------------------------------------------
# Run targets
# ---------------------------------------------------------------------------
TARGET_LEADS = 100  # 100-150 qualified per weekly run; no time window —
                    # companies don't expire, dedup keeps runs fresh.

# ---------------------------------------------------------------------------
# ICP definition (fed verbatim into the Claude prompts)
# ---------------------------------------------------------------------------
NICHES = [
    "SaaS",
    "AI tools",
    "Tech/Software products (apps — mobile or web — and sites both count)",
    "Fintech",
    "Trading platform (actual trading platforms / trading infrastructure)",
    "Biotech (AI-software side only — not wet-lab pharma)",
]

# Halal gate + company-type exclusions — hard, non-negotiable.
EXCLUSIONS = [
    "Gambling or betting of any kind",
    "Interest-based lending as the core product (BNPL / consumer credit)",
    "Alcohol or cannabis",
    "Adult content",
    "Dating apps",
    "Israeli companies",
    "Agencies or consultancies (services businesses, not products)",
    "Public companies",
]

# Regions: prioritized vs acceptable. Region is recorded, never a hard filter
# unless timezone/payment problems are obvious.
REGIONS_PRIORITY = ["US", "UK", "Canada"]
REGIONS_ACCEPTABLE = ["Europe", "Australia"]

# ---------------------------------------------------------------------------
# Stage 3 — funding/stage rules (fed verbatim into the filter prompt)
# ---------------------------------------------------------------------------
MAX_LIGHT_FUNDING_USD = "3M"      # total raised under this = "lightly funded"
HARD_MAX_FUNDING_USD = "5M"       # over this = excluded
NO_RAISE_MONTHS = 12              # raised anything in the last N months = excluded
LIGHT_FUNDING_QUIET_MONTHS = 18   # lightly-funded requires no round in last N months

# ---------------------------------------------------------------------------
# Stage 5 — social qualification bar
# ---------------------------------------------------------------------------
# False (Rayan, 2026-07-14): a stale X/Instagram no longer disqualifies a
# revenue-verified company — activity is still checked and recorded in the
# X Active / Instagram columns so outreach can prioritize, but quiet
# companies stay in the Leads tab. Set True to restore the hard bar.
REQUIRE_ACTIVE_SOCIAL = False

# ---------------------------------------------------------------------------
# Stage 4 — revenue estimation bars
# ---------------------------------------------------------------------------
MRR_BAR = "$80k"                  # estimated MRR must be at least this
REVENUE_CONFIDENCE_BAR = 60       # 0-100 score must be >= this
MIN_REVENUE_SIGNALS = 2           # and at least this many independent signals

# Proxy-signal sweet spots (interpolated into prompts below)
INSTALL_RANGE = (3_000, 50_000)   # Chrome/Shopify/Slack/WordPress installs
G2_REVIEW_RANGE = (40, 400)       # below 40 = too small; above 400 = usually VC-backed (verify, don't assume)
MIN_MONTHLY_TRAFFIC = 20_000      # est. monthly visits floor for B2B SaaS
TEAM_SIZE_RANGE = (4, 40)         # LinkedIn headcount sweet spot
MIN_PRODUCT_AGE_YEARS = 2

# ---------------------------------------------------------------------------
# Stage 1 — collection sources.
# Toggle any source on/off here, or pass --sources on the CLI.
# Each search-based source has a "hunting_ground" description that drives a
# Claude web-search collection call — edit the text freely.
# ---------------------------------------------------------------------------
CANDIDATES_PER_SOURCE = 30        # asked of each search-based collector
COLLECT_MAX_SEARCHES = 15         # web-search budget per collection call

SEARCH_SOURCES = {
    "indiehackers": {
        "enabled": True,
        "hunting_ground": (
            "Indie Hackers (indiehackers.com) — the products directory (many "
            "products publicly list revenue) and popular posts where founders "
            "share MRR numbers. Searches like: site:indiehackers.com \"MRR\", "
            "indiehackers products \"$50k/mo\", founders sharing revenue "
            "milestones. Prefer products reporting roughly $50k+ MRR that are "
            "still alive today."
        ),
    },
    "tinyseed": {
        "enabled": True,
        "hunting_ground": (
            "The bootstrap-friendly funding ecosystem: TinySeed portfolio "
            "companies, Calm Company Fund portfolio, MicroConf speakers and "
            "community companies. These companies took bootstrap-compatible "
            "money (still counts as lightly funded) and are usually "
            "profitable SaaS in the exact revenue range we want."
        ),
    },
    "chrome": {
        "enabled": True,
        "hunting_ground": (
            "Chrome Web Store — extensions in ICP-relevant categories "
            "(productivity, developer tools, marketing, sales) whose PUBLIC "
            f"user count is roughly {INSTALL_RANGE[0]:,}-{INSTALL_RANGE[1]:,} "
            "users (big enough to pay, small enough to have no agency), made "
            "by an actual paid product company, not a hobby project."
        ),
    },
    "shopify": {
        "enabled": True,
        "hunting_ground": (
            "Shopify App Store — apps with meaningful install + review "
            f"counts (roughly {INSTALL_RANGE[0]:,}-{INSTALL_RANGE[1]:,} "
            "installs or several hundred reviews) charging monthly. The app "
            "developer/company is the lead, not the merchants."
        ),
    },
    "wordpress": {
        "enabled": True,
        "hunting_ground": (
            "WordPress plugin directory (wordpress.org/plugins) — paid/"
            "freemium plugin companies whose free plugin shows active-install "
            f"counts roughly {INSTALL_RANGE[0]:,}+ and that sell a pro "
            "version (forms, SEO, e-commerce, backups, membership, etc.)."
        ),
    },
    "slack": {
        "enabled": True,
        "hunting_ground": (
            "Slack App Directory — paid Slack apps in ICP-relevant "
            "categories (productivity, HR, devops, analytics) with real "
            "install traction, made by independent software companies."
        ),
    },
    "g2": {
        "enabled": True,
        "hunting_ground": (
            "G2 category pages in ICP categories — companies with roughly "
            f"{G2_REVIEW_RANGE[0]}-{G2_REVIEW_RANGE[1]} reviews (below "
            f"{G2_REVIEW_RANGE[0]} = too small; above {G2_REVIEW_RANGE[1]} = "
            "usually VC-backed with in-house teams — verify rather than "
            "assume) and no visible VC funding."
        ),
    },
    "capterra": {
        "enabled": True,
        "hunting_ground": (
            "Capterra category pages in ICP categories — same review-count "
            f"sweet spot as G2 (roughly {G2_REVIEW_RANGE[0]}-"
            f"{G2_REVIEW_RANGE[1]} reviews), companies without visible "
            "VC funding."
        ),
    },
    "producthunt": {
        "enabled": True,
        "hunting_ground": (
            "Product Hunt archive — software products launched 1-3 YEARS ago "
            "that are still alive and shipping today (active changelog, blog, "
            "or social feed). Survived-and-monetized products, not last "
            "week's launches."
        ),
    },
    "foundersignal": {
        "enabled": True,
        "hunting_ground": (
            "Founder revenue-bragging signal, anywhere on the public web. "
            "Searches like: \"bootstrapped\" \"$100k MRR\" SaaS; "
            "\"we're profitable\" \"no VC\" software; \"bootstrapped to\" "
            "\"ARR\"; founder tweets / interviews / Starter Story features "
            "where a founder states their MRR or ARR. Harvest the company "
            "names."
        ),
    },
    "acquire": {
        "enabled": True,
        "hunting_ground": (
            "acquire.com public/browsable listings — SaaS listings where "
            "revenue is literally stated (TTM revenue / profit shown). A "
            "founder listing their company may also be a founder open to "
            "growth spend. Only include companies whose identity is public "
            "or discoverable; skip anonymous listings."
        ),
    },
}

# ---------------------------------------------------------------------------
# Batch sizes / search budgets
# ---------------------------------------------------------------------------
STAGE_BATCH_SIZE = 10         # companies per Claude stage/funding-filter call
STAGE_MAX_SEARCHES = 25       # web-search budget per filter call
REVENUE_MAX_SEARCHES = 10     # web-search budget per revenue-estimation call
ENRICH_MAX_SEARCHES = 8       # web-search budget per enrichment call

# Polite delay between any raw HTTP requests (seconds) — 1-2 req/s.
REQUEST_DELAY_SECONDS = 0.6

# ---------------------------------------------------------------------------
# Local state
# ---------------------------------------------------------------------------
SEEN_DB = "seen.db"
LOG_DIR = "logs"
