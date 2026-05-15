from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ScoreResult:
    """
    Output of the HuggingFace scoring step.

    Contains all dimension scores, the composite, the tier,
    human-readable signal bullets, and the raw model output
    for transparency.

    The UI reads from this to show the score card on Page 2.
    The Mistral writer reads from this to know which signal
    to reference in the draft.
    """

    #  Identity 
    prospect_id: str = ""
    scored_at: str = ""
    icp_profile_name: str = ""
    model_used: str = "facebook/bart-large-mnli"

    #  Five dimension scores (0–100 each) 
    # Each maps to one label pair in hf_models/scorer.py.
    # The scorer normalises the positive label confidence to 0–100.
    hiring_velocity_score: float = 0.0
    funding_timing_score:  float = 0.0
    expansion_news_score:  float = 0.0
    lease_expiry_score:    float = 0.0
    decision_maker_score:  float = 0.0

    # Composite and tier 
    composite: float = 0.0           # weighted average of 5 dimensions
    tier: str = "Nurture"            # "Hot" | "Warm" | "Nurture"

    # Signal bullets 
    # Human-readable strings shown in the UI.
    # Positive: dimensions where the positive label scored >= 65%
    # Risk: dimensions where the positive label scored <= 40%
    positive_signals: list = field(default_factory=list)
    risk_signals: list = field(default_factory=list)

    # Best signal for draft generation 
    # The single strongest signal — Mistral opens the email with this.
    top_signal_type: str = ""        # e.g. "funding_timing"
    top_signal_text: str = ""        # e.g. "raised Series B 14 months ago"

    #  Raw model output 
    # The unprocessed label → confidence dict from HuggingFace.
    # Shown in UI expander for technical transparency.
    raw_label_confidences: dict = field(default_factory=dict)

    #  The text sent to the model 
    # Stored for audit trail and UI "see what the model received" expander.
    description_sent: str = ""

    # Fallback flag 
    # True if HF API was unavailable and rule-based scoring was used instead.
    used_fallback_scoring: bool = False
    fallback_reason: str = ""

    # Methods


    def tier_color(self) -> str:
        """Return hex colour for this tier — used in Streamlit UI."""
        return {
            "Hot":     "#E74C3C",
            "Warm":    "#F39C12",
            "Nurture": "#2980B9",
        }.get(self.tier, "#95A5A6")

    def tier_emoji(self) -> str:
        """Return emoji for this tier."""
        return {
            "Hot":     "🔥",
            "Warm":    "☀️",
            "Nurture": "❄️",
        }.get(self.tier, "◯")

    def tier_badge(self) -> str:
        """Return formatted tier badge string."""
        return f"{self.tier_emoji()} {self.tier}"

    def dimension_scores(self) -> dict:
        """
        Return all five dimension scores as a dict.
        Used by the UI to render the score breakdown chart.
        """
        return {
            "Hiring velocity":  self.hiring_velocity_score,
            "Funding timing":   self.funding_timing_score,
            "Expansion news":   self.expansion_news_score,
            "Lease expiry":     self.lease_expiry_score,
            "Decision maker":   self.decision_maker_score,
        }

    def to_dict(self) -> dict:
        """Serialise to dict for session state storage."""
        return {
            "prospect_id":           self.prospect_id,
            "scored_at":             self.scored_at,
            "icp_profile_name":      self.icp_profile_name,
            "model_used":            self.model_used,
            "hiring_velocity_score": self.hiring_velocity_score,
            "funding_timing_score":  self.funding_timing_score,
            "expansion_news_score":  self.expansion_news_score,
            "lease_expiry_score":    self.lease_expiry_score,
            "decision_maker_score":  self.decision_maker_score,
            "composite":             self.composite,
            "tier":                  self.tier,
            "positive_signals":      self.positive_signals,
            "risk_signals":          self.risk_signals,
            "top_signal_type":       self.top_signal_type,
            "top_signal_text":       self.top_signal_text,
            "raw_label_confidences": self.raw_label_confidences,
            "description_sent":      self.description_sent,
            "used_fallback_scoring": self.used_fallback_scoring,
            "fallback_reason":       self.fallback_reason,
        }