"""Shared record types passed between pipeline stages."""

from dataclasses import dataclass, field


@dataclass
class RawCandidate:
    """Stage 1 output: one bootstrapped-company candidate from a source."""

    company_name_raw: str
    source: str                  # source tag, e.g. "indiehackers", "g2"
    source_url: str = ""
    website_hint: str = ""
    category_hint: str = ""
    evidence: str = ""           # concrete signal seen at collection time,
                                 # e.g. "IH: founder reports $45k MRR"

    @property
    def dedup_key(self) -> str:
        from .dedup import normalize_name

        return normalize_name(self.company_name_raw)


@dataclass
class Lead:
    """A fully qualified lead ready to be appended to the sheet."""

    raw: RawCandidate
    # Stage 3 (stage/funding + ICP filter) fields
    company: str = ""
    website: str = ""
    category: str = ""
    region: str = ""
    funding_status: str = ""      # "bootstrapped" / "lightly funded (...)"
    in_house_creative: str = ""   # none | one (deprioritized) | unknown
    fit_reasoning: str = ""
    # Stage 4 (revenue estimation) fields
    mrr_range: str = ""
    revenue_confidence: int = 0
    signals_used: list = field(default_factory=list)
    team_size: str = ""
    # Stage 6 (enrichment) fields
    x_handle: str = ""
    x_active: bool = False
    linkedin_url: str = ""
    instagram: str = ""
    instagram_active: bool | None = None
    discord: str = ""
    email: str = ""
    founder_name: str = ""
    founder_title: str = ""
    founder_x: str = ""
    founder_linkedin: str = ""

    def to_sheet_row(self, date_added: str) -> list:
        return [
            date_added,
            self.company,
            self.website,
            self.category,
            self.region,
            self.mrr_range,
            self.revenue_confidence,
            "; ".join(self.signals_used),
            self.funding_status,
            self.team_size,
            self.raw.source,
            self.x_handle,
            "TRUE" if self.x_active else "FALSE",
            self.linkedin_url,
            self.instagram,
            self.discord,
            self.email,
            (f"{self.founder_name} ({self.founder_title})".strip()
             if self.founder_title else self.founder_name),
            self.founder_x,
            self.founder_linkedin,
            self.in_house_creative,
            self.fit_reasoning,
        ]


LEADS_HEADERS = [
    "Date Added", "Company", "Website", "Category", "Region",
    "Est. MRR Range", "Revenue Confidence (0-100)", "Signals Used",
    "Funding Status", "Team Size", "Source", "X Handle", "X Active",
    "LinkedIn", "Instagram", "Discord", "Email", "Founder", "Founder X",
    "Founder LinkedIn", "In-House Creative?", "Fit Reasoning",
]

PROCESSED_HEADERS = ["Key", "Company", "Domain", "Date Processed", "Outcome"]

REJECTED_HEADERS = ["Date", "Company", "Source", "Reason"]


@dataclass
class RunStats:
    """Counters for the run summary."""

    raw_collected: int = 0
    after_dedup: int = 0
    stage_pass: int = 0
    rejected_stage: int = 0        # funding profile / ICP / halal / creative team
    revenue_pass: int = 0
    rejected_low_confidence: int = 0
    qualified: int = 0
    rejected_no_socials: int = 0
    founders_found: int = 0
    confidence_sum: int = 0        # over qualified leads, for the average
    per_source: dict = field(default_factory=dict)
    # API accounting
    api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0

    def cost_estimate(self) -> float:
        import config

        return (
            self.input_tokens / 1_000_000 * config.PRICE_INPUT_PER_MTOK
            + self.output_tokens / 1_000_000 * config.PRICE_OUTPUT_PER_MTOK
            + self.web_searches / 1000 * config.PRICE_PER_1000_SEARCHES
        )
