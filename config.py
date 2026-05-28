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
# Mistral-7B-Instruct-v0.2 was pulled from the hf-inference free provider in
# mid-2025. Llama-3.1-8B-Instruct routes through the OpenAI-compatible
# /v1/chat/completions endpoint below, drawing from the $0.10/mo free credits
# before pay-as-you-go kicks in.
WRITING_MODEL   = "meta-llama/Llama-3.1-8B-Instruct"
BRIEFING_MODEL  = "meta-llama/Llama-3.1-8B-Instruct"

# Chat-completions URL used by hf_client.generate_text. The legacy
# /hf-inference/models/{model} endpoint is CPU/legacy-only now; chat models
# go through this OpenAI-style router instead.
HF_CHAT_URL     = "https://router.huggingface.co/v1/chat/completions"

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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght,SOFT@9..144,300..900,0..100&family=Inter+Tight:wght@300..700&family=JetBrains+Mono:wght@400..700&display=swap" rel="stylesheet">
<style>
/* ─────────────────────────────────────────────────────────────────────── */
/*  CRE Outreach Intelligence — Editorial Terminal aesthetic                */
/*  Type: Fraunces (display serif) · Inter Tight (body) · JetBrains Mono   */
/*  Palette: bone on near-black with vermillion · gold · cobalt accents    */
/* ─────────────────────────────────────────────────────────────────────── */

:root {
    --bg-deep:        #0a0a0c;
    --bg-surface:     #15161a;
    --bg-elevated:    #1c1d22;
    --border-faint:   #23252b;
    --border:         #2a2c33;
    --border-strong:  #3d4049;
    --text-primary:   #ede9df;   /* bone */
    --text-secondary: #a8acb5;
    --text-muted:     #6f7178;
    --text-data:      #c9c6bd;   /* slightly warmer for numeric */

    /* Sharp accents — used sparingly */
    --accent-vermillion: #ff5b3a;   /* hot */
    --accent-gold:       #d4a548;   /* warm */
    --accent-cobalt:     #5170c4;   /* nurture / info */
    --accent-sage:       #86b169;   /* success */
    --accent-rust:       #c2542d;   /* error */

    --font-display: 'Fraunces', 'Iowan Old Style', Georgia, serif;
    --font-body:    'Inter Tight', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-mono:    'JetBrains Mono', ui-monospace, 'SF Mono', monospace;
}

/* ── Ground / typography baseline ─────────────────────────────────────── */
html, body, .stApp, [data-testid="stAppViewContainer"] {
    background:
        radial-gradient(ellipse 1200px 600px at 88% -10%,
                        rgba(81,112,196,0.06) 0%, transparent 60%),
        radial-gradient(ellipse 800px 400px at -5% 100%,
                        rgba(255,91,58,0.04) 0%, transparent 50%),
        var(--bg-deep) !important;
    color: var(--text-primary);
    font-family: var(--font-body);
    font-feature-settings: "ss01", "cv11", "tnum";
}

.block-container {
    padding-top: 1.4rem !important;
    padding-bottom: 3rem !important;
    max-width: 1480px !important;
}

#MainMenu, footer, header, .stDeployButton { display: none !important; visibility: hidden !important; }

/* Headings — serif display with tight optical sizing */
h1, h2, h3, h4, h5, h6 {
    font-family: var(--font-display);
    color: var(--text-primary);
    font-weight: 500;
    font-variation-settings: "opsz" 144, "SOFT" 50;
    letter-spacing: -0.012em;
    line-height: 1.05;
}
h1 { font-size: 2.4rem; }
h2 { font-size: 1.7rem; }
h3 { font-size: 1.25rem; }

p, span, label, .stCaption, div {
    font-family: var(--font-body);
    color: var(--text-secondary);
}

/* Tabular numerals everywhere numbers matter */
.cre-mono, code, kbd {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
}

/* ── Masthead (top of every page) ──────────────────────────────────────── */
.cre-masthead {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    padding: 0 0 12px 0;
    margin-bottom: 22px;
    border-bottom: 1px solid var(--border);
    position: relative;
}
.cre-masthead::after {
    content: "";
    position: absolute;
    left: 0; right: 0; bottom: -4px;
    height: 1px;
    background: var(--border-faint);
}
.cre-wordmark {
    font-family: var(--font-display);
    font-variation-settings: "opsz" 144, "SOFT" 100;
    font-weight: 600;
    font-size: 22px;
    color: var(--text-primary);
    letter-spacing: -0.02em;
}
.cre-wordmark em {
    font-style: italic;
    font-variation-settings: "opsz" 144, "SOFT" 100;
    color: var(--accent-vermillion);
    font-weight: 400;
}
.cre-volume {
    font-family: var(--font-mono);
    font-size: 10.5px;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.18em;
}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0e0f12 0%, var(--bg-deep) 100%);
    border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] *, section[data-testid="stSidebar"] p {
    color: var(--text-secondary);
    font-family: var(--font-body);
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    font-family: var(--font-display);
    color: var(--text-primary);
}
section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] {
    color: var(--text-secondary) !important;
    background: transparent;
    border-radius: 0;
    padding: 8px 10px;
    border-left: 2px solid transparent;
    transition: all 0.18s ease;
}
section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover {
    background: var(--bg-surface);
    border-left-color: var(--accent-vermillion);
    color: var(--text-primary) !important;
}

/* ── Cards / surfaces ─────────────────────────────────────────────────── */
.cre-card {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    padding: 18px 20px;
    position: relative;
    transition: border-color 0.2s ease, transform 0.2s ease;
    animation: cre-fade-in 0.6s ease both;
}
.cre-card:hover {
    border-color: var(--border-strong);
    transform: translateY(-1px);
}
.cre-card.hot::before,
.cre-card.warm::before,
.cre-card.nurture::before {
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 3px;
}
.cre-card.hot::before     { background: var(--accent-vermillion); }
.cre-card.warm::before    { background: var(--accent-gold); }
.cre-card.nurture::before { background: var(--accent-cobalt); }

/* Staggered card reveal */
.cre-card:nth-child(1) { animation-delay: 0.00s; }
.cre-card:nth-child(2) { animation-delay: 0.05s; }
.cre-card:nth-child(3) { animation-delay: 0.10s; }
.cre-card:nth-child(4) { animation-delay: 0.15s; }
.cre-card:nth-child(5) { animation-delay: 0.20s; }
.cre-card:nth-child(6) { animation-delay: 0.25s; }
.cre-card:nth-child(7) { animation-delay: 0.30s; }
.cre-card:nth-child(8) { animation-delay: 0.35s; }

@keyframes cre-fade-in {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* ── Metric cards (Streamlit native + custom) ─────────────────────────── */
div[data-testid="metric-container"] {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 0;
    padding: 14px 16px;
    position: relative;
}
div[data-testid="metric-container"]::before {
    content: "";
    position: absolute; top: 0; left: 0; height: 1px; width: 28px;
    background: var(--accent-vermillion);
}
div[data-testid="metric-container"] label {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 9.5px;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    font-weight: 500;
}
div[data-testid="metric-container"] div[data-testid="stMetricValue"] {
    color: var(--text-primary);
    font-family: var(--font-display);
    font-variation-settings: "opsz" 144, "SOFT" 50;
    font-size: 28px;
    font-weight: 500;
    letter-spacing: -0.02em;
}

/* ── Buttons ──────────────────────────────────────────────────────────── */
.stButton > button {
    background: transparent;
    border: 1px solid var(--border-strong);
    color: var(--text-primary);
    border-radius: 0;
    font-family: var(--font-body);
    font-size: 12.5px;
    font-weight: 500;
    letter-spacing: 0.02em;
    padding: 6px 16px;
    transition: all 0.18s ease;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}
.stButton > button:hover {
    background: var(--text-primary);
    color: var(--bg-deep);
    border-color: var(--text-primary);
}
.stButton > button:focus { box-shadow: none !important; }
.stButton > button[kind="primary"],
.primary-btn .stButton > button {
    background: var(--accent-vermillion);
    border-color: var(--accent-vermillion);
    color: var(--bg-deep);
    font-weight: 600;
}
.stButton > button[kind="primary"]:hover,
.primary-btn .stButton > button:hover {
    background: var(--text-primary);
    border-color: var(--text-primary);
    color: var(--accent-vermillion);
}

/* ── Inputs ───────────────────────────────────────────────────────────── */
.stTextInput input, .stTextArea textarea,
.stSelectbox > div > div, .stNumberInput input {
    background: var(--bg-surface) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-primary) !important;
    border-radius: 0 !important;
    font-family: var(--font-body) !important;
    font-size: 13.5px !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: var(--accent-vermillion) !important;
    box-shadow: 0 0 0 1px var(--accent-vermillion) !important;
}

/* ── Tabs ─────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent;
    border-bottom: 1px solid var(--border);
    gap: 32px;
}
.stTabs [data-baseweb="tab"] {
    color: var(--text-muted);
    font-family: var(--font-mono);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    background: transparent;
    border-bottom: 2px solid transparent;
    padding-bottom: 8px;
}
.stTabs [aria-selected="true"] {
    color: var(--text-primary) !important;
    border-bottom: 2px solid var(--accent-vermillion) !important;
}

/* ── Expander ─────────────────────────────────────────────────────────── */
details {
    background: var(--bg-surface);
    border: 1px solid var(--border) !important;
    border-radius: 0;
}
summary {
    color: var(--text-secondary);
    font-family: var(--font-mono);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
}

/* ── Alerts — flat, single-rule accent ─────────────────────────────────── */
div[data-testid="stInfo"], div[data-testid="stWarning"],
div[data-testid="stSuccess"], div[data-testid="stError"] {
    background: var(--bg-surface);
    border-radius: 0;
    border: 1px solid var(--border);
    border-left-width: 3px;
    color: var(--text-primary);
    font-family: var(--font-body);
}
div[data-testid="stInfo"]    { border-left-color: var(--accent-cobalt); }
div[data-testid="stWarning"] { border-left-color: var(--accent-gold); }
div[data-testid="stSuccess"] { border-left-color: var(--accent-sage); }
div[data-testid="stError"]   { border-left-color: var(--accent-rust); }

/* ── Radio (filter pills) ─────────────────────────────────────────────── */
div[data-testid="stRadio"] > div {
    flex-direction: row;
    gap: 0;
    border: 1px solid var(--border);
    background: var(--bg-surface);
    width: fit-content;
}
div[data-testid="stRadio"] label {
    background: transparent;
    border: none;
    border-right: 1px solid var(--border);
    border-radius: 0;
    padding: 7px 18px;
    font-family: var(--font-mono);
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--text-muted);
    cursor: pointer;
    transition: all 0.15s ease;
    margin: 0;
}
div[data-testid="stRadio"] label:last-child { border-right: none; }
div[data-testid="stRadio"] label:hover { color: var(--text-primary); }
div[data-testid="stRadio"] label:has(input:checked) {
    background: var(--text-primary);
    color: var(--bg-deep);
}

/* ── Progress bar ─────────────────────────────────────────────────────── */
div[data-testid="stProgress"] {
    height: 2px;
}
div[data-testid="stProgress"] > div > div {
    background: var(--accent-vermillion);
    border-radius: 0;
}

/* ── Scrollbar ────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg-deep); }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 0; }
::-webkit-scrollbar-thumb:hover { background: var(--accent-vermillion); }

/* ── Section / editorial markers ──────────────────────────────────────── */
.cre-section-rule {
    display: flex;
    align-items: center;
    gap: 12px;
    font-family: var(--font-mono);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.22em;
    color: var(--text-muted);
    margin: 28px 0 14px 0;
}
.cre-section-rule::after {
    content: "";
    flex: 1;
    height: 1px;
    background: var(--border);
}

/* Editorial tier chip — pure monospace, sharp */
.cre-chip {
    display: inline-block;
    padding: 2px 9px;
    font-family: var(--font-mono);
    font-size: 9.5px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    border: 1px solid currentColor;
    border-radius: 0;
    margin-right: 8px;
}
.cre-chip.hot     { color: var(--accent-vermillion); }
.cre-chip.warm    { color: var(--accent-gold); }
.cre-chip.nurture { color: var(--accent-cobalt); }
.cre-chip.new     { color: var(--accent-sage); background: rgba(134,177,105,0.08); }
.cre-chip.sent    { color: var(--text-muted); }

/* Pulse dot */
.cre-pulse {
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    margin-right: 8px;
    vertical-align: middle;
}
.cre-pulse.live { background: var(--accent-vermillion); animation: cre-breathe 2.2s ease-in-out infinite; }
.cre-pulse.idle { background: var(--text-muted); }
.cre-pulse.ok   { background: var(--accent-sage); }
@keyframes cre-breathe {
    0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(255,91,58,0.6); }
    50%      { opacity: 0.5; box-shadow: 0 0 0 6px rgba(255,91,58,0); }
}

/* Data display — for headline numbers like "1,600" */
.cre-stat {
    font-family: var(--font-display);
    font-variation-settings: "opsz" 144, "SOFT" 50;
    font-size: 30px;
    font-weight: 500;
    color: var(--text-primary);
    letter-spacing: -0.02em;
    line-height: 1;
}
.cre-stat-label {
    font-family: var(--font-mono);
    font-size: 9.5px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: var(--text-muted);
    margin-bottom: 6px;
    display: block;
}

/* Decorative bracket markers around important values */
.cre-bracket {
    color: var(--accent-vermillion);
    font-family: var(--font-mono);
    margin: 0 4px;
    font-weight: 300;
    opacity: 0.6;
}

/* DataFrame container */
div[data-testid="stDataFrame"] {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 0;
}

/* Links */
a { color: var(--accent-vermillion); text-decoration: none; }
a:hover { color: var(--text-primary); }

/* Toasts */
div[data-testid="stToast"] {
    background: var(--bg-elevated) !important;
    border: 1px solid var(--border-strong) !important;
    border-left: 3px solid var(--accent-vermillion) !important;
    border-radius: 0 !important;
    color: var(--text-primary) !important;
    font-family: var(--font-body) !important;
}

/* Markdown copy */
.stMarkdown p { line-height: 1.55; font-size: 14px; color: var(--text-secondary); }

/* Selectbox dropdown */
div[data-baseweb="popover"] > div { background: var(--bg-elevated) !important; border: 1px solid var(--border) !important; }

hr { border-color: var(--border) !important; opacity: 0.6; }

/* The signature ornament — small geometric mark we can place anywhere */
.cre-mark::before {
    content: "◆";
    color: var(--accent-vermillion);
    font-size: 7px;
    margin-right: 8px;
    vertical-align: middle;
    opacity: 0.8;
}
</style>
"""
