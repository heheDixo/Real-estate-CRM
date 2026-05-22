"""
Public job-board scraper — Greenhouse + Ashby + Lever.

Most NYC tech companies post open roles on one of three ATS systems:
  - Greenhouse — `boards-api.greenhouse.io`
  - Ashby      — `api.ashbyhq.com/posting-api/job-board/{slug}`
  - Lever      — `api.lever.co/v0/postings/{slug}`

All three have public JSON endpoints — no auth, no documented rate limits,
and they return every open role for the company.

Usage:
    bundle = scrape("Ramp", "ramp.com")
    # → {"count": 47, "office_count": 12, "source": "Greenhouse",
    #    "roles": [{"title": "...", "location": "...", "office": True}, ...]}

The scraper tries a small set of slug guesses derived from company name +
domain. On the first 200 with a non-empty job list it stops. Returns an
empty bundle when nothing is found (no exception).
"""

from __future__ import annotations

import datetime
import json
import os
import re
from typing import Dict, List, Optional

import requests


_TIMEOUT = 10
_OFFICE_HINTS = (
    "real estate", "workplace", "facility", "facilities",
    "office", "admin", "operations", "people ops", "executive assistant",
)


def _log_error(scope: str, exc: Exception) -> None:
    try:
        path = os.path.join("data", "error_log.json")
        os.makedirs("data", exist_ok=True)
        log: List[Dict] = []
        if os.path.exists(path):
            try:
                with open(path) as f:
                    log = json.load(f) or []
            except (json.JSONDecodeError, OSError):
                log = []
        log.append({
            "at":    datetime.datetime.now().isoformat(),
            "scope": scope,
            "error": str(exc)[:280],
            "type":  type(exc).__name__,
        })
        with open(path, "w") as f:
            json.dump(log[-200:], f, indent=2)
    except Exception:
        pass


def _slug_candidates(company: str, domain: str) -> List[str]:
    """Generate plausible Greenhouse/Lever slugs from a company name."""
    name = (company or "").strip()
    # Common slug patterns:
    #   "Oscar Health"      → ["oscarhealth", "oscar-health", "oscar"]
    #   "Notion Labs"       → ["notionlabs", "notion-labs", "notion"]
    #   "Ramp"              → ["ramp"]
    compact     = re.sub(r"[^a-z0-9]", "", name.lower())
    hyphenated  = re.sub(r"\s+", "-", name.lower().strip())
    first_word  = name.lower().split()[0] if name else ""
    domain_root = (domain or "").split(".")[0]
    out: List[str] = []
    for c in (compact, hyphenated, first_word, domain_root):
        if c and c not in out:
            out.append(c)
    return out


def _is_office_role(title: str) -> bool:
    low = (title or "").lower()
    return any(hint in low for hint in _OFFICE_HINTS)


# ── Greenhouse ──────────────────────────────────────────────────────────────


def _try_greenhouse(slug: str) -> Optional[Dict]:
    """Return a bundle dict on a successful hit, None on miss."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json() or {}
    except ValueError:
        return None
    jobs = data.get("jobs") or []
    if not jobs:
        return None
    roles: List[Dict] = []
    for j in jobs:
        title    = (j.get("title") or "").strip()
        location = (j.get("location") or {}).get("name") or ""
        roles.append({
            "title":    title,
            "location": location,
            "office":   _is_office_role(title),
            "url":      j.get("absolute_url") or "",
        })
    return {
        "count":        len(roles),
        "office_count": sum(1 for r in roles if r["office"]),
        "source":       "Greenhouse",
        "slug":         slug,
        "roles":        roles[:50],
    }


# ── Ashby ───────────────────────────────────────────────────────────────────


def _try_ashby(slug: str) -> Optional[Dict]:
    """Ashby's job-board slug is usually Title-Cased (e.g. 'Ramp' not 'ramp')."""
    # Ashby slugs are case-sensitive but the API is forgiving; try both
    # the original casing and a title-cased version.
    for variant in (slug, slug.title()):
        url = (
            f"https://api.ashbyhq.com/posting-api/job-board/{variant}"
            f"?includeCompensation=false"
        )
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue
        try:
            data = resp.json() or {}
        except ValueError:
            continue
        jobs = data.get("jobs") or []
        if not jobs:
            continue
        roles: List[Dict] = []
        for j in jobs:
            title    = (j.get("title") or "").strip()
            loc_raw  = j.get("location")
            if isinstance(loc_raw, dict):
                location = loc_raw.get("name") or ""
            else:
                location = loc_raw or j.get("locationName") or ""
            roles.append({
                "title":    title,
                "location": location,
                "office":   _is_office_role(title),
                "url":      j.get("jobUrl") or j.get("applicationUrl") or "",
            })
        return {
            "count":        len(roles),
            "office_count": sum(1 for r in roles if r["office"]),
            "source":       "Ashby",
            "slug":         variant,
            "roles":        roles[:50],
        }
    return None


# ── Lever ───────────────────────────────────────────────────────────────────


def _try_lever(slug: str) -> Optional[Dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if not isinstance(data, list) or not data:
        return None
    roles: List[Dict] = []
    for j in data:
        title    = (j.get("text") or "").strip()
        location = ""
        cats = j.get("categories") or {}
        if isinstance(cats, dict):
            location = cats.get("location") or ""
        roles.append({
            "title":    title,
            "location": location,
            "office":   _is_office_role(title),
            "url":      j.get("hostedUrl") or "",
        })
    return {
        "count":        len(roles),
        "office_count": sum(1 for r in roles if r["office"]),
        "source":       "Lever",
        "slug":         slug,
        "roles":        roles[:50],
    }


# ── Public entry ────────────────────────────────────────────────────────────


def scrape(company: str, domain: str = "") -> Dict:
    """
    Try Greenhouse first, then Lever. Returns an empty bundle if no ATS
    is detected. Safe to call for every prospect — silent on misses.
    """
    candidates = _slug_candidates(company, domain)
    for try_fn in (_try_greenhouse, _try_ashby, _try_lever):
        for slug in candidates:
            bundle = try_fn(slug)
            if bundle:
                return bundle
    return {"count": 0, "office_count": 0, "source": "", "slug": "", "roles": []}


if __name__ == "__main__":
    for c, d in [("Ramp", "ramp.com"),
                 ("Oscar Health", "hioscar.com"),
                 ("Notion", "notion.so"),
                 ("Anthropic", "anthropic.com")]:
        b = scrape(c, d)
        print(f"{c:18}  count={b['count']:>4}  office={b['office_count']:>3}  source={b['source']!r}")
