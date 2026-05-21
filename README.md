# CRE Outreach Intelligence

**A morning research agent for tenant rep brokers — from overnight signal scan to reviewed Gmail draft in one screen.**

Each morning at 05:00 ET the pipeline runs unattended: discovers fresh NYC prospects, scrapes free signal sources for the watchlist, scores every company with `facebook/bart-large-mnli`, and drafts personalised email + LinkedIn copy with `mistralai/Mistral-7B-Instruct-v0.2`. By the time the broker opens Streamlit at 07:00, every actionable lead has a Gmail draft waiting and a research brief explaining *why* it's actionable today.

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
2. **Researches every prospect** in parallel (ThreadPoolExecutor, max 4 workers). For each one:
   - `scrapers/google_news.py` — Google News RSS, last 7 days
   - `scrapers/newsapi_scraper.py` — NewsAPI free tier, last 7 days
   - `scrapers/firecrawl_scraper.py` — company website (about / home / news)
   - All Firecrawl text passes through `_clean_web_text()` first, stripping markdown chrome, navigation phrases, image markdown, phone numbers — otherwise bart-mnli scores every label high on the same bland about-us page.
3. **Scores** every prospect against five candidate hypotheses in one bart-mnli call with `multi_label=True`:
   - *company is expanding to new office locations*
   - *company is hiring aggressively and growing headcount*
   - *company recently raised funding and has capital to deploy*
   - *company office lease may be expiring soon*
   - *company needs more office space*
   Composite = weighted mean of the top two signal scores (0.7) + the rest (0.3), bounded 0–100. Tiers: **Hot 🔥 ≥75**, **Warm ☀️ ≥50**, **Nurture ❄️ below 30 skipped**.
4. **Builds per-label signal cards** via `_snippet_for_label()` — picks the sentence from the winning article that actually mentions a keyword for the label, so the five cards don't all parrot the same blob. When the winning article is the company-website pseudo-article *and* no label-keyword appears in the body, the signal is suppressed entirely (phantom-score guard).
5. **Drafts** an email + LinkedIn message via Mistral-7B for every actionable lead in the chosen tone (Direct / Warm / Consultative).
6. **Pushes** every draft to Gmail Drafts via the Gmail API, logs the digest, and (optionally) emails the broker a summary.

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
│  pages/        Streamlit UI (5 = home, 3 = review, 6/7 = log)  │
│      ↓ reads data/morning_run_*.json, calls run_now()          │
├────────────────────────────────────────────────────────────────┤
│  scheduler.py  APScheduler cron + run_morning_pipeline()       │
│      ↓ parallel ThreadPool over watchlist + discovered leads   │
├────────────────────────────────────────────────────────────────┤
│  research_agent.py     bart-mnli scoring + Signal construction │
│  lead_discovery.py     new-lead candidates from free sources   │
│  hf_models/writer.py   Mistral-7B email + LinkedIn draft       │
│      ↓ HF router endpoint (router.huggingface.co)              │
├────────────────────────────────────────────────────────────────┤
│  scrapers/             google_news · newsapi · firecrawl       │
│  gmail_drafts.py       Gmail API — drafts + digest send        │
│  google_sheets.py      Sheets API — append sent rows           │
│  google_calendar.py    Calendar API — follow-up events         │
│      ↓ all three share one credentials.json + per-service token│
├────────────────────────────────────────────────────────────────┤
│  config.py             env vars, prompts, thresholds, theme    │
└────────────────────────────────────────────────────────────────┘
```

The single rule: pages read JSON, scheduler writes JSON, and the API connectors live behind their own module so a key missing for one service doesn't break the others.

---

## What you need to run it

### Prerequisites

- Python 3.11
- A terminal
- A Google account (for Gmail / Sheets / Calendar — one OAuth client covers all three)
- A free HuggingFace token

### One-time setup

```bash
python3 -m venv venv
source venv/bin/activate          # macOS / Linux
# .\venv\Scripts\activate         # Windows

pip install -r requirements.txt

cp .env.example .env              # then fill in keys
```

For Google integration, download an OAuth client (`Desktop app` type) from Google Cloud Console and save it as `credentials.json` at the project root. Enable the Gmail API, Sheets API, and Calendar API on the same project. First run will open a browser for consent and cache per-service tokens under `data/gmail_token.json` / `data/sheets_token.json` / `data/calendar_token.json`.

### Running

```bash
source venv/bin/activate

# Streamlit (default — the broker's view)
streamlit run app.py

# Pipeline once, on demand
python scheduler.py --once

# Scheduler daemon (runs the cron forever)
python scheduler.py
```

If `START_SCHEDULER=true` in `.env`, the Streamlit app spawns the scheduler in a background thread automatically — no separate process needed for local use.

---

## API keys

All keys live in your local `.env` file and are never shared or hardcoded. Anything missing degrades gracefully (the source just contributes zero signals).

| Key | Required? | Purpose |
|---|---|---|
| `HF_TOKEN` | yes | bart-mnli scoring + Mistral drafting via HuggingFace Inference (router endpoint) |
| `NEWSAPI_KEY` | recommended | NewsAPI free tier (~100 req/day, last 30 days) |
| `FIRECRAWL_API_KEY` | recommended | Company website scraping |
| `HUNTER_API_KEY` | optional | Email enrichment for discovered leads |
| `GOOGLE_CREDENTIALS_PATH` | yes for Gmail/Sheets/Calendar | path to `credentials.json` (default: project root) |
| `SHEETS_SPREADSHEET_ID` | optional | target sheet for the sent-tracker |
| `CALENDAR_ID` | optional | target calendar for follow-up events (default: primary) |
| `BROKER_EMAIL` | optional | who the morning digest is sent to |
| `AGENT_NAME` / `FIRM_NAME` / `AGENT_EMAIL` | recommended | signature block in drafts |
| `TIMEZONE` | optional | default `America/New_York` |
| `RESEARCH_CRON_HOUR` / `_MINUTE` | optional | default 5:00 |
| `START_SCHEDULER` | optional | `true` makes Streamlit spin up the background scheduler |

Google News RSS needs no key.

---

## The watchlist

Lives at `data/watchlist.json`. Each entry is one prospect the broker is actively tracking. New entries are added through the discovered-leads approval flow on page 5 (auto-promotion of approved candidates) or by editing the file directly. Seed data ships with three real NYC companies (Oscar Health, Ramp, Notion Labs) so a first run produces real signals immediately.

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
| "Send now" is greyed out | The watchlist entry has no `contact_email`. Edit the field directly in the draft-review screen (it persists back to `data/watchlist.json`). |
| HF returns 401/403 | Renew the token at huggingface.co → Settings → Access Tokens (read scope is enough). |
| HF returns "Not Found" | The `api-inference.huggingface.co` host was deprecated in 2025 — `config.HF_API_BASE` must point at `https://router.huggingface.co/hf-inference/models`. |
| Streamlit can't import `apscheduler` / `google.oauth2` | You're running the system Python rather than the venv. `source venv/bin/activate` and try again. |
| `data/morning_run_*.json` missing | The cron hasn't fired yet today. Either wait for 05:00 ET, click **Run pipeline** in the UI, or run `python scheduler.py --once`. |

For anything else: check the **API status** strip in the left sidebar — it shows which connectors are live vs degraded.
