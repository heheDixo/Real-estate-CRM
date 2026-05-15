import time
import requests
from typing import Optional
import config
from models.enrichment import JobPosting


# Keywords that indicate an office or workplace management role
OFFICE_ROLE_KEYWORDS = [
    "office manager", "office management",
    "workplace", "facilities", "real estate",
    "space planning", "office experience",
    "office operations", "corporate services",
    "head of office", "director of office",
    "office lead", "office coordinator",
]


class ProxycurlConnector:
    """
    Wrapper around the Proxycurl API for LinkedIn data.

    Two public methods:
      - get_job_postings(linkedin_url)     → list[JobPosting]
      - get_company_profile(linkedin_url)  → dict

    Falls back to empty results (not mock data) if:
      - PROXYCURL_API_KEY is not set
      - The LinkedIn URL is not available
      - The API returns an error

    We return empty rather than mock here because the enrichment
    pipeline checks sources_failed and handles missing Proxycurl
    data gracefully — the other two sources still provide signal.
    """

    BASE_URL    = "https://nubela.co/proxycurl/api"
    MAX_RETRIES = 3
    RETRY_WAIT  = 2

    def __init__(self):
        self.api_key   = config.PROXYCURL_API_KEY
        self.available = config.PROXYCURL_AVAILABLE and not config.FORCE_MOCK_MODE
        self.headers   = {"Authorization": f"Bearer {self.api_key}"}

    # Public methods


    def get_job_postings(self, linkedin_url: str,
                          target_geo: str = "New York") -> list:
        """
        Get active job postings for a company from LinkedIn via Proxycurl.

        Args:
            linkedin_url: company LinkedIn URL
                          e.g. "https://www.linkedin.com/company/healthaxis"
            target_geo:   geography to count as "in target geo"

        Returns:
            list of JobPosting instances
        """
        if not self.available or not linkedin_url:
            return []

        data = self._get_with_retry(
            endpoint = "/v2/linkedin/company/job",
            params   = {
                "linkedin_job_url": linkedin_url,
                "page":             1,
            },
        )

        if data is None:
            return []

        raw_jobs = data.get("job", []) or []
        postings = []

        for job in raw_jobs:
            title    = job.get("title", "")
            location = job.get("location", "")
            date_str = job.get("listed_at", "")

            posting = JobPosting(
                title             = title,
                location          = location,
                posted_date       = date_str[:10] if date_str else "",
                is_office_related = self._is_office_role(title),
            )
            postings.append(posting)

        return postings

    def get_company_profile(self, linkedin_url: str) -> dict:
        """
        Get the LinkedIn company profile for a given URL.

        Args:
            linkedin_url: company LinkedIn URL

        Returns:
            dict with follower_count, employee_count, description,
            or empty dict on failure
        """
        if not self.available or not linkedin_url:
            return {}

        data = self._get_with_retry(
            endpoint = "/v2/linkedin/company",
            params   = {
                "url":                     linkedin_url,
                "resolve_numeric_id":      "false",
                "categories":             "include",
                "funding_data":           "include",
                "exit_data":              "skip",
                "acquisitions":           "skip",
                "extra":                  "include",
            },
        )

        if data is None:
            return {}

        return {
            "follower_count":    data.get("follower_count", 0) or 0,
            "employee_count":    data.get("company_size_on_linkedin", 0) or 0,
            "description":       data.get("description", ""),
            "specialities":      data.get("specialities", []),
            "company_type":      data.get("company_type", ""),
            "hq_location":       self._extract_hq(data),
        }


    # Private helpers


    def _is_office_role(self, title: str) -> bool:
        """
        Check if a job title indicates an office or workplace management role.
        These are the strongest space-need signals in the job posting data.

        Args:
            title: job title string

        Returns:
            True if title matches any office role keyword
        """
        title_lower = title.lower()
        return any(kw in title_lower for kw in OFFICE_ROLE_KEYWORDS)

    def _extract_hq(self, data: dict) -> str:
        """Extract HQ city and country from company profile."""
        hq = data.get("hq", {}) or {}
        city    = hq.get("city", "")
        country = hq.get("country", "")
        if city and country:
            return f"{city}, {country}"
        return city or country or ""

    def _count_in_geo(self, postings: list, geo: str) -> int:
        """Count job postings in a target geography."""
        geo_lower = geo.lower()
        return sum(
            1 for p in postings
            if geo_lower in p.location.lower()
        )

    def get_hiring_summary(self, linkedin_url: str,
                            target_geo: str = "New York",
                            headcount: int = 1) -> dict:
        """
        Convenience method that returns a processed hiring summary
        combining job postings and velocity calculation.

        Used by pipeline/enrichment.py as the single Proxycurl call.

        Args:
            linkedin_url: company LinkedIn URL
            target_geo:   geography for in-geo count
            headcount:    current headcount for velocity calculation

        Returns:
            dict with all fields needed to populate EnrichmentResult
        """
        postings = self.get_job_postings(linkedin_url, target_geo)
        profile  = self.get_company_profile(linkedin_url)

        total_jobs       = len(postings)
        jobs_in_geo      = self._count_in_geo(postings, target_geo)
        office_roles     = sum(1 for p in postings if p.is_office_related)
        top_titles       = self._top_titles(postings, n=5)

        # hiring velocity: jobs posted as % of current headcount
        velocity = 0.0
        if headcount > 0 and total_jobs > 0:
            velocity = min(round((total_jobs / headcount) * 100, 1), 100.0)

        return {
            "job_postings":           postings,
            "total_jobs_posted":      total_jobs,
            "jobs_in_target_geo":     jobs_in_geo,
            "office_roles_posted":    office_roles,
            "top_job_titles":         top_titles,
            "linkedin_follower_count": profile.get("follower_count", 0),
            "linkedin_employee_count": profile.get("employee_count", 0),
            "hiring_velocity_score":  velocity,
        }

    def _top_titles(self, postings: list, n: int = 5) -> list:
        """Return the n most common job title words (excluding stop words)."""
        stop_words = {
            "senior", "junior", "lead", "head", "director", "manager",
            "of", "and", "the", "a", "in", "at", "for", "to",
        }
        title_words: dict = {}
        for p in postings:
            for word in p.title.lower().split():
                if word not in stop_words and len(word) > 3:
                    title_words[word] = title_words.get(word, 0) + 1

        sorted_words = sorted(
            title_words.items(), key=lambda x: x[1], reverse=True
        )
        return [w.title() for w, _ in sorted_words[:n]]

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
                    timeout = 20,
                )

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 429:
                    print(f"[Proxycurl] Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    wait *= 2
                    continue

                if response.status_code == 401:
                    print("[Proxycurl] Invalid API key.")
                    return None

                if response.status_code == 404:
                    print("[Proxycurl] Company profile not found.")
                    return None

                print(f"[Proxycurl] Status {response.status_code}")
                return None

            except requests.exceptions.Timeout:
                print(f"[Proxycurl] Timeout (attempt {attempt + 1})")
                time.sleep(wait)
                wait *= 2
            except requests.exceptions.ConnectionError as e:
                print(f"[Proxycurl] Connection error: {e}")
                return None

        print("[Proxycurl] Max retries reached.")
        return None