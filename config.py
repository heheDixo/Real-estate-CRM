# config.py

import os
from dotenv import load_dotenv

load_dotenv()

# BLOCK 1 — API credentials
# All loaded from .env — never hardcoded.
# If a key is missing, the corresponding connector falls back to mock data.


HF_TOKEN            = os.getenv("HF_TOKEN", "")
APOLLO_API_KEY      = os.getenv("APOLLO_API_KEY", "")
PROXYCURL_API_KEY   = os.getenv("PROXYCURL_API_KEY", "")
NEWSAPI_KEY         = os.getenv("NEWSAPI_KEY", "")

# Gmail
GMAIL_ADDRESS       = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD", "")
DEMO_RECIPIENT      = os.getenv("DEMO_RECIPIENT", "")

# Agent identity
AGENT_NAME          = os.getenv("AGENT_NAME",  "Michael Hartley")
AGENT_TITLE         = os.getenv("AGENT_TITLE", "Senior Director, Tenant Representation")
FIRM_NAME           = os.getenv("FIRM_NAME",   "Hartley CRE Partners")
AGENT_PHONE         = os.getenv("AGENT_PHONE", "+1 (212) 555-0147")
AGENT_EMAIL         = os.getenv("AGENT_EMAIL", "")

#  Brand colours 
AGENCY_COLOR  = "#1B4F72"   # dark navy — primary brand colour
AGENCY_ACCENT = "#2ECC71"   # emerald green — positive signals, tier badges
# ── API availability flags ─────────────────────────────────────────────────
# Set to True only if the corresponding key is present.
# Used by connectors to decide: real API vs mock data.
APOLLO_AVAILABLE    = bool(APOLLO_API_KEY)
PROXYCURL_AVAILABLE = bool(PROXYCURL_API_KEY)
NEWSAPI_AVAILABLE   = bool(NEWSAPI_KEY)
HF_AVAILABLE        = bool(HF_TOKEN)


HF_API_BASE     = "https://api-inference.huggingface.co/models"
SCORING_MODEL   = "facebook/bart-large-mnli"
WRITING_MODEL   = "mistralai/Mistral-7B-Instruct-v0.2"
BRIEFING_MODEL  = "mistralai/Mistral-7B-Instruct-v0.2"

# Inference API timeouts (seconds)
SCORING_TIMEOUT  = 30
WRITING_TIMEOUT  = 60
BRIEFING_TIMEOUT = 60

# parameters for Mistral
WRITING_PARAMS = {
    "max_new_tokens":  400,
    "temperature":     0.7,
    "top_p":           0.9,
    "do_sample":       True,
    "return_full_text": False,
}

BRIEFING_PARAMS = {
    "max_new_tokens":  300,
    "temperature":     0.4,   # lower temp for more factual brief
    "top_p":           0.9,
    "do_sample":       True,
    "return_full_text": False,
}



# BLOCK 3 — HuggingFace scoring label pairs
#
# These are the six label pairs fed to bart-large-mnli.
# Each is a tuple of (positive_label, negative_label).
#
# Rule of thumb for writing good labels:
# — Be specific and grounded. "needs more office space soon" outperforms
#   "has real estate needs" because it is more concrete.
# — The negative label should be the genuine opposite, not just "no".
# — Both labels should be plausible descriptions of a company.


SCORING_LABEL_PAIRS = [
    # 1. Hiring velocity — are they growing fast enough to need more space?
    (
        "rapidly growing headcount and hiring aggressively for new roles",
        "stable or shrinking team with minimal open positions",
    ),

    # 2. Funding timing — are they in the deployment window?
    (
        "recently funded with capital available to invest in office expansion",
        "no recent funding and not in a position to expand real estate footprint",
    ),

    # 3. Expansion news — have they announced geographic growth?
    (
        "publicly announced expansion into new markets or office locations",
        "no geographic expansion plans and operating from existing locations only",
    ),

    # 4. Lease expiry signal — is their current lease likely expiring?
    (
        "likely approaching end of current office lease and evaluating options",
        "recently signed a long-term lease and not in the market for space",
    ),

    # 5. Decision maker — is the contact reachable and relevant?
    (
        "decision maker with authority over real estate and workplace decisions",
        "individual contributor with no influence over office or facilities decisions",
    ),

    # 6. Overall space need — the aggregate signal
    (
        "company has an imminent need for new or expanded commercial office space",
        "company has no current need for commercial real estate changes",
    ),
]

# Dimension names — must match the order of SCORING_LABEL_PAIRS
# and the field names in models/score_result.py
SCORING_DIMENSIONS = [
    "hiring_velocity",
    "funding_timing",
    "expansion_news",
    "lease_expiry",
    "decision_maker",
    "overall_space_need",   # 6th pair — used for composite validation only
]



# BLOCK 4 — Scoring thresholds and sector weight presets


# Tier assignment thresholds
TIER_HOT    = 75   # composite >= 75  → Hot    🔥  contact within 24 hours
TIER_WARM   = 50   # composite >= 50  → Warm   ☀️  contact this week
               #   composite <  50  → Nurture ❄️  monitor, revisit in 90 days

# Signal strength thresholds
SIGNAL_STRONG   = 65   # dimension score >= 65 → positive signal bullet
SIGNAL_WEAK     = 40   # dimension score <= 40 → risk signal bullet

# Default signal weights per sector (must sum to 1.0)
SECTOR_SIGNAL_WEIGHTS = {
    "healthcare": {
        "hiring_velocity":  0.35,
        "funding_timing":   0.25,
        "expansion_news":   0.25,
        "lease_expiry":     0.10,
        "decision_maker":   0.05,
    },
    "tech": {
        "hiring_velocity":  0.25,
        "funding_timing":   0.35,
        "expansion_news":   0.25,
        "lease_expiry":     0.10,
        "decision_maker":   0.05,
    },
    "financial_services": {
        "hiring_velocity":  0.20,
        "funding_timing":   0.20,
        "expansion_news":   0.20,
        "lease_expiry":     0.30,
        "decision_maker":   0.10,
    },
    "default": {
        "hiring_velocity":  0.25,
        "funding_timing":   0.25,
        "expansion_news":   0.25,
        "lease_expiry":     0.15,
        "decision_maker":   0.10,
    },
}

# Funding deployment window (months)
DEPLOYMENT_WINDOW_MIN = 10   # months since funding — start of window
DEPLOYMENT_WINDOW_MAX = 20   # months since funding — end of window

# Hiring velocity thresholds
HIRING_VELOCITY_HIGH   = 30.0   # jobs / headcount * 100 >= 30 → strong signal
HIRING_VELOCITY_MEDIUM = 15.0   # >= 15 → moderate signal
HEADCOUNT_GROWTH_HIGH  = 20.0   # % growth in 6 months >= 20 → strong signal


# BLOCK 5 — Trigger signal definitions
#
# Maps trigger signal names (used in ICPProfile.trigger_signals) to
# human-readable labels shown in the UI and to the enrichment field
# they check in EnrichmentResult.check_triggers().


TRIGGER_SIGNAL_DEFINITIONS = {
    "raised_funding_last_18_months": {
        "label":       "Raised funding in last 18 months",
        "description": "Recent capital raise puts them in the expansion window",
        "enrichment_field": "months_since_funding",
        "icon":        "💰",
    },
    "headcount_growth_20pct_6months": {
        "label":       "20%+ headcount growth in 6 months",
        "description": "Rapid hiring implies upcoming space need",
        "enrichment_field": "headcount_growth_pct",
        "icon":        "📈",
    },
    "expansion_announcement_90_days": {
        "label":       "Expansion announcement in last 90 days",
        "description": "Public statement of geographic or market expansion",
        "enrichment_field": "has_expansion_news",
        "icon":        "🗺️",
    },
    "office_role_posted": {
        "label":       "Hiring for office or workplace role",
        "description": "Active search for Office Manager or Workplace lead",
        "enrichment_field": "office_roles_posted",
        "icon":        "🏢",
    },
    "hiring_velocity_high": {
        "label":       "High hiring velocity (30%+ of headcount)",
        "description": "Jobs posted relative to company size is unusually high",
        "enrichment_field": "hiring_velocity_score",
        "icon":        "⚡",
    },
    "has_relocation_signal": {
        "label":       "Relocation or move signal detected",
        "description": "News or job postings suggest an office move",
        "enrichment_field": "has_relocation_news",
        "icon":        "🚚",
    },
}

# All available trigger signal keys (used to populate ICP form checkboxes)
ALL_TRIGGER_SIGNALS = list(TRIGGER_SIGNAL_DEFINITIONS.keys())



# BLOCK 6 — Mistral prompt templates
#
# These are the system and user prompts for briefing, email, and LinkedIn.
# The system prompt sets the persona and rules.
# The user prompt is built dynamically in hf_models/ with prospect data.
#
# Quality of AI output depends almost entirely on these prompts.
# Iterate on them against real company data before the demo.


#  Research brief system prompt 
BRIEFING_SYSTEM_PROMPT = """You are a senior commercial real estate analyst 
preparing a prospect brief for a tenant rep broker. Your job is to distil 
enrichment data about a company into exactly 5 bullet points that tell the 
broker what he needs to know before reaching out.

Rules:
- Exactly 5 bullets. No more, no less.
- Each bullet starts with a bold category label followed by a colon.
  Categories: Company stage, Space need signal, Right contact, Best angle, Main risk.
- Be specific. Use numbers, dates, and named signals. Never be vague.
- The "Best angle" bullet tells the broker which specific signal to open with.
- The "Main risk" bullet is honest — if the signal is weak, say so.
- Do not invent information. Only use what is provided.
- Total length: under 120 words across all 5 bullets.
- Format: plain text bullets starting with "•"."""

# First-touch email system prompt 
EMAIL_SYSTEM_PROMPT = f"""You are {AGENT_NAME}, a senior tenant representation 
broker at {FIRM_NAME}. You are writing a cold outreach email to a potential 
client — a decision maker at a company that shows signals of needing new or 
expanded office space.

Non-negotiable rules:
- Under 100 words total. Count every word.
- Open with one specific, verifiable signal about their company. 
  Never open with a compliment or "I came across your profile."
- Never use these phrases: "I hope this finds you well", 
  "I wanted to reach out", "touching base", "circle back", 
  "leverage", "synergy", "innovative", "disruptive".
- Peer-level tone. You are not selling to them. 
  You are a senior professional who noticed something and is curious.
- End with a single, low-pressure question. 
  Never ask for a meeting in the first touch.
- Do not mention you found them through a database or tool.
- Sign off as: {AGENT_NAME}, {FIRM_NAME}.
- Format: Subject line on line 1 starting with "Subject:". 
  Then a blank line. Then the email body. Then the sign-off."""

#LinkedIn message system prompt 
LINKEDIN_SYSTEM_PROMPT = f"""You are {AGENT_NAME}, a senior tenant rep broker. 
You are writing a LinkedIn connection message or InMail to a potential client.

Rules:
- Under 300 characters total (LinkedIn limit for connection requests).
- Reference one specific, real signal about their company.
- Conversational and direct. No formalities.
- No ask for a meeting or call in the first message.
- End with a question or a light observation that invites a reply.
- Do not mention you found them through a database.
- Do not use emojis."""

#  Follow-up email system prompt 
FOLLOWUP_SYSTEM_PROMPT = f"""You are {AGENT_NAME} writing a follow-up email 
to someone who did not reply to your first outreach.

Rules:
- Under 60 words.
- Do not apologise for following up.
- Add one new piece of context that was not in the first email — 
  a new signal, a recent news item, or a market observation.
- Assume they are busy, not uninterested.
- Same low-pressure question format as the first touch.
- Sign off as: {AGENT_NAME}."""



# BLOCK 7 — UI constants, demo config, Salesforce export


#  ICP form options 
SECTOR_OPTIONS = [
    "Healthcare",
    "Health Tech",
    "MedTech / Life Sciences",
    "Technology",
    "SaaS",
    "Fintech",
    "Financial Services",
    "Asset Management",
    "Law / Legal Services",
    "Media / Entertainment",
    "Real Estate",
    "E-commerce / Retail",
    "Other",
]

COMPANY_STAGE_OPTIONS = [
    "Seed",
    "Series A",
    "Series B",
    "Series C",
    "Series D+",
    "Growth / PE-backed",
    "Bootstrapped",
    "Public",
]

GEOGRAPHY_OPTIONS = [
    "New York",
    "Manhattan",
    "Brooklyn",
    "New Jersey",
    "Connecticut",
    "Boston",
    "San Francisco",
    "Los Angeles",
    "Chicago",
    "Austin",
    "Miami",
    "Washington DC",
    "Seattle",
    "Other",
]

# Time saving calculation 
# Used by pipeline/audit.py to calculate the time savings shown on Page 4.
MANUAL_TIME_PER_PROSPECT = {
    "list_building":       15,   # minutes
    "contact_research":    10,
    "email_writing":       10,
    "linkedin_writing":     5,
    "crm_logging":          5,
    "followup_tracking":   10,
    "total":               55,   # sum of above
}

SYSTEM_TIME_PER_PROSPECT = {
    "enrichment":           0,   # runs in background
    "scoring":              0,   # runs in background
    "brief_generation":     0,   # runs in background
    "draft_generation":     0,   # runs in background
    "review_and_approve":   5,   # his active time
    "crm_export":           0,   # one click
    "total":                5,   # sum of above
}

#  Salesforce export field mapping 
# Maps our internal field names to Salesforce Engage column headers.
SALESFORCE_EXPORT_FIELDS = {
    "company_name":         "Company",
    "contact_name":         "Full Name",
    "contact_first_name":   "First Name",
    "contact_last_name":    "Last Name",
    "contact_title":        "Title",
    "contact_email":        "Email",
    "contact_phone":        "Phone",
    "domain":               "Website",
    "city":                 "City",
    "state":                "State",
    "headcount":            "Number of Employees",
    "company_stage":        "Lead Source Detail",
    "industry":             "Industry",
    "last_funding_type":    "Lead Source",
    "composite":            "LeadFlow Score",
    "tier":                 "LeadFlow Tier",
    "top_signal_text":      "LeadFlow Top Signal",
    "email_subject":        "Email Subject",
    "email_body":           "Email Body",
    "approval_status":      "Outreach Status",
}

# Demo mode flag
# When True, uses mock data regardless of API key availability.
# Useful for demos where you don't want to spend API credits.
FORCE_MOCK_MODE = os.getenv("FORCE_MOCK_MODE", "false").lower() == "true"

#  App display
APP_TITLE   = "CRE Outreach Intelligence"
APP_TAGLINE = "AI-powered tenant rep prospecting — from signal to sent in minutes"
APP_ICON    = "🏢"

# Tier display config
TIER_CONFIG = {
    "Hot": {
        "color":      "#E74C3C",
        "background": "#FDEDEC",
        "emoji":      "🔥",
        "action":     "Contact within 24 hours",
    },
    "Warm": {
        "color":      "#F39C12",
        "background": "#FEF9E7",
        "emoji":      "☀️",
        "action":     "Contact this week",
    },
    "Nurture": {
        "color":      "#2980B9",
        "background": "#EBF5FB",
        "emoji":      "❄️",
        "action":     "Monitor — revisit in 90 days",
    },
}