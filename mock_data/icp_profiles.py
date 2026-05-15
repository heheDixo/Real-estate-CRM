import datetime
from models.icp_profile import ICPProfile, SECTOR_WEIGHT_PRESETS

_NOW = datetime.datetime.now().isoformat()


# PROFILE 1 — Healthcare Tech NYC (ACTIVE by default)


HEALTHCARE_NYC = ICPProfile(
    name        = "Healthcare Tech — NYC",
    description = (
        "Health tech and digital health companies in New York. "
        "Series B and C. 50–400 employees. "
        "Hiring velocity and deployment window are the primary signals."
    ),
    sector_key  = "healthcare",
    created_at  = _NOW,
    is_active   = True,

    # Block 1: Targeting
    sectors         = ["Healthcare", "Health Technology", "MedTech / Life Sciences"],
    geographies     = ["New York", "Manhattan", "Brooklyn"],
    headcount_min   = 50,
    headcount_max   = 400,
    company_stages  = ["Series B", "Series C", "Growth / PE-backed"],

    # Block 2: Signal weights 
    signal_weights = SECTOR_WEIGHT_PRESETS["healthcare"],

    # Block 3: Trigger signals
    trigger_signals = [
        "raised_funding_last_18_months",
        "headcount_growth_20pct_6months",
        "expansion_announcement_90_days",
        "office_role_posted",
        "hiring_velocity_high",
    ],
    min_triggers_required = 2,

    #Block 4: Exclusions 
    exclusions = {
        "min_employees":        50,
        "exclude_crm_contacts": True,
        "max_lease_age_months": 18,
        "excluded_domains":     [],
    },

    # Block 5: Tone rules 
    tone_rules = {
        "max_words_first_touch": 100,
        "max_words_followup":    60,
        "opening_style":         "specific_signal",
        "cta_style":             "single_question",
        "forbidden_phrases": [
            "I came across your profile",
            "I hope this finds you well",
            "I wanted to reach out",
            "touching base",
            "circle back",
            "leverage",
            "synergy",
            "innovative",
            "disruptive",
            "game-changing",
        ],
        "tone_descriptor":  "peer-level, direct, relationship-first, concise",
        "sign_off":         "Best,",
        "sector_context":   (
            "Healthcare companies are cautious about vendor relationships. "
            "Lead with operational insight, not sales language. "
            "Reference the specific growth signal — never generic flattery."
        ),
    },

    # ── Block 6: Decision history (empty — new profile) ─────────────────────
    approved_prospects = [],
    rejected_prospects = [],
    edited_drafts      = [],
    learned_rules      = [],
    total_decisions    = 0,
    approval_rate      = 0.0,
)



# PROFILE 2 — Tech / SaaS NYC


TECH_NYC = ICPProfile(
    name        = "Tech / SaaS — NYC",
    description = (
        "B2B SaaS and technology companies in New York. "
        "Series B through D. 75–600 employees. "
        "Funding timing is the primary signal — tech deploys capital fast."
    ),
    sector_key  = "tech",
    created_at  = _NOW,
    is_active   = False,

    #  Block 1: Targeting
    sectors        = ["Technology", "SaaS", "Fintech", "E-commerce / Retail"],
    geographies    = ["New York", "Manhattan", "Brooklyn", "New Jersey"],
    headcount_min  = 75,
    headcount_max  = 600,
    company_stages = ["Series B", "Series C", "Series D+", "Growth / PE-backed"],

    #  Block 2: Signal weights 
    signal_weights = SECTOR_WEIGHT_PRESETS["tech"],

    #  Block 3: Trigger signals 
    trigger_signals = [
        "raised_funding_last_18_months",
        "headcount_growth_20pct_6months",
        "expansion_announcement_90_days",
        "office_role_posted",
        "hiring_velocity_high",
    ],
    min_triggers_required = 2,

    # ── Block 4: Exclusions ─────────────────────────────────────────────────
    exclusions = {
        "min_employees":        75,
        "exclude_crm_contacts": True,
        "max_lease_age_months": 24,
        "excluded_domains":     [],
    },

    # ── Block 5: Tone rules ─────────────────────────────────────────────────
    tone_rules = {
        "max_words_first_touch": 90,
        "max_words_followup":    55,
        "opening_style":         "specific_signal",
        "cta_style":             "single_question",
        "forbidden_phrases": [
            "I came across your profile",
            "I hope this finds you well",
            "touching base",
            "circle back",
            "leverage",
            "synergy",
            "space needs",
            "real estate solution",
        ],
        "tone_descriptor": "direct, smart, peer-level — like a fellow operator",
        "sign_off":        "Best,",
        "sector_context":  (
            "Tech founders and operators get a lot of vendor outreach. "
            "Get to the point in the first sentence. "
            "Reference the specific growth signal. No throat-clearing."
        ),
    },

    approved_prospects = [],
    rejected_prospects = [],
    edited_drafts      = [],
    learned_rules      = [],
    total_decisions    = 0,
    approval_rate      = 0.0,
)


# PROFILE 3 — Financial Services NYC


FINSERV_NYC = ICPProfile(
    name        = "Financial Services — NYC",
    description = (
        "PE firms, asset managers, hedge funds, and established fintech "
        "in New York. 100–500 employees. "
        "Lease expiry and headcount growth are the primary signals. "
        "Tone is more formal — these are institutional relationships."
    ),
    sector_key  = "financial_services",
    created_at  = _NOW,
    is_active   = False,

    # Block 1: Targeting 
    sectors        = [
        "Financial Services", "Asset Management",
        "Private Equity", "Hedge Fund", "Fintech"
    ],
    geographies    = ["New York", "Manhattan", "Connecticut"],
    headcount_min  = 100,
    headcount_max  = 500,
    company_stages = [
        "Growth / PE-backed", "Series C", "Series D+",
        "Public", "Bootstrapped"
    ],

    #  Block 2: Signal weights 
    signal_weights = SECTOR_WEIGHT_PRESETS["financial_services"],

    #  Block 3: Trigger signals
    trigger_signals = [
        "raised_funding_last_18_months",
        "headcount_growth_20pct_6months",
        "office_role_posted",
        "hiring_velocity_high",
        "has_relocation_signal",
    ],
    min_triggers_required = 2,

    #  Block 4: Exclusions 
    exclusions = {
        "min_employees":        100,
        "exclude_crm_contacts": True,
        "max_lease_age_months": 30,
        "excluded_domains":     [],
    },

    #  Block 5: Tone rules 
    tone_rules = {
        "max_words_first_touch": 100,
        "max_words_followup":    65,
        "opening_style":         "specific_signal",
        "cta_style":             "single_question",
        "forbidden_phrases": [
            "I came across your profile",
            "I hope this finds you well",
            "touching base",
            "leverage",
            "synergy",
            "innovative",
            "space solution",
            "reach out",
        ],
        "tone_descriptor": (
            "peer-level and institutional — "
            "like a trusted advisor, not a vendor"
        ),
        "sign_off":       "Best regards,",
        "sector_context": (
            "Financial services professionals are highly relationship-driven "
            "and skeptical of vendor outreach. "
            "Demonstrate market knowledge and credibility in the first line. "
            "Reference a specific, verifiable fact about their firm."
        ),
    },

    approved_prospects = [],
    rejected_prospects = [],
    edited_drafts      = [],
    learned_rules      = [],
    total_decisions    = 0,
    approval_rate      = 0.0,
)


# Public list of all mock profiles 
ALL_MOCK_PROFILES = [HEALTHCARE_NYC, TECH_NYC, FINSERV_NYC]

MOCK_PROFILE_BY_NAME = {p.name: p for p in ALL_MOCK_PROFILES}


def get_all_mock_profiles() -> list:
    """Return all three pre-built ICP profiles."""
    return list(ALL_MOCK_PROFILES)


def get_active_mock_profile() -> ICPProfile:
    """Return the default active profile (Healthcare Tech — NYC)."""
    return HEALTHCARE_NYC


def get_mock_profile(name: str) -> ICPProfile:
    """
    Return a mock profile by name.
    Falls back to HEALTHCARE_NYC if not found.

    Args:
        name: profile name string

    Returns:
        ICPProfile instance
    """
    return MOCK_PROFILE_BY_NAME.get(name, HEALTHCARE_NYC)