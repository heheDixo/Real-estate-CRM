"""
scrapers/crunchbase_scraper.py

Crunchbase public data scraper — no API key required for basic searches.

Uses two public-facing endpoints:
  1. Crunchbase autocomplete API — resolves company names to real entities
  2. Crunchbase recent funding RSS via Google News RSS (sector-filtered)
     Google indexes Crunchbase funding pages and the RSS surfaces them.

Why Crunchbase matters for CRE lead quality:
  - Crunchbase is the canonical source for startup funding data
  - A company on Crunchbase with a recent raise is guaranteed to be real
  - The funding date gives us the exact deployment window start
  - Headquarters city is often included

Rate limits: None documented for the autocomplete endpoint; be polite.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import time
import urllib.parse
from typing import Dict, List, Optional

import requests

try:
    import feedparser
    _FEEDPARSER_OK = True
except ImportError:
    _FEEDPARSER_OK = False


# ── Constants ────────────────────────────────────────────────────────────────

_AUTOCOMPLETE_URL = (
    "https://www.crunchbase.com/v4/data/autocompletes"
    "?query={query}&collection_ids=organizations&limit=5"
)

# Crunchbase funding news surfaced via Google News RSS
# e.g. "site:crunchbase.com funding Atlanta technology"
_GNEWS_BASE = "https://news.google.com/rss/search"

_TIMEOUT    = 15
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# ── Error log ────────────────────────────────────────────────────────────────


def _log_error(scope: str, exc) -> None:
    try:
        path = os.path.join("data", "error_log.json")
        os.makedirs("data", exist_ok=True)
        log = []
        if os.path.exists(path):
            try:
                with open(path) as f:
                    log = json.load(f) or []
            except Exception:
                log = []
        log.append({
            "at":    datetime.datetime.now().isoformat(),
            "scope": scope,
            "error": str(exc)[:280],
            "type":  type(exc).__name__ if isinstance(exc, Exception) else "info",
        })
        with open(path, "w") as f:
            json.dump(log[-200:], f, indent=2)
    except Exception:
        pass


# ── Autocomplete resolver ────────────────────────────────────────────────────


def resolve_company(name: str) -> Optional[Dict]:
    """
    Check if a company name resolves to a real Crunchbase entity.

    Returns:
        dict with {name, permalink, short_description, city} or None
    """
    url = _AUTOCOMPLETE_URL.format(query=urllib.parse.quote_plus(name))
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent":   _USER_AGENT,
                "Accept":       "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        _log_error("crunchbase.autocomplete.network", exc)
        return None

    if resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except ValueError:
        return None

    entities = data.get("entities") or []
    if not entities:
        return None

    # Take the first hit — autocomplete ranks by relevance
    ent = entities[0]
    props = ent.get("properties") or {}
    return {
        "name":              props.get("name") or name,
        "permalink":         ent.get("identifier", {}).get("permalink", ""),
        "short_description": props.get("short_description", ""),
        "city":              props.get("city_name") or props.get("location_identifiers", [{}])[0].get("value", "") if props.get("location_identifiers") else "",
        "crunchbase_url":    f"https://www.crunchbase.com/organization/{ent.get('identifier', {}).get('permalink', '')}",
    }


# ── RSS-based recent funding discovery ──────────────────────────────────────


def _gnews_rss(query: str, max_items: int = 15) -> List[Dict]:
    """Fetch Google News RSS items for a Crunchbase-related funding query."""
    if not _FEEDPARSER_OK:
        return []

    full_query = f"site:crunchbase.com {query}"
    url = f"{_GNEWS_BASE}?q={urllib.parse.quote_plus(full_query)}"

    try:
        feed = feedparser.parse(url, agent=_USER_AGENT)
    except Exception as exc:
        _log_error("crunchbase.gnews_rss.parse", exc)
        return []

    items = []
    for entry in feed.entries[:max_items]:
        items.append({
            "title":       getattr(entry, "title", ""),
            "description": getattr(entry, "summary", ""),
            "url":         getattr(entry, "link", ""),
            "source":      "Crunchbase via Google News",
        })

    return items


# ── Company-name extraction from Crunchbase RSS titles ───────────────────────


_FUNDING_TITLE_RE = re.compile(
    # "Acme Corp Raises $12M Series B" or "Acme Corp Secures $5M Seed"
    r"^(.+?)\s+(?:raises?|secures?|closes?|announces?|lands?|gets?)\s+\$[\d,.]+[MBK]",
    re.IGNORECASE,
)

_AMOUNT_RE = re.compile(r"\$\s*([\d,.]+)\s*([MBK])", re.IGNORECASE)


def _parse_amount_usd(text: str) -> int:
    """Parse '$12.5M' → 12500000, '$500K' → 500000, etc."""
    m = _AMOUNT_RE.search(text)
    if not m:
        return 0
    try:
        num = float(m.group(1).replace(",", ""))
        suffix = m.group(2).upper()
        if suffix == "B":
            return int(num * 1_000_000_000)
        if suffix == "M":
            return int(num * 1_000_000)
        if suffix == "K":
            return int(num * 1_000)
    except ValueError:
        pass
    return 0


def scrape_recent_funding(
    geo: str = "Atlanta",
    sector: str = "technology",
    days_back: int = 540,
    max_results: int = 25,
) -> List[Dict]:
    """
    Discover recently funded companies from Crunchbase via Google News RSS.

    Args:
        geo:        city or region to filter by (e.g. \"Atlanta\", \"Georgia\")
        sector:     industry keyword
        days_back:  look-back window in days
        max_results: cap on returned companies

    Returns:
        list of dicts: {company, amount_usd, source, source_url, industry_hint}
    """
    queries = [
        f"funding {sector} {geo}",
        f"series {geo} {sector}",
        f"raises million {geo}",
    ]

    results: List[Dict] = []
    seen: set = set()

    for q in queries:
        if len(results) >= max_results:
            break

        items = _gnews_rss(q, max_items=15)
        time.sleep(1.0)   # polite delay

        for item in items:
            title = item.get("title", "")
            m = _FUNDING_TITLE_RE.match(title)
            if not m:
                continue

            company = m.group(1).strip()
            # Strip common suffixes that aren't part of the name
            company = re.sub(
                r"\s+(Inc\.?|LLC|Ltd\.?|Corp\.?|Co\.?)$", "", company, flags=re.IGNORECASE
            ).strip()

            if not company or company.lower() in seen or len(company) < 3:
                continue
            seen.add(company.lower())

            amount_usd = _parse_amount_usd(title)

            results.append({
                "company":       company,
                "amount_usd":    amount_usd,
                "source":        "Crunchbase / Google News RSS",
                "source_url":    item.get("url", ""),
                "industry_hint": sector,
                "title":         title,
                "description":   item.get("description", "")[:300],
            })

            if len(results) >= max_results:
                break

    return results


# ── Public entry point ───────────────────────────────────────────────────────


def scrape(
    geo: str = "Atlanta",
    sectors: Optional[List[str]] = None,
    days_back: int = 540,
    max_results: int = 20,
) -> List[Dict]:
    """
    Public entry point matching the interface of edgar_scraper.scrape().

    Returns a list of recently funded companies found on Crunchbase.
    """
    sectors = sectors or ["technology", "healthcare", "SaaS", "fintech"]
    results: List[Dict] = []
    seen: set = set()

    for sector in sectors:
        if len(results) >= max_results:
            break
        batch = scrape_recent_funding(
            geo=geo, sector=sector, days_back=days_back,
            max_results=max_results - len(results),
        )
        for item in batch:
            key = item["company"].lower()
            if key not in seen:
                seen.add(key)
                results.append(item)

    return results[:max_results]


# ── CLI test ─────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("Fetching recent Crunchbase funding events (Atlanta)...")
    results = scrape(geo="Atlanta", days_back=180, max_results=10)
    for r in results:
        amt = f"${r['amount_usd']:,}" if r.get("amount_usd") else "undisclosed"
        print(f"  {r['company']:40}  {amt:>15}  [{r['industry_hint']}]")
    print(f"\nTotal: {len(results)} companies found")

    print("\nResolving 'Salesloft' on Crunchbase...")
    cb = resolve_company("Salesloft")
    print(json.dumps(cb, indent=2) if cb else "Not found")
