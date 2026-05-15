
import datetime
from models.prospect    import Prospect
from models.enrichment  import EnrichmentResult
from models.score_result import ScoreResult
from models.icp_profile  import ICPProfile
from models.draft_result import DraftResult
from hf_models           import ProspectBriefer, OutreachWriter


class DraftingPipeline:
    """
    Orchestrates the briefing + writing steps.
    Returns a fully populated DraftResult.
    """

    def __init__(self):
        self.briefer = ProspectBriefer()
        self.writer  = OutreachWriter()

    def draft(self, prospect: Prospect,
               enrichment: EnrichmentResult,
               score: ScoreResult,
               icp: ICPProfile) -> DraftResult:
        """
        Generate research brief, email draft, and LinkedIn message.

        Args:
            prospect:   Prospect instance (status = "scored")
            enrichment: EnrichmentResult instance
            score:      ScoreResult instance
            icp:        active ICPProfile

        Returns:
            Fully populated DraftResult
        """
        result = DraftResult(
            prospect_id      = prospect.domain,
            drafted_at       = datetime.datetime.now().isoformat(),
            icp_profile_name = icp.name,
        )

        # Step 1: Generate research brief 
        try:
            brief = self.briefer.generate_brief(prospect, enrichment, score)
            result.brief_bullets = brief
        except Exception as e:
            print(f"[DraftingPipeline] Briefing failed: {e}")
            result.brief_bullets = [
                f"**Company stage:** {prospect.company_stage} "
                f"company with {enrichment.headcount_current} employees.",
                f"**Space need signal:** Score {score.composite}/100 "
                f"— {score.tier}.",
                f"**Right contact:** {prospect.contact_name}, "
                f"{prospect.contact_title}.",
                "**Best angle:** Reference their recent growth trajectory.",
                "**Main risk:** Brief generation failed — review manually.",
            ]

        # Step 2: Generate email 
        try:
            subject, body = self.writer.generate_email(
                prospect, enrichment, score, icp, result.brief_bullets)
            result.email_subject = subject
            result.email_body    = body
        except Exception as e:
            print(f"[DraftingPipeline] Email generation failed: {e}")
            subject, body = self.writer._fallback_email(
                prospect, enrichment, score)
            result.email_subject = subject
            result.email_body    = body

        # ── Step 3: Generate LinkedIn message 
        try:
            linkedin_msg = self.writer.generate_linkedin(
                prospect, enrichment, score, icp)
            result.linkedin_message = linkedin_msg
        except Exception as e:
            print(f"[DraftingPipeline] LinkedIn generation failed: {e}")
            result.linkedin_message = self.writer._fallback_linkedin(
                prospect, enrichment, score)

        #  Step 4: Build personalisation tags 
        result.personalisation_tags = self._build_tags(enrichment, score)

        #  Step 5: Set opening signal
        result.opening_signal = self.writer._get_top_signal_sentence(
            prospect, enrichment, score)

        #  Step 6: Advance status 
        prospect.advance_status("drafted")

        return result

    def _build_tags(self, enrichment: EnrichmentResult,
                     score: ScoreResult) -> list:
        """
        Build the list of personalisation signal tags shown in the UI.
        Each tag is a short string describing which enrichment field
        fed into the draft.

        Args:
            enrichment: EnrichmentResult instance
            score:      ScoreResult instance

        Returns:
            list of tag strings
        """
        tags = []

        if enrichment.headcount_growth_pct >= 20:
            tags.append(
                f"📈 Headcount growth: +{enrichment.headcount_growth_pct:.0f}%"
            )

        if enrichment.total_jobs_posted > 0:
            tags.append(
                f"💼 {enrichment.total_jobs_posted} active job postings"
            )

        if enrichment.office_roles_posted > 0:
            tags.append(
                f"🏢 {enrichment.office_roles_posted} office/workplace role(s)"
            )

        if enrichment.is_in_deployment_window:
            tags.append(
                f"💰 In 12–18 month deployment window "
                f"({enrichment.months_since_funding}mo post-funding)"
            )

        if enrichment.has_expansion_news:
            tags.append("📰 Expansion announcement detected")

        if enrichment.has_funding_news:
            tags.append("💵 Funding news detected")

        if enrichment.strongest_signal_headline:
            short = enrichment.strongest_signal_headline[:50] + "..."
            tags.append(f"🔍 News: {short}")

        if score.top_signal_type:
            tags.append(f"⭐ Top signal: {score.top_signal_type.replace('_', ' ')}")

        return tags