import time
import datetime
import requests
from typing import Optional
import config
from models.enrichment import NewsSignal


# Keywords that indicate different signal types
# Each dict maps signal_type → list of keywords to look for in headlines/excerpts

SIGNAL_KEYWORDS = {
    "expansion": [
        "expand", "expansion", "new office", "opens office",
        "new headquarters", "new location", "growing team",
        "new market", "entering", "launch", "opens in",
    ],
    "funding": [
        "raises", "raised", "funding", "series", "investment",
        "venture", "backed", "capital", "round", "million",
        "closes fund", "secures",
    ],
    "hiring": [
        "hiring", "headcount", "employees", "team growth",
        "adds", "recruits", "talent", "workforce",
        "staffing up", "growing team",
    ],
    "office": [
        "office", "headquarters", "hq", "workspace",
        "facilities", "real estate", "lease", "sublease",
        "sq ft", "square feet", "building",
    ],
    "relocation": [
        "relocat", "moves to", "moving to", "new address",
        "left their", "vacating", "from their office",
    ],
}

# Signal type priority — used to pick the "strongest" signal
SIGNAL_PRIORITY = [
    "expansion",
    "relocation",
    "office",
    "funding",
    "hiring",
]


class NewsAPIConnector:
    """
    Wrapper around NewsAPI for CRE-relevant news signals.

    One public method:
      - get_company_signals(company_name, days) → list[NewsSignal]

    Falls back to empty list if:
      - NEWSAPI_KEY is not set
      - FORCE_MOCK_MODE is True
      - The API returns an error
    """

    BASE_URL    = "https://newsapi.org/v2"
    MAX_RETRIES = 3
    RETRY_WAIT  = 2

    def __init__(self):
        self.api_key   = config.NEWSAPI_KEY
        self.available = config.NEWSAPI_AVAILABLE and not config.FORCE_MOCK_MODE
        self.headers   = {"X-Api-Key": self.api_key}


    # Public methods


    def get_company_signals(self, company_name: str,
                             days: int = 180) -> list:
        """
        Search for recent news about a company and filter for
        CRE-relevant signals.

        Args:
            company_name: company name to search for
            days:         how many days back to search

        Returns:
            list of NewsSignal instances, sorted by signal priority
        """
        if not self.available or not company_name:
            return []

        from_date = (
            datetime.datetime.now() - datetime.timedelta(days=days)
        ).strftime("%Y-%m-%d")

        params = {
            "q":          f'"{company_name}"',
            "from":       from_date,
            "sortBy":     "relevancy",
            "language":   "en",
            "pageSize":   20,
        }

        data = self._get_with_retry(
            endpoint = "/everything",
            params   = params,
        )

        if data is None:
            return []

        raw_articles = data.get("articles", []) or []
        signals      = []

        for article in raw_articles:
            headline = article.get("title", "") or ""
            excerpt  = article.get("description", "") or ""
            source   = (article.get("source", {}) or {}).get("name", "")
            url      = article.get("url", "")
            pub_date = article.get("publishedAt", "")[:10] \
                       if article.get("publishedAt") else ""

            # detect signal type from headline and excerpt
            signal_type = self._detect_signal_type(headline, excerpt)

            # only keep articles that are CRE-relevant
            if signal_type is None:
                continue

            signals.append(NewsSignal(
                headline       = headline,
                source         = source,
                published_date = pub_date,
                url            = url,
                signal_type    = signal_type,
                excerpt        = excerpt[:300] if excerpt else "",
            ))

        # sort by signal priority — expansion first, hiring last
        signals.sort(
            key=lambda s: SIGNAL_PRIORITY.index(s.signal_type)
            if s.signal_type in SIGNAL_PRIORITY else 99
        )

        return signals

    def get_signals_summary(self, company_name: str,
                             days: int = 180) -> dict:
        """
        Convenience method that returns a processed summary
        of all news signals for a company.

        Used by pipeline/enrichment.py as the single NewsAPI call.

        Args:
            company_name: company name to search
            days:         lookback window in days

        Returns:
            dict with all fields needed to populate EnrichmentResult
        """
        signals = self.get_company_signals(company_name, days)

        if not signals:
            return {
                "news_signals":            [],
                "total_news_signals":      0,
                "strongest_signal_type":   "",
                "strongest_signal_headline": "",
                "strongest_signal_date":   "",
                "has_expansion_news":      False,
                "has_funding_news":        False,
                "has_office_news":         False,
                "has_relocation_news":     False,
            }

        # determine which signal types are present
        signal_types = {s.signal_type for s in signals}

        # strongest = first in SIGNAL_PRIORITY that is present
        strongest = next(
            (t for t in SIGNAL_PRIORITY if t in signal_types),
            signals[0].signal_type if signals else ""
        )

        # find the strongest signal article
        strongest_article = next(
            (s for s in signals if s.signal_type == strongest),
            signals[0] if signals else None,
        )

        return {
            "news_signals":            signals,
            "total_news_signals":      len(signals),
            "strongest_signal_type":   strongest,
            "strongest_signal_headline": (
                strongest_article.headline if strongest_article else ""
            ),
            "strongest_signal_date": (
                strongest_article.published_date if strongest_article else ""
            ),
            "has_expansion_news":   "expansion"  in signal_types,
            "has_funding_news":     "funding"    in signal_types,
            "has_office_news":      "office"     in signal_types,
            "has_relocation_news":  "relocation" in signal_types,
        }


    # Private helpers


    def _detect_signal_type(self, headline: str,
                              excerpt: str) -> Optional[str]:
        """
        Detect the CRE signal type from a news article's headline
        and excerpt text.

        Returns the highest-priority signal type found,
        or None if no CRE-relevant signal is detected.

        Args:
            headline: article headline
            excerpt:  article description or first paragraph

        Returns:
            signal type string or None
        """
        combined = (headline + " " + excerpt).lower()

        # check signal types in priority order
        for signal_type in SIGNAL_PRIORITY:
            keywords = SIGNAL_KEYWORDS.get(signal_type, [])
            if any(kw in combined for kw in keywords):
                return signal_type

        return None

    def _get_with_retry(self, endpoint: str,
                         params: dict) -> Optional[dict]:
        """GET with exponential backoff on rate limit."""
        url  = f"{self.BASE_URL}{endpoint}"
        wait = self.RETRY_WAIT

        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.get(
                    url,
                    headers = self.headers,
                    params  = params,
                    timeout = 15,
                )

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 429:
                    print(f"[NewsAPI] Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    wait *= 2
                    continue

                if response.status_code == 401:
                    print("[NewsAPI] Invalid API key.")
                    return None

                if response.status_code == 426:
                    print("[NewsAPI] Plan upgrade required for this endpoint.")
                    return None

                print(f"[NewsAPI] Status {response.status_code}")
                return None

            except requests.exceptions.Timeout:
                print(f"[NewsAPI] Timeout (attempt {attempt + 1})")
                time.sleep(wait)
                wait *= 2
            except requests.exceptions.ConnectionError as e:
                print(f"[NewsAPI] Connection error: {e}")
                return None

        print("[NewsAPI] Max retries reached.")
        return None