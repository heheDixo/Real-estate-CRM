import time
import requests
from typing import Optional
import config
from models.prospect import Prospect
from mock_data import get_mock_prospect, get_all_mock_prospects


class ApolloConnector:
    """
    Wrapper around the Apollo.io API.

    Two public methods:
      - search_prospects(icp) → list[Prospect]
      - enrich_org(domain)    → dict

    Falls back to mock data if:
      - APOLLO_API_KEY is not set
      - FORCE_MOCK_MODE is True
      - The API returns an error after 3 retries
    """

    BASE_URL    = "https://api.apollo.io/v1"
    MAX_RETRIES = 3
    RETRY_WAIT  = 2   # seconds — doubles on each retry

    def __init__(self):
        self.api_key   = config.APOLLO_API_KEY
        self.available = config.APOLLO_AVAILABLE and not config.FORCE_MOCK_MODE
        self.headers   = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key":    self.api_key,
        }


    # Public methods


    def search_prospects(self, icp, max_results: int = 10) -> list:
        """
        Search Apollo for people matching the ICP's targeting filters.

        Args:
            icp:         ICPProfile instance — used to build search filters
            max_results: max number of prospects to return

        Returns:
            list of Prospect instances
        """
        if not self.available:
            return get_all_mock_prospects()

        payload = self._build_search_payload(icp, max_results)

        response_data = self._post_with_retry(
            endpoint = "/mixed_people/search",
            payload  = payload,
        )

        if response_data is None:
            return get_all_mock_prospects()

        raw_people = response_data.get("people", [])
        prospects  = []
        for person in raw_people:
            try:
                prospect = Prospect.from_apollo_record(person)
                # apply exclusions from ICP
                if self._passes_exclusions(prospect, icp):
                    prospects.append(prospect)
            except Exception as e:
                print(f"[Apollo] Failed to parse record: {e}")
                continue

        return prospects if prospects else get_all_mock_prospects()

    def enrich_org(self, domain: str) -> dict:
        """
        Get deeper company data for a domain from Apollo's
        organisation enrichment endpoint.

        Args:
            domain: company domain e.g. "healthaxis.io"

        Returns:
            dict of enrichment fields, or empty dict on failure
        """
        if not self.available:
            return {}

        response_data = self._get_with_retry(
            endpoint = "/organizations/enrich",
            params   = {"domain": domain},
        )

        if response_data is None:
            return {}

        org = response_data.get("organization", {}) or {}
        return {
            "description":     org.get("short_description", ""),
            "founded_year":    org.get("founded_year", 0) or 0,
            "technologies":    [t.get("name", "") for t in
                               org.get("technologies", [])],
            "keywords":        org.get("keywords", []),
            "annual_revenue":  org.get("annual_revenue_printed", 0) or 0,
            "linkedin_url":    org.get("linkedin_url", ""),
            "headcount_range": org.get("employee_count", ""),
            "sic_codes":       org.get("sic_codes", []),
            # Apollo sometimes has headcount at different time points
            "headcount_6mo_ago": org.get(
                "organization_headcount_six_months_ago", 0) or 0,
            "headcount_1yr_ago": org.get(
                "organization_headcount_one_year_ago", 0) or 0,
        }


    # Private helpers


    def _build_search_payload(self, icp, max_results: int) -> dict:
        """
        Convert an ICPProfile into an Apollo people search payload.

        Maps ICP fields to Apollo's filter parameter names.
        """
        # map company stages to Apollo's funding stage labels
        stage_map = {
            "Seed":              "seed",
            "Series A":          "series_a",
            "Series B":          "series_b",
            "Series C":          "series_c",
            "Series D+":         "series_d_plus",
            "Growth / PE-backed":"private_equity",
            "Bootstrapped":      "bootstrapped",
            "Public":            "public",
        }

        funding_stages = [
            stage_map[s] for s in icp.company_stages
            if s in stage_map
        ]

        # decision maker titles for CRE tenant rep
        titles = [
            "VP of Operations", "Chief of Staff", "COO", "CFO",
            "VP Real Estate", "Director of Facilities",
            "Workplace Experience", "Head of Operations",
            "VP Finance", "SVP Operations", "President",
            "CEO",   # for smaller companies
        ]

        return {
            "page":                    1,
            "per_page":                max_results,
            "person_titles":           titles,
            "organization_locations":  icp.geographies,
            "organization_num_employees_ranges": [
                f"{icp.headcount_min},{icp.headcount_max}"
            ],
            "organization_latest_funding_stage_cd": funding_stages,
            "q_organization_keyword_tags": icp.sectors,
            "contact_email_status": ["verified", "likely to engage"],
        }

    def _passes_exclusions(self, prospect: Prospect, icp) -> bool:
        """
        Check if a prospect passes the ICP's exclusion rules.

        Returns:
            True if prospect should be included, False if excluded
        """
        excl = icp.exclusions

        # minimum headcount check
        if prospect.headcount < excl.get("min_employees", 0):
            prospect.is_excluded     = True
            prospect.exclusion_reason = (
                f"Under minimum headcount "
                f"({prospect.headcount} < {excl['min_employees']})"
            )
            return False

        # excluded domains check
        excluded_domains = excl.get("excluded_domains", [])
        if prospect.domain in excluded_domains:
            prospect.is_excluded      = True
            prospect.exclusion_reason = "Domain on exclusion list"
            return False

        return True

    def _post_with_retry(self, endpoint: str, payload: dict) -> Optional[dict]:
        """
        POST to an Apollo endpoint with exponential backoff on 429.

        Returns:
            Response JSON dict, or None on failure after MAX_RETRIES
        """
        url   = f"{self.BASE_URL}{endpoint}"
        wait  = self.RETRY_WAIT

        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(
                    url,
                    headers = self.headers,
                    json    = payload,
                    timeout = 15,
                )

                if response.status_code == 200:
                    return response.json()

                if response.status_code == 429:
                    print(f"[Apollo] Rate limited. Waiting {wait}s... "
                          f"(attempt {attempt + 1}/{self.MAX_RETRIES})")
                    time.sleep(wait)
                    wait *= 2
                    continue

                if response.status_code == 401:
                    print("[Apollo] Invalid API key.")
                    return None

                print(f"[Apollo] Unexpected status {response.status_code}")
                return None

            except requests.exceptions.Timeout:
                print(f"[Apollo] Request timed out (attempt {attempt + 1})")
                time.sleep(wait)
                wait *= 2
            except requests.exceptions.ConnectionError as e:
                print(f"[Apollo] Connection error: {e}")
                return None

        print("[Apollo] Max retries reached. Falling back to mock data.")
        return None

    def _get_with_retry(self, endpoint: str,
                         params: dict) -> Optional[dict]:
        """
        GET from an Apollo endpoint with exponential backoff on 429.
        """
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
                    print(f"[Apollo] Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    wait *= 2
                    continue

                print(f"[Apollo] Status {response.status_code} on GET")
                return None

            except requests.exceptions.Timeout:
                print(f"[Apollo] GET timeout (attempt {attempt + 1})")
                time.sleep(wait)
                wait *= 2
            except requests.exceptions.ConnectionError as e:
                print(f"[Apollo] Connection error: {e}")
                return None

        return None