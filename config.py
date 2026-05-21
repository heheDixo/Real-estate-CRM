# config.py

import os
from dotenv import load_dotenv

load_dotenv()

# BLOCK 1 — API credentials
# All loaded from .env — never hardcoded.
# If a key is missing, the corresponding connector falls back to mock data.


HF_TOKEN            = os.getenv("HF_TOKEN", "")
APOLLO_API_KEY      = os.getenv("APOLLO_API_KEY", "")
NEWSAPI_KEY         = os.getenv("NEWSAPI_KEY", "")
HUNTER_API_KEY      = os.getenv("HUNTER_API_KEY", "")
FIRECRAWL_API_KEY   = os.getenv("FIRECRAWL_API_KEY", "")

# Gmail (SMTP)
GMAIL_ADDRESS       = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD", "")
GMAIL_SENDER        = os.getenv("GMAIL_SENDER", "") or GMAIL_ADDRESS
DEMO_RECIPIENT      = os.getenv("DEMO_RECIPIENT", "")

# Google OAuth (Gmail drafts, Sheets, Calendar — one credentials file)
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
SHEETS_SPREADSHEET_ID   = os.getenv("SHEETS_SPREADSHEET_ID", "")
CALENDAR_ID             = os.getenv("CALENDAR_ID", "primary")

# Morning research scheduler
RESEARCH_CRON_HOUR   = int(os.getenv("RESEARCH_CRON_HOUR",   "5"))
RESEARCH_CRON_MINUTE = int(os.getenv("RESEARCH_CRON_MINUTE", "0"))
DIGEST_SEND_HOUR     = int(os.getenv("DIGEST_SEND_HOUR",     "7"))
BROKER_EMAIL         = os.getenv("BROKER_EMAIL", "")
TIMEZONE             = os.getenv("TIMEZONE", "America/New_York")
START_SCHEDULER      = os.getenv("START_SCHEDULER", "false").lower() == "true"

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
NEWSAPI_AVAILABLE   = bool(NEWSAPI_KEY)
HUNTER_AVAILABLE    = bool(HUNTER_API_KEY)
FIRECRAWL_AVAILABLE = bool(FIRECRAWL_API_KEY)
HF_AVAILABLE        = bool(HF_TOKEN)
GMAIL_AVAILABLE     = bool(GMAIL_ADDRESS and GMAIL_APP_PASSWORD)
GOOGLE_OAUTH_AVAILABLE = bool(GOOGLE_CREDENTIALS_PATH) and os.path.exists(GOOGLE_CREDENTIALS_PATH)


# HuggingFace moved the old api-inference.huggingface.co endpoint to the
# new router URL in 2025. Same model ID, same payload, but the host has to
# match what's currently in DNS.
HF_API_BASE     = "https://router.huggingface.co/hf-inference/models"
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

# BLOCK 8 — Plain-English explanations for each scoring dimension
#
# Used by pages/2_prospect_found.py to translate a numeric score into a
# sentence the broker can read in a glance. {placeholders} are filled in
# from the EnrichmentResult — see _format_explanation() on page 2.

SCORE_EXPLANATIONS = {
    "hiring_velocity": {
        "high":   "they posted {jobs} jobs in the last 60 days against a {headcount}-person team — that velocity usually shows up in space planning",
        "medium": "their hiring pace is steady ({jobs} open roles for {headcount} employees) — keep watching",
        "low":    "only {jobs} open roles for a {headcount}-person team — no urgency on space from hiring alone",
    },
    "funding_timing": {
        "high":   "they raised {funding_type} {months_since_funding} months ago — right in the 12–18 month deployment window",
        "medium": "funding was {months_since_funding} months ago — close to the deployment window but not centre of it",
        "low":    "no recent funding on record or funding is outside the typical deployment window",
    },
    "expansion_news": {
        "high":   "they have publicly announced an expansion — that is the strongest possible space signal",
        "medium": "some growth-adjacent news but no explicit expansion announcement",
        "low":    "no public expansion announcements detected in the last 6 months",
    },
    "lease_expiry": {
        "high":   "relocation or office-change signals detected in the last 90 days",
        "medium": "office-related news but no clear lease expiry signal",
        "low":    "no lease expiry signal — they may have recently signed",
    },
    "decision_maker": {
        "high":   "the named contact ({title}) sits in operations or the C-suite and likely owns real estate decisions",
        "medium": "the contact is senior but real-estate authority is not certain",
        "low":    "the contact may not have authority over real estate — verify before investing heavily",
    },
}

# BLOCK 9 — Research agent signal labels (zero-shot on bart-large-mnli)
#
# Used by research_agent.py to classify the day's news and job postings
# into CRE-relevant signals. Each label is a candidate hypothesis the
# article text is scored against.

RESEARCH_SIGNAL_LABELS = [
    "company is expanding to new office locations",
    "company is hiring aggressively and growing headcount",
    "company recently raised funding and has capital to deploy",
    "company office lease may be expiring soon",
    "company needs more office space",
]

RESEARCH_SIGNAL_LABEL_TYPES = {
    "company is expanding to new office locations":         "expansion",
    "company is hiring aggressively and growing headcount": "hiring",
    "company recently raised funding and has capital to deploy": "funding",
    "company office lease may be expiring soon":            "lease",
    "company needs more office space":                       "space_need",
}

# Research tier thresholds (different from scoring tiers — research is daily)
RESEARCH_TIER_HOT     = 75
RESEARCH_TIER_WARM    = 50
RESEARCH_SKIP_BELOW   = 30

# Tone variants used on page 3 (draft review).
# Each prefix is prepended verbatim to the system prompt so Mistral biases
# its style/structure toward the named variant. Keep them tight — the model
# weights early instructions heavily.
TONE_VARIANT_PREFIXES = {
    "Direct": (
        "You are writing a cold outreach email for a commercial real estate broker. "
        "RULES: Under 80 words total. No greetings like 'I hope this finds you well'. "
        "Lead with the single strongest signal in the first sentence. "
        "One sentence CTA at the end — ask a yes/no or short-answer question. "
        "Never use: leverage, circle back, touching base, synergy, excited, thrilled, pleased. "
        "No fluff. No pleasantries. Broker-to-executive tone."
    ),
    "Warm": (
        "You are writing a cold outreach email for a commercial real estate broker. "
        "RULES: 90-120 words. Open by acknowledging something specific about their "
        "company — a milestone, an announcement, a hire — before mentioning space. "
        "Softer ask: 'happy to share what we're seeing' or "
        "'worth a quick call to explore'. Conversational but professional. "
        "One paragraph. No bullet points. "
        "Never use: leverage, circle back, touching base, synergy."
    ),
    "Consultative": (
        "You are writing a cold outreach email for a commercial real estate broker "
        "who leads with market insight. "
        "RULES: 100-130 words. Open with a market data point or trend observation "
        "relevant to their sector — NOT about their specific company. "
        "Position yourself as a market expert, not a vendor. "
        "Then connect the market insight to their company's situation. "
        "CTA: offer to share a market brief or data point, not a sales call. "
        "Tone: peer-level, analytical, no hard sell. "
        "Never use: leverage, circle back, touching base, synergy, excited, thrilled."
    ),
}


# BLOCK 10 — Dark theme styling
#
# A single CSS block injected at the top of every page via st.markdown. Keeps
# all visual styling in one place so theme tweaks land everywhere at once.

TIER_COLORS = {
    "hot":     {"bg": "#3d0f0f", "text": "#f85149", "border": "#5a1a1a",
                "bar": "#f85149", "emoji": "🔥"},
    "warm":    {"bg": "#3d2800", "text": "#d29922", "border": "#5a3d00",
                "bar": "#d29922", "emoji": "☀"},
    "nurture": {"bg": "#0d2136", "text": "#58a6ff", "border": "#1c3a5e",
                "bar": "#3b82f6", "emoji": "❄"},
}

DARK_THEME_CSS = """
<style>
/* App background */
.stApp { background-color: #0d1117; color: #e6edf3; }
.block-container { padding-top: 1.5rem; padding-bottom: 2rem; }

/* Hide default Streamlit chrome */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header { visibility: hidden; }
.stDeployButton { display: none; }

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #161b22;
    border-right: 1px solid #30363d;
}
section[data-testid="stSidebar"] * { color: #c9d1d9; }

/* Sidebar page links */
section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] {
    color: #c9d1d9 !important;
    background: transparent;
    border-radius: 6px;
    padding: 6px 8px;
}
section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover {
    background: #21262d;
}

/* Metric cards */
div[data-testid="metric-container"] {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px;
}
div[data-testid="metric-container"] label { color: #8b949e; font-size: 11px; }
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    color: #e6edf3; font-size: 22px;
}

/* Buttons */
.stButton > button {
    background-color: #21262d;
    border: 1px solid #30363d;
    color: #e6edf3;
    border-radius: 6px;
    font-size: 13px;
    transition: background 0.15s;
}
.stButton > button:hover { background-color: #2d333b; border-color: #484f58; }
.stButton > button:focus { box-shadow: none; }
.stButton > button[kind="primary"] {
    background-color: #1d4ed8;
    border-color: #1d4ed8;
    color: #ffffff;
}
.stButton > button[kind="primary"]:hover { background-color: #2563eb; }

/* Primary button override — wrap in div.primary-btn */
.primary-btn .stButton > button {
    background-color: #1d4ed8;
    border-color: #1d4ed8;
    color: #ffffff;
}
.primary-btn .stButton > button:hover { background-color: #2563eb; }

/* Inputs */
.stTextInput input, .stTextArea textarea, .stSelectbox > div > div {
    background-color: #0d1117 !important;
    border: 1px solid #30363d !important;
    color: #e6edf3 !important;
    border-radius: 6px !important;
}

/* Divider */
hr { border-color: #30363d !important; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background-color: transparent;
    border-bottom: 1px solid #30363d;
    gap: 24px;
}
.stTabs [data-baseweb="tab"] {
    color: #8b949e;
    font-size: 13px;
    background: transparent;
}
.stTabs [aria-selected="true"] {
    color: #58a6ff !important;
    border-bottom: 2px solid #3b82f6 !important;
}

/* Expander */
details {
    background-color: #161b22;
    border: 1px solid #30363d !important;
    border-radius: 6px;
}
summary { color: #8b949e; font-size: 13px; }

/* Alerts */
div[data-testid="stInfo"]    { background-color: #0d2136; border: 1px solid #1c3a5e; color: #58a6ff; }
div[data-testid="stWarning"] { background-color: #2d1f00; border: 1px solid #5a3d00; color: #d29922; }
div[data-testid="stSuccess"] { background-color: #0d2b1a; border: 1px solid #1a5e35; color: #3fb950; }
div[data-testid="stError"]   { background-color: #2d0f0f; border: 1px solid #5a1a1a; color: #f85149; }

/* Radio button pill styling */
div[data-testid="stRadio"] > div {
    flex-direction: row;
    gap: 6px;
    flex-wrap: wrap;
}
div[data-testid="stRadio"] label {
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 12px;
    color: #8b949e;
    cursor: pointer;
}
div[data-testid="stRadio"] label:has(input:checked) {
    background: #1d4ed8;
    border-color: #1d4ed8;
    color: #ffffff;
}

/* Spinner */
.stSpinner > div { border-top-color: #3b82f6 !important; }

/* Progress bar */
div[data-testid="stProgress"] > div > div {
    background-color: #1d4ed8;
}

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0d1117; }
::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }

/* Captions */
.stCaption, p, label, span { color: #8b949e; }
h1, h2, h3, h4, h5 { color: #e6edf3; }

/* DataFrame container (used by Sent Tracker fallback) */
div[data-testid="stDataFrame"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
}

/* Markdown links */
a { color: #58a6ff; }
a:hover { color: #79c0ff; }
</style>
"""
