"""
Apollo.io free-plan connector.

IMPORTANT: Apollo's free plan only exposes ONE endpoint we can use —
``organizations/enrich``. ``mixed_companies/search``,
``mixed_people/search``, and ``people/match`` are all 403 on free.

So this module supports only:

- ``enrich_organization(domain)``
  Free, unlimited (within Apollo's daily rate limits). Given a known
  domain, returns the company's name, headcount, LinkedIn URL, industry,
  founded year, technologies, and city.

The other functions (``search_organizations``, ``search_people``,
``reveal_email``) are kept as stubs that return empty results and log a
single warning to data/error_log.json so a future paid-plan upgrade can
swap them back in without touching downstream code.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Dict, List, Optional

import requests

import config


_BASE_URL = "https://api.apollo.io/api/v1"


# ── Shared error logging ────────────────────────────────────────────────────


def _log_error(scope: str, exc: Exception) -> None:
    try:
        path = os.path.join("data", "error_log.json")
        os.makedirs("data", exist_ok=True)
        log = []
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


def _headers() -> Dict[str, str]:
    return {
        "Content-Type":   "application/json",
        "Cache-Control":  "no-cache",
        "X-Api-Key":      config.APOLLO_API_KEY,
    }


# ── Organization Enrichment (the one endpoint free plan allows) ─────────────


def enrich_organization(domain: str) -> Dict:
    """
    Given a domain, return Apollo's metadata for the company.

    Returns a dict like:
        {company, domain, website, headcount, headcount_range,
         linkedin_url, industry, founded_year, city, technologies}
    Empty dict on any failure.
    """
    if not config.APOLLO_AVAILABLE or not domain:
        return {}

    # Strip protocol if the caller passed a full URL
    domain = domain.replace("https://", "").replace("http://", "").strip("/")

    body = {"domain": domain}
    try:
        resp = requests.post(
            f"{_BASE_URL}/organizations/enrich",
            headers=_headers(),
            json=body,
            timeout=20,
        )
    except requests.RequestException as exc:
        _log_error("apollo.enrich.network", exc)
        return {}

    if resp.status_code == 401 or resp.status_code == 403:
        _log_error(
            "apollo.enrich.auth",
            RuntimeError(f"Apollo returned {resp.status_code} — check APOLLO_API_KEY."),
        )
        return {}
    if resp.status_code != 200:
        _log_error(
            "apollo.enrich.http",
            RuntimeError(f"Apollo {resp.status_code}: {resp.text[:200]}"),
        )
        return {}

    try:
        data = resp.json() or {}
    except ValueError as exc:
        _log_error("apollo.enrich.parse", exc)
        return {}

    org = data.get("organization") or {}
    if not org:
        return {}

    return {
        "company":          (org.get("name") or "").strip(),
        "domain":           domain,
        "website":          (org.get("website_url") or f"https://{domain}").strip(),
        "linkedin_url":     org.get("linkedin_url") or "",
        "industry":         org.get("industry") or "",
        "founded_year":     org.get("founded_year") or 0,
        "city":             (org.get("city") or "").strip(),
        "country":          (org.get("country") or "").strip(),
        "headcount":        int(org.get("estimated_num_employees") or 0),
        "headcount_range":  org.get("organization_headcount_six_month_growth") or "",
        "technologies":     [t.get("name") for t in (org.get("current_technologies") or []) if t.get("name")][:10],
    }


# ── Stubs for the paid-only endpoints ───────────────────────────────────────


_FREE_PLAN_WARNING_LOGGED = False


def _warn_free_plan_once(endpoint: str) -> None:
    """Log once per process that the paid-only endpoint was called."""
    global _FREE_PLAN_WARNING_LOGGED
    if _FREE_PLAN_WARNING_LOGGED:
        return
    _FREE_PLAN_WARNING_LOGGED = True
    _log_error(
        f"apollo.{endpoint}.free_plan",
        RuntimeError(
            f"{endpoint} requires an Apollo paid plan. Using free fallbacks."
        ),
    )


def search_organizations(*_args, **_kwargs) -> List[Dict]:
    """Paid-only stub. Returns []. See module docstring."""
    _warn_free_plan_once("search_organizations")
    return []


def search_people(*_args, **_kwargs) -> List[Dict]:
    """Paid-only stub. Returns []. See module docstring."""
    _warn_free_plan_once("search_people")
    return []


def reveal_email(*_args, **_kwargs) -> str:
    """Paid-only stub. Returns ''. See module docstring."""
    _warn_free_plan_once("reveal_email")
    return ""


# Module-level convenience aliases — kept so existing imports don't break.
scrape_organizations = search_organizations
scrape_people        = search_people
