from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JobPosting:
    """A single LinkedIn job posting."""
    title: str = ""
    location: str = ""
    posted_date: str = ""
    is_office_related: bool = False   # True if title contains workplace/office keywords


@dataclass
class NewsSignal:
    """A single news article flagged as a CRE signal."""
    headline: str = ""
    source: str = ""
    published_date: str = ""
    url: str = ""
    signal_type: str = ""    # "funding" | "expansion" | "office" | "hiring" | "relocation"
    excerpt: str = ""        # first 200 chars of article body


@dataclass
class EnrichmentResult:
    """
    Everything discovered about a prospect after the enrichment
    waterfall runs. Decorates a Prospect — does not replace it.

    Three source blocks correspond to the three connectors:
    - Apollo block:     firmographic depth
    - Proxycurl block:  LinkedIn hiring signals
    - NewsAPI block:    recent news signals

    Computed fields at the bottom are what the scorer reads.
    The scorer never reads raw source fields directly — it reads
    the computed fields so the scoring logic is source-agnostic.
    """

    # Identity 
    prospect_id: str = ""            # matches Prospect.domain
    enriched_at: str = ""            # ISO timestamp
    sources_used: list = field(default_factory=list)   # ["apollo","proxycurl","newsapi"]
    sources_failed: list = field(default_factory=list) # which APIs returned errors

    # Apollo block 
    # Deeper firmographic data than what Apollo returns in search results.
    headcount_6mo_ago: int = 0        # headcount 6 months ago (Apollo history)
    headcount_current: int = 0        # current headcount
    headcount_1yr_ago: int = 0        # headcount 1 year ago
    founded_year: int = 0
    description: str = ""             # company description from Apollo
    technologies: list = field(default_factory=list)    # tech stack
    keywords: list = field(default_factory=list)
    alexa_rank: int = 0
    annual_revenue: int = 0           # USD estimate
    sic_codes: list = field(default_factory=list)

    # Proxycurl block
    # LinkedIn hiring signals — the strongest space-need proxy.
    job_postings: list = field(default_factory=list)    # list of JobPosting objects
    total_jobs_posted: int = 0
    jobs_in_target_geo: int = 0       # jobs posted in ICP geography
    office_roles_posted: int = 0      # jobs with workplace/office in title
    top_job_titles: list = field(default_factory=list)  # most common titles posted
    linkedin_follower_count: int = 0
    linkedin_employee_count: int = 0  # LinkedIn's own headcount figure

    # NewsAPI block 
    # Recent news that signals a real estate need.
    news_signals: list = field(default_factory=list)    # list of NewsSignal objects
    total_news_signals: int = 0
    strongest_signal_type: str = ""   # the highest-value signal type found
    strongest_signal_headline: str = ""
    strongest_signal_date: str = ""
    has_expansion_news: bool = False
    has_funding_news: bool = False
    has_office_news: bool = False
    has_relocation_news: bool = False

    #  Computed fields
    # These are what the scorer reads. Calculated from the source blocks above.
    # The scoring logic never reads raw source fields.

    headcount_growth_pct: float = 0.0
    # (headcount_current - headcount_6mo_ago) / headcount_6mo_ago * 100

    months_since_funding: Optional[int] = None
    # calculated from Prospect.last_funding_date in pipeline/enrichment.py

    is_in_deployment_window: bool = False
    # True if months_since_funding is between 10 and 20

    hiring_velocity_score: float = 0.0
    # 0–100: normalised score based on jobs posted vs headcount

    triggers_fired: list = field(default_factory=list)
    # list of trigger signal names from ICP that this prospect fired
    # e.g. ["raised_funding_last_18_months", "office_role_posted"]

    triggers_count: int = 0
    # len(triggers_fired) — compared to ICP.min_triggers_required

    # Raw description for HuggingFace 
    # Built by pipeline/enrichment.py after all sources run.
    # This is the paragraph fed to bart-large-mnli.
    hf_description: str = ""

    # 
    # Methods
    # 

    def compute_headcount_growth(self) -> None:
        """
        Calculate headcount growth percentage from source data.
        Called by pipeline/enrichment.py after Apollo data is loaded.
        """
        if self.headcount_6mo_ago and self.headcount_6mo_ago > 0:
            self.headcount_growth_pct = round(
                (self.headcount_current - self.headcount_6mo_ago)
                / self.headcount_6mo_ago * 100, 1
            )
        else:
            self.headcount_growth_pct = 0.0

    def compute_hiring_velocity(self) -> None:
        """
        Calculate a 0-100 hiring velocity score.
        Formula: (jobs_in_target_geo / max(headcount_current, 1)) * 100
        Capped at 100.
        Called by pipeline/enrichment.py after Proxycurl data is loaded.
        """
        if self.headcount_current > 0:
            raw = (self.total_jobs_posted / self.headcount_current) * 100
            self.hiring_velocity_score = min(round(raw, 1), 100.0)
        else:
            self.hiring_velocity_score = 0.0

    def check_triggers(self, trigger_signals: list,
                        months_since_funding: Optional[int]) -> None:
        """
        Check which ICP trigger signals this prospect fires.
        Populates triggers_fired and triggers_count.

        Called by pipeline/enrichment.py after all sources have run.

        """
        fired = []

        checks = {
            "raised_funding_last_18_months": (
                months_since_funding is not None and months_since_funding <= 18
            ),
            "headcount_growth_20pct_6months": (
                self.headcount_growth_pct >= 20.0
            ),
            "expansion_announcement_90_days": (
                self.has_expansion_news
            ),
            "office_role_posted": (
                self.office_roles_posted >= 1
            ),
            "hiring_velocity_high": (
                self.hiring_velocity_score >= 30.0
            ),
            "has_relocation_signal": (
                self.has_relocation_news
            ),
        }

        for signal_name in trigger_signals:
            if checks.get(signal_name, False):
                fired.append(signal_name)

        self.triggers_fired = fired
        self.triggers_count = len(fired)

    def build_hf_description(self, prospect) -> str:
        """
        Build the natural language paragraph fed to bart-large-mnli.
        Reads from computed fields, not raw source fields.

        Called by pipeline/enrichment.py after compute_ methods have run.


        """
        name        = prospect.company_name
        city        = prospect.city or "their target market"
        headcount   = self.headcount_current or prospect.headcount
        growth      = self.headcount_growth_pct
        jobs        = self.total_jobs_posted
        office_jobs = self.office_roles_posted
        months_fund = self.months_since_funding
        stage       = prospect.last_funding_type or prospect.company_stage
        amount      = prospect.last_funding_amount
        expansion   = self.has_expansion_news
        headline    = self.strongest_signal_headline
        triggers    = ", ".join(self.triggers_fired) if self.triggers_fired \
                      else "no specific triggers detected"

        funding_text = ""
        if months_fund is not None and stage:
            amount_text = (f"${amount:,}" if amount else "an undisclosed amount")
            funding_text = (f"They raised {stage} of {amount_text} "
                           f"{months_fund} months ago. ")
            if self.is_in_deployment_window:
                funding_text += ("This puts them in the typical 12–18 month "
                                "window when companies deploy capital on space. ")

        growth_text = ""
        if growth > 0:
            growth_text = (f"Headcount has grown {growth:.0f}% in the last "
                          f"6 months, from {self.headcount_6mo_ago} to "
                          f"{headcount} employees. ")

        jobs_text = ""
        if jobs > 0:
            jobs_text = (f"They have {jobs} active job postings")
            if jobs_in_geo := self.jobs_in_target_geo:
                jobs_text += f", {jobs_in_geo} of which are in {city}"
            if office_jobs > 0:
                jobs_text += (f", including {office_jobs} office or "
                             f"workplace management role(s)")
            jobs_text += ". "

        expansion_text = ""
        if expansion and headline:
            expansion_text = f"Recent news: {headline}. "

        description = (
            f"{name} is a {stage or 'venture-backed'} company based in "
            f"{city} with approximately {headcount} employees. "
            f"{funding_text}"
            f"{growth_text}"
            f"{jobs_text}"
            f"{expansion_text}"
            f"Detected signals: {triggers}."
        )

        self.hf_description = description
        return description

    def to_dict(self) -> dict:
        """Serialise to dict, converting nested dataclasses to dicts."""
        return {
            "prospect_id":              self.prospect_id,
            "enriched_at":              self.enriched_at,
            "sources_used":             self.sources_used,
            "sources_failed":           self.sources_failed,
            "headcount_6mo_ago":        self.headcount_6mo_ago,
            "headcount_current":        self.headcount_current,
            "headcount_1yr_ago":        self.headcount_1yr_ago,
            "founded_year":             self.founded_year,
            "description":              self.description,
            "technologies":             self.technologies,
            "keywords":                 self.keywords,
            "total_jobs_posted":        self.total_jobs_posted,
            "jobs_in_target_geo":       self.jobs_in_target_geo,
            "office_roles_posted":      self.office_roles_posted,
            "top_job_titles":           self.top_job_titles,
            "total_news_signals":       self.total_news_signals,
            "strongest_signal_type":    self.strongest_signal_type,
            "strongest_signal_headline":self.strongest_signal_headline,
            "strongest_signal_date":    self.strongest_signal_date,
            "has_expansion_news":       self.has_expansion_news,
            "has_funding_news":         self.has_funding_news,
            "has_office_news":          self.has_office_news,
            "has_relocation_news":      self.has_relocation_news,
            "headcount_growth_pct":     self.headcount_growth_pct,
            "months_since_funding":     self.months_since_funding,
            "is_in_deployment_window":  self.is_in_deployment_window,
            "hiring_velocity_score":    self.hiring_velocity_score,
            "triggers_fired":           self.triggers_fired,
            "triggers_count":           self.triggers_count,
            "hf_description":           self.hf_description,
            "news_signals": [
                {
                    "headline":      s.headline,
                    "source":        s.source,
                    "published_date":s.published_date,
                    "url":           s.url,
                    "signal_type":   s.signal_type,
                    "excerpt":       s.excerpt,
                }
                for s in self.news_signals
            ],
            "job_postings": [
                {
                    "title":            j.title,
                    "location":         j.location,
                    "posted_date":      j.posted_date,
                    "is_office_related":j.is_office_related,
                }
                for j in self.job_postings
            ],
        }