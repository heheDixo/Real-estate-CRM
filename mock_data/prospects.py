import datetime
from models.prospect import Prospect

# Helper
_NOW = datetime.datetime.now().isoformat()



# PROSPECT 1 — Healthcare Tech · Series B · New York · HOT expected score
#
# HealthAxis is a clinical workflow SaaS company that raised Series B
# 14 months ago. They have grown from 120 to 190 employees in 6 months
# and recently announced a New York expansion. Strong space need signals.
# The demo's hero prospect — designed to score Hot and produce a great draft.


HEALTHAXIS = Prospect(
    id                  = "healthaxis.io",
    source              = "mock",
    company_name        = "HealthAxis",
    domain              = "healthaxis.io",
    linkedin_url        = "https://www.linkedin.com/company/healthaxis",
    website             = "https://www.healthaxis.io",
    city                = "New York",
    state               = "NY",
    country             = "United States",
    headcount           = 190,
    headcount_range     = "51-200",
    company_stage       = "Series B",
    industry            = "Health Technology",
    sub_industry        = "Clinical Workflow SaaS",
    last_funding_type   = "Series B",
    last_funding_amount = 42_000_000,
    last_funding_date   = (
        datetime.datetime.now() - datetime.timedelta(days=420)
    ).strftime("%Y-%m-%d"),   # 14 months ago
    total_funding       = 58_000_000,
    contact_name        = "Rachel Kim",
    contact_first_name  = "Rachel",
    contact_last_name   = "Kim",
    contact_title       = "VP of Operations",
    contact_email       = "rachel.kim@healthaxis.io",
    contact_linkedin    = "https://www.linkedin.com/in/rachelkim-ops",
    contact_phone       = "",
    status              = "new",
    icp_profile_name    = "Healthcare Tech — NYC",
    ingested_at         = _NOW,
    updated_at          = _NOW,
    is_in_crm           = False,
    is_excluded         = False,
)



# PROSPECT 2 — Technology / SaaS · Series C · New York · WARM expected score

# Meridian Analytics is a data infrastructure company that raised Series C
# 22 months ago (past the ideal deployment window). Moderate hiring velocity.
# Good prospect but less urgent — expected to score Warm.


MERIDIAN_ANALYTICS = Prospect(
    id                  = "meridiananalytics.com",
    source              = "mock",
    company_name        = "Meridian Analytics",
    domain              = "meridiananalytics.com",
    linkedin_url        = "https://www.linkedin.com/company/meridian-analytics",
    website             = "https://www.meridiananalytics.com",
    city                = "New York",
    state               = "NY",
    country             = "United States",
    headcount           = 320,
    headcount_range     = "201-500",
    company_stage       = "Series C",
    industry            = "Technology",
    sub_industry        = "Data Infrastructure",
    last_funding_type   = "Series C",
    last_funding_amount = 78_000_000,
    last_funding_date   = (
        datetime.datetime.now() - datetime.timedelta(days=660)
    ).strftime("%Y-%m-%d"),   # 22 months ago
    total_funding       = 110_000_000,
    contact_name        = "James Okafor",
    contact_first_name  = "James",
    contact_last_name   = "Okafor",
    contact_title       = "Chief of Staff",
    contact_email       = "j.okafor@meridiananalytics.com",
    contact_linkedin    = "https://www.linkedin.com/in/jamesokafor",
    contact_phone       = "",
    status              = "new",
    icp_profile_name    = "Tech — NYC",
    ingested_at         = _NOW,
    updated_at          = _NOW,
    is_in_crm           = False,
    is_excluded         = False,
)

# PROSPECT 3 — Financial Services · Growth / PE-backed · New York
#              WARM to HOT expected score
#
# Vantage Capital Partners is a mid-market PE firm that completed a
# management buyout 16 months ago and has been building out its NY team.
# Headcount has grown from 85 to 140. Lease expiry signal detected.


VANTAGE_CAPITAL = Prospect(
    id                  = "vantagecapitalpartners.com",
    source              = "mock",
    company_name        = "Vantage Capital Partners",
    domain              = "vantagecapitalpartners.com",
    linkedin_url        = "https://www.linkedin.com/company/vantage-capital-partners",
    website             = "https://www.vantagecapitalpartners.com",
    city                = "New York",
    state               = "NY",
    country             = "United States",
    headcount           = 140,
    headcount_range     = "51-200",
    company_stage       = "Growth / PE-backed",
    industry            = "Financial Services",
    sub_industry        = "Private Equity",
    last_funding_type   = "Management Buyout",
    last_funding_amount = 0,          # PE — amount not disclosed
    last_funding_date   = (
        datetime.datetime.now() - datetime.timedelta(days=480)
    ).strftime("%Y-%m-%d"),   # 16 months ago
    total_funding       = 0,
    contact_name        = "Sandra Whitmore",
    contact_first_name  = "Sandra",
    contact_last_name   = "Whitmore",
    contact_title       = "COO",
    contact_email       = "s.whitmore@vantagecapitalpartners.com",
    contact_linkedin    = "https://www.linkedin.com/in/sandrawhitmore",
    contact_phone       = "",
    status              = "new",
    icp_profile_name    = "Financial Services — NYC",
    ingested_at         = _NOW,
    updated_at          = _NOW,
    is_in_crm           = False,
    is_excluded         = False,
)


# Public list of all mock prospects 
ALL_MOCK_PROSPECTS = [HEALTHAXIS, MERIDIAN_ANALYTICS, VANTAGE_CAPITAL]

#  Lookup by domain 
MOCK_PROSPECT_BY_DOMAIN = {p.domain: p for p in ALL_MOCK_PROSPECTS}


def get_mock_prospect(domain: str) -> Prospect:
    """
    Return the mock prospect matching a domain.
    Falls back to HEALTHAXIS if domain not found.

    Args:
        domain: company domain string

    Returns:
        Prospect instance
    """
    return MOCK_PROSPECT_BY_DOMAIN.get(domain, HEALTHAXIS)


def get_all_mock_prospects() -> list:
    """Return all three mock prospects as a list."""
    return list(ALL_MOCK_PROSPECTS)