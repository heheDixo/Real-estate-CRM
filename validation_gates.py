"""
validation_gates.py
Entity-type validation gates for lead discovery.

Drop-in addition to the existing lead_discovery pipeline. Used as a
filter between the DNS gate and the article-intent gate: any candidate
that passes DNS but is not a real B2B company (publications,
government entities, geographic places, individual people, generic
category names) is rejected here before it can pollute the dashboard.

Gate order (cheap → expensive):
  1. Wikidata wbsearchentities   →  free, no API key, ~200ms
  2. Gemini Flash-Lite fallback  →  free (1000 RPD), needs GEMINI_API_KEY

The combined gate is permissive on infrastructure failure: if Wikidata
returns "unknown" and Gemini is unavailable (no API key or transient
error), the candidate is accepted and the existing Hunter.io gate makes
the final call. This preserves current pipeline behavior as a safe
fallback and ensures Wikidata/Gemini outages don't zero the dashboard.

Workflow impact: NONE. This module only refines which candidates make
it past discovery. Everything downstream — enrichment, scoring, draft
generation, Gmail push — is unchanged.

────────────────────────────────────────────────────────────────────
Cost: $0
Setup: get a free Gemini API key at https://aistudio.google.com
       then add to .env:  GEMINI_API_KEY=AIza...
       Restart Streamlit + uvicorn.
────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
from typing import Optional, Dict

import requests


# ─── Endpoints ──────────────────────────────────────────────────────


_WIKIDATA_API = "https://www.wikidata.org/w/api.php"

_GEMINI_API = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash-lite:generateContent"
)

_USER_AGENT = "absolv-cre-outreach/1.0 (validation-gates)"


# ─── Wikidata classification keywords ───────────────────────────────


# Description fragments that mark a Wikidata hit as NOT a B2B tenant.
# Matched case-insensitively against the entity's short description.
_DENY_KEYWORDS = frozenset({
    # publications & media (specific publication types only — NOT broad
    # "media company" or "broadcaster" which over-trigger on real product
    # companies that happen to have a media arm, e.g. Peloton).
    "newspaper", "magazine", "publication", "tabloid", "wire service",
    "press release", "news agency", "news organization",
    "online newspaper", "online magazine",
    "journal of",  # academic / trade journals
    # government & geography
    "city in", "city of", "town in", "town of", "village in",
    "municipality", "county in", "county of", "u.s. state",
    "province", "country in", "region in", "district of",
    "neighborhood", "government agency", "ministry of", "department of",
    "federal agency", "state agency", "local government",
    "administrative", "administrative territorial",
    # institutions / non-profit
    "university", "college", "school district", "high school",
    "hospital", "library", "museum", "non-profit", "nonprofit",
    "charity", "foundation",
    # individual people
    "footballer", "actor", "actress", "politician", "musician",
    "singer", "writer", "author", "given name", "surname",
    "fictional character",
    # other non-B2B
    "song by", "album by", "film by", "movie", "book by", "novel",
    "video game", "programming language",
})

# Description fragments that strongly indicate a B2B company.
_ALLOW_KEYWORDS = frozenset({
    "company", "corporation", "enterprise", "firm",
    "startup", "private company", "public company", "holding company",
    "subsidiary", "conglomerate", "limited liability",
    "manufacturer", "retailer", "service provider",
    "tech company", "technology company", "software company",
    "biotech", "biotechnology", "pharmaceutical",
    "consulting firm", "financial services", "investment firm",
    "logistics company", "shipping company",
    "supplier of", "producer of", "developer of",
})


# ─── Caches (per-process, reset on restart) ─────────────────────────


_wikidata_cache: Dict[str, str] = {}     # name → 'company' | 'not_company' | 'unknown'
_gemini_cache:   Dict[str, Optional[bool]] = {}  # name|domain → True | False | None


# ─── Wikidata gate ──────────────────────────────────────────────────


def _wikidata_classify(name: str) -> str:
    """
    Returns 'company', 'not_company', or 'unknown'.
    Free, no API key. ~200ms per uncached lookup.
    """
    key = name.strip().lower()
    if key in _wikidata_cache:
        return _wikidata_cache[key]

    try:
        resp = requests.get(
            _WIKIDATA_API,
            params={
                "action":   "wbsearchentities",
                "search":   name,
                "language": "en",
                "format":   "json",
                "limit":    3,
            },
            timeout=5,
            headers={"User-Agent": _USER_AGENT},
        )
    except requests.RequestException:
        _wikidata_cache[key] = "unknown"
        return "unknown"

    if resp.status_code != 200:
        _wikidata_cache[key] = "unknown"
        return "unknown"

    try:
        hits = resp.json().get("search", []) or []
    except ValueError:
        _wikidata_cache[key] = "unknown"
        return "unknown"

    if not hits:
        _wikidata_cache[key] = "unknown"
        return "unknown"

    # Examine the top 2 hits' descriptions. Whichever side fires first wins.
    for hit in hits[:2]:
        desc = (hit.get("description") or "").lower()
        if not desc:
            continue
        if any(kw in desc for kw in _DENY_KEYWORDS):
            _wikidata_cache[key] = "not_company"
            return "not_company"
        if any(kw in desc for kw in _ALLOW_KEYWORDS):
            _wikidata_cache[key] = "company"
            return "company"

    _wikidata_cache[key] = "unknown"
    return "unknown"


# ─── Gemini fallback ────────────────────────────────────────────────


def _gemini_is_b2b_company(name: str, domain: str) -> Optional[bool]:
    """
    LLM fallback. Returns True / False / None (None means API down or
    no key set). Free up to 1000 requests/day on Gemini Flash-Lite.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    cache_key = f"{name.strip().lower()}|{domain.strip().lower()}"
    if cache_key in _gemini_cache:
        return _gemini_cache[cache_key]

    prompt = (
        f'Is "{name}" (domain: {domain}) a real B2B company that '
        f"occupies office space and could be a commercial real-estate "
        f"tenant?\n\n"
        f"REJECT: publications, newspapers, press release services, "
        f"government agencies, geographic places (cities, counties, "
        f"states), universities, hospitals, individual people, "
        f"generic category names.\n\n"
        f"ACCEPT: private and public companies in tech, biotech, "
        f"healthcare, finance, manufacturing, consulting, and similar "
        f"B2B sectors.\n\n"
        f"Reply with exactly one word: YES or NO."
    )

    try:
        resp = requests.post(
            f"{_GEMINI_API}?key={api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 5,
                    "temperature":     0.0,
                },
            },
            timeout=10,
            headers={"User-Agent": _USER_AGENT},
        )
    except requests.RequestException:
        _gemini_cache[cache_key] = None
        return None

    if resp.status_code != 200:
        _gemini_cache[cache_key] = None
        return None

    try:
        data = resp.json()
        text = (
            data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
                .upper()
        )
    except (KeyError, IndexError, AttributeError, ValueError):
        _gemini_cache[cache_key] = None
        return None

    verdict: Optional[bool] = None
    if text.startswith("YES"):
        verdict = True
    elif text.startswith("NO"):
        verdict = False
    _gemini_cache[cache_key] = verdict
    return verdict


# ─── Combined gate (public entry point) ─────────────────────────────


def is_b2b_company(name: str, domain: str) -> bool:
    """
    Combined entity-type gate, used by lead_discovery.

    Returns True iff the candidate appears to be a real B2B company
    suitable for CRE tenant outreach. Returns True permissively when
    both upstream gates are unavailable (preserves existing pipeline
    behaviour and ensures upstream outages do not zero the dashboard).
    """
    wd = _wikidata_classify(name)
    if wd == "company":
        return True
    if wd == "not_company":
        return False

    # Wikidata says "unknown" — fall through to Gemini.
    gemini = _gemini_is_b2b_company(name, domain)
    if gemini is None:
        # Both upstream gates unavailable. Be permissive; let the
        # downstream Hunter.io gate make the final call.
        return True
    return gemini


# ─── Quick smoke test ───────────────────────────────────────────────


if __name__ == "__main__":
    # Pure Wikidata sanity check; runs without GEMINI_API_KEY.
    cases = [
        ("Business Wire",     "businesswire.com"),
        ("Charlotte Observer", "charlotteobserver.com"),
        ("Cobb County",       "cobbcounty.com"),
        ("Bellevue",          "bellevue.com"),
        ("Abbott",            "abbott.com"),
        ("Deloitte",          "deloitte.com"),
        ("Ramp",              "ramp.com"),
        ("Peloton",           "onepeloton.com"),
        ("Health Tech Company To", "healthtechcompanyto.com"),
        ("Comments URL",      "commentsurl.com"),
    ]
    print(f"{'name':32} {'wd_verdict':14} {'b2b?':>6}")
    print("-" * 60)
    for n, d in cases:
        wd = _wikidata_classify(n)
        b  = is_b2b_company(n, d)
        print(f"{n:32} {wd:14} {'YES' if b else 'NO':>6}")