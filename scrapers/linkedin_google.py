"""
scrapers/linkedin_google.py

Gets LinkedIn company data via Google search — zero LinkedIn ban risk.
Searches Google for the company's LinkedIn page and extracts employee
count / follower count from the SERP snippet.

This is a complement to linkedin_jobs.py — use both together. Google may
also rate-limit; failures are silent ([] / empty dict returned).
"""

from __future__ import annotations

import random
import re
import time
from typing import Dict

import requests
from bs4 import BeautifulSoup

from database import _log_error

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

_EMPLOYEE_PATTERNS = [
    r"([\d,]+)\s+followers",
    r"([\d,]+)\s+employees",
    r"([\d,]+)\s+connections",
]


def get_linkedin_snapshot(company_name: str) -> Dict:
    """
    Searches Google for the company's LinkedIn page.
    Extracts employee/follower count from the search snippet.

    Returns:
    {
        "employee_count_text": str,   e.g. "1,234 followers"
        "linkedin_url":        str,
        "snippet":             str,   raw Google snippet, capped at 300 chars
        "found":               bool,
    }
    """
    try:
        query = f"{company_name} site:linkedin.com/company"
        url   = f"https://www.google.com/search?q={requests.utils.quote(query)}&num=3"

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
        }

        time.sleep(random.uniform(3, 7))
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code != 200:
            return {
                "found":               False,
                "employee_count_text": "",
                "linkedin_url":        "",
                "snippet":             "",
            }

        soup = BeautifulSoup(resp.text, "html.parser")

        linkedin_url = ""
        snippet_text = ""

        for result in soup.select("div.g"):
            link = result.select_one("a")
            if not link:
                continue
            href = link.get("href", "")
            if "linkedin.com/company" in href:
                linkedin_url = href
                snippet_el = (
                    result.select_one("div.VwiC3b")
                    or result.select_one("span.st")
                )
                if snippet_el:
                    snippet_text = snippet_el.get_text(strip=True)
                break

        employee_text = ""
        for pattern in _EMPLOYEE_PATTERNS:
            m = re.search(pattern, snippet_text, re.IGNORECASE)
            if m:
                employee_text = m.group(0)
                break

        return {
            "found":               bool(linkedin_url),
            "employee_count_text": employee_text,
            "linkedin_url":        linkedin_url,
            "snippet":             snippet_text[:300],
        }

    except Exception as e:
        _log_error("linkedin_google.get_snapshot", f"{company_name}: {e}")
        return {
            "found":               False,
            "employee_count_text": "",
            "linkedin_url":        "",
            "snippet":             "",
        }


if __name__ == "__main__":
    import json
    print(json.dumps(get_linkedin_snapshot("Cityblock"), indent=2))
