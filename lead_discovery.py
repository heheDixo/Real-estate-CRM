"""
lead_discovery.py
Discovers new companies matching the active ICP from free sources.

Sources:
  1. Google News RSS — sector-keyed signal queries
  2. NewsAPI — same queries, last 7 days
  3. BuiltInNYC / HN Jobs scraping — recently posted job pages

For each candidate company name we extract from those sources, we:
  - skip it if it already exists in the watchlist or dismissed list
  - look up a decision-maker contact via Hunter.io (graceful degrade if no key)
  - emit a candidate lead dict

Nothing is added to the watchlist automatically — the broker approves on the
research page via approve_lead() or dismisses via dismiss_lead().
"""

from __future__ import annotations

import datetime
import json
import os
import re
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import requests

import config


# ── Files ───────────────────────────────────────────────────────────────────


DATA_DIR        = "data"
WATCHLIST_PATH  = os.path.join(DATA_DIR, "watchlist.json")
DISMISSED_PATH  = os.path.join(DATA_DIR, "dismissed_leads.json")
ERROR_LOG_PATH  = os.path.join(DATA_DIR, "error_log.json")


# ── Tunables ────────────────────────────────────────────────────────────────


# Words that look capitalised but are not companies — used by the extractor.
_NOISE_WORDS = {
    "New", "York", "NYC", "Manhattan", "Brooklyn", "Series",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "AI", "API", "CEO", "CTO", "CFO", "COO", "VP", "SVP", "EVP",
    "Q1", "Q2", "Q3", "Q4", "IPO", "VC", "PE", "LLC", "Inc", "Corp",
    "The", "And", "For", "With", "From", "After", "Before", "About",
    "Million", "Billion", "USD", "USA", "UK", "EU",
    "Office", "Startup", "Company", "Companies", "Funding",
    "Hiring", "Expansion", "Round", "Lead", "Tech", "SaaS",
    "Health", "Healthcare", "Fintech", "MedTech", "Real", "Estate",
    "United", "States", "America", "American",
}

_DECISION_TITLES = {
    "ceo", "coo", "cfo", "cto", "chief", "head of", "vp ",
    "vice president", "svp", "evp", "director", "president",
    "chief of staff", "founder", "co-founder", "managing partner",
}

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ── File helpers ────────────────────────────────────────────────────────────


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_json(path: str, default):
    _ensure_data_dir()
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: str, data):
    _ensure_data_dir()
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _log_error(scope: str, exc: Exception):
    log = _read_json(ERROR_LOG_PATH, [])
    log.append({
        "at":    datetime.datetime.now().isoformat(),
        "scope": scope,
        "error": str(exc),
        "type":  type(exc).__name__,
    })
    _write_json(ERROR_LOG_PATH, log[-200:])


def _slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s.strip().lower())
    return s.strip("-")


def _existing_watchlist_domains() -> set:
    out = set()
    for p in _read_json(WATCHLIST_PATH, []):
        if p.get("domain"):
            out.add(p["domain"].lower())
        if p.get("company"):
            out.add(_slugify(p["company"]))
    return out


def _dismissed_ids() -> set:
    return set(_read_json(DISMISSED_PATH, []))


# ── Company-name extraction from article text ───────────────────────────────


# Match capitalised noun phrases of 1–4 tokens (e.g. "Acme", "Acme Health",
# "Acme Health Partners"). Filter out junk via the noise list + repetition.
_CAP_PHRASE = re.compile(
    r"\b([A-Z][A-Za-z0-9&]+(?:\s+[A-Z][A-Za-z0-9&]+){0,3})\b"
)


_COMMON_ENGLISH_CAPS = {
    s.casefold() for s in {
        "Our", "Your", "Their", "Its", "His", "Her", "We", "You", "They",
        "I", "It", "He", "She", "Me", "Us", "Them",
        "Full", "Half", "Most", "Many", "Some", "All", "Few",
        "Best", "Top", "Big", "Small", "Large", "New", "Old",
        "Yes", "No", "Maybe", "Sure", "Right", "Wrong", "True", "False",
        "Here", "There", "Now", "Then", "Today", "Tomorrow", "Yesterday",
        "When", "Where", "Why", "How", "What", "Who", "Which",
        "Onsite", "Remote", "Hybrid", "Hiring", "Posted", "Apply", "Open",
        "Job", "Jobs", "Role", "Roles", "Position", "Positions",
        "React", "Python", "JavaScript", "Node", "Java", "Go", "Rust",
        "Frontend", "Backend", "Fullstack", "Mobile", "iOS", "Android",
        "Engineer", "Engineering", "Engineers", "Designer", "Manager",
        "Senior", "Junior", "Staff", "Lead", "Principal",
        "Friday", "Update", "Updates", "Latest", "Breaking",
        "Read", "More", "Click", "Story", "Stories", "News",
        "U.S.", "US", "America", "European", "Asian", "Africa",
        "Email", "Sign", "Login", "Logout", "Search", "Filter",
        "Software", "Hardware", "Product", "Marketing", "Sales",
        "Full Time", "Part Time", "New York", "New York City",
        "Sign In", "Log In", "Read More", "Click Here",
        # cities / regions
        "San Francisco", "Los Angeles", "Washington", "Chicago",
        "Boston", "Austin", "Miami", "Seattle", "Toronto", "London",
        "Berlin", "Tokyo", "Paris", "Singapore", "Dubai",
        "Atlanta", "Charlotte", "Dallas", "Denver", "Houston",
        "Phoenix", "Philadelphia", "Detroit", "Baltimore", "Portland",
        # tech stack tokens
        "Kubernetes", "Docker", "Swift", "Kotlin", "TypeScript",
        "GraphQL", "Postgres", "MongoDB", "Redis", "AWS", "GCP",
        "Azure", "Linux", "Ubuntu", "Mac", "Windows",
        "React Native", "Vue", "Angular", "Django", "Flask",
        "Terraform", "Ansible", "Jenkins", "Grafana", "Datadog",
        # generic job-title plurals that look like company names
        "Data Scientists", "Software Engineers", "Product Managers",
        "Account Executives", "Site Reliability", "Machine Learning",
        "Customer Success", "Business Development",
        "Solutions Engineer", "Solutions Architect", "Sales Engineer",
        # remaining low-signal English
        "Please", "Front", "Back", "Side", "End", "Begin", "Start",
        # common HTML/site noise
        "Cookies", "Privacy", "Policy", "Terms", "Sitemap", "Subscribe",
        "Newsletter", "Account", "Profile", "Settings", "Notifications",
        # publications and news outlets — never tenant prospects
        "Fortune", "Forbes", "Bloomberg", "Reuters", "Axios",
        "TechCrunch", "VentureBeat", "Pitchbook", "Crunchbase",
        "Crunchbase News", "AlleyWatch", "Fierce Healthcare", "PYMNTS",
        "CoinDesk", "MarketBeat", "Wccftech", "Engadget", "Wired",
        "The Information", "The Verge", "The Week", "The Guardian",
        "The Times", "The Times Of India", "Times Of India",
        "Business Insider", "Insider", "NDTV", "BBC", "CNN", "CNBC",
        "MSNBC", "FOX", "ABC", "NBC", "CBS", "Sky News", "RTE", "RTE.ie",
        "WSJ", "Wall Street Journal", "NYT", "New York Times",
        "FT", "Financial Times", "Mint", "Livemint", "Quartz",
        "The Hindu", "The Print", "Hindustan Times", "Politico",
        "Time", "Newsweek", "Vox", "Slate", "Salon", "ProPublica",
        "Variety", "Deadline", "Hollywood Reporter",
        "Haver Analytics", "Gasgoo", "fundsforNGOs News",
        "Built In", "BuiltIn", "BuiltInNYC",
        # social and big-tech that look like companies but are not tenant prospects
        "Facebook", "Twitter", "X", "Instagram", "TikTok", "YouTube",
        "Snapchat", "Pinterest", "Reddit", "LinkedIn",
        "Google", "Alphabet", "Apple", "Microsoft", "Amazon", "Meta",
        # headline fragments and superlative bait
        "Exclusive", "Funding Rounds", "Biggest Funding Rounds",
        "Largest Funding Rounds", "Latest Funding", "Largest NYC",
        "Largest NYC Tech Startup", "Biggest", "Largest", "Newest",
        "Hottest", "Coolest", "Worst", "Strongest", "Weakest",
        "Story", "Stories", "Headlines", "Headline", "Report",
        "Reports", "Roundup", "Recap", "Digest", "Wrap",
        "First Edition", "Special Report", "Special Edition",
        # vague entity fragments
        "Exclusive Design", "First Look", "Quick Look",
        # NYC streets / landmarks — not companies
        "Park Avenue", "Fifth Avenue", "Madison Avenue", "Wall Street",
        "Times Square", "Hudson Yards", "Bryant Park", "Central Park",
        "Sixth Avenue", "Lexington Avenue", "Broadway", "Battery Park",
        "Union Square", "Washington Square", "Columbus Circle",
        "Rockefeller Center", "Grand Central", "Penn Station",
        # generic facility / corporate-event phrases
        "Grand Opening", "Global Headquarters", "New Global Headquarters",
        "Corporate Headquarters", "World Headquarters", "Head Office",
        "Open House", "Ribbon Cutting", "Town Hall", "Annual Report",
        "Earnings Call", "Investor Day",
        # additional publications that surfaced
        "Business Journals", "The Business Journals", "Business Today",
        "Economic Times", "The Economic Times", "Livemint",
    }
}

# Prefix words that mark a phrase as a headline fragment, not a company.
_HEADLINE_PREFIX_TOKENS = {
    "biggest", "largest", "newest", "hottest", "coolest", "worst",
    "strongest", "weakest", "latest", "freshest", "leading",
    "top", "best", "first", "last", "most", "least", "exclusive",
    "breaking",
}

# Verbs that should never appear inside a real company name. If a token
# matches one of these the phrase is a headline ("JPMorganChase Celebrates
# Grand Opening", "Apple Announces…", "Google Launches…").
_HEADLINE_VERB_TOKENS = {
    "celebrates", "announces", "launches", "opens", "opened",
    "unveils", "unveiled", "reveals", "revealed", "releases",
    "released", "acquires", "acquired", "buys", "bought", "sells",
    "sold", "hires", "fires", "joins", "leaves", "lays", "cuts",
    "raises", "raised", "expands", "expanded", "files", "filed",
    "settles", "settled", "wins", "won", "loses", "lost",
    "appoints", "appointed", "names", "named", "promotes", "promoted",
    "denies", "denied", "confirms", "confirmed", "says", "said",
    "reports", "reported", "warns", "warned", "plans", "planned",
}

# Lowercase common-noun tokens that, when paired with another such token,
# almost certainly indicate a headline fragment ("Funding Rounds", "Tech
# Startup"). Companies don't normally have names like this.
_COMMON_NOUN_TOKENS = {
    "funding", "rounds", "round", "tech", "startup", "startups",
    "company", "companies", "deal", "deals", "investor", "investors",
    "report", "reports", "story", "stories", "news", "update",
    "updates", "edition", "digest", "wrap", "recap", "headline",
    "headlines", "industry", "sector", "market", "markets",
    "ai", "machine", "learning", "data", "science", "platform",
}


def _looks_like_company(phrase: str) -> bool:
    tokens = phrase.split()
    if not tokens or len(tokens) > 4:
        return False
    if phrase.casefold() in _COMMON_ENGLISH_CAPS:
        return False
    if any(t in _NOISE_WORDS for t in tokens):
        # allow when the phrase has at least one non-noise token AND >=2 tokens
        if not (len(tokens) >= 2 and any(t not in _NOISE_WORDS for t in tokens)):
            return False
    if all(len(t) <= 2 for t in tokens):
        return False
    # Drop ALL CAPS phrases — they're almost always banners or job-listing tags.
    if phrase == phrase.upper() and len(phrase) > 1:
        return False
    if all(t.casefold() in _COMMON_ENGLISH_CAPS for t in tokens):
        return False
    # Headline superlatives — "Biggest Funding Rounds", "Largest NYC Tech…"
    if tokens[0].casefold() in _HEADLINE_PREFIX_TOKENS:
        return False
    # Headline verbs in any position — "X Celebrates Y", "X Announces Y",
    # "X Launches Y". Real company names don't contain conjugated verbs.
    if any(t.casefold() in _HEADLINE_VERB_TOKENS for t in tokens):
        return False
    # All-common-noun phrases — "Funding Rounds", "Tech Startup",
    # "Industry Report". Real companies rarely have names like this.
    if len(tokens) >= 2 and all(
        t.casefold() in _COMMON_NOUN_TOKENS for t in tokens
    ):
        return False
    # Reject obvious garbage — Google News article IDs, URL fragments,
    # hashes. Any single token > 18 chars without a hyphen or any token
    # > 24 chars regardless. Real company tokens are short.
    for t in tokens:
        if len(t) > 24:
            return False
        if len(t) > 18 and "-" not in t:
            return False
        # Mixed-case alphanumeric run with no vowels in the latter half is
        # almost always a base64 / hash fragment.
        if len(t) > 12 and not any(
            c.lower() in "aeiou" for c in t[len(t)//2:]
        ):
            return False
    # Single-token candidates are the noisy ones — require some real signal.
    if len(tokens) == 1:
        t = tokens[0]
        if t.casefold() in _COMMON_ENGLISH_CAPS:
            return False
        # require at least 5 characters OR mixed case/digit content
        if len(t) < 5 and not any(c.isdigit() for c in t):
            return False
    return True


def _extract_companies(texts: List[str]) -> List[str]:
    """
    Pull candidate company names from a list of article texts.

    A phrase has to appear in more than one article (or twice in the same one)
    to be considered a real company — that filters out one-off capitalised
    fragments like product names mentioned in passing.
    """
    counter: Counter = Counter()
    for text in texts:
        if not text:
            continue
        # de-dupe within an article so a single article doesn't carry a name
        seen_here = set()
        for match in _CAP_PHRASE.findall(text):
            phrase = match.strip()
            if not _looks_like_company(phrase):
                continue
            key = phrase.lower()
            if key in seen_here:
                continue
            seen_here.add(key)
            counter[phrase] += 1

    return [name for name, count in counter.most_common(40) if count >= 2]


# ── Source 1: Google News RSS ───────────────────────────────────────────────


def _google_news_articles(query: str, max_items: int = 12) -> List[Dict]:
    try:
        import feedparser
    except ImportError:
        return []

    url = f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(query)}"
    try:
        feed = feedparser.parse(url, agent=_USER_AGENT)
    except Exception as exc:
        _log_error("lead_discovery.google_news", exc)
        return []

    items: List[Dict] = []
    for entry in feed.entries[:max_items]:
        items.append({
            "title":       getattr(entry, "title", ""),
            "description": getattr(entry, "summary", ""),
            "url":         getattr(entry, "link", ""),
            "source":      "Google News RSS",
        })
    return items


# ── Source 2: NewsAPI ───────────────────────────────────────────────────────


def _newsapi_articles(query: str, max_items: int = 12) -> List[Dict]:
    if not config.NEWSAPI_AVAILABLE:
        return []
    from_iso = (datetime.datetime.utcnow() -
                 datetime.timedelta(days=7)).isoformat() + "Z"
    try:
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q":        query,
                "from":     from_iso,
                "sortBy":   "publishedAt",
                "language": "en",
                "pageSize": min(max_items, 20),
                "apiKey":   config.NEWSAPI_KEY,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        _log_error("lead_discovery.newsapi", exc)
        return []

    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []

    out: List[Dict] = []
    for art in data.get("articles", [])[:max_items]:
        out.append({
            "title":       (art.get("title") or ""),
            "description": (art.get("description") or ""),
            "url":         art.get("url", ""),
            "source":      f"NewsAPI · {(art.get('source') or {}).get('name','')}",
        })
    return out


# ── Source 3: BuiltInNYC + HN Jobs ──────────────────────────────────────────


def _builtinnyc_companies(sector_hint: str = "") -> List[str]:
    """
    Scrape company names from the BuiltInNYC jobs page (free, no key).

    Returns the bare company names — we'll feed them through the same
    contact-lookup path as RSS-derived candidates.
    """
    url = "https://www.builtinnyc.com/jobs"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _USER_AGENT},
            timeout=15,
        )
    except requests.RequestException as exc:
        _log_error("lead_discovery.builtin", exc)
        return []

    if resp.status_code != 200:
        return []

    # very loose extraction: look for "company-name" CSS hooks; otherwise
    # fall back to noun-phrase mining over the raw HTML text.
    candidates: List[str] = []
    text = resp.text

    # CSS data attributes BuiltInNYC has historically used
    for match in re.findall(
        r'data-cy=["\']company-name["\'][^>]*>([^<]+)<', text
    ):
        name = match.strip()
        if name and _looks_like_company(name):
            candidates.append(name)

    if not candidates:
        candidates = _extract_companies([text[:30000]])

    # de-dupe preserving order
    seen, deduped = set(), []
    for c in candidates:
        if c.lower() in seen:
            continue
        seen.add(c.lower())
        deduped.append(c)
    return deduped[:20]


def _hn_jobs_companies() -> List[str]:
    """Pull company names from the latest Hacker News Who Is Hiring thread."""
    url = "https://hn.algolia.com/api/v1/search?query=who+is+hiring&tags=story"
    try:
        resp = requests.get(url, timeout=15)
    except requests.RequestException as exc:
        _log_error("lead_discovery.hn", exc)
        return []
    if resp.status_code != 200:
        return []
    try:
        hits = resp.json().get("hits", [])
    except ValueError:
        return []
    if not hits:
        return []

    thread_id = hits[0].get("objectID")
    if not thread_id:
        return []
    try:
        thread = requests.get(
            f"https://hn.algolia.com/api/v1/items/{thread_id}",
            timeout=15,
        ).json()
    except Exception as exc:
        _log_error("lead_discovery.hn.thread", exc)
        return []

    nyc_blobs = []
    for child in thread.get("children", [])[:200]:
        text = (child.get("text") or "")
        if "new york" in text.lower() or "nyc" in text.lower():
            nyc_blobs.append(text)

    return _extract_companies(nyc_blobs)[:20]


# ── Hunter.io contact lookup ────────────────────────────────────────────────


def _domain_for(company: str) -> str:
    return _slugify(company).replace("-", "") + ".com"


def _hunter_lookup(domain: str) -> Dict:
    """
    Domain search for a decision-maker. Returns {} on miss or no key.
    """
    if not config.HUNTER_AVAILABLE or not domain:
        return {}
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={
                "domain":   domain,
                "api_key":  config.HUNTER_API_KEY,
                "limit":    5,
                "seniority": "executive,senior",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        _log_error("lead_discovery.hunter", exc)
        return {}
    if resp.status_code != 200:
        return {}
    try:
        data = resp.json().get("data", {})
    except ValueError:
        return {}

    emails = data.get("emails", []) or []
    # prefer a decision-maker title
    best = None
    for e in emails:
        title = (e.get("position") or "").lower()
        if any(t in title for t in _DECISION_TITLES):
            best = e
            break
    if not best and emails:
        best = emails[0]

    if not best:
        return {}

    return {
        "full_name": f"{best.get('first_name','')} {best.get('last_name','')}".strip(),
        "position":  best.get("position", ""),
        "value":     best.get("value", ""),
    }


# ── Main entry points ───────────────────────────────────────────────────────


def _icp_queries(icp_profile: Dict) -> List[str]:
    """Build the lead-discovery search queries from the active ICP profile."""
    sectors = icp_profile.get("sectors") or [icp_profile.get("sector", "tech")]
    geo     = (icp_profile.get("geographies") or ["New York"])[0]
    sector  = sectors[0] if sectors else "tech"

    return [
        f"{sector} company {geo} hiring expansion office",
        f"{sector} startup Series B Series C {geo}",
        f"{geo} {sector} company new headquarters",
    ]


def discover_new_leads(icp_profile: Dict, max_results: int = 10) -> List[Dict]:
    """
    Run all three discovery sources, dedupe, contact-enrich, and return
    a list of candidate lead dicts ready for broker approval.
    """
    queries  = _icp_queries(icp_profile)
    existing = _existing_watchlist_domains()
    dismissed = _dismissed_ids()

    # ── Parallel fetch ─────────────────────────────────────────────────────
    articles: List[Dict] = []
    builtin_names: List[str] = []
    hn_names:      List[str] = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = []
        for q in queries:
            futures.append(pool.submit(_google_news_articles, q))
            futures.append(pool.submit(_newsapi_articles, q))
        futures.append(pool.submit(_builtinnyc_companies))
        futures.append(pool.submit(_hn_jobs_companies))

        for fut in as_completed(futures):
            try:
                result = fut.result()
            except Exception as exc:
                _log_error("lead_discovery.fetch", exc)
                continue
            if not result:
                continue
            if isinstance(result, list) and result and isinstance(result[0], dict):
                articles.extend(result)
            elif isinstance(result, list):
                if not builtin_names:
                    builtin_names = list(result)
                else:
                    hn_names.extend(result)

    # ── Extract candidate company names from articles ──────────────────────
    blobs = [f"{a.get('title','')}. {a.get('description','')}" for a in articles]
    article_names = _extract_companies(blobs)

    all_names: List[str] = []
    seen = set()
    for name in article_names + builtin_names + hn_names:
        key = _slugify(name)
        if not key or key in seen:
            continue
        if key in existing:
            continue
        candidate_id = f"discovered-{key}-{datetime.date.today().isoformat()}"
        if candidate_id in dismissed:
            continue
        seen.add(key)
        all_names.append(name)

    # ── Build candidates ──────────────────────────────────────────────────
    sector  = (icp_profile.get("sectors") or
               [icp_profile.get("sector", "tech")])[0]
    profile_id = icp_profile.get("id") or icp_profile.get("name") or "default"
    geo     = (icp_profile.get("geographies") or ["New York"])[0]
    today   = datetime.date.today().isoformat()
    now_iso = datetime.datetime.now().isoformat()

    candidates: List[Dict] = []
    for name in all_names[: max_results * 3]:   # over-fetch for contact misses
        domain  = _domain_for(name)
        contact = _hunter_lookup(domain)
        # provenance — pull the first article that mentions this name
        mention = next(
            (a for a in articles
             if name.lower() in (a.get("title","") + " " + a.get("description","")).lower()),
            {},
        )

        candidates.append({
            "id":             f"discovered-{_slugify(name)}-{today}",
            "company":        name,
            "domain":         domain,
            "website":        f"https://{domain}",
            "contact_name":   contact.get("full_name", ""),
            "contact_title":  contact.get("position", ""),
            "contact_email":  contact.get("value", ""),
            "linkedin_url":   "",
            "sector":         sector,
            "city":           geo,
            "icp_profile":    profile_id,
            "source":         "discovered",
            "discovered_at":  now_iso,
            "discovered_via": mention.get("source", "Google News RSS"),
            "discovery_url":  mention.get("url", ""),
            "approved":       False,
            "active":         True,
        })
        if len(candidates) >= max_results:
            break

    return candidates


# ── Approve / dismiss ──────────────────────────────────────────────────────


def approve_lead(lead: Dict) -> bool:
    """Move a discovered lead onto the watchlist."""
    watch = _read_json(WATCHLIST_PATH, [])
    domain = (lead.get("domain") or "").lower()

    if any((w.get("domain") or "").lower() == domain for w in watch):
        return False   # already there

    record = dict(lead)
    record["approved"]   = True
    record["source"]     = "watchlist"
    record["added_at"]   = datetime.date.today().isoformat()
    record.setdefault("active", True)
    watch.append(record)
    _write_json(WATCHLIST_PATH, watch)
    return True


def dismiss_lead(lead_id: str) -> bool:
    """Add a discovered-lead id to the dismissal list so it never re-surfaces."""
    if not lead_id:
        return False
    dismissed = _read_json(DISMISSED_PATH, [])
    if lead_id in dismissed:
        return True
    dismissed.append(lead_id)
    _write_json(DISMISSED_PATH, dismissed)
    return True


# ── CLI ────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    sample_icp = {
        "id": "tech_saas_nyc",
        "name": "Tech / SaaS — NYC",
        "sectors": ["Technology"],
        "geographies": ["New York"],
    }
    leads = discover_new_leads(sample_icp, max_results=5)
    print(json.dumps(leads, indent=2, default=str))
