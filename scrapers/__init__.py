"""
Free data-source scrapers used by the morning research pipeline.

Each module exposes a single `scrape(...)` function returning a list of dicts
(or a dict for verifiers). All scrapers must be defensive — never raise
into the caller. On any failure return an empty list / safe default.

Real-data sources (open, no paid key):
  - SEC EDGAR Form D filings     (edgar_scraper)
  - Crunchbase funding RSS       (crunchbase_scraper)
  - Greenhouse / Ashby / Lever   (jobs_board)
  - Google News RSS              (google_news)
  - Hacker News Algolia API      (via lead_discovery)

Contact-resolution sources:
  - Hunter.io multi-domain resolver (hunter_company_search)
  - Hunter.io email verifier        (hunter_verify)
"""

from scrapers.google_news        import scrape as scrape_google_news
from scrapers.newsapi_scraper    import scrape as scrape_newsapi
from scrapers.hunter_verify      import verify as verify_hunter_email
from scrapers.firecrawl_scraper  import scrape as scrape_firecrawl
from scrapers.apollo_scraper     import (
    enrich_organization  as apollo_enrich_org,
    search_organizations as scrape_apollo_orgs,
    search_people        as scrape_apollo_people,
    reveal_email         as apollo_reveal_email,
)
from scrapers.jobs_board         import scrape as scrape_jobs_board
from scrapers.linkedin_jobs      import (
    scrape_linkedin_jobs,
    summarise_jobs as summarise_linkedin_jobs,
)
from scrapers.linkedin_google    import get_linkedin_snapshot

# ── New real-data sources ────────────────────────────────────────────────────
from scrapers.edgar_scraper      import scrape as scrape_edgar_filings
from scrapers.crunchbase_scraper import scrape as scrape_crunchbase_funding
from scrapers.hunter_company_search import (
    find_contact       as hunter_find_contact,
    find_company_domain as hunter_find_domain,
    domain_search      as hunter_domain_search,
)

__all__ = [
    # Article / news
    "scrape_google_news",
    "scrape_newsapi",
    # Company enrichment
    "verify_hunter_email",
    "scrape_firecrawl",
    "apollo_enrich_org",
    "scrape_apollo_orgs",
    "scrape_apollo_people",
    "apollo_reveal_email",
    # Job boards
    "scrape_jobs_board",
    "scrape_linkedin_jobs",
    "summarise_linkedin_jobs",
    # LinkedIn
    "get_linkedin_snapshot",
    # Real-data lead discovery (new)
    "scrape_edgar_filings",
    "scrape_crunchbase_funding",
    # Hunter contact resolution (new — multi-domain strategy)
    "hunter_find_contact",
    "hunter_find_domain",
    "hunter_domain_search",
]
