import datetime
import requests
from typing import Optional
import config
from models.enrichment  import EnrichmentResult
from models.icp_profile import ICPProfile
from models.score_result import ScoreResult


class ProspectScorer:
    """
    Scores a prospect using facebook/bart-large-mnli zero-shot
    classification via the HuggingFace Inference API.

    One public method:
      - score(enrichment, icp) → ScoreResult

    Falls back to rule-based scoring if HF API is unavailable.
    """

    MODEL_URL = (
        f"{config.HF_API_BASE}/{config.SCORING_MODEL}"
    )

    def __init__(self):
        self.available = config.HF_AVAILABLE and not config.FORCE_MOCK_MODE
        self.headers   = {
            "Authorization": f"Bearer {config.HF_TOKEN}",
            "Content-Type":  "application/json",
        }


    # Public method


    def score(self, enrichment: EnrichmentResult,
               icp: ICPProfile) -> ScoreResult:
        """
        Score a prospect against the ICP using zero-shot classification.

        Args:
            enrichment: fully populated EnrichmentResult
            icp:        active ICPProfile

        Returns:
            ScoreResult with all dimension scores, composite, tier,
            signal bullets, and raw model output
        """
        description = enrichment.hf_description
        if not description:
            # build description if not already built
            description = f"Company with {enrichment.headcount_current} employees."

        result = ScoreResult(
            prospect_id      = enrichment.prospect_id,
            scored_at        = datetime.datetime.now().isoformat(),
            icp_profile_name = icp.name,
            model_used       = config.SCORING_MODEL,
            description_sent = description,
        )

        if self.available:
            raw = self._call_hf_api(description)
            if raw is not None:
                self._populate_from_hf(result, raw, icp)
                return result

        # fallback to rule-based scoring
        self._populate_from_rules(result, enrichment, icp)
        return result


    # HuggingFace API call


    def _call_hf_api(self, description: str) -> Optional[dict]:
        """
        Call the bart-large-mnli API with all twelve labels in one request.

        We flatten all label pairs into a single list and pass them as
        candidate_labels. The model returns a probability distribution
        across all twelve labels. We then pair them up to get dimension scores.

        Args:
            description: natural language prospect description

        Returns:
            dict of {label: confidence} or None on failure
        """
        # flatten all label pairs into one list
        all_labels = []
        for pos_label, neg_label in config.SCORING_LABEL_PAIRS:
            all_labels.append(pos_label)
            all_labels.append(neg_label)

        payload = {
            "inputs":     description,
            "parameters": {
                "candidate_labels":  all_labels,
                "multi_label":       False,
            },
        }

        try:
            response = requests.post(
                self.MODEL_URL,
                headers = self.headers,
                json    = payload,
                timeout = config.SCORING_TIMEOUT,
            )

            if response.status_code == 200:
                data   = response.json()
                labels = data.get("labels", [])
                scores = data.get("scores", [])
                return dict(zip(labels, scores))

            if response.status_code == 503:
                # model is loading — wait and retry once
                import time
                print("[Scorer] Model loading. Waiting 20s...")
                time.sleep(20)
                response = requests.post(
                    self.MODEL_URL,
                    headers = self.headers,
                    json    = payload,
                    timeout = config.SCORING_TIMEOUT,
                )
                if response.status_code == 200:
                    data   = response.json()
                    labels = data.get("labels", [])
                    scores = data.get("scores", [])
                    return dict(zip(labels, scores))

            print(f"[Scorer] HF API returned {response.status_code}")
            return None

        except requests.exceptions.Timeout:
            print("[Scorer] HF API timed out.")
            return None
        except Exception as e:
            print(f"[Scorer] HF API error: {e}")
            return None

    # Populate ScoreResult from HuggingFace output


    def _populate_from_hf(self, result: ScoreResult,
                            raw_scores: dict,
                            icp: ICPProfile) -> None:
        """
        Convert raw HuggingFace label confidences into dimension scores,
        composite, tier, and signal bullets.

        For each label pair, the dimension score is the positive label's
        share of the pair's combined probability, normalised to 0–100.

        Args:
            result:     ScoreResult to populate in-place
            raw_scores: dict of {label: confidence} from HF API
            icp:        ICPProfile for signal weights
        """
        result.raw_label_confidences = raw_scores

        # extract pair scores
        pair_scores = []
        for pos_label, neg_label in config.SCORING_LABEL_PAIRS:
            pos_conf = raw_scores.get(pos_label, 0.5)
            neg_conf = raw_scores.get(neg_label, 0.5)
            total    = pos_conf + neg_conf
            # normalise: positive label's share * 100
            score    = round((pos_conf / total * 100) if total > 0 else 50.0)
            pair_scores.append(score)

        # assign to dimension fields
        # order matches config.SCORING_LABEL_PAIRS
        result.hiring_velocity_score = float(pair_scores[0])
        result.funding_timing_score  = float(pair_scores[1])
        result.expansion_news_score  = float(pair_scores[2])
        result.lease_expiry_score    = float(pair_scores[3])
        result.decision_maker_score  = float(pair_scores[4])
        # pair_scores[5] is the "overall space need" — used for validation

        # weighted composite using ICP signal weights
        weights  = icp.signal_weights
        composite = (
            result.hiring_velocity_score * weights.get("hiring_velocity", 0.25) +
            result.funding_timing_score  * weights.get("funding_timing",  0.25) +
            result.expansion_news_score  * weights.get("expansion_news",  0.25) +
            result.lease_expiry_score    * weights.get("lease_expiry",    0.15) +
            result.decision_maker_score  * weights.get("decision_maker",  0.10)
        )
        result.composite = round(composite)

        # assign tier
        result.tier = self._assign_tier(result.composite)

        # extract signal bullets
        self._extract_signals(result)

        # identify top signal for Mistral
        self._identify_top_signal(result)


    # Rule-based fallback scoring


    def _populate_from_rules(self, result: ScoreResult,
                               enrichment: EnrichmentResult,
                               icp: ICPProfile) -> None:
        """
        Rule-based scoring used when HF API is unavailable.
        Uses computed fields from EnrichmentResult directly.

        This is not as nuanced as the model but produces reasonable
        scores that keep the demo running without API access.

        Args:
            result:     ScoreResult to populate in-place
            enrichment: EnrichmentResult with computed fields
            icp:        ICPProfile for signal weights
        """
        result.used_fallback_scoring = True
        result.fallback_reason       = "HuggingFace API unavailable"
        result.model_used            = "rule-based fallback"

        #  Hiring velocity score (0–100)
        vel = enrichment.hiring_velocity_score
        if vel >= config.HIRING_VELOCITY_HIGH:
            hv_score = min(50 + vel, 95.0)
        elif vel >= config.HIRING_VELOCITY_MEDIUM:
            hv_score = 55.0
        else:
            hv_score = max(20.0, vel * 1.5)

        # boost for headcount growth
        growth = enrichment.headcount_growth_pct
        if growth >= config.HEADCOUNT_GROWTH_HIGH:
            hv_score = min(hv_score + 15, 95.0)
        result.hiring_velocity_score = round(hv_score, 1)

        # Funding timing score (0–100) 
        months = enrichment.months_since_funding
        if months is None:
            ft_score = 35.0
        elif enrichment.is_in_deployment_window:
            # peak of deployment window = 100, edges = lower
            mid      = (config.DEPLOYMENT_WINDOW_MIN + config.DEPLOYMENT_WINDOW_MAX) / 2
            distance = abs(months - mid)
            ft_score = max(60.0, 95.0 - (distance * 5))
        elif months < config.DEPLOYMENT_WINDOW_MIN:
            ft_score = 45.0   # too recent — capital not yet deployed
        else:
            ft_score = max(20.0, 60.0 - ((months - 20) * 3))
        result.funding_timing_score = round(ft_score, 1)

        #  Expansion news score (0–100) 
        en_score = 30.0
        if enrichment.has_expansion_news:
            en_score = 90.0
        elif enrichment.has_office_news:
            en_score = 75.0
        elif enrichment.has_relocation_news:
            en_score = 70.0
        elif enrichment.has_funding_news:
            en_score = 50.0
        result.expansion_news_score = en_score

        # Lease expiry score (0–100)
        # Without CoStar data we use tenure as a proxy
        # (older companies are more likely to be near a lease expiry)
        le_score = 40.0
        if enrichment.has_relocation_news:
            le_score = 85.0
        elif enrichment.has_office_news:
            le_score = 65.0
        result.lease_expiry_score = le_score

        #  Decision maker score (0–100) 
        # We have a named contact from Apollo — that is a positive signal
        result.decision_maker_score = 65.0

        #  Weighted composite 
        weights   = icp.signal_weights
        composite = (
            result.hiring_velocity_score * weights.get("hiring_velocity", 0.25) +
            result.funding_timing_score  * weights.get("funding_timing",  0.25) +
            result.expansion_news_score  * weights.get("expansion_news",  0.25) +
            result.lease_expiry_score    * weights.get("lease_expiry",    0.15) +
            result.decision_maker_score  * weights.get("decision_maker",  0.10)
        )
        result.composite = round(composite)
        result.tier      = self._assign_tier(result.composite)

        # signal bullets
        self._extract_signals(result)
        self._identify_top_signal(result)

    # Signal extraction helpers


    def _assign_tier(self, composite: float) -> str:
        """Assign tier based on composite score."""
        if composite >= config.TIER_HOT:
            return "Hot"
        elif composite >= config.TIER_WARM:
            return "Warm"
        return "Nurture"

    def _extract_signals(self, result: ScoreResult) -> None:
        """
        Extract positive and risk signal bullets from dimension scores.

        Positive: dimension score >= SIGNAL_STRONG (65)
        Risk:     dimension score <= SIGNAL_WEAK   (40)

        Each bullet is a human-readable string shown in the UI.
        """
        dimension_map = {
            "Hiring velocity":  (result.hiring_velocity_score, [
                "Rapid headcount growth signals imminent space need",
                "High hiring velocity relative to current team size",
            ], [
                "Stable or declining headcount — no hiring pressure",
                "Low hiring activity — space need not imminent",
            ]),
            "Funding timing":   (result.funding_timing_score, [
                "In the 12–18 month post-funding deployment window",
                "Capital raised and likely being deployed on expansion",
            ], [
                "Outside typical deployment window — too early or too late",
                "No recent funding — capital constraint possible",
            ]),
            "Expansion news":   (result.expansion_news_score, [
                "Public expansion announcement detected in recent news",
                "Geographic growth into target market confirmed",
            ], [
                "No expansion news detected in last 6 months",
                "No geographic growth signals found",
            ]),
            "Lease expiry":     (result.lease_expiry_score, [
                "Lease expiry or relocation signal detected",
                "Office footprint change likely based on available signals",
            ], [
                "No lease expiry signal — may have recently signed",
                "Insufficient data on current lease status",
            ]),
            "Decision maker":   (result.decision_maker_score, [
                "Decision maker with real estate authority identified",
                "Named contact has operational or C-suite authority",
            ], [
                "Contact authority over real estate decisions unclear",
                "No clear decision maker identified in this company",
            ]),
        }

        positives = []
        risks     = []

        for dim_name, (score, pos_texts, neg_texts) in dimension_map.items():
            if score >= config.SIGNAL_STRONG:
                positives.append(f"{pos_texts[0]} ({score:.0f}/100)")
            elif score <= config.SIGNAL_WEAK:
                risks.append(f"{neg_texts[0]} ({score:.0f}/100)")

        result.positive_signals = positives
        result.risk_signals     = risks

    def _identify_top_signal(self, result: ScoreResult) -> None:
        """
        Identify the single strongest signal to pass to the Mistral
        writer as the email opening hook.

        The top signal is the dimension with the highest score that
        is above SIGNAL_STRONG (65). If none qualify, use the
        highest-scoring dimension regardless.
        """
        scores = {
            "hiring_velocity": result.hiring_velocity_score,
            "funding_timing":  result.funding_timing_score,
            "expansion_news":  result.expansion_news_score,
            "lease_expiry":    result.lease_expiry_score,
            "decision_maker":  result.decision_maker_score,
        }

        # pick highest scoring dimension
        top_dim   = max(scores, key=scores.get)
        top_score = scores[top_dim]

        signal_text_map = {
            "hiring_velocity": (
                "rapid headcount growth and high hiring activity"
            ),
            "funding_timing":  (
                "recent funding round placing them in the deployment window"
            ),
            "expansion_news":  (
                "public announcement of geographic expansion"
            ),
            "lease_expiry":    (
                "signals suggesting current lease may be expiring"
            ),
            "decision_maker":  (
                "direct access to operational decision maker"
            ),
        }

        result.top_signal_type = top_dim
        result.top_signal_text = signal_text_map.get(top_dim, top_dim)