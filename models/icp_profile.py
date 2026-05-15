from dataclasses import dataclass, field
from typing import Optional
import copy
import json



SECTOR_WEIGHT_PRESETS = {
    "healthcare": {
        "hiring_velocity":   0.35,   # hiring = headcount = space need
        "funding_timing":    0.25,   # capital deployed = expansion ready
        "expansion_news":    0.25,   # explicit geographic signal
        "lease_expiry":      0.10,   # harder to get in healthcare
        "decision_maker":    0.05,   # contact accessibility
    },
    "tech": {
        "hiring_velocity":   0.25,
        "funding_timing":    0.35,   # tech deploys capital fastest
        "expansion_news":    0.25,
        "lease_expiry":      0.10,
        "decision_maker":    0.05,
    },
    "financial_services": {
        "hiring_velocity":   0.20,
        "funding_timing":    0.20,
        "expansion_news":    0.20,
        "lease_expiry":      0.30,   # finserv stays put until lease forces move
        "decision_maker":    0.10,
    },
    "default": {
        "hiring_velocity":   0.25,
        "funding_timing":    0.25,
        "expansion_news":    0.25,
        "lease_expiry":      0.15,
        "decision_maker":    0.10,
    },
}


TIER_HOT    = 75   
TIER_WARM   = 50   
              


@dataclass
class ICPProfile:
    """
    Complete definition of one outreach campaign / sector focus.

    One profile = one set of targeting criteria + one scoring calibration
    + one tone model + one decision history.

    He can have multiple profiles saved simultaneously and switch between
    them with one click. Nothing bleeds across profiles.
    """


    name: str = "New Profile"
    description: str = ""
    sector_key: str = "default"          # used to look up weight preset
    created_at: str = ""                 # ISO timestamp, set on creation
    is_active: bool = False

    #Block 1: Targeting filters
    sectors: list = field(default_factory=lambda: ["Technology"])
    geographies: list = field(default_factory=lambda: ["New York"])
    headcount_min: int = 50
    headcount_max: int = 500
    company_stages: list = field(default_factory=lambda: ["Series B", "Series C"])

    # Block 2: Signal weights
    # Keys must match the 5 scoring dimensions in scorer.py.
    # Values must sum to 1.0.
    signal_weights: dict = field(default_factory=lambda: {
        "hiring_velocity":  0.25,
        "funding_timing":   0.25,
        "expansion_news":   0.25,
        "lease_expiry":     0.15,
        "decision_maker":   0.10,
    })

    #  Block 3: Trigger signals 
    # A prospect must fire at least `min_triggers_required` of these
    # to surface in the daily list. Each string maps to a check in
    # pipeline/enrichment.py.
    trigger_signals: list = field(default_factory=lambda: [
        "raised_funding_last_18_months",
        "headcount_growth_20pct_6months",
        "expansion_announcement_90_days",
        "office_role_posted",
    ])
    min_triggers_required: int = 2

    # Block 4: Exclusions 
    exclusions: dict = field(default_factory=lambda: {
        "min_employees":          50,
        "exclude_crm_contacts":   True,
        "max_lease_age_months":   24,    # skip if signed lease < 24 months ago
        "excluded_domains":       [],    # specific domains to never surface
    })

    # Block 5: Tone rules
    # These get compiled into the Mistral system prompt in hf_models/writer.py.
    tone_rules: dict = field(default_factory=lambda: {
        "max_words_first_touch":  100,
        "max_words_followup":     60,
        "opening_style":          "specific_signal",  # not "compliment"
        "cta_style":              "single_question",  # not "meeting_request"
        "forbidden_phrases":      [
            "I came across your profile",
            "I hope this finds you well",
            "I wanted to reach out",
            "touching base",
            "circle back",
            "leverage",
            "synergy",
        ],
        "tone_descriptor":        "peer-level, direct, relationship-first",
        "sign_off":               "Best,",
    })

    #Block 6: Decision history (starts empty, fills with use) 
    approved_prospects: list = field(default_factory=list)
    rejected_prospects: list = field(default_factory=list)
    edited_drafts: list = field(default_factory=list)   # stores what changed
    learned_rules: list = field(default_factory=list)   # extracted patterns

    #  Computed metadata 
    total_decisions: int = 0
    approval_rate: float = 0.0

    # 
    # Methods
    # 

    def apply_sector_preset(self, sector_key: str) -> None:
        """
        Apply the default signal weights for a given sector.
        Call this when creating a new profile or changing sector.

        """
        self.sector_key = sector_key
        preset = SECTOR_WEIGHT_PRESETS.get(sector_key,
                                            SECTOR_WEIGHT_PRESETS["default"])
        self.signal_weights = dict(preset)

    def record_approval(self, prospect_id: str, signals: list) -> None:
        """
        Record that he approved a prospect.
        Called by pages/3_draft_review.py when he clicks Approve.

        """
        self.approved_prospects.append({
            "prospect_id": prospect_id,
            "signals":     signals,
        })
        self._update_metadata()

    def record_rejection(self, prospect_id: str, reason: str = "") -> None:
        """
        Record that he rejected a prospect.
        Called by pages/3_draft_review.py when he clicks Reject.

       
        """
        self.rejected_prospects.append({
            "prospect_id": prospect_id,
            "reason":      reason,
        })
        self._update_metadata()

    def record_edit(self, prospect_id: str,
                    original: str, edited: str) -> None:
        """
        Record that he edited a draft before approving.
        The diff between original and edited feeds the tone learning.

        """
        self.edited_drafts.append({
            "prospect_id": prospect_id,
            "original":    original,
            "edited":      edited,
        })
        self._update_metadata()

    def add_learned_rule(self, rule: str) -> None:
        """
        Add a plain-English rule extracted from decision patterns.
        These get injected into the Claude/Mistral scoring prompt.

        Example rules:
          - "Skip companies under 60 employees regardless of funding"
          - "Prioritise companies that posted Office Manager roles"

        Args:
            rule: plain English string
        """
        if rule not in self.learned_rules:
            self.learned_rules.append(rule)

    def get_system_prompt_rules(self) -> str:
        """
        Compile the learned rules into a block for injection into
        the HuggingFace model system prompt.

        Returns:
            Multi-line string of rules, or empty string if none yet.
        """
        if not self.learned_rules:
            return ""
        rules_text = "\n".join(f"- {r}" for r in self.learned_rules)
        return f"Based on past decisions, apply these preferences:\n{rules_text}"

    def get_tone_prompt_block(self) -> str:
        """
        Compile tone rules into a block for the Mistral system prompt.

        Returns:
            Multi-line string of tone instructions.
        """
        t = self.tone_rules
        forbidden = ", ".join(f'"{p}"' for p in t.get("forbidden_phrases", []))
        return (
            f"Tone: {t.get('tone_descriptor', 'professional')}.\n"
            f"Max words (first touch): {t.get('max_words_first_touch', 100)}.\n"
            f"Opening style: {t.get('opening_style', 'specific_signal')} "
            f"— always reference one specific signal about the company.\n"
            f"CTA style: {t.get('cta_style', 'single_question')} "
            f"— end with a question, never a meeting request.\n"
            f"Never use these phrases: {forbidden}.\n"
            f"Sign off as: {t.get('sign_off', 'Best,')}."
        )

    def clone(self, new_name: str) -> "ICPProfile":
        """
        Create a new profile from this one.
        Copies tone rules and style — resets all targeting and history.

        Use this when starting a new sector: his writing style carries
        across but the targeting logic starts fresh.

        Args:
            new_name: name for the new profile

        Returns:
            A new ICPProfile instance
        """
        import datetime
        new = ICPProfile(
            name        = new_name,
            tone_rules  = copy.deepcopy(self.tone_rules),
            created_at  = datetime.datetime.now().isoformat(),
        )
        return new

    def to_dict(self) -> dict:
        """Serialise to dict for JSON storage / session state."""
        return {
            "name":                  self.name,
            "description":           self.description,
            "sector_key":            self.sector_key,
            "created_at":            self.created_at,
            "is_active":             self.is_active,
            "sectors":               self.sectors,
            "geographies":           self.geographies,
            "headcount_min":         self.headcount_min,
            "headcount_max":         self.headcount_max,
            "company_stages":        self.company_stages,
            "signal_weights":        self.signal_weights,
            "trigger_signals":       self.trigger_signals,
            "min_triggers_required": self.min_triggers_required,
            "exclusions":            self.exclusions,
            "tone_rules":            self.tone_rules,
            "approved_prospects":    self.approved_prospects,
            "rejected_prospects":    self.rejected_prospects,
            "edited_drafts":         self.edited_drafts,
            "learned_rules":         self.learned_rules,
            "total_decisions":       self.total_decisions,
            "approval_rate":         self.approval_rate,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ICPProfile":
        """Deserialise from dict (e.g. loaded from session state or JSON)."""
        profile = cls()
        for key, value in data.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        return profile

    def _update_metadata(self) -> None:
        """Recalculate total_decisions and approval_rate after any decision."""
        total = len(self.approved_prospects) + len(self.rejected_prospects)
        self.total_decisions = total
        if total > 0:
            self.approval_rate = round(
                len(self.approved_prospects) / total * 100, 1)