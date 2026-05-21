"""
NewsAPI free-tier scraper (newsapi.org).
Free tier: 100 requests/day, articles up to 24h old in the free plan.

Reads NEWSAPI_KEY from environment via config.
Returns empty list silently if the key is missing or rate-limited.
"""

import datetime
from typing import List, Dict

import requests
import config


_ENDPOINT = "https://newsapi.org/v2/everything"
_TIMEOUT  = 15


def scrape(company_name: str, max_articles: int = 5,
           hours_back: int = 168) -> List[Dict]:
    """
    Search NewsAPI for recent mentions of the company.

    Args:
        company_name: company display name
        max_articles: cap on returned items (NewsAPI free pageSize cap is 100)
        hours_back:   only return items published within this many hours

    Returns:
        list of dicts with keys: title, description, url, published_at,
        source_name. Empty list on any failure.
    """
    if not config.NEWSAPI_AVAILABLE or not company_name:
        return []

    from_date = (datetime.datetime.utcnow() -
                 datetime.timedelta(hours=hours_back)).isoformat() + "Z"

    params = {
        "q":         f"\"{company_name}\"",
        "from":      from_date,
        "sortBy":    "publishedAt",
        "language":  "en",
        "pageSize":  min(max_articles, 20),
        "apiKey":    config.NEWSAPI_KEY,
    }

    try:
        resp = requests.get(_ENDPOINT, params=params, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        print(f"[newsapi] request failed for {company_name}: {exc}")
        return []

    if resp.status_code != 200:
        print(f"[newsapi] returned {resp.status_code} for {company_name}")
        return []

    try:
        data = resp.json()
    except ValueError:
        return []

    items: List[Dict] = []
    for article in data.get("articles", [])[:max_articles]:
        items.append({
            "title":        (article.get("title")       or "").strip(),
            "description":  (article.get("description") or "").strip(),
            "url":          article.get("url", ""),
            "published_at": article.get("publishedAt", ""),
            "source_name":  (article.get("source") or {}).get("name", "NewsAPI"),
        })

    return items


if __name__ == "__main__":
    import json
    print(json.dumps(scrape("Microsoft", max_articles=3), indent=2))
