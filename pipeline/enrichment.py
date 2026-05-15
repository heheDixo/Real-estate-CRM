import datetime
import config
from models.prospect   import Prospect
from models.enrichment import EnrichmentResult
from models.icp_profile import ICPProfile
from connectors        import ApolloConnector, ProxycurlConnector, NewsAPIConnector
from mock_data         import get_mock_enrichment


class EnrichmentPipeline:
    """
    Waterfall enrichment pipeline.
    Runs Apollo → Proxycurl → NewsAPI in sequence.
    Each source adds fields to one EnrichmentResult object.
    Falls back to mock data per-source if that source's API is unavailable.
    """

    def __init__(self):
        self.apollo    = ApolloConnector()
        self.proxycurl = ProxycurlConnector()
        self.newsapi   = NewsAPIConnector()

    def enrich(self, prospect: Prospect,
                icp: ICPProfile) -> EnrichmentResult:
        """
        Run the full enrichment waterfall for one prospect.

        Args:
            prospect: Prospect instance (status = "new")
            icp:      active ICPProfile — used for geo and trigger checks

        Returns:
            Fully populated EnrichmentResult
        """
        # if mock mode — return pre-built enrichment immediately
        if config.FORCE_MOCK_MODE:
            result = get_mock_enrichment(prospect.domain)
            prospect.advance_status("enriched")
            return result

        # initialise empty result
        result = EnrichmentResult(
            prospect_id = prospect.domain,
            enriched_at = datetime.datetime.now().isoformat(),
        )

        # ── Source 1: Apollo org enrichment ───────────────────────────────
        result = self._run_apollo(result, prospect)

        # ── Source 2: Proxycurl LinkedIn ──────────────────────────────────
        result = self._run_proxycurl(result, prospect, icp)

        # ── Source 3: NewsAPI ─────────────────────────────────────────────
        result = self._run_newsapi(result, prospect)

        # ── Computed fields ───────────────────────────────────────────────
        result.compute_headcount_growth()
        result.compute_hiring_velocity()

        # months since funding
        months = prospect.funding_months_ago()
        result.months_since_funding   = months
        result.is_in_deployment_window = (
            months is not None and
            config.DEPLOYMENT_WINDOW_MIN <= months <= config.DEPLOYMENT_WINDOW_MAX
        )

        # check which ICP triggers fired
        result.check_triggers(icp.trigger_signals, months)

        # build the HuggingFace description paragraph
        result.build_hf_description(prospect)

        # advance prospect status
        prospect.advance_status("enriched")

        return result

    # ──────────────────────────────────────────────────────────────────────────
    # Source runners
    # ──────────────────────────────────────────────────────────────────────────

    def _run_apollo(self, result: EnrichmentResult,
                     prospect: Prospect) -> EnrichmentResult:
        """
        Run Apollo org enrichment and populate Apollo block fields.
        Falls back gracefully if Apollo unavailable.
        """
        if not self.apollo.available:
            result.sources_failed.append("apollo")
            # use headcount from prospect as fallback
            result.headcount_current = prospect.headcount
            return result

        try:
            org_data = self.apollo.enrich_org(prospect.domain)

            if org_data:
                result.sources_used.append("apollo")
                result.founded_year      = org_data.get("founded_year", 0) or 0
                result.description       = org_data.get("description", "")
                result.technologies      = org_data.get("technologies", [])
                result.keywords          = org_data.get("keywords", [])
                result.annual_revenue    = org_data.get("annual_revenue", 0) or 0
                result.headcount_6mo_ago = org_data.get("headcount_6mo_ago", 0) or 0
                result.headcount_1yr_ago = org_data.get("headcount_1yr_ago", 0) or 0
                result.headcount_current = (
                    prospect.headcount or
                    org_data.get("headcount_6mo_ago", 0) or 0
                )
            else:
                result.sources_failed.append("apollo_org")
                result.headcount_current = prospect.headcount

        except Exception as e:
            print(f"[EnrichmentPipeline] Apollo error: {e}")
            result.sources_failed.append("apollo")
            result.headcount_current = prospect.headcount

        return result

    def _run_proxycurl(self, result: EnrichmentResult,
                        prospect: Prospect,
                        icp: ICPProfile) -> EnrichmentResult:
        """
        Run Proxycurl LinkedIn enrichment and populate Proxycurl block.
        Falls back gracefully if Proxycurl unavailable or no LinkedIn URL.
        """
        linkedin_url = prospect.linkedin_url
        if not linkedin_url or not self.proxycurl.available:
            if not linkedin_url:
                result.sources_failed.append("proxycurl_no_url")
            else:
                result.sources_failed.append("proxycurl")
            return result

        try:
            target_geo = icp.geographies[0] if icp.geographies else "New York"
            summary    = self.proxycurl.get_hiring_summary(
                linkedin_url = linkedin_url,
                target_geo   = target_geo,
                headcount    = result.headcount_current or 1,
            )

            result.sources_used.append("proxycurl")
            result.job_postings           = summary.get("job_postings", [])
            result.total_jobs_posted      = summary.get("total_jobs_posted", 0)
            result.jobs_in_target_geo     = summary.get("jobs_in_target_geo", 0)
            result.office_roles_posted    = summary.get("office_roles_posted", 0)
            result.top_job_titles         = summary.get("top_job_titles", [])
            result.linkedin_follower_count = summary.get("linkedin_follower_count", 0)
            result.linkedin_employee_count = summary.get("linkedin_employee_count", 0)
            result.hiring_velocity_score  = summary.get("hiring_velocity_score", 0.0)

        except Exception as e:
            print(f"[EnrichmentPipeline] Proxycurl error: {e}")
            result.sources_failed.append("proxycurl")

        return result

    def _run_newsapi(self, result: EnrichmentResult,
                      prospect: Prospect) -> EnrichmentResult:
        """
        Run NewsAPI signal search and populate news block.
        Falls back gracefully if NewsAPI unavailable.
        """
        if not self.newsapi.available:
            result.sources_failed.append("newsapi")
            return result

        try:
            summary = self.newsapi.get_signals_summary(
                company_name = prospect.company_name,
                days         = 180,
            )

            result.sources_used.append("newsapi")
            result.news_signals              = summary.get("news_signals", [])
            result.total_news_signals        = summary.get("total_news_signals", 0)
            result.strongest_signal_type     = summary.get("strongest_signal_type", "")
            result.strongest_signal_headline = summary.get("strongest_signal_headline", "")
            result.strongest_signal_date     = summary.get("strongest_signal_date", "")
            result.has_expansion_news        = summary.get("has_expansion_news", False)
            result.has_funding_news          = summary.get("has_funding_news", False)
            result.has_office_news           = summary.get("has_office_news", False)
            result.has_relocation_news       = summary.get("has_relocation_news", False)

        except Exception as e:
            print(f"[EnrichmentPipeline] NewsAPI error: {e}")
            result.sources_failed.append("newsapi")

        return result