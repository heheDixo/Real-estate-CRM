# pipeline/scoring.py

import datetime
from models.prospect     import Prospect
from models.enrichment   import EnrichmentResult
from models.icp_profile  import ICPProfile
from models.score_result import ScoreResult
from hf_models           import ProspectScorer


class ScoringPipeline:
    """
    Thin orchestration wrapper around ProspectScorer.

    Exists to give pages a consistent (prospect, enrichment, icp) → ScoreResult
    interface without pages needing to know about hf_models internals.

    Responsibilities:
      1. Call ProspectScorer.score(enrichment, icp)
      2. Advance prospect.status to "scored"
      3. Return a ScoreResult — never raises, always returns something safe
    """

    def __init__(self):
        self.scorer = ProspectScorer()

    def score(self, prospect: Prospect,
               enrichment: EnrichmentResult,
               icp: ICPProfile) -> ScoreResult:
        """
        Score a prospect and return a ScoreResult.

        Args:
            prospect:   Prospect instance — status advanced to "scored" on success
            enrichment: EnrichmentResult instance with hf_description populated
            icp:        Active ICPProfile — provides signal_weights

        Returns:
            ScoreResult — always returns, never raises
        """
        try:
            # ProspectScorer.score() takes (enrichment, icp) — not prospect
            result = self.scorer.score(enrichment, icp)
            prospect.advance_status("scored")
            return result

        except Exception as e:
            print(f"[ScoringPipeline] Scoring failed: {e}")
            return self._safe_default(prospect, icp, str(e))

    # ──────────────────────────────────────────────────────────────────────────

    def _safe_default(self, prospect: Prospect,
                       icp: ICPProfile,
                       error: str) -> ScoreResult:
        """
        Return a safe Nurture-tier score when scoring fails entirely.
        Keeps the pipeline moving so the demo never hard-crashes.
        """
        prospect.advance_status("scored")
        return ScoreResult(
            prospect_id           = prospect.domain,
            scored_at             = datetime.datetime.now().isoformat(),
            icp_profile_name      = icp.name,
            model_used            = "safe default — scoring failed",
            composite             = 40.0,
            tier                  = "Nurture",
            positive_signals      = [],
            risk_signals          = [f"Scoring unavailable: {error}"],
            used_fallback_scoring = True,
            fallback_reason       = error,
        )