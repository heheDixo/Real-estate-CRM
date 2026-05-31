"""
scrapers/linkedin_jobs.py

Scrapes LinkedIn public job search page as a guest (no login).
Rate limited to 1 request per 30 seconds to avoid blocks.
Returns [] on any failure — never crashes the pipeline.

LinkedIn aggressively serves auth-walls / 429s to non-browser traffic, so
expect a high fraction of requests to return []. The 30s minimum delay is
a hard floor — do not lower it.

What we look for:
- Office Manager, Workplace Experience, Facilities = direct space signal
- High job count relative to company size = hiring velocity signal
"""

from __future__ import annotations

import random
import time
from typing import Dict, List

import requests
from bs4 import BeautifulSoup

from database import _log_error

# Single source-of-truth label for any Signal whose data came from this
# scraper. Imported by research_agent so the brief / signal cards show one
# consistent string instead of two near-duplicates.
SOURCE_LABEL = "LinkedIn Jobs · last 7 days"

# Strict rate limiting — do not lower this
MIN_DELAY_SECONDS = 30

# Retry-with-jitter window on empty result — LinkedIn intermittently returns
# 200 OK with no job cards rendered (silent rate-limit). One retry after a
# longer cooldown raises success rate noticeably without burning quota.
RETRY_SLEEP_MIN_SECONDS = 45
RETRY_SLEEP_MAX_SECONDS = 90

# Office-specific role keywords — these are direct CRE signals
OFFICE_SIGNAL_KEYWORDS = [
    "office manager",
    "workplace experience",
    "workplace manager",
    "facilities manager",
    "facilities director",
    "real estate manager",
    "office coordinator",
    "office operations",
    "head of real estate",
    "vp real estate",
    "director of facilities",
]

# Hiring velocity keywords — indicates growth
GROWTH_KEYWORDS = [
    "head of people",
    "people operations",
    "chief of staff",
    "vp operations",
    "director of operations",
    "head of operations",
]

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

# Track last request time globally to enforce rate limit across all calls
_last_request_time: float = 0.0


def _wait_rate_limit() -> None:
    """Enforces minimum delay between requests."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_DELAY_SECONDS:
        wait = MIN_DELAY_SECONDS - elapsed + random.uniform(2, 8)
        time.sleep(wait)
    _last_request_time = time.time()


def _scrape_attempt(company_name: str, city: str, max_jobs: int) -> List[Dict]:
    """
    One scrape attempt — respects the global rate limit, returns [] on any
    failure. Callers wrap this with retry logic.
    """
    try:
        _wait_rate_limit()

        # The public /jobs/search/ page is now guest-blocked (returns a
        # "Sign in" landing page with no results). The guest-API endpoint
        # below still renders job cards without a session.
        url = (
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/"
            "search"
            f"?keywords={requests.utils.quote(company_name)}"
            f"&location={requests.utils.quote(city)}"
            "&f_TPR=r604800"  # last 7 days
            "&start=0"
        )

        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code == 429:
            _log_error(
                "linkedin_jobs",
                f"Rate limited for {company_name} — backing off",
            )
            time.sleep(60)
            return []

        if resp.status_code != 200:
            _log_error(
                "linkedin_jobs",
                f"Status {resp.status_code} for {company_name}",
            )
            return []

        if "authwall" in resp.url or "login" in resp.url:
            _log_error("linkedin_jobs", f"Hit auth wall for {company_name}")
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        jobs: List[Dict] = []

        # LinkedIn guest page job cards — try both common layouts
        job_cards = soup.select("div.base-card") or soup.select(
            "li.jobs-search__results-list"
        )

        for card in job_cards[:max_jobs]:
            title_el = card.select_one("h3.base-search-card__title") or card.select_one("h3")
            location_el = (
                card.select_one("span.job-search-card__location")
                or card.select_one("span.job-result-card__location")
            )
            posted_el = card.select_one("time")
            link_el = card.select_one("a.base-card__full-link") or card.select_one("a")

            title = title_el.get_text(strip=True) if title_el else ""
            location = location_el.get_text(strip=True) if location_el else ""
            posted = posted_el.get("datetime", "") if posted_el else ""
            job_url = link_el.get("href", "") if link_el else ""

            if not title:
                continue

            title_lower = title.lower()
            is_office = any(kw in title_lower for kw in OFFICE_SIGNAL_KEYWORDS)
            is_growth = any(kw in title_lower for kw in GROWTH_KEYWORDS)

            jobs.append({
                "title":            title,
                "location":         location,
                "posted":           posted,
                "is_office_signal": is_office,
                "is_office_role":   is_office,
                "is_growth_signal": is_growth,
                "url":              job_url,
            })

        return jobs

    except Exception as e:
        _log_error("linkedin_jobs.scrape", f"{company_name}: {e}")
        return []


def scrape_linkedin_jobs(
    company_name: str,
    city: str = "Atlanta",
    max_jobs: int = 10,
) -> List[Dict]:
    """
    Scrapes LinkedIn public job search for a company.
    Returns list of job dicts. Returns [] on any failure.

    LinkedIn's guest endpoint intermittently returns 200 OK with no rendered
    job cards (silent rate-limit). On an empty first attempt we sleep 45–90s
    and retry once with a fresh random User-Agent. This noticeably lifts the
    success rate without burning quota; sustained failure still falls back to
    [] cleanly.

    Each job dict:
    {
        "title":            str,
        "location":         str,
        "posted":           str,
        "is_office_signal": bool,   # direct CRE signal (spec field)
        "is_office_role":   bool,   # mirror field consumed by
                                    # research_agent._build_signal_from_label
        "is_growth_signal": bool,   # hiring velocity signal
        "url":              str,
    }
    """
    jobs = _scrape_attempt(company_name, city, max_jobs)

    if not jobs:
        cooldown = random.uniform(
            RETRY_SLEEP_MIN_SECONDS, RETRY_SLEEP_MAX_SECONDS
        )
        time.sleep(cooldown)
        jobs = _scrape_attempt(company_name, city, max_jobs)

    return jobs[:max_jobs]


def get_office_signals(jobs: List[Dict]) -> List[Dict]:
    """Returns only the office-specific signal jobs."""
    return [j for j in jobs if j.get("is_office_signal")]


def get_growth_signals(jobs: List[Dict]) -> List[Dict]:
    """Returns growth/hiring velocity signal jobs."""
    return [j for j in jobs if j.get("is_growth_signal")]


def summarise_jobs(jobs: List[Dict], company_name: str) -> Dict:
    """
    Returns a summary dict for research_agent to use.
    """
    if not jobs:
        return {
            "total_jobs":          0,
            "office_signal_count": 0,
            "growth_signal_count": 0,
            "office_roles":        [],
            "top_signal":          "",
            "has_signal":          False,
        }

    office = get_office_signals(jobs)
    growth = get_growth_signals(jobs)

    top_signal = ""
    if office:
        roles = ", ".join(j["title"] for j in office[:2])
        top_signal = f"{company_name} posted {len(office)} office role(s): {roles}"
    elif len(jobs) >= 5:
        top_signal = (
            f"{company_name} has {len(jobs)} open roles in the last 7 days "
            f"— active hiring"
        )

    return {
        "total_jobs":          len(jobs),
        "office_signal_count": len(office),
        "growth_signal_count": len(growth),
        "office_roles":        [j["title"] for j in office],
        "top_signal":          top_signal,
        "has_signal":          bool(office) or len(jobs) >= 5,
    }


if __name__ == "__main__":
    import json
    sample = scrape_linkedin_jobs("Salesloft", "Atlanta")
    print(json.dumps(sample, indent=2)[:1500])
    print()
    print(json.dumps(summarise_jobs(sample, "Salesloft"), indent=2))
