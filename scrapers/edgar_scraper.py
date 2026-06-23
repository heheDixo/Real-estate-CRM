"""
scrapers/edgar_scraper.py

SEC EDGAR Form D scraper — completely free, no API key, real data.

Form D is filed when a company raises a private placement (Reg D offering).
It is a legally mandated disclosure — company names are verified, amounts
are real, and dates are exact.

Uses the official EDGAR company search endpoint:
  https://www.sec.gov/cgi-bin/browse-edgar
  ?action=getcompany&State=GA&SIC=7372&type=D&dateb=&owner=include&count=40

Then resolves each CIK to get filing dates from:
  https://data.sec.gov/submissions/CIK{zero_padded_cik}.json

User-Agent with email is REQUIRED per EDGAR fair-access policy.
Rate limit: 10 req/sec max. We stay well under that.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

# ── Constants ────────────────────────────────────────────────────────────────

_BASE_EDGAR = "https://www.sec.gov"
_DATA_SEC   = "https://data.sec.gov"
_TIMEOUT    = 20
_USER_AGENT = "AbsolvCREResearch/1.0 research@absolv.com"

# SIC codes for office-space-needing companies
# 7372 = Prepackaged Software, 7371 = Computer Programming
# 7374 = Computer Processing / Data Prep, 8099 = Health Services
# 6282 = Investment Advice (fintech)
_PRIORITY_SICS = [
    "7372",   # Software / SaaS
    "7371",   # Computer programming
    "8099",   # Health services
    "7374",   # Computer data processing
    "6282",   # Investment advice / fintech
    "7389",   # Services - misc business (consulting)
    "8742",   # Management consulting
]

# Patterns that indicate a fund / SPV rather than an operating company
_SKIP_RE = re.compile(
    r"\b(fund|funds|lp\b|l\.p\.|llp|trust|reit|spv|feeder|"
    r"opportunity|holdings|partners|investors|capital partners)\b",
    re.IGNORECASE,
)


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
        })
        with open(path, "w") as f:
            json.dump(log[-200:], f, indent=2)
    except Exception:
        pass


def _get(url: str, params: Optional[Dict] = None) -> Optional[requests.Response]:
    try:
        resp = requests.get(
            url,
            params=params,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept":     "text/html,application/json",
            },
            timeout=_TIMEOUT,
        )
        return resp
    except requests.RequestException as exc:
        _log_error(f"edgar.get", exc)
        return None


# ── EDGAR company-browse HTML parser ────────────────────────────────────────


def _browse_edgar_form_d(state: str, sic: str, count: int = 40) -> List[Dict]:
    """
    Fetch EDGAR company search results for a state + SIC code, Form D type.
    Parses the results HTML table.
    Returns list of {company, cik, last_filing_date}.
    """
    url = f"{_BASE_EDGAR}/cgi-bin/browse-edgar"
    params = {
        "action":      "getcompany",
        "State":       state,
        "SIC":         sic,
        "type":        "D",
        "dateb":       "",
        "owner":       "include",
        "count":       count,
        "search_text": "",
    }

    resp = _get(url, params=params)
    if not resp or resp.status_code != 200:
        return []

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return []

    results: List[Dict] = []

    # EDGAR results are in a table — rows have company name links and CIK numbers
    table = soup.find("table", {"class": "tableFile2"}) or soup.find("table", summary=re.compile(r"Result", re.I))
    if not table:
        # Fallback: parse any table that has CIK-looking data
        tables = soup.find_all("table")
        for t in tables:
            rows = t.find_all("tr")
            if len(rows) > 2:
                table = t
                break

    if not table:
        return []

    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        # EDGAR table: col0 = CIK (link to company page), col1 = company name + SIC
        cik_cell  = cells[0].get_text(strip=True)
        name_cell = cells[1].get_text(strip=True) if len(cells) > 1 else ""

        # Extract just the company name from "COMPANY NAMESIC:XXXX - description STATE"
        # or "COMPANY NAME SIC:XXXX - description"
        entity = re.split(r"\s*SIC:", name_cell, maxsplit=1)[0].strip()
        # Also strip trailing state abbreviation (last 2 uppercase chars)
        entity = re.sub(r"\s+[A-Z]{2}$", "", entity).strip()
        if not entity or len(entity) < 3:
            continue

        # Extract CIK from the first cell
        cik = ""
        if cik_cell.isdigit():
            cik = cik_cell.lstrip("0") or cik_cell
        else:
            link = cells[0].find("a", href=True)
            if link:
                m = re.search(r"CIK=?(\d+)", link["href"], re.IGNORECASE)
                if m:
                    cik = str(int(m.group(1)))

        if _SKIP_RE.search(entity):
            continue

        results.append({
            "company":    entity,
            "cik":        cik,
            "sic":        sic,
            "state":      state,
        })

    return results


# ── Filing-date lookup via data.sec.gov ─────────────────────────────────────


def _get_last_form_d_date(cik: str, days_back: int) -> Optional[str]:
    """
    Check data.sec.gov/submissions/CIK{cik}.json for the most recent Form D date.
    Returns the date string if within days_back, else None.
    """
    if not cik:
        return None

    cik_padded = cik.zfill(10)
    url = f"{_DATA_SEC}/submissions/CIK{cik_padded}.json"
    resp = _get(url)
    if not resp or resp.status_code != 200:
        return None

    try:
        data = resp.json()
    except ValueError:
        return None

    filings = data.get("filings") or {}
    recent  = filings.get("recent") or {}
    forms   = recent.get("form") or []
    dates   = recent.get("filingDate") or []

    cutoff = datetime.date.today() - datetime.timedelta(days=days_back)

    for form, date_str in zip(forms, dates):
        if form.upper().startswith("D"):
            try:
                filed = datetime.date.fromisoformat(date_str[:10])
                if filed >= cutoff:
                    return date_str[:10]
            except ValueError:
                pass

    return None


# ── Public API ───────────────────────────────────────────────────────────────


def scrape(
    state: str = "GA",
    industry_keywords: Optional[List[str]] = None,
    days_back: int = 540,
    max_results: int = 20,
) -> List[Dict]:
    """
    Public entry point. Returns list of dicts with 'company' and 'file_date'.

    Queries EDGAR's state+SIC company search to find real companies that
    filed Form D (private placement) within days_back.
    """
    candidates: List[Dict] = []
    seen: set = set()

    for sic in _PRIORITY_SICS:
        if len(candidates) >= max_results * 3:  # over-collect before date filter
            break
        batch = _browse_edgar_form_d(state, sic, count=40)
        time.sleep(0.2)
        for item in batch:
            key = item["company"].lower()
            if key not in seen:
                seen.add(key)
                candidates.append(item)

    # Verify filing date is within window (with rate-limited API calls)
    results: List[Dict] = []
    for item in candidates:
        if len(results) >= max_results:
            break
        cik = item.get("cik", "")
        date_str = _get_last_form_d_date(cik, days_back) if cik else None
        time.sleep(0.12)

        if date_str:
            results.append({
                "company":      item["company"],
                "file_date":    date_str,
                "state":        item.get("state", state),
                "cik":          cik,
                "source":       "SEC EDGAR Form D",
                "source_url":   f"{_BASE_EDGAR}/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=D",
                "industry_hint": item.get("sic", ""),
            })

    return results


def search_recent_form_d(
    state: str = "GA",
    industry_keywords: Optional[List[str]] = None,
    days_back: int = 540,
    max_results: int = 30,
) -> List[Dict]:
    """Alias for scrape() — kept for backward compatibility."""
    return scrape(state=state, industry_keywords=industry_keywords,
                  days_back=days_back, max_results=max_results)


# ── CLI test ─────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("Fetching recent Form D filings from SEC EDGAR (Georgia, 540 days)...")
    results = scrape(state="GA", days_back=540, max_results=8)
    for r in results:
        company = r.get("company", "")[:45]
        filed   = r.get("file_date", "")
        sic     = r.get("industry_hint", "")
        print(f"  {company:45}  filed {filed}  SIC={sic}")
    print(f"\nTotal: {len(results)} companies found")
