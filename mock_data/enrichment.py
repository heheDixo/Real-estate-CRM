import datetime
from models.enrichment import EnrichmentResult, JobPosting, NewsSignal

_NOW = datetime.datetime.now().isoformat()



# ENRICHMENT 1 — HealthAxis
# All signals firing — designed to score Hot.


HEALTHAXIS_ENRICHMENT = EnrichmentResult(

    #  Identity 
    prospect_id  = "healthaxis.io",
    enriched_at  = _NOW,
    sources_used = ["apollo", "proxycurl", "newsapi"],
    sources_failed = [],

    #  Apollo block 
    headcount_6mo_ago  = 120,
    headcount_current  = 190,
    headcount_1yr_ago  = 95,
    founded_year       = 2018,
    description        = (
        "HealthAxis builds clinical workflow automation software for "
        "mid-sized hospital networks and multi-site ambulatory care groups. "
        "Their platform reduces administrative burden for clinical staff "
        "by automating scheduling, referrals, and prior authorisation."
    ),
    technologies = [
        "AWS", "React", "PostgreSQL", "Salesforce", "Slack", "Workday"
    ],
    keywords     = [
        "clinical workflow", "health tech", "SaaS", "EMR integration",
        "ambulatory care", "prior auth automation"
    ],
    annual_revenue = 18_000_000,   # estimated ARR

    #  Proxycurl block
    job_postings = [
        JobPosting(
            title              = "Office Manager — New York HQ",
            location           = "New York, NY",
            posted_date        = (
                datetime.datetime.now() - datetime.timedelta(days=12)
            ).strftime("%Y-%m-%d"),
            is_office_related  = True,
        ),
        JobPosting(
            title              = "Workplace Experience Lead",
            location           = "New York, NY",
            posted_date        = (
                datetime.datetime.now() - datetime.timedelta(days=18)
            ).strftime("%Y-%m-%d"),
            is_office_related  = True,
        ),
        JobPosting(
            title              = "Senior Software Engineer — Backend",
            location           = "New York, NY",
            posted_date        = (
                datetime.datetime.now() - datetime.timedelta(days=8)
            ).strftime("%Y-%m-%d"),
            is_office_related  = False,
        ),
        JobPosting(
            title              = "Product Manager — Platform",
            location           = "New York, NY",
            posted_date        = (
                datetime.datetime.now() - datetime.timedelta(days=22)
            ).strftime("%Y-%m-%d"),
            is_office_related  = False,
        ),
        JobPosting(
            title              = "Enterprise Account Executive",
            location           = "New York, NY",
            posted_date        = (
                datetime.datetime.now() - datetime.timedelta(days=5)
            ).strftime("%Y-%m-%d"),
            is_office_related  = False,
        ),
        JobPosting(
            title              = "Clinical Implementation Specialist",
            location           = "New York, NY",
            posted_date        = (
                datetime.datetime.now() - datetime.timedelta(days=31)
            ).strftime("%Y-%m-%d"),
            is_office_related  = False,
        ),
    ],
    total_jobs_posted        = 23,
    jobs_in_target_geo       = 21,
    office_roles_posted      = 2,
    top_job_titles           = [
        "Software Engineer", "Account Executive",
        "Implementation Specialist", "Product Manager"
    ],
    linkedin_follower_count  = 4_200,
    linkedin_employee_count  = 188,

    # NewsAPI block 
    news_signals = [
        NewsSignal(
            headline       = (
                "HealthAxis raises $42M Series B to expand clinical "
                "automation platform across New York and Boston markets"
            ),
            source         = "TechCrunch",
            published_date = (
                datetime.datetime.now() - datetime.timedelta(days=420)
            ).strftime("%Y-%m-%d"),
            url            = "https://techcrunch.com/healthaxis-series-b",
            signal_type    = "funding",
            excerpt        = (
                "HealthAxis, the New York-based clinical workflow automation "
                "platform, today announced a $42 million Series B led by "
                "General Catalyst. The company plans to use the funding to "
                "double its engineering team and expand its New York presence."
            ),
        ),
        NewsSignal(
            headline       = (
                "HealthAxis expands NYC headquarters to support 200% "
                "revenue growth, targets 300 employees by year end"
            ),
            source         = "Fierce Healthcare",
            published_date = (
                datetime.datetime.now() - datetime.timedelta(days=58)
            ).strftime("%Y-%m-%d"),
            url            = "https://fiercehealthcare.com/healthaxis-nyc",
            signal_type    = "expansion",
            excerpt        = (
                "HealthAxis is expanding its New York City footprint as the "
                "company targets 300 employees by Q4. The clinical automation "
                "startup has seen 200% revenue growth over the past 18 months "
                "and is actively recruiting across engineering, sales, and "
                "clinical implementation."
            ),
        ),
    ],
    total_news_signals         = 2,
    strongest_signal_type      = "expansion",
    strongest_signal_headline  = (
        "HealthAxis expands NYC headquarters to support 200% revenue growth, "
        "targets 300 employees by year end"
    ),
    strongest_signal_date      = (
        datetime.datetime.now() - datetime.timedelta(days=58)
    ).strftime("%Y-%m-%d"),
    has_expansion_news   = True,
    has_funding_news     = True,
    has_office_news      = True,
    has_relocation_news  = False,

    #  Computed fields 
    # These are pre-calculated here so the scorer can run immediately.
    headcount_growth_pct     = 58.3,    # (190-120)/120 * 100
    months_since_funding     = 14,
    is_in_deployment_window  = True,    # 10 <= 14 <= 20
    hiring_velocity_score    = 60.5,    # (23/190)*100 = 12.1 -> normalised
    triggers_fired = [
        "raised_funding_last_18_months",
        "headcount_growth_20pct_6months",
        "expansion_announcement_90_days",
        "office_role_posted",
        "hiring_velocity_high",
    ],
    triggers_count = 5,
    hf_description = (
        "HealthAxis is a Series B company based in New York with approximately "
        "190 employees. They raised Series B of $42,000,000 14 months ago. "
        "This puts them in the typical 12–18 month window when companies deploy "
        "capital on space. Headcount has grown 58.3% in the last 6 months, from "
        "120 to 190 employees. They have 23 active job postings, 21 of which are "
        "in New York, including 2 office or workplace management role(s). "
        "Recent news: HealthAxis expands NYC headquarters to support 200% revenue "
        "growth, targets 300 employees by year end. "
        "Detected signals: raised_funding_last_18_months, "
        "headcount_growth_20pct_6months, expansion_announcement_90_days, "
        "office_role_posted, hiring_velocity_high."
    ),
)



# ENRICHMENT 2 — Meridian Analytics
# Moderate signals — designed to score Warm.


MERIDIAN_ENRICHMENT = EnrichmentResult(

    prospect_id    = "meridiananalytics.com",
    enriched_at    = _NOW,
    sources_used   = ["apollo", "proxycurl", "newsapi"],
    sources_failed = [],

    # ── Apollo block ───────────────────────────────────────────────────────────
    headcount_6mo_ago  = 290,
    headcount_current  = 320,
    headcount_1yr_ago  = 260,
    founded_year       = 2016,
    description        = (
        "Meridian Analytics provides real-time data infrastructure and "
        "observability tooling for enterprise engineering teams. Their "
        "platform processes over 2 trillion events per day for customers "
        "across financial services, healthcare, and e-commerce."
    ),
    technologies = [
        "GCP", "Kubernetes", "Apache Kafka", "Snowflake",
        "Datadog", "Terraform", "Slack"
    ],
    keywords = [
        "data infrastructure", "observability", "real-time analytics",
        "enterprise", "DevOps"
    ],
    annual_revenue = 45_000_000,

    # Proxycurl block
    job_postings = [
        JobPosting(
            title             = "Senior Data Engineer",
            location          = "New York, NY",
            posted_date       = (
                datetime.datetime.now() - datetime.timedelta(days=14)
            ).strftime("%Y-%m-%d"),
            is_office_related = False,
        ),
        JobPosting(
            title             = "Enterprise Sales Director",
            location          = "New York, NY",
            posted_date       = (
                datetime.datetime.now() - datetime.timedelta(days=21)
            ).strftime("%Y-%m-%d"),
            is_office_related = False,
        ),
        JobPosting(
            title             = "Head of People Operations",
            location          = "New York, NY",
            posted_date       = (
                datetime.datetime.now() - datetime.timedelta(days=9)
            ).strftime("%Y-%m-%d"),
            is_office_related = False,
        ),
    ],
    total_jobs_posted        = 11,
    jobs_in_target_geo       = 9,
    office_roles_posted      = 0,
    top_job_titles           = [
        "Data Engineer", "Sales Director", "Solutions Architect"
    ],
    linkedin_follower_count  = 8_900,
    linkedin_employee_count  = 318,

    #  NewsAPI block
    news_signals = [
        NewsSignal(
            headline       = (
                "Meridian Analytics named to Forbes Cloud 100 for "
                "second consecutive year"
            ),
            source         = "Forbes",
            published_date = (
                datetime.datetime.now() - datetime.timedelta(days=95)
            ).strftime("%Y-%m-%d"),
            url            = "https://forbes.com/cloud100/meridian",
            signal_type    = "recognition",
            excerpt        = (
                "Meridian Analytics has been named to the Forbes Cloud 100 "
                "for the second year running, recognising its growth in the "
                "enterprise data infrastructure market."
            ),
        ),
    ],
    total_news_signals         = 1,
    strongest_signal_type      = "recognition",
    strongest_signal_headline  = (
        "Meridian Analytics named to Forbes Cloud 100 for second consecutive year"
    ),
    strongest_signal_date      = (
        datetime.datetime.now() - datetime.timedelta(days=95)
    ).strftime("%Y-%m-%d"),
    has_expansion_news   = False,
    has_funding_news     = False,
    has_office_news      = False,
    has_relocation_news  = False,

    # ── Computed fields ────────────────────────────────────────────────────────
    headcount_growth_pct     = 10.3,   # moderate growth
    months_since_funding     = 22,     # past deployment window
    is_in_deployment_window  = False,
    hiring_velocity_score    = 17.2,
    triggers_fired = [
        "headcount_growth_20pct_6months",   # borderline — 10% doesn't hit 20%
    ],
    triggers_count = 0,   # did not hit min_triggers_required of 2
    hf_description = (
        "Meridian Analytics is a Series C company based in New York with "
        "approximately 320 employees. They raised Series C of $78,000,000 "
        "22 months ago. Headcount has grown 10.3% in the last 6 months. "
        "They have 11 active job postings, 9 of which are in New York. "
        "No office or workplace roles posted. "
        "No significant expansion announcements detected. "
        "Detected signals: none above threshold."
    ),
)



# ENRICHMENT 3 — Vantage Capital Partners
# Strong lease expiry and headcount signals — designed to score Hot/Warm.


VANTAGE_ENRICHMENT = EnrichmentResult(

    prospect_id    = "vantagecapitalpartners.com",
    enriched_at    = _NOW,
    sources_used   = ["apollo", "proxycurl", "newsapi"],
    sources_failed = [],

    # Apollo block
    headcount_6mo_ago  = 85,
    headcount_current  = 140,
    headcount_1yr_ago  = 70,
    founded_year       = 2008,
    description        = (
        "Vantage Capital Partners is a mid-market private equity firm "
        "focused on healthcare services, business services, and technology "
        "companies in North America. They manage approximately $2.4B in AUM "
        "across three active funds."
    ),
    technologies = [
        "Salesforce", "Microsoft 365", "Bloomberg Terminal",
        "Carta", "DocuSign"
    ],
    keywords = [
        "private equity", "mid-market", "healthcare services",
        "business services", "growth equity"
    ],
    annual_revenue = 0,   # PE — revenue not applicable

    #  Proxycurl block
    job_postings = [
        JobPosting(
            title             = "Office and Facilities Manager",
            location          = "New York, NY",
            posted_date       = (
                datetime.datetime.now() - datetime.timedelta(days=7)
            ).strftime("%Y-%m-%d"),
            is_office_related = True,
        ),
        JobPosting(
            title             = "Vice President — Healthcare Services",
            location          = "New York, NY",
            posted_date       = (
                datetime.datetime.now() - datetime.timedelta(days=15)
            ).strftime("%Y-%m-%d"),
            is_office_related = False,
        ),
        JobPosting(
            title             = "Senior Associate — Deal Sourcing",
            location          = "New York, NY",
            posted_date       = (
                datetime.datetime.now() - datetime.timedelta(days=20)
            ).strftime("%Y-%m-%d"),
            is_office_related = False,
        ),
        JobPosting(
            title             = "Chief Financial Officer",
            location          = "New York, NY",
            posted_date       = (
                datetime.datetime.now() - datetime.timedelta(days=11)
            ).strftime("%Y-%m-%d"),
            is_office_related = False,
        ),
    ],
    total_jobs_posted        = 14,
    jobs_in_target_geo       = 14,
    office_roles_posted      = 1,
    top_job_titles           = [
        "Vice President", "Senior Associate",
        "Associate", "Principal"
    ],
    linkedin_follower_count  = 2_100,
    linkedin_employee_count  = 138,

    #  NewsAPI block
    news_signals = [
        NewsSignal(
            headline       = (
                "Vantage Capital Partners closes third fund at $850M, "
                "plans to double New York investment team"
            ),
            source         = "Private Equity International",
            published_date = (
                datetime.datetime.now() - datetime.timedelta(days=490)
            ).strftime("%Y-%m-%d"),
            url            = "https://pei.com/vantage-capital-fund-iii",
            signal_type    = "funding",
            excerpt        = (
                "Vantage Capital Partners has closed its third fund at $850 "
                "million hard cap, exceeding its $700 million target. The firm "
                "plans to expand its New York investment team from 85 to over "
                "150 professionals over the next 18 months."
            ),
        ),
        NewsSignal(
            headline       = (
                "Vantage Capital hires four senior MDs from major PE shops "
                "as New York team expansion continues"
            ),
            source         = "PE Hub",
            published_date = (
                datetime.datetime.now() - datetime.timedelta(days=62)
            ).strftime("%Y-%m-%d"),
            url            = "https://pehub.com/vantage-hiring",
            signal_type    = "hiring",
            excerpt        = (
                "Vantage Capital Partners has added four Managing Directors "
                "poached from Blackstone, KKR, Apollo, and Warburg Pincus as "
                "the firm continues its aggressive New York expansion."
            ),
        ),
    ],
    total_news_signals         = 2,
    strongest_signal_type      = "hiring",
    strongest_signal_headline  = (
        "Vantage Capital hires four senior MDs from major PE shops "
        "as New York team expansion continues"
    ),
    strongest_signal_date      = (
        datetime.datetime.now() - datetime.timedelta(days=62)
    ).strftime("%Y-%m-%d"),
    has_expansion_news   = True,
    has_funding_news     = True,
    has_office_news      = True,
    has_relocation_news  = False,

    # Computed fields 
    headcount_growth_pct     = 64.7,   # (140-85)/85 * 100 — very strong
    months_since_funding     = 16,
    is_in_deployment_window  = True,
    hiring_velocity_score    = 50.0,
    triggers_fired = [
        "raised_funding_last_18_months",
        "headcount_growth_20pct_6months",
        "expansion_announcement_90_days",
        "office_role_posted",
        "hiring_velocity_high",
    ],
    triggers_count = 5,
    hf_description = (
        "Vantage Capital Partners is a Growth / PE-backed company based in "
        "New York with approximately 140 employees. They completed a Management "
        "Buyout 16 months ago. This puts them in the typical 12–18 month window "
        "when companies deploy capital on space. Headcount has grown 64.7% in "
        "the last 6 months, from 85 to 140 employees. They have 14 active job "
        "postings, all in New York, including 1 office or workplace management "
        "role. Recent news: Vantage Capital hires four senior MDs from major PE "
        "shops as New York team expansion continues. "
        "Detected signals: raised_funding_last_18_months, "
        "headcount_growth_20pct_6months, expansion_announcement_90_days, "
        "office_role_posted, hiring_velocity_high."
    ),
)


# Public lookup 
ALL_MOCK_ENRICHMENTS = {
    "healthaxis.io":              HEALTHAXIS_ENRICHMENT,
    "meridiananalytics.com":      MERIDIAN_ENRICHMENT,
    "vantagecapitalpartners.com": VANTAGE_ENRICHMENT,
}


def get_mock_enrichment(prospect_id: str) -> EnrichmentResult:
    """
    Return the pre-built enrichment for a given prospect domain.
    Falls back to HEALTHAXIS_ENRICHMENT if domain not found.

    Args:
        prospect_id: company domain string

    Returns:
        EnrichmentResult instance
    """
    return ALL_MOCK_ENRICHMENTS.get(prospect_id, HEALTHAXIS_ENRICHMENT)