"""
lead_discovery.py
Discovers new companies matching the active ICP from free sources.

Sources:
  1. Google News RSS — sector-keyed signal queries
  2. NewsAPI — same queries, last 7 days
  3. BuiltInNYC / HN Jobs scraping — recently posted job pages

For each candidate company name we extract from those sources, we:
  - skip if it already exists in the watchlist or dismissed list
  - DNS-resolve the auto-generated domain (drop if it doesn't exist)
  - require an RE-intent keyword in the originating article
  - require a valid Hunter.io decision-maker contact (drop on miss)
  - emit the candidate

Nothing is added to the watchlist automatically — the broker approves on the
research page via approve_lead() or dismisses via dismiss_lead().

────────────────────────────────────────────────────────────────────────
Validity-gate audit (June 2026):
  The capitalised-phrase extraction strategy is inherently noisy; news
  articles contain place names, publication names, headline fragments,
  and job-board boilerplate that look like companies to a regex.

  Rather than chase noise with a longer blacklist, we now apply three
  hard gates downstream of extraction:
    1. _domain_resolves    — the auto-generated domain must exist (DNS)
    2. _article_has_intent — the originating article must mention
                              leasing, HQ, expansion, hiring, or offices
    3. Hunter contact      — must return a real executive email
  Each rejection writes a structured reason to error_log.json under
  scope `lead_discovery.reject.*` so quality can be measured per-stage.
────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import datetime
import json
import os
import re
import socket
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple
from validation_gates import is_b2b_company

import requests

import config
import database


# ── Files ───────────────────────────────────────────────────────────────────


DATA_DIR        = "data"
WATCHLIST_PATH  = os.path.join(DATA_DIR, "watchlist.json")
DISMISSED_PATH  = os.path.join(DATA_DIR, "dismissed_leads.json")
ERROR_LOG_PATH  = os.path.join(DATA_DIR, "error_log.json")


# ── Tunables ────────────────────────────────────────────────────────────────


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

# Hard blocklist — names that DNS-resolve and Hunter returns a contact for
# but are NOT real companies we should outreach. Checked exact casefold match.
_HARD_REJECT_NAMES = {
    "airbnb",           # consumer marketplace — not a CRE prospect
    "nabla",            # AI tool, not B2B office tenant
    "failory",          # media blog
    "hypepotamus",      # tech blog
    "businesswire",     # wire service
    "business wire",
    "charlotte observer", "georgia institute", "science square",
    "business facilities", "relocate hq to metro",
    "health tech company to",
    "comments url", "article url", "comments", "points",
    "watch", "medical", "commerce", "investing", "failory",
    "cobb county", "abbott",  # consumer healthcare
}

_DECISION_TITLES = {
    "ceo", "coo", "cfo", "cto", "chief", "head of", "vp ",
    "vice president", "svp", "evp", "director", "president",
    "chief of staff", "founder", "co-founder", "managing partner",
}

# Real-estate intent keywords. An article that doesn't mention any of these
# isn't useful even if it does mention a real company — there's no signal
# about leasing, expansion, or hiring that would matter to a tenant-rep
# broker. This is the strongest single filter in the pipeline.
_RE_INTENT_KEYWORDS = {
    # explicit real-estate
    "lease", "leased", "leases", "leasing",
    "sublease", "sublet",
    "headquarter", "headquarters", "hq",
    "office", "offices", "campus", "workspace",
    "square feet", "sq ft", "sqft", "sq. ft", "sq.ft.",
    "footprint", "real estate",
    "tenant", "landlord", "broker",
    # corporate move signals
    "expand", "expansion", "expanding", "expanded",
    "relocate", "relocation", "relocating", "relocated",
    "moves", "moving", "moved to",
    "opens", "opening", "opened",
    "signs", "signed", "signing",
    "new home", "new office", "new headquarters",
    # growth signals (weaker but useful)
    "hiring", "hire", "hired", "hires",
    "headcount", "workforce",
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


def _log_error(scope: str, exc) -> None:
    log = _read_json(ERROR_LOG_PATH, [])
    log.append({
        "at":    datetime.datetime.now().isoformat(),
        "scope": scope,
        "error": str(exc),
        "type":  type(exc).__name__ if isinstance(exc, BaseException) else "info",
    })
    _write_json(ERROR_LOG_PATH, log[-200:])


def _log_reject(stage: str, company: str, detail: str = "") -> None:
    """Structured rejection log — separate scope so it's measurable."""
    log = _read_json(ERROR_LOG_PATH, [])
    log.append({
        "at":      datetime.datetime.now().isoformat(),
        "scope":   f"lead_discovery.reject.{stage}",
        "error":   f"{company}: {detail}" if detail else company,
        "type":    "rejected",
    })
    _write_json(ERROR_LOG_PATH, log[-200:])


def _slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s.strip().lower())
    return s.strip("-")


def _existing_watchlist_domains() -> set:
    out = set()
    for p in database.get_watchlist(active_only=False):
        if p.get("domain"):
            out.add(p["domain"].lower())
        if p.get("company"):
            out.add(_slugify(p["company"]))
    return out


def _dismissed_ids() -> set:
    ids = set(database.get_dismissed_ids())
    ids.update(_read_json(DISMISSED_PATH, []))
    return ids


# ── Validity gates ──────────────────────────────────────────────────────────


# Cache to avoid re-resolving the same domain repeatedly in one run
_dns_cache: Dict[str, bool] = {}


def _domain_resolves(domain: str) -> bool:
    """
    Gate 1: does this domain have a DNS A-record?
    Auto-generated domains like 'relocatehqtometro.com' don't resolve.
    Real companies' domains do. Sub-100ms per check, cached per-run.
    """
    if not domain or "." not in domain:
        return False
    if domain in _dns_cache:
        return _dns_cache[domain]
    try:
        socket.setdefaulttimeout(3.0)
        socket.gethostbyname(domain)
        _dns_cache[domain] = True
        return True
    except (socket.gaierror, socket.herror, OSError):
        _dns_cache[domain] = False
        return False
    finally:
        socket.setdefaulttimeout(None)


def _article_has_re_intent(text: str) -> bool:
    """
    Gate 2: does the originating article contain ANY real-estate-relevant
    keyword? If not, the lead has no signal value even if the company is
    real. Catches generic mentions in unrelated articles.
    """
    if not text:
        return False
    text_lower = text.lower()
    return any(kw in text_lower for kw in _RE_INTENT_KEYWORDS)


# ── Company-name extraction from article text ───────────────────────────────


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
        "San Francisco", "Los Angeles", "Washington", "Chicago",
        "Boston", "Austin", "Miami", "Seattle", "Toronto", "London",
        "Berlin", "Tokyo", "Paris", "Singapore", "Dubai",
        "Atlanta", "Charlotte", "Dallas", "Denver", "Houston",
        "Phoenix", "Philadelphia", "Detroit", "Baltimore", "Portland",
        "Georgia", "Buckhead", "Midtown", "Midtown Atlanta",
        "Sandy Springs", "Alpharetta", "Marietta", "Decatur",
        # NEW: more geo / institution junk
        "Cobb County", "Fulton County", "DeKalb County", "Gwinnett",
        "Oakland", "Bellevue", "Charlotte Observer", "Georgia Institute",
        "Science Square", "Business Facilities",
        "Kubernetes", "Docker", "Swift", "Kotlin", "TypeScript",
        "GraphQL", "Postgres", "MongoDB", "Redis", "AWS", "GCP",
        "Azure", "Linux", "Ubuntu", "Mac", "Windows", "MySQL",
        "React Native", "Vue", "Angular", "Django", "Flask",
        "Terraform", "Ansible", "Jenkins", "Grafana", "Datadog",
        "Data Scientists", "Software Engineers", "Product Managers",
        "Account Executives", "Site Reliability", "Machine Learning",
        "Customer Success", "Business Development",
        "Solutions Engineer", "Solutions Architect", "Sales Engineer",
        "Data Engineering", "Tech Stack",
        "Please", "Front", "Back", "Side", "End", "Begin", "Start",
        "Investing", "Medical", "Watch", "Simple", "Comments",
        "Regarding", "Excellent", "Commerce",
        "Cookies", "Privacy", "Policy", "Terms", "Sitemap", "Subscribe",
        "Newsletter", "Account", "Profile", "Settings", "Notifications",
        "Show HN", "Comments URL", "Article URL",
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
        "Facebook", "Twitter", "X", "Instagram", "TikTok", "YouTube",
        "Snapchat", "Pinterest", "Reddit", "LinkedIn",
        "Google", "Alphabet", "Apple", "Microsoft", "Amazon", "Meta",
        "Exclusive", "Funding Rounds", "Biggest Funding Rounds",
        "Largest Funding Rounds", "Latest Funding", "Largest NYC",
        "Largest NYC Tech Startup", "Biggest", "Largest", "Newest",
        "Hottest", "Coolest", "Worst", "Strongest", "Weakest",
        "Story", "Stories", "Headlines", "Headline", "Report",
        "Reports", "Roundup", "Recap", "Digest", "Wrap",
        "First Edition", "Special Report", "Special Edition",
        "Exclusive Design", "First Look", "Quick Look",
        "Park Avenue", "Fifth Avenue", "Madison Avenue", "Wall Street",
        "Times Square", "Hudson Yards", "Bryant Park", "Central Park",
        "Sixth Avenue", "Lexington Avenue", "Broadway", "Battery Park",
        "Union Square", "Washington Square", "Columbus Circle",
        "Rockefeller Center", "Grand Central", "Penn Station",
        "Grand Opening", "Global Headquarters", "New Global Headquarters",
        "Corporate Headquarters", "World Headquarters", "Head Office",
        "Open House", "Ribbon Cutting", "Town Hall", "Annual Report",
        "Earnings Call", "Investor Day",
        "Business Journals", "The Business Journals", "Business Today",
        "Economic Times", "The Economic Times", "Livemint",
        "Hacker News", "The Healthcare Technology Report",
        "Healthcare Technology Report", "Healthcare Technology Companies",
        "The Top", "Spring Health Implements",
        "India Today", "Mashable", "Mashable.com", "Engadget",
        "PCMag", "blog.google",
    }
}

_HEADLINE_PREFIX_TOKENS = {
    "biggest", "largest", "newest", "hottest", "coolest", "worst",
    "strongest", "weakest", "latest", "freshest", "leading",
    "top", "best", "first", "last", "most", "least", "exclusive",
    "breaking", "relocate", "relocates", "relocating",
}

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

_COMMON_NOUN_TOKENS = {
    "funding", "rounds", "round", "tech", "startup", "startups",
    "company", "companies", "deal", "deals", "investor", "investors",
    "report", "reports", "story", "stories", "news", "update",
    "updates", "edition", "digest", "wrap", "recap", "headline",
    "headlines", "industry", "sector", "market", "markets",
    "ai", "machine", "learning", "data", "science", "platform",
    "healthcare", "healthtech", "medtech", "biotech",
    "technology", "technologies", "fintech", "saas",
    "service", "services", "solutions", "systems",
    "innovation", "innovations",
    "group", "groups", "team", "teams", "world", "global",
    "top", "best", "first",
    "venture", "ventures", "brand", "brands", "business",
    "businesses", "enterprise", "enterprises",
    # NEW: more headline-fragment fodder
    "to", "from", "with", "after", "before", "about", "as",
    "metro", "area", "region", "district",
    "institute", "university", "college", "school",
    "facilities", "facility", "observer", "tribune", "herald",
    "post", "gazette", "journal", "magazine",
    "comments", "url", "show", "regarding", "watch", "simple",
    "excellent", "investing", "medical", "engineering", "stack",
}

_JOB_TITLE_TOKENS = {
    "engineer", "engineers", "developer", "developers",
    "designer", "designers", "manager", "managers",
    "director", "directors", "specialist", "specialists",
    "analyst", "analysts", "associate", "associates",
    "consultant", "consultants", "coordinator", "coordinators",
    "intern", "interns", "trainee", "trainees",
    "architect", "architects", "scientist", "scientists",
    "researcher", "researchers", "writer", "writers",
    "ux", "ui", "qa", "devops", "sre",
}


def _looks_like_company(phrase: str) -> bool:
    tokens = phrase.split()
    if not tokens or len(tokens) > 4:
        return False
    if phrase.casefold() in _COMMON_ENGLISH_CAPS:
        return False

    token_lowers = [t.casefold() for t in tokens]

    # NEW: cross-list "all-junk" check — every token belongs to some
    # known junk list. Catches "Health Tech Company To",
    # "Data Engineering Tech Stack", etc.
    def _is_junk_token(t: str) -> bool:
        return (
            t in _COMMON_ENGLISH_CAPS
            or t in _COMMON_NOUN_TOKENS
            or t in _HEADLINE_PREFIX_TOKENS
            or t in _HEADLINE_VERB_TOKENS
            or t in _JOB_TITLE_TOKENS
            or t in {w.casefold() for w in _NOISE_WORDS}
        )

    if all(_is_junk_token(t) for t in token_lowers):
        return False

    if any(t in _NOISE_WORDS for t in tokens):
        if not (len(tokens) >= 2 and any(t not in _NOISE_WORDS for t in tokens)):
            return False
    if all(len(t) <= 2 for t in tokens):
        return False
    if phrase == phrase.upper() and len(phrase) > 1:
        return False
    if all(t in _COMMON_ENGLISH_CAPS for t in token_lowers):
        return False
    if token_lowers[0] in _HEADLINE_PREFIX_TOKENS:
        return False
    if any(t in _HEADLINE_VERB_TOKENS for t in token_lowers):
        return False
    if any(t in _JOB_TITLE_TOKENS for t in token_lowers):
        return False
    if all(t in _COMMON_NOUN_TOKENS for t in token_lowers):
        return False
    if (
        len(tokens) >= 2
        and token_lowers[0] == "the"
        and all(
            t in _COMMON_NOUN_TOKENS or t in _COMMON_ENGLISH_CAPS
            for t in token_lowers[1:]
        )
    ):
        return False

    for t in tokens:
        if len(t) > 24:
            return False
        if len(t) > 18 and "-" not in t:
            return False
        if len(t) > 12 and not any(c.lower() in "aeiou" for c in t[len(t)//2:]):
            return False

    if len(tokens) == 1:
        t = tokens[0]
        if t.casefold() in _COMMON_ENGLISH_CAPS:
            return False
        if len(t) < 5 and not any(c.isdigit() for c in t):
            return False
    return True


def _clean_candidate_name(name: str) -> str:
    """
    Strip noise prefixes / suffixes that pollute company names scraped
    from news headlines and Crunchbase titles.

    Examples:
      "Atlanta-Based OneTrust"          → "OneTrust"
      "Exclusive: Stripe Challenger Rainforest" → "Rainforest"
      "The Briefing: Human Interest"    → "Human Interest"
      "GLOBAL PAYMENTS INC"             → "Global Payments"
      "CoreCard Corp"                   → "CoreCard"
    """
    if not name:
        return name

    # Strip leading geo/descriptor prefixes like "Atlanta-Based ", "NYC-Based "
    name = re.sub(
        r"^[A-Z][A-Za-z\-]+\-Based\s+",   # "Atlanta-Based "
        "", name,
    ).strip()

    # Strip leading publication prefixes: "Exclusive: ", "The Briefing: "
    name = re.sub(r"^[A-Za-z\s]+:\s+", "", name, count=1).strip()

    # Strip leading descriptor words before the actual company name
    # "Stripe Challenger Rainforest" → try to keep the LAST capitalised word
    # if the phrase is >3 tokens and ends with a proper noun
    tokens = name.split()
    if len(tokens) >= 3:
        # If first 1-2 tokens are known descriptors, strip them
        _DESCRIPTOR_PREFIXES = {
            "stripe", "uber", "shopify", "microsoft", "google", "amazon",
            "challenger", "rival", "competitor", "alternative", "spinout",
            "spinoff", "startup", "startup", "backed", "funded", "led",
        }
        while len(tokens) > 1 and tokens[0].lower() in _DESCRIPTOR_PREFIXES:
            tokens = tokens[1:]
        name = " ".join(tokens)

    # Strip legal suffixes
    name = re.sub(
        r"\s+(Inc\.?|LLC\.?|Ltd\.?|Corp\.?|Co\.?|L\.P\.|LP|LLP)$",
        "", name, flags=re.IGNORECASE,
    ).strip()

    # Normalise all-caps to title case (e.g. "GLOBAL PAYMENTS" → "Global Payments")
    if name == name.upper() and len(name) > 4:
        name = name.title()

    return name.strip()


def _extract_companies(texts: List[str]) -> List[str]:
    counter: Counter = Counter()
    for text in texts:
        if not text:
            continue
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
    # Require count >= 2 for news-extracted names (strong dedup signal)
    # Single-count extractions are too noisy from article boilerplate
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


# ── Source 3: BuiltIn + HN Jobs ─────────────────────────────────────────────


def _builtinnyc_companies(sector_hint: str = "") -> List[str]:
    url = "https://www.builtinatlanta.com/jobs"
    try:
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
    except requests.RequestException as exc:
        _log_error("lead_discovery.builtin", exc)
        return []
    if resp.status_code != 200:
        return []
    candidates: List[str] = []
    text = resp.text
    for match in re.findall(
        r'data-cy=["\']company-name["\'][^>]*>([^<]+)<', text
    ):
        name = match.strip()
        if name and _looks_like_company(name):
            candidates.append(name)
    if not candidates:
        candidates = _extract_companies([text[:30000]])
    seen, deduped = set(), []
    for c in candidates:
        if c.lower() in seen:
            continue
        seen.add(c.lower())
        deduped.append(c)
    return deduped[:20]


def _hn_jobs_companies() -> List[str]:
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
            f"https://hn.algolia.com/api/v1/items/{thread_id}", timeout=15
        ).json()
    except Exception as exc:
        _log_error("lead_discovery.hn.thread", exc)
        return []
    _LOCATION_HINTS = ("atlanta", "georgia", ", ga", "buckhead", "midtown")
    local_blobs = []
    for child in thread.get("children", [])[:200]:
        text = (child.get("text") or "")
        if any(hint in text.lower() for hint in _LOCATION_HINTS):
            local_blobs.append(text)
    return _extract_companies(local_blobs)[:20]


# ── Hunter.io contact lookup — multi-domain strategy ────────────────────────


def _domain_for(company: str) -> str:
    """Legacy single-guess fallback. Prefer _resolve_domain() instead."""
    return _slugify(company).replace("-", "") + ".com"


def _build_domain_candidates(name: str) -> List[str]:
    """
    Build multiple plausible domain guesses for a company name.
    Strips legal suffixes before building candidates so that
    'Global Payments Inc' -> globalpayments.com (not global.com).
    'Spring Health' -> ['springhealth.com','spring-health.com', ...]
    """
    # Strip legal entity suffixes before building domains
    clean = re.sub(
        r"\s+(Inc\.?|LLC\.?|Ltd\.?|Corp\.?|Co\.?|L\.P\.|LP|LLP)$",
        "", name.strip(), flags=re.IGNORECASE,
    ).strip()

    words = re.findall(r"[A-Za-z0-9]+", clean)
    if not words:
        words = re.findall(r"[A-Za-z0-9]+", name)

    compact    = "".join(words).lower()
    hyphenated = "-".join(w.lower() for w in words)
    first_word = words[0].lower() if words else ""
    tlds = [".com", ".io", ".co", ".ai"]
    candidates: List[str] = []
    for tld in tlds:
        c = compact + tld
        if c not in candidates:
            candidates.append(c)
    if len(words) > 1:
        for tld in tlds[:2]:
            c = hyphenated + tld
            if c not in candidates:
                candidates.append(c)
    if first_word and first_word != compact:
        candidates.append(first_word + ".com")
    if len(compact) <= 12:
        candidates.append(f"get{compact}.com")
    return candidates[:7]


def _resolve_domain(company: str) -> Optional[str]:
    """
    Resolve a company name to its real domain.
    1. Try each domain candidate against DNS.
    2. If Hunter is available, confirm with Hunter (first hit wins).
    Returns the verified domain or None.
    """
    candidates = _build_domain_candidates(company)

    # Phase 1: DNS check — cheap, no quota used
    dns_hits = [d for d in candidates if _domain_resolves(d)]
    if not dns_hits:
        return None

    # Phase 2: Hunter confirmation — pick the domain Hunter knows emails for
    if config.HUNTER_AVAILABLE:
        for domain in dns_hits:
            try:
                resp = requests.get(
                    "https://api.hunter.io/v2/domain-search",
                    params={
                        "domain":  domain,
                        "api_key": config.HUNTER_API_KEY,
                        "limit":   1,
                    },
                    timeout=8,
                )
                if resp.status_code == 429:
                    break   # quota hit — fall back to first DNS hit
                if resp.status_code != 200:
                    continue
                data = resp.json().get("data") or {}
                emails = data.get("emails") or []
                total  = (data.get("meta") or {}).get("total") or 0
                if emails or total > 0:
                    return domain
            except requests.RequestException:
                continue

    # Phase 3: fallback to first DNS-resolving candidate
    return dns_hits[0] if dns_hits else None


def _hunter_lookup(domain: str) -> Dict:
    """Hunter domain-search for executive contacts on a confirmed domain."""
    if not config.HUNTER_AVAILABLE or not domain:
        return {}
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={
                "domain":    domain,
                "api_key":   config.HUNTER_API_KEY,
                "limit":     5,
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
        "linkedin":  best.get("linkedin", ""),
    }


# ── Real-data sources: EDGAR + Crunchbase ───────────────────────────────────


def _edgar_company_names(geo: str, sectors: List[str]) -> List[str]:
    """
    Pull verified company names from SEC EDGAR Form D filings.
    Cleans legal suffixes from names.
    """
    try:
        from scrapers.edgar_scraper import scrape as edgar_scrape
        _GEO_TO_STATE = {
            "atlanta": "GA", "georgia": "GA", "buckhead": "GA",
            "midtown": "GA", "sandy springs": "GA", "alpharetta": "GA",
            "new york": "NY", "manhattan": "NY", "brooklyn": "NY",
            "boston": "MA", "san francisco": "CA", "los angeles": "CA",
            "chicago": "IL", "austin": "TX", "miami": "FL",
            "seattle": "WA", "washington dc": "DC", "denver": "CO",
        }
        state = _GEO_TO_STATE.get(geo.lower(), "GA")
        raw = edgar_scrape(state=state, industry_keywords=sectors, days_back=540, max_results=30)
        cleaned: List[str] = []
        for r in raw:
            name = r.get("company", "")
            if name:
                name = _clean_candidate_name(name)
                if name and len(name) >= 3:
                    cleaned.append(name)
        return cleaned
    except Exception as exc:
        _log_error("lead_discovery.edgar", exc)
        return []


def _crunchbase_company_names(geo: str, sectors: List[str]) -> List[str]:
    """
    Pull recently funded company names from Crunchbase via Google News RSS.
    Applies _clean_candidate_name to strip headline prefixes.
    """
    try:
        from scrapers.crunchbase_scraper import scrape as cb_scrape
        raw = cb_scrape(geo=geo, sectors=sectors, days_back=540, max_results=25)
        cleaned: List[str] = []
        for r in raw:
            name = r.get("company", "")
            if name:
                name = _clean_candidate_name(name)
                if name and len(name) >= 3:
                    cleaned.append(name)
        return cleaned
    except Exception as exc:
        _log_error("lead_discovery.crunchbase", exc)
        return []


# ── Main entry points ───────────────────────────────────────────────────────


def _icp_queries(icp_profile: Dict) -> List[str]:
    sectors = icp_profile.get("sectors") or [icp_profile.get("sector", "tech")]
    geo     = (icp_profile.get("geographies") or ["Atlanta"])[0]
    sector  = sectors[0] if sectors else "tech"
    return [
        f"{sector} company {geo} hiring expansion office",
        f"{sector} startup Series B Series C {geo}",
        f"{geo} {sector} company new headquarters",
        f"{geo} {sector} funding announcement",
        f"{geo} office lease {sector}",
        f"{geo} {sector} raises million",
        f"{geo} {sector} new office space lease",
    ]


def _find_mention(articles: List[Dict], company: str) -> Dict:
    """Find the first article whose title or description mentions the company."""
    c_lower = company.lower()
    for a in articles:
        blob = (a.get("title", "") + " " + a.get("description", "")).lower()
        if c_lower in blob:
            return a
    return {}


def discover_new_leads(icp_profile: Dict, max_results: int = 10) -> List[Dict]:
    """
    Discover candidate leads from multiple real-data sources.

    Source priority (real data first):
      1. SEC EDGAR Form D filings — legally verified companies + funding date
      2. Crunchbase RSS — recently funded companies via Google News
      3. Google News RSS — sector + geo filtered news
      4. NewsAPI — recent article mentions
      5. BuiltIn Atlanta — active hiring companies
      6. Hacker News "Who's Hiring" — tech companies

    Validity gates (cheap → expensive):
      G1. Multi-domain DNS resolution (tries 7 domain variants)
      G1.5. Wikidata + Gemini entity-type classification
      G2. RE-intent keyword in originating article (news sources only)
      G3. Hunter.io executive contact on the RESOLVED domain
    """
    sectors   = icp_profile.get("sectors") or [icp_profile.get("sector", "Technology")]
    geo       = (icp_profile.get("geographies") or ["Atlanta"])[0]
    sector    = sectors[0] if sectors else "Technology"
    queries   = _icp_queries(icp_profile)
    existing  = _existing_watchlist_domains()
    dismissed = _dismissed_ids()
    today     = datetime.date.today().isoformat()
    now_iso   = datetime.datetime.now().isoformat()
    profile_id = icp_profile.get("id") or icp_profile.get("name") or "default"

    # ── Phase 1: Collect from all sources in parallel ────────────────────────
    articles: List[Dict] = []
    builtin_names: List[str] = []
    hn_names:      List[str] = []
    edgar_names:   List[str] = []
    crunchbase_names: List[str] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures_articles = []
        for q in queries:
            futures_articles.append(pool.submit(_google_news_articles, q))
            futures_articles.append(pool.submit(_newsapi_articles, q))

        fut_builtin    = pool.submit(_builtinnyc_companies)
        fut_hn         = pool.submit(_hn_jobs_companies)
        fut_edgar      = pool.submit(_edgar_company_names, geo, sectors)
        fut_crunchbase = pool.submit(_crunchbase_company_names, geo, sectors)

        for fut in as_completed(futures_articles):
            try:
                result = fut.result()
                if isinstance(result, list) and result and isinstance(result[0], dict):
                    articles.extend(result)
            except Exception as exc:
                _log_error("lead_discovery.fetch_articles", exc)

        for fut, dest, label in [
            (fut_builtin,    builtin_names,    "builtin"),
            (fut_hn,         hn_names,         "hn"),
            (fut_edgar,      edgar_names,      "edgar"),
            (fut_crunchbase, crunchbase_names, "crunchbase"),
        ]:
            try:
                result = fut.result()
                if isinstance(result, list):
                    dest.extend(result)
            except Exception as exc:
                _log_error(f"lead_discovery.fetch_{label}", exc)

    # ── Phase 2: Extract company names from news articles ────────────────────
    blobs = [f"{a.get('title','')}. {a.get('description','')}" for a in articles]
    article_names = _extract_companies(blobs)

    # ── Phase 3: Deduplicate across all sources ───────────────────────────────
    # Priority: EDGAR > Crunchbase > BuiltIn > HN > News (real data first)
    ordered_sources = (
        [(n, "SEC EDGAR")        for n in edgar_names]
        + [(n, "Crunchbase")     for n in crunchbase_names]
        + [(n, "BuiltIn")        for n in builtin_names]
        + [(n, "Hacker News")    for n in hn_names]
        + [(n, "News Article")   for n in article_names]
    )

    all_names: List[Tuple[str, str]] = []
    seen_keys = set()
    for name, source_label in ordered_sources:
        key = _slugify(name)
        if not key or key in seen_keys:
            continue
        if key in existing:
            continue
        candidate_id = f"discovered-{key}-{today}"
        if candidate_id in dismissed:
            continue
        seen_keys.add(key)
        all_names.append((name, source_label))

    # ── Phase 4: Validate through gates ─────────────────────────────────────
    candidates: List[Dict] = []
    stats = Counter()
    is_edgar_or_crunchbase = {_slugify(n) for n in edgar_names + crunchbase_names}

    for raw_name, source_label in all_names[: max_results * 8]:
        stats["seen"] += 1

        # Gate 0: Clean the name (strip geo prefixes, legal suffixes, all-caps)
        name = _clean_candidate_name(raw_name)
        if not name or len(name) < 3:
            stats["rejected_name_clean"] += 1
            continue

        # Gate 0.5: Hard reject list — names that pass DNS/Hunter but are NOT
        # companies we should be pitching (media, blogs, govt, generic words)
        if name.lower().strip() in _HARD_REJECT_NAMES:
            _log_reject("hard_reject", name, "in hard-reject list")
            stats["rejected_hard"] += 1
            continue

        # Gate 0.6: Reject single-word generic English nouns
        # Multi-word company names rarely need this check; single words do.
        if " " not in name and name.casefold() in _COMMON_NOUN_TOKENS | _COMMON_ENGLISH_CAPS:
            _log_reject("generic_word", name, "single generic noun")
            stats["rejected_generic"] += 1
            continue

        domain = _resolve_domain(name)
        if not domain:
            _log_reject("dns", name, f"{name} → no domain resolved")
            stats["rejected_dns"] += 1
            continue

        # Gate 1.5: Entity-type classification (Wikidata + Gemini fallback)
        # Skip for EDGAR/Crunchbase — they are definitionally real companies
        if _slugify(name) not in is_edgar_or_crunchbase:
            if not is_b2b_company(name, domain):
                _log_reject("entity_type", name, domain)
                stats["rejected_entity_type"] += 1
                continue

        # Gate 2: RE-intent check — only for news article leads
        mention: Dict = {}
        if source_label == "News Article":
            mention = _find_mention(articles, name)
            if mention:
                mt = mention.get("title", "") + " " + mention.get("description", "")
                if not _article_has_re_intent(mt):
                    _log_reject("no_intent", name, mention.get("title", "")[:80])
                    stats["rejected_no_intent"] += 1
                    continue
        # Structured sources (EDGAR, Crunchbase, BuiltIn, HN) skip Gate 2

        # Gate 3: Hunter must return a real executive contact
        contact = _hunter_lookup(domain)
        if not contact.get("full_name") or not contact.get("value"):
            _log_reject("no_contact", name, domain)
            stats["rejected_no_contact"] += 1
            continue

        stats["accepted"] += 1
        candidates.append({
            "id":             f"discovered-{_slugify(name)}-{today}",
            "company":        name,
            "domain":         domain,
            "website":        f"https://{domain}",
            "contact_name":   contact.get("full_name", ""),
            "contact_title":  contact.get("position", ""),
            "contact_email":  contact.get("value", ""),
            "linkedin_url":   contact.get("linkedin", ""),
            "sector":         sector,
            "city":           geo,
            "icp_profile":    profile_id,
            "source":         "discovered",
            "data_source":    source_label,
            "discovered_at":  now_iso,
            "discovered_via": mention.get("source", source_label),
            "discovery_url":  mention.get("url", ""),
            "approved":       True,
            "active":         True,
        })
        if len(candidates) >= max_results:
            break

    _log_error("lead_discovery.funnel", json.dumps(dict(stats)))
    return candidates


# ── Approve / dismiss ──────────────────────────────────────────────────────


def approve_lead(lead: Dict) -> bool:
    domain = (lead.get("domain") or "").lower()
    watch = database.get_watchlist(active_only=False)
    if domain and any((w.get("domain") or "").lower() == domain for w in watch):
        return False
    record = dict(lead)
    record["approved"]   = True
    record["source"]     = "watchlist"
    record["added_at"]   = datetime.date.today().isoformat()
    record.setdefault("active", True)
    database.upsert_prospect(record)
    wl = _read_json(WATCHLIST_PATH, [])
    if not any((w.get("domain") or "").lower() == domain for w in wl):
        wl.append(record)
        _write_json(WATCHLIST_PATH, wl)
    return True


def dismiss_lead(lead_id: str) -> bool:
    if not lead_id:
        return False
    database.dismiss_prospect(lead_id)
    dismissed = _read_json(DISMISSED_PATH, [])
    if lead_id not in dismissed:
        dismissed.append(lead_id)
        _write_json(DISMISSED_PATH, dismissed)
    return True


# ── CLI ────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    sample_icp = {
        "id": "tech_saas_atl",
        "name": "Tech / SaaS — Atlanta",
        "sectors": ["Technology"],
        "geographies": ["Atlanta"],
    }
    leads = discover_new_leads(sample_icp, max_results=5)
    print(json.dumps(leads, indent=2, default=str))
    print(f"\nTotal: {len(leads)} accepted leads")