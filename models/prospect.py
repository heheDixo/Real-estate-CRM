from dataclasses import dataclass, field
from typing import Optional

PROSPECT_STATUSES = [
    "new",        # just ingested, no enrichment yet
    "enriched",   # enrichment complete, not yet scored
    "scored",     # scored, not yet drafted
    "drafted",    # drafts generated, awaiting review
    "approved",   # he approved — ready to send
    "sent",       # email sent (or LinkedIn copied)
    "rejected",   # he rejected — removed from active queue
    "error",      # something failed in the pipeline
]


@dataclass
class Prospect:
    """
    A single company + contact being evaluated for outreach.

    This is the raw record — only fields available from the
    ingestion source (Apollo, CSV, manual). No enrichment,
    no scores, no drafts. Those live in their own models.

    The `status` field tracks where this prospect is in the
    pipeline at any point in time.
    """

    #  Identity 
    id: str = ""                     # unique — domain is used as ID
    source: str = "apollo"           # "apollo" | "csv" | "manual" | "mock"

    # Company fields
    company_name: str = ""
    domain: str = ""                 # e.g. "healthco.com" — used as primary key
    linkedin_url: str = ""           # company LinkedIn URL
    website: str = ""
    city: str = ""
    state: str = ""
    country: str = "United States"

    #  Size and stage 
    headcount: int = 0
    headcount_range: str = ""        # e.g. "51-200" from Apollo
    company_stage: str = ""          # "Series A" | "Series B" etc.
    industry: str = ""
    sub_industry: str = ""

    # Funding 
    last_funding_type: str = ""      # "Series B" | "Series C" etc.
    last_funding_amount: int = 0     # USD
    last_funding_date: str = ""      # ISO date string "2024-03-15"
    total_funding: int = 0           # USD

    # Contact
    contact_name: str = ""
    contact_first_name: str = ""
    contact_last_name: str = ""
    contact_title: str = ""
    contact_email: str = ""
    contact_linkedin: str = ""       # individual LinkedIn URL
    contact_phone: str = ""

    # Pipeline state 
    status: str = "new"
    icp_profile_name: str = ""       # which ICP profile this was scored against
    ingested_at: str = ""            # ISO timestamp
    updated_at: str = ""             # ISO timestamp of last status change

    # Flags 
    is_in_crm: bool = False          # already exists in Salesforce
    is_excluded: bool = False        # hit an exclusion rule
    exclusion_reason: str = ""       # why it was excluded

    # 
    # Methods
    # 

    def advance_status(self, new_status: str) -> None:
        """
        Move this prospect to the next pipeline status.
        Updates the updated_at timestamp.

        """
        import datetime
        if new_status not in PROSPECT_STATUSES:
            raise ValueError(f"Invalid status: {new_status}. "
                             f"Must be one of {PROSPECT_STATUSES}")
        self.status     = new_status
        self.updated_at = datetime.datetime.now().isoformat()

    def display_name(self) -> str:
        """Human-readable name for UI display."""
        if self.company_name:
            return self.company_name
        return self.domain or self.id or "Unknown company"

    def funding_months_ago(self) -> Optional[int]:
        """
        How many months ago was the last funding round?
        Returns None if no funding date available.
        Used by the scorer to calculate funding timing signal.
        """
        if not self.last_funding_date:
            return None
        import datetime
        try:
            funded = datetime.datetime.fromisoformat(
                self.last_funding_date.replace("Z", ""))
            delta = datetime.datetime.now() - funded
            return int(delta.days / 30)
        except (ValueError, TypeError):
            return None

    def is_in_deployment_window(self) -> bool:
        """
        Is this company in the typical 12–18 month post-funding
        deployment window where space expansion is most likely?

        """
        months = self.funding_months_ago()
        if months is None:
            return False
        return 10 <= months <= 20

    def to_dict(self) -> dict:
        """Serialise to dict for session state storage."""
        return {
            "id":                   self.id,
            "source":               self.source,
            "company_name":         self.company_name,
            "domain":               self.domain,
            "linkedin_url":         self.linkedin_url,
            "website":              self.website,
            "city":                 self.city,
            "state":                self.state,
            "country":              self.country,
            "headcount":            self.headcount,
            "headcount_range":      self.headcount_range,
            "company_stage":        self.company_stage,
            "industry":             self.industry,
            "sub_industry":         self.sub_industry,
            "last_funding_type":    self.last_funding_type,
            "last_funding_amount":  self.last_funding_amount,
            "last_funding_date":    self.last_funding_date,
            "total_funding":        self.total_funding,
            "contact_name":         self.contact_name,
            "contact_first_name":   self.contact_first_name,
            "contact_last_name":    self.contact_last_name,
            "contact_title":        self.contact_title,
            "contact_email":        self.contact_email,
            "contact_linkedin":     self.contact_linkedin,
            "contact_phone":        self.contact_phone,
            "status":               self.status,
            "icp_profile_name":     self.icp_profile_name,
            "ingested_at":          self.ingested_at,
            "updated_at":           self.updated_at,
            "is_in_crm":            self.is_in_crm,
            "is_excluded":          self.is_excluded,
            "exclusion_reason":     self.exclusion_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Prospect":
        """Deserialise from dict."""
        p = cls()
        for key, value in data.items():
            if hasattr(p, key):
                setattr(p, key, value)
        return p

    @classmethod
    def from_apollo_record(cls, record: dict) -> "Prospect":
        """
        Build a Prospect from a raw Apollo API response record.
        Maps Apollo field names to our field names.

        """
        import datetime
        org = record.get("organization", {}) or {}
        return cls(
            id             = record.get("id", ""),
            source         = "apollo",
            company_name   = org.get("name", ""),
            domain         = org.get("primary_domain", ""),
            linkedin_url   = org.get("linkedin_url", ""),
            website        = org.get("website_url", ""),
            city           = record.get("city", ""),
            state          = record.get("state", ""),
            country        = record.get("country", "United States"),
            headcount      = org.get("estimated_num_employees", 0) or 0,
            headcount_range= org.get("employee_count", ""),
            company_stage  = org.get("latest_funding_stage", ""),
            industry       = org.get("industry", ""),
            sub_industry   = org.get("keywords", [""])[0] if org.get("keywords") else "",
            last_funding_type   = org.get("latest_funding_stage", ""),
            last_funding_amount = org.get("latest_funding_round_amount", 0) or 0,
            last_funding_date   = org.get("latest_funding_round_date", ""),
            total_funding       = org.get("total_funding", 0) or 0,
            contact_name        = record.get("name", ""),
            contact_first_name  = record.get("first_name", ""),
            contact_last_name   = record.get("last_name", ""),
            contact_title       = record.get("title", ""),
            contact_email       = record.get("email", ""),
            contact_linkedin    = record.get("linkedin_url", ""),
            contact_phone       = record.get("sanitized_phone", ""),
            status              = "new",
            ingested_at         = datetime.datetime.now().isoformat(),
        )