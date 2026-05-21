"""
Google News RSS scraper. No API key required.

URL:  https://news.google.com/rss/search?q={company+name}
Limit: 1 request every 2 seconds, max 5 articles per company, last 7 days
by default (override via ``hours_back``).
"""

import datetime
import time
import urllib.parse
from typing import List, Dict

try:
    import feedparser
    _FEEDPARSER_AVAILABLE = True
except ImportError:
    _FEEDPARSER_AVAILABLE = False

_LAST_REQUEST_TIME = 0.0
_MIN_INTERVAL_SEC  = 2.0
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _rate_limit():
    global _LAST_REQUEST_TIME
    elapsed = time.time() - _LAST_REQUEST_TIME
    if elapsed < _MIN_INTERVAL_SEC:
        time.sleep(_MIN_INTERVAL_SEC - elapsed)
    _LAST_REQUEST_TIME = time.time()


def scrape(company_name: str, max_articles: int = 5,
           hours_back: int = 168) -> List[Dict]:
    """
    Fetch recent news mentions of a company from Google News RSS.

    Args:
        company_name: company display name (e.g. "HealthAxis")
        max_articles: cap on returned items
        hours_back:   only return items published within this many hours

    Returns:
        list of dicts with keys: title, description, url, published_at,
        source_name. Empty list on any failure.
    """
    if not _FEEDPARSER_AVAILABLE or not company_name:
        return []

    _rate_limit()

    query = urllib.parse.quote_plus(company_name)
    url   = f"https://news.google.com/rss/search?q={query}"

    try:
        feed = feedparser.parse(url, agent=_USER_AGENT)
    except Exception as exc:
        print(f"[google_news] parse failed for {company_name}: {exc}")
        return []

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours_back)
    items: List[Dict] = []

    for entry in feed.entries[: max_articles * 3]:   # over-fetch then filter
        published = _parse_date(entry)
        if published and published < cutoff:
            continue

        source_name = ""
        if hasattr(entry, "source") and isinstance(entry.source, dict):
            source_name = entry.source.get("title", "")
        elif hasattr(entry, "source"):
            source_name = getattr(entry.source, "title", "") or ""

        items.append({
            "title":        getattr(entry, "title", "").strip(),
            "description":  _clean_summary(getattr(entry, "summary", "")),
            "url":          getattr(entry, "link", ""),
            "published_at": published.isoformat() if published else "",
            "source_name":  source_name or "Google News",
        })

        if len(items) >= max_articles:
            break

    return items


def _parse_date(entry) -> datetime.datetime | None:
    parsed = getattr(entry, "published_parsed", None) or \
             getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    try:
        return datetime.datetime(*parsed[:6])
    except (TypeError, ValueError):
        return None


def _clean_summary(html: str) -> str:
    """Strip HTML tags from RSS summaries."""
    if not html:
        return ""
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500]


if __name__ == "__main__":
    import json
    sample = scrape("Microsoft", max_articles=3)
    print(json.dumps(sample, indent=2))
