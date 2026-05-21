"""
Free data-source scrapers used by the morning research pipeline.

Each module exposes a single `scrape(...)` function returning a list of dicts
(or a dict for verifiers). All scrapers must be defensive — never raise
into the caller. On any failure return an empty list / safe default.
"""

from scrapers.google_news      import scrape as scrape_google_news
from scrapers.newsapi_scraper  import scrape as scrape_newsapi
from scrapers.hunter_verify    import verify as verify_hunter_email
from scrapers.firecrawl_scraper import scrape as scrape_firecrawl

__all__ = [
    "scrape_google_news",
    "scrape_newsapi",
    "verify_hunter_email",
    "scrape_firecrawl",
]
