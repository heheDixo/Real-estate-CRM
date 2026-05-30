# CRE Outreach Intelligence

**A morning research agent for tenant rep brokers — from overnight signal scan to reviewed Gmail draft in one screen.**

Each morning at 05:00 ET the pipeline runs unattended: discovers fresh NYC prospects, scrapes free signal sources for the watchlist, scores every company with `facebook/bart-large-mnli`, and drafts personalised email + LinkedIn copy with `meta-llama/Llama-3.1-8B-Instruct` (Mistral-7B-Instruct-v0.2 was the original writer; it was retired from the free `hf-inference` provider in mid-2025 — see [PROGRESS.md](PROGRESS.md) §5). By the time the broker opens Streamlit at 07:00, every actionable lead has a Gmail draft waiting, a research brief explaining *why* it's actionable today, and a Telegram morning brief on their phone.

Nothing sends without the broker's approval.

---

## What it replaces

| Step in the manual workflow | Time it normally takes |
|---|---|
| Building the daily lead list | ~15 min per prospect |
| Researching the company + contact | ~10 min |
| Drafting the outreach email | ~10 min |
| Drafting the LinkedIn message | ~5 min |
| Logging the prospect to a tracker | ~5 min |
| Setting the follow-up reminder | ~5 min |
| **Total** | **~50 min per prospect** |

With the system everything except the broker's review runs in the background. Review takes ~5 min per draft. That's ~45 min saved per prospect, ~12 hours back in the week at 15 qualified prospects.

---

## How it works — the morning loop

The whole pipeline is a single APScheduler cron firing at `RESEARCH_CRON_HOUR:RESEARCH_CRON_MINUTE` (default 05:00) in `TIMEZONE` (default America/New_York). The 5am job:

1. **Discovers new leads** — `lead_discovery.discover_new_leads()` queries Google News RSS, NewsAPI, BuiltInNYC, and Hacker News Jobs for companies that match the active ICP (sector + city) derived from the watchlist. Junk filters (city names, dictionary words, tech-stack tokens, job-title plurals) keep "Front" / "You" / "Software Engineer" out of the candidate list.
2. **Researches every prospect** sequentially — Phase 5 swapped the prior ThreadPoolExecutor for a serial loop so the **LinkedIn 30-second global rate limit** isn't a race condition. For each one:
   - `scrapers/google_news.py` — Google News RSS, last 7 days
   - `scrapers/newsapi_scraper.py` — NewsAPI free tier, last 7 days
   - `scrapers/firecrawl_scraper.py` — company website (about / home / news)
   - `scrapers/linkedin_jobs.py` — guest-API job search, last 7 days, 30s rate limit + single retry-with-jitter on empty result
   - `scrapers/linkedin_google.py` — follower / employee count text from Google's LinkedIn-company SERP snippet
   - All Firecrawl text passes through `_clean_web_text()` first, stripping markdown chrome, navigation phrases, image markdown, phone numbers — otherwise bart-mnli scores every label high on the same bland about-us page.
3. **Scores** every prospect against five candidate hypotheses in one bart-mnli call with `multi_label=True`:
   - *company is expanding to new office locations*
   - *company is hiring aggressively and growing headcount*
   - *company recently raised funding and has capital to deploy*
   - *company office lease may be expiring soon*
   - *company needs more office space*
   Composite = weighted mean of the top two signal scores (0.7) + the rest (0.3), bounded 0–100. Tiers: **Hot 🔥 ≥75**, **Warm ☀️ ≥50**, **Nurture below 15 skipped** (Phase 5 lowered the skip threshold from 30 → 15 to surface warm leads while the watchlist is small). LinkedIn signals are injected with deterministic scores after the bart-mnli loop — 2+ office roles → 90, 1 office role → 75, 3+ total roles → 55 — and replace any weaker LinkedIn signal the existing hiring-label path produced.
4. **Builds per-label signal cards** via `_snippet_for_label()` — picks the sentence from the winning article that actually mentions a keyword for the label, so the five cards don't all parrot the same blob. When the winning article is the company-website pseudo-article *and* no label-keyword appears in the body, the signal is suppressed entirely (phantom-score guard).
5. **Drafts** an email + LinkedIn message via Llama-3.1-8B for every actionable lead in the chosen tone (Direct / Warm / Consultative). All HF calls go through `hf_client.py` — 3 retries with 2s/4s/8s backoff, scorer results cached in Supabase, template fallback when the writer is down.
6. **Pushes** every draft to Gmail Drafts via the Gmail API, sends a Telegram morning brief to every connected user, logs the digest, and (optionally) emails the broker a summary. Pipeline failure + warm-up failure also alert via Telegram.

Output lands in `data/morning_run_<YYYY-MM-DD>.json`. The Streamlit app reads from that file — no live re-scraping when the broker opens the UI.

---

## The four screens

### `pages/5_morning_research.py` — home
The default landing page. Top bar shows pipeline status (pulse-dot) and a primary **Run pipeline** button if the broker wants to re-run mid-morning. Four metric cards: actionable / hot / warm / new leads. Filter pills across the top. Left: lead cards sorted by composite score with tier accent + NEW / Draft ready / Sent badges. Right: detail pane with signal cards (icon + type + strength dots + score), the chosen top hook, and a primary **Start outreach** button.

### `pages/3_draft_review.py` — review + send
Breadcrumb back to research. 35/65 split. Left: research brief expander, opening-hook callout, contact info row (with inline-editable email field if missing). Right: tone radio (Direct / Warm / Consultative — auto-regenerates), subject + body + LinkedIn editor with colour-coded character counts, four actions: **Regenerate** / **Copy** / **Save to Gmail draft** / **Send now**. Send now path: SMTP send → Sheets log → Calendar follow-up created → tone_learner archives the diff → return to home.

### `pages/6_sent_tracker.py` — sent log
Dark HTML table from Google Sheets. Status pills (Sent / Opened / Replied / Meeting). Four metric cards: Total / Open rate / Reply rate / Meetings booked. Empty states for missing credentials.

### `pages/7_followups.py` — follow-up queue
Reads from Google Calendar. Blue date badges, purple suggested-angle callouts (drawn from the original signal), **Mark replied** + **Delete** buttons.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  pages/                Streamlit UI                            │
│      ↓ require_login() → reads Supabase + morning_run JSON     │
├────────────────────────────────────────────────────────────────┤
│  oauth_server.py       FastAPI sidecar — /oauth/* + /telegram  │
│  session_manager.py    Streamlit auth gate + dark login page   │
│  google_auth_loader.py Rehydrates Google creds in non-UI code  │
├────────────────────────────────────────────────────────────────┤
│  scheduler.py          APScheduler — 04:50 warm-up, 05:00 pipe │
│      ↓ run_morning_pipeline_safe (try/except + alert mirror)   │
├────────────────────────────────────────────────────────────────┤
│  research_agent.py     bart-mnli scoring + Signal construction │
│  lead_discovery.py     new-lead candidates from free sources   │
│  hf_models/writer.py   Llama-3.1-8B email + LinkedIn draft     │
│  hf_client.py          retry + cache + warm-up + fallback      │
│      ↓ HF router (bart on hf-inference, Llama on /v1/chat)     │
├────────────────────────────────────────────────────────────────┤
│  scrapers/             google_news · newsapi · firecrawl       │
│  gmail_drafts.py       Gmail API — drafts + digest send        │
│  google_sheets.py      Sheets API — append sent rows           │
│  google_calendar.py    Calendar API — follow-up events         │
│  telegram_bot.py       Telegram Bot API — brief + alerts       │
│  monitoring.py         SMTP_SSL email alerts                   │
├────────────────────────────────────────────────────────────────┤
│  database.py           Supabase CRUD; JSON fallback everywhere │
│  config.py             env vars, prompts, thresholds, theme    │
└────────────────────────────────────────────────────────────────┘
```

The single rule: pages read Supabase (with JSON as fallback), scheduler writes Supabase, and every connector lives behind its own module so a key missing for one service doesn't break the others. Detailed walkthrough in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## What you need to run it

### Prerequisites

- Python 3.11
- A terminal
- A Google account (for Gmail / Sheets / Calendar — one OAuth client covers all three)
- A free HuggingFace token (route scoring through `hf-inference` and writing through `/v1/chat/completions` — $0.10/mo free credits per HF account)
- A Supabase project (free tier — URL + anon key)
- A Telegram bot token from @BotFather (optional, only needed for the morning brief notification)

### One-time setup

```bash
python3 -m venv venv
source venv/bin/activate          # macOS / Linux
# .\venv\Scripts\activate         # Windows

pip install -r requirements.txt

cp .env.example .env              # then fill in keys
```

For Google integration, create an OAuth 2.0 client (**Web application** type, not Desktop — Phase 2 moved auth to a browser flow) at Google Cloud Console. Add `http://localhost:8000/oauth/callback` as an authorised redirect URI. Enable Gmail, Sheets, Calendar, and Docs APIs on the same project. Tokens persist in Supabase (`users.google_token` JSONB), refreshed automatically by [`google_auth_loader.py`](google_auth_loader.py) — no more per-service JSON token files.

For Supabase, create a free project, run [`setup_database.sql`](setup_database.sql) in the SQL editor once, then put `SUPABASE_URL` + `SUPABASE_ANON_KEY` in `.env`. The one-time migration of seed JSON into the DB is `python migrate_json_to_db.py` (idempotent for prospects + tone profile; don't re-run for approved_emails — it has no natural unique key).

For Telegram, message @BotFather → `/newbot` → grab the token → put `TELEGRAM_BOT_TOKEN` + `TELEGRAM_BOT_USERNAME` in `.env`. The connect banner on the research page generates a one-tap deep link.

Full deployment notes — Railway 3-service triad walkthrough, Google OAuth consent screen scopes (Test users + Microsoft 365 caveat), Supabase RLS plan, and Telegram webhook registration — are in [DEPLOYMENT.md](DEPLOYMENT.md). Phase 7 deployment status, Phase 5 / 6 changelog, debugging quick-reference and known gotchas are in [PROGRESS.md](PROGRESS.md).

### Running

Two terminals (the FastAPI sidecar handles OAuth callback + the Telegram webhook):

```bash
# Terminal 1 — OAuth + Telegram sidecar
source venv/bin/activate
uvicorn oauth_server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Streamlit (the broker's view)
source venv/bin/activate
streamlit run app.py
```

Visit http://localhost:8501 → "Sign in with Google".

Other commands:

```bash
# Pipeline once, on demand
python scheduler.py --once

# Scheduler daemon (runs the 04:50 warm-up + 05:00 pipeline forever)
python scheduler.py

# Telegram polling — local-dev only; production uses the webhook on the
# FastAPI sidecar
python -c "from telegram_bot import run_polling; run_polling()"
```

If `START_SCHEDULER=true` in `.env`, the Streamlit app spawns the scheduler in a background thread automatically — no separate process needed for local use.

---

## API keys

All keys live in your local `.env` file and are never shared or hardcoded. Anything missing degrades gracefully (the source just contributes zero signals).

| Key | Required? | Purpose |
|---|---|---|
| `HF_TOKEN` | yes | bart-mnli scoring (via `hf-inference`) + Llama-3.1-8B drafting (via `/v1/chat/completions`) |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | yes | Database backing every CRUD path — Phase 1 |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | yes for Gmail/Sheets/Calendar/Docs | Web-app OAuth client — Phase 2 |
| `GOOGLE_REDIRECT_URI` | yes | Default `http://localhost:8000/oauth/callback`; update for deploy |
| `FASTAPI_URL` / `STREAMLIT_URL` | yes | Sidecar + UI URLs (defaults `localhost:8000` / `localhost:8501`) |
| `ALLOWED_EMAILS` | recommended | Comma-separated whitelist of emails allowed to complete Google sign-in |
| `PRIMARY_USER_ID` | optional (Phase 8) | UUID of the `users` row the 5am cron acts as. Wins over everything else. |
| `PRIMARY_BROKER_EMAIL` | recommended (Phase 8) | Match against `users.google_email` for the cron when `PRIMARY_USER_ID` is unset. Falls back to `BROKER_EMAIL`, then row-1. |
| `TELEGRAM_BOT_TOKEN` | optional | Morning brief + alerts via Telegram — Phase 4 |
| `TELEGRAM_BOT_USERNAME` | optional | Bot username (no @) used to build the connect deep link |
| `APOLLO_API_KEY` | recommended | Apollo.io free tier — Organization Search + People Search |
| `NEWSAPI_KEY` | recommended | NewsAPI free tier (~100 req/day, last 30 days) |
| `FIRECRAWL_API_KEY` | recommended | Company website scraping |
| `HUNTER_API_KEY` | optional | Email enrichment fallback when Apollo doesn't return a verified address |
| `GMAIL_SENDER` / `GMAIL_APP_PASSWORD` / `ALERT_EMAIL` | optional | SMTP alert mirror for pipeline + warm-up failures (`monitoring.py`) |
| `SHEETS_SPREADSHEET_ID` | optional | target sheet for the sent-tracker |
| `CALENDAR_ID` | optional | target calendar for follow-up events (default: primary) |
| `BROKER_EMAIL` | optional | who the morning digest is sent to |
| `AGENT_NAME` / `FIRM_NAME` / `AGENT_EMAIL` | recommended | signature block in drafts |
| `TIMEZONE` | optional | default `America/New_York` |
| `RESEARCH_CRON_HOUR` / `_MINUTE` | optional | default 5:00 (warm-up fires at 4:50) |
| `START_SCHEDULER` | optional | `true` makes Streamlit spin up the background scheduler |

Google News RSS needs no key.

---

## The watchlist

Lives at `data/watchlist.json` (now `.gitignore`d — Supabase `prospects` is the authoritative store; the file is just a local mirror / migration source). Each entry is one prospect the broker is actively tracking. New entries are added through the discovered-leads approval flow on page 5 (auto-promotion of approved candidates) or by editing the file directly and re-running `migrate_json_to_db.py`. Seed data in Phase 5 was switched from the original three demo companies (Oscar Health, Ramp, Notion Labs) to **five health-tech NYC entries**: Northwell Health, CityMD, Ro, Cityblock (active) + Quartet Health (inactive — kept for reference). Company names were trimmed to the canonical forms the press uses ("Northwell Health Ventures" → "Northwell Health", "Cityblock Health" → "Cityblock") so news + LinkedIn search matching works.

Schema:

```json
{
  "id":             "ramp-001",
  "company":        "Ramp",
  "domain":         "ramp.com",
  "website":        "https://ramp.com",
  "contact_name":   "",
  "contact_title":  "Head of Real Estate",
  "contact_email":  "broker@example.com",
  "linkedin_url":   "https://www.linkedin.com/company/ramp",
  "sector":         "Fintech",
  "city":           "New York",
  "icp_profile":    "financial_services_nyc",
  "source":         "watchlist",
  "added_at":       "2026-05-21",
  "active":         true
}
```

---

## What the AI is and isn't doing

**It is doing:**
- Reading cleaned article text + cleaned website prose and scoring it against five CRE-relevant hypotheses with a public zero-shot model.
- Writing first-touch email + LinkedIn copy with prompts that enforce the chosen tone variant — word counts, opening style, sign-off.
- Extracting the most label-relevant *sentence* from each winning article so signal cards are distinct.

**It is not doing:**
- Sending anything without the broker hitting **Send now**.
- Posting to LinkedIn automatically — that's still copy-paste, by design (automating LinkedIn risks the account).
- Trusting bart-mnli's score blindly. When the only article is the bland about-us page and no keyword for the label appears, the signal is suppressed even if the model scored it 0.9+. That guard exists because zero-shot models confabulate on bland marketing text.

---

## What gets better with use

`tone_learner.py` records every diff between the AI's draft and the broker's edited version after **Send now**. That diff feeds the next morning's tone injection — over a few weeks the system writes closer to the broker's voice without ever shipping their old emails into the prompt verbatim.

The watchlist itself accumulates: discovered leads the broker approved last week are first-class watchlist entries this week, with one more cycle of signal history each morning.

---

## Privacy and data handling

- All credentials live in your local `.env` and `credentials.json`. They're never sent anywhere except the API they belong to.
- No prospect data is stored on any server we control. Pipeline output lives under `data/morning_run_*.json` on disk; the Streamlit session has no separate persistence.
- Per-run JSON, OAuth tokens, error logs, and progress files are all gitignored.
- The HuggingFace Inference router receives the cleaned article + website text for scoring and drafting. If that's a concern for any specific prospect, leave its `website` field blank in the watchlist.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Every prospect scored exactly 20 | `_mock_fallback` fired — scrapers + bart-mnli both came back empty. Check `data/error_log.json` for `scheduler.no_articles` / `research_agent.*` entries. |
| All signal cards show the same text | Pre-fix bug — make sure `_clean_web_text` + `_snippet_for_label` are in place. After the fix each card uses a label-specific sentence. |
| Draft signature says "Michael Hartley, Hartley CRE Partners" instead of the broker's real name | Either (a) the draft row was generated before Phase 6 commit `439637c` (regenerate with `DELETE FROM research_reports WHERE run_date = CURRENT_DATE;` + Run pipeline), or (b) Railway env vars `AGENT_NAME` / `AGENT_TITLE` / `FIRM_NAME` aren't set on every service — they fall back to the `config.py` defaults which are the demo Michael. |
| "Send now" is greyed out | The watchlist entry has no `contact_email`. Edit the field directly in the draft-review screen (it persists back to `data/watchlist.json`). |
| HF returns 401/403 | Renew the token at huggingface.co → Settings → Access Tokens (read scope is enough). |
| HF returns "Not Found" | The `api-inference.huggingface.co` host was deprecated in 2025 — `config.HF_API_BASE` must point at `https://router.huggingface.co/hf-inference/models`. |
| Writer returns `"Model not supported by provider hf-inference"` | Mistral was retired from the free `hf-inference` provider in mid-2025. Writer must be a model that routes through `/v1/chat/completions` (current default: `meta-llama/Llama-3.1-8B-Instruct`). |
| Drafts are all template fallbacks | `$0.10/mo` HF free credits exhausted. Top up at huggingface.co/settings/billing or subscribe to PRO ($9/mo → $2/mo credits). |
| LinkedIn returns 0 jobs for everyone | (a) Global rate limiter is still cooling from a prior run within 30s, or (b) LinkedIn's silent IP rate-limit hit (`200 OK` with no job-card HTML). The retry-with-jitter in `scrape_linkedin_jobs` usually recovers; tomorrow's cron will pick it up either way. |
| Telegram brief not arriving | (1) Did you `/start <user_id>` the bot? Check `users.telegram_connected` in Supabase. (2) Is `TELEGRAM_BOT_TOKEN` set? (3) For production, is the webhook registered? `curl .../getWebhookInfo` to verify. |
| `redirect_uri_mismatch` from Google on sign-in | The `GOOGLE_REDIRECT_URI` env var (api service) and the **Authorised redirect URIs** in Google Cloud Console must match character-for-character. Both must point at `https://<api-host>/oauth/callback`. |
| "Email addresses must be associated with an active Google Account" when adding a broker as Test user | The email is on Microsoft 365 (Cushman & Wakefield, JLL, CBRE, Newmark — every major CRE firm). Workaround: the broker uses a personal Gmail; signature still says their firm. See [ASSUMPTIONS_AND_IMPROVEMENTS.md](ASSUMPTIONS_AND_IMPROVEMENTS.md) §12. |
| Streamlit can't import `apscheduler` / `google.oauth2` | You're running the system Python rather than the venv. `source venv/bin/activate` and try again. |
| `data/morning_run_*.json` missing | The cron hasn't fired yet today. Either wait for 05:00 ET, click **Run pipeline** in the UI, or run `python scheduler.py --once`. |
| Every web user's drafts / sends / docs land in the *primary broker's* account | Pre-Phase-8 bug. Fixed in Phase 8: every Streamlit page now passes the logged-in user's credentials to `authenticate_*`. If it's still happening after Phase 8 ships, the user dict in `st.session_state["current_user"]` is missing; have them sign out + sign in. |
| "Generate research doc" button returns 403 `ACCESS_TOKEN_SCOPE_INSUFFICIENT` | The user's OAuth token predates the Phase 8 scope expansion. Sign out, sign in again, accept the new Docs + Drive scopes at the consent screen. Confirm the Google Docs API is enabled under **APIs & Services → Library**. |
| Sent-tracker page is empty but you definitely just sent an email | The user's `users.sheets_spreadsheet_id` either (a) never got persisted (run the Phase 8 migration: `ALTER TABLE users ADD COLUMN IF NOT EXISTS sheets_spreadsheet_id TEXT;`) or (b) points at a duplicate sheet from before the column existed. Resolution: `UPDATE users SET sheets_spreadsheet_id = NULL WHERE google_email = '<you>';`, trash duplicate "CRE Outreach — Sent Emails" sheets in Drive, send-now once. |
| Send-now button is greyed out | The lead's `contact_email` is empty. Fill it in the contact-email field on the left pane of the draft-review page — both Gmail draft + Send now light up once an address is present. |

For anything else: check the **API status** strip in the left sidebar — it shows which connectors are live vs degraded.
