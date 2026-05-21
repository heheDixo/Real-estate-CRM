"""
Firecrawl scraper — extracts clean text from a company website (About,
News/Blog). Free tier; defensive on missing key or failure.

Reads FIRECRAWL_API_KEY from config.
"""

from typing import Dict
import requests

import config


_ENDPOINT = "https://api.firecrawl.dev/v0/scrape"
_TIMEOUT  = 30


def _scrape_url(url: str) -> str:
    if not config.FIRECRAWL_AVAILABLE or not url:
        return ""

    headers = {
        "Authorization": f"Bearer {config.FIRECRAWL_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {"url": url, "pageOptions": {"onlyMainContent": True}}

    try:
        resp = requests.post(
            _ENDPOINT, headers=headers, json=payload, timeout=_TIMEOUT
        )
    except requests.RequestException as exc:
        print(f"[firecrawl] request failed for {url}: {exc}")
        return ""

    if resp.status_code != 200:
        print(f"[firecrawl] returned {resp.status_code} for {url}")
        return ""

    try:
        data = resp.json().get("data", {})
    except ValueError:
        return ""

    return (data.get("markdown") or data.get("content") or "").strip()[:8000]


def scrape(website_url: str) -> Dict:
    """
    Fetch the company homepage plus likely About/News pages.

    Args:
        website_url: company website (e.g. "https://www.healthaxis.io")

    Returns:
        dict with keys: home, about, news. Empty strings on failure.
    """
    if not website_url:
        return {"home": "", "about": "", "news": ""}

    base = website_url.rstrip("/")
    return {
        "home":  _scrape_url(base),
        "about": _scrape_url(f"{base}/about"),
        "news":  _scrape_url(f"{base}/news") or _scrape_url(f"{base}/blog"),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(scrape("https://www.stripe.com"), indent=2)[:1000])
