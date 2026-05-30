# Progress so far — CRE Outreach Intelligence

Status as of **2026-05-30**. Covers Phase 1 (database foundation),
Phase 2 (Google OAuth login), Phase 3 (HuggingFace model hardening),
Phase 4 (Telegram bot), Phase 5 (LinkedIn signal scrapers + scoring
tune), Phase 6 (broker-email fan-out + per-broker identity prompts),
Phase 7 (Railway production deployment — live as of this update), and
Phase 8 (per-user Google action routing — multi-tenant web app, cron
stays single-tenant).

The production app is reachable at
**https://web-production-a655b.up.railway.app** (Streamlit) and
**https://api-production-7962b.up.railway.app** (FastAPI). Both
services pass health checks; Telegram webhook registration and a final
sign-in flight check are the only outstanding deploy steps.

---

## 1. What this project is

CRE Outreach Intelligence is a single-broker prospecting system for
commercial real-estate tenant representation. The morning pipeline:

1. **Discovers** companies matching the broker's ICP from free sources
   (Google News RSS, NewsAPI, BuiltInNYC, HN Who-Is-Hiring), then enriches
   each with Apollo (headcount, industry, LinkedIn) and Greenhouse / Ashby /
   Lever (live job postings).
2. **Researches** each prospect — scrapers pull news + website text + open
   roles, then `bart-large-mnli` (zero-shot classification on HuggingFace
   Inference API) scores the bundle against five CRE-relevant labels:
   hiring, funding, expansion, lease, space-need.
3. **Drafts** an outreach email + LinkedIn message via Llama-3.1-8B-Instruct
   (HF Inference Providers, OpenAI-style chat-completions endpoint),
   wrapped in a tone profile learned from the broker's past approved
   emails. Mistral-7B-Instruct-v0.2 used to be the writer; it was retired
   from the free `hf-inference` provider in mid-2025 — see Phase 3.
4. **Pushes** hot leads to Gmail Drafts, sends a Telegram morning brief to
   every connected user, optionally sends a 7 AM email digest, and creates
   a 5-day follow-up event on Google Calendar after the broker hits
   "Send now".

The UI is a Streamlit dark editorial dashboard (`/`, `/draft_review`,
`/morning_research`, `/sent_tracker`, `/followups`). All long-running work
runs in a background thread; the UI polls `data/pipeline_progress.json` for
a live progress bar.

## 2. Tech stack as of today

| Layer | Tech |
|---|---|
| UI | Streamlit 1.35 (dark editorial theme via custom CSS) |
| Auth server | FastAPI + uvicorn (sidecar on port 8000) |
| Database | Supabase (Postgres + PostgREST) with local JSON fallback |
| LLM | HuggingFace Inference API (bart-mnli scorer via `hf-inference`; Llama-3.1-8B writer via `/v1/chat/completions`) |
| Notifications | Telegram Bot API (morning brief + alert mirrors) |
| Discovery | Google News RSS, NewsAPI, BuiltInNYC, HN Algolia |
| Enrichment | Apollo, Greenhouse / Ashby / Lever, Hunter.io, Firecrawl |
| Outbound | Gmail API (drafts + send), Google Sheets, Calendar, Docs |
| Scheduling | APScheduler |
| Hosting | Procfile-ready for Railway / Fly / Render (3 processes: web, api, worker) |

---

## 3. Phase 1 — Database foundation (✅ complete)

Goal: move the system from JSON files in `data/` to Supabase as the single
source of truth, with JSON as a fallback when the DB is unreachable.

### What landed

**New files**
- [`setup_database.sql`](setup_database.sql) — 11-table schema, run once
  in the Supabase SQL editor. Tables: `users`, `sessions`, `prospects`,
  `research_reports`, `sent_emails`, `approved_emails`, `tone_profiles`,
  `pipeline_runs`, `oauth_tokens`, `dismissed_leads`, `score_cache`. Plus
  8 indexes for the common query paths (sessions by token, reports by
  run_date, sent_emails by sent_at desc, etc.).
- [`database.py`](database.py) — single module wrapping every CRUD call.
  Pattern used everywhere:
  - try Supabase first
  - on any exception: log to `data/error_log.json`, fall back to a local
    JSON read/write so the UI never crashes on a DB error
  - `_db()` lazily builds a client from `SUPABASE_URL` + `SUPABASE_ANON_KEY`
- [`migrate_json_to_db.py`](migrate_json_to_db.py) — one-shot migration
  that upserts the existing `watchlist.json`, `tone_profile.json`, and
  `approved_emails.json` into Supabase. Idempotent on prospects + tone
  (upserts); approved_emails has no natural unique key so re-runs
  duplicate — only run once unless you also wipe the table.

**Modified to use `database.py`**
- [`tone_learner.py`](tone_learner.py) — `load_tone_profile`,
  `save_approved_email`, `update_tone_profile` now route through DB.
- [`scheduler.py`](scheduler.py) — watchlist load via
  `database.get_watchlist()`; per-report `save_research_report()`;
  pipeline run logged via `log_pipeline_run()`; discovered leads
  upserted as prospects.
- [`lead_discovery.py`](lead_discovery.py) — `approve_lead` /
  `dismiss_lead` / dedupe paths backed by Supabase, local JSON kept
  as offline mirror.
- [`pages/3_draft_review.py`](pages/3_draft_review.py) — contact-edit
  upserts to `prospects`; sends log to `sent_emails`.
- [`pages/5_morning_research.py`](pages/5_morning_research.py) —
  `_load_reports()` reads `get_most_recent_reports()` first, falls back
  to the local `morning_run_*.json` bundle.
- [`pages/6_sent_tracker.py`](pages/6_sent_tracker.py) — primary feed is
  `database.get_sent_emails()`, Sheets remains the fallback.

**Config**
- [`requirements.txt`](requirements.txt) — `supabase>=2.3.0` added.
- [`.env`](.env) / [`.env.example`](.env.example) — `SUPABASE_URL`,
  `SUPABASE_ANON_KEY`.

### State right now

```
users:               1
prospects:           3   (Oscar Health, Ramp, Notion Labs)
tone_profiles:       1   (sign_off "Best, Michael", ~90 word target)
approved_emails:    28   (duplicated by repeated migration runs)
research_reports:    *   (populated nightly + on Run-Now)
sent_emails:         *   (every Send-Now and Gmail-sync row)
pipeline_runs:       *   (one row per pipeline invocation)
```

### Known gaps

- **Row-Level Security is disabled.** Multi-tenant lockdown deferred to
  Phase 2.5 — see "RLS plan" below.
- **`approved_emails` lacks a natural unique key.** Re-running
  `migrate_json_to_db.py` duplicates rows. Cleanup SQL:
  ```sql
  delete from approved_emails
  where id not in (
    select min(id::text)::uuid from approved_emails group by subject, body
  );
  ```
- **`research_reports` doesn't yet store firmographic fields** (headcount,
  industry, open_roles, ats, linkedin_url). The dataclass has defaults so
  the UI renders "—" gracefully, but to surface those numbers from DB
  they'd need to be added to the schema + writer.

---

## 4. Phase 2 — Google OAuth login (✅ complete)

Goal: replace any prior local-token / password auth with "Sign in with
Google", store tokens in Supabase so the scheduler can run unattended, and
gate access by email whitelist.

### Architecture

Two processes run alongside each other:

```
┌────────────────────┐     ┌────────────────────┐
│  Streamlit UI      │     │  FastAPI sidecar   │
│  port 8501         │     │  port 8000         │
│                    │     │                    │
│  page_shell() ───► │     │  /oauth/login      │──► Google consent
│   require_login()  │     │  /oauth/callback   │◄── code exchange
│        │           │     │  /health           │
│        ▼           │     │  /telegram/webhook │   (Phase-4 stub)
│  Login page ─link──┼────►│                    │
│                    │     │                    │
│  Sidebar           │     │                    │
│   ↳ Sign out       │     │                    │
└─────────┬──────────┘     └─────────┬──────────┘
          │                          │
          └──────────► Supabase ◄────┘
                      users / sessions
```

Flow:
1. Unauthenticated user hits any page → `page_shell()` calls
   `require_login()` → renders the dark login page with a "Sign in with
   Google" anchor pointing at `FASTAPI_URL/oauth/login`.
2. FastAPI redirects to Google's consent screen with the right scopes
   (Gmail compose/read/send, Sheets, Calendar, openid/email/profile),
   `access_type=offline`, `prompt=consent` to force a refresh_token, and
   an auto-generated PKCE code_verifier.
3. Google redirects back to `/oauth/callback` with `code` + `state`.
   FastAPI:
   - Pops the PKCE verifier from the in-memory `_PKCE_STORE[state]`
   - Exchanges the code for tokens
   - Calls Google's userinfo endpoint for email + name
   - Checks the email against `ALLOWED_EMAILS` whitelist
   - Upserts the user row in `users` and writes/refreshes `google_token`
     (JSONB)
   - Creates a 30-day row in `sessions` with a `secrets.token_urlsafe(32)`
     session token
   - Redirects to `STREAMLIT_URL/?session=<token>`
4. Streamlit picks up `?session=` from query params, validates against
   `sessions`, caches the user dict in `st.session_state["current_user"]`.
   Subsequent renders inside the same browser tab don't re-query Supabase.
5. The sidebar shows "Signed in as <FirstName>" and a Sign out button
   that deletes the session row and clears state.

### Token use by background work

The scheduler (and any non-UI code path) doesn't have a Streamlit session.
It calls `google_auth_loader.load_user_credentials_from_db()`, which:
- Reads the first user's `google_token` JSONB from `users`
- Rehydrates a `google.oauth2.Credentials` object
- Refreshes silently if expired (via the stored `refresh_token`) and
  persists the new access token back to Supabase

All four Google API helpers — `gmail_drafts.authenticate_gmail`,
`google_sheets.authenticate_sheets`, `google_calendar.authenticate_calendar`,
`google_docs.authenticate_docs` — now accept an optional `credentials`
parameter. When omitted (scheduler path), they call the loader.

### What landed

**New files**
- [`oauth_server.py`](oauth_server.py) — FastAPI app with routes:
  - `GET /oauth/login` — redirect to Google
  - `GET /oauth/callback` — exchange + persist + redirect
  - `GET /health` — JSON `{status, ts, database}`, used by UptimeRobot
  - `POST /telegram/webhook` — Phase-4 stub (returns `{ok: true}`)
- [`session_manager.py`](session_manager.py) — `require_login()`,
  `get_google_credentials(user)`, `logout()`, plus the dark login page.
- [`google_auth_loader.py`](google_auth_loader.py) — Streamlit-free
  helper used by all Google API modules to source credentials from
  Supabase in non-UI contexts.
- [`Procfile`](Procfile) — three processes: `web` (streamlit), `api`
  (uvicorn), `worker` (scheduler).
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — Google Cloud Console setup steps
  + production deploy notes.

**Modified**
- `gmail_drafts.py`, `google_sheets.py`, `google_calendar.py`,
  `google_docs.py` — `authenticate_*` accepts optional `credentials`;
  local-token file paths removed; scheduler falls back to Supabase via
  the shared loader.
- [`ui_components.py`](ui_components.py) — `page_shell()` calls
  `require_login()` before rendering anything; sidebar shows greeting at
  the top and Sign out at the bottom.
- [`requirements.txt`](requirements.txt) — added `fastapi`, `uvicorn`,
  `httpx`, `python-jose[cryptography]`, `google-auth-oauthlib`.
- `.env` / `.env.example` — `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  `GOOGLE_REDIRECT_URI`, `FASTAPI_URL`, `STREAMLIT_URL`, `ALLOWED_EMAILS`.

### Gotchas that ate time during Phase 2

| Symptom | Cause | Fix |
|---|---|---|
| `Invalid Origin: URIs must not contain a path` | Pasted the redirect URI into the "JavaScript origins" field on Google Cloud Console | Leave JavaScript origins empty; put the full URL only in "Authorised redirect URIs" |
| `address already in use` on port 8000 | Another process was bound to 8000 | `lsof -ti:8000 \| xargs kill -9` |
| Raw CSS dumped onto the login page | `_show_login_page()` was re-injecting `DARK_THEME_CSS` via `st.markdown` after `page_shell` had already injected it via `st.html()`; markdown preprocessor mangles `:hover` / `:nth-child` etc. | Removed the redundant injection in `session_manager._show_login_page` |
| `(invalid_grant) Missing code verifier` on token exchange | `google-auth-oauthlib >= 1.2.0` auto-generates a PKCE verifier in `/oauth/login` but a fresh `Flow` instance was being built for `/oauth/callback` with no memory of it | Added `_PKCE_STORE: dict` keyed by OAuth `state`; round-tripped the verifier between the two endpoints |
| Couldn't get Google token (SSL EOF) | Transient — one-off `SSLEOFError` from `oauth2.googleapis.com` | None needed; second attempt succeeded |

### State right now

```
users table:    1 row    — RAHUL DIXIT / dixit.rahul1301@gmail.com
                          last_login 2026-05-28T07:34:53+00:00
                          google_token has refresh_token ✓
sessions:       1 row    — expires 2026-06-27
allowed list:   1 email  — dixit.rahul1301@gmail.com
```

`google_auth_loader.load_user_credentials_from_db(...)` returns a valid
`Credentials` object — confirmed that the scheduler can run unattended.

---

## 5. Phase 3 — HuggingFace model hardening (✅ complete)

Goal: make the morning pipeline never crash on an HF outage. Retry +
backoff every call, cache zero-shot results so the same text/labels are
never re-scored, fall back to a template draft when the writer is down,
ping both models 10 minutes before the cron fires, and wrap the cron job
itself so a crash logs to Supabase + emails the broker instead of dying
silently.

### What landed

**New**
- [`hf_client.py`](hf_client.py) — resilient wrapper around HF Inference.
  Public surface:
    * `classify_zero_shot(text, candidate_labels, fallback_scores=None)`
      — 3 retries with 2s/4s/8s backoff, 30s timeout, Supabase score
      cache via `make_cache_key`/`get_cached_score`/`save_cached_score`,
      equal-distribution fallback when all retries fail
    * `generate_text(prompt, model, max_new_tokens, temperature,
      fallback_text)` — same retry shape, returns `fallback_text` on
      failure
    * `warm_up_models()` — pings scorer + writer, returns
      `{"scorer": bool, "writer": bool}`
  Implemented with `requests` rather than `huggingface_hub`'s
  `InferenceClient` because the 0.23.2 client defaults to the deprecated
  `api-inference.huggingface.co` host and rejects the router payload.
- [`monitoring.py`](monitoring.py) — `send_alert(subject, body)` over
  `SMTP_SSL` (silent no-op when GMAIL_SENDER / GMAIL_APP_PASSWORD /
  ALERT_EMAIL not set) + `alert_pipeline_failed(error, run_date)`.

**Modified**
- [`research_agent.py`](research_agent.py) — `_classify` swapped from
  ~75 lines of inline `requests` + retry to one
  `hf_client.classify_zero_shot` call; signal-construction logic
  untouched.
- [`hf_models/writer.py`](hf_models/writer.py) — `_call_hf_api`
  delegated to `hf_client.generate_text`; new
  `_build_fallback_draft(prospect_name, top_hook, sign_off)` at the
  bottom of the file for the deepest-fallback case.
- [`scheduler.py`](scheduler.py) —
    * `run_morning_pipeline_safe()` wraps the raw pipeline (catches every
      exception, logs `pipeline_runs` row, sends alert email)
    * `_run_warmup()` fires at 4:50am and alerts if either model is
      unreachable
    * both blocking + background schedulers register the new warm-up job
    * `--once` uses the safe wrapper

### Mistral retirement + Llama swap

Mid-2025, HF narrowed the free `hf-inference` provider to CPU / legacy
models only (BERT, GPT-2, embeddings, text-classification — which is why
`facebook/bart-large-mnli` still works there). Every text-generation
model — Mistral-7B-Instruct-v0.2, Mistral-7B-Instruct-v0.3, Llama,
Qwen, Gemma, Zephyr, Phi — returns
`{"error":"Model not supported by provider hf-inference"}` from the old
`/hf-inference/models/{model}` URL.

The router's OpenAI-compatible `/v1/chat/completions` endpoint auto-picks
a paid provider (Together, Fireworks, etc), drawing from the **$0.10/mo
free credits** per free HF account ($2.00/mo on PRO). So the swap was:

- `config.WRITING_MODEL` → `meta-llama/Llama-3.1-8B-Instruct`
- `config.HF_CHAT_URL`  → `https://router.huggingface.co/v1/chat/completions`
- `hf_client.generate_text` now POSTs OpenAI-style chat completions
  (`{"model": ..., "messages": [{"role": "user", "content": prompt}]}`)
  and reads `choices[0].message.content`
- Legacy Mistral `[INST]/[/INST]/<s>/</s>` markers are stripped inside
  `generate_text` so the existing prompt builders in `writer.py` and
  `scheduler._generate_draft` need no edits

### State right now

```
hf_client.classify_zero_shot     working  — bart-mnli on hf-inference
hf_client.generate_text          working  — Llama-3.1-8B via /v1/chat/completions
score_cache                      populated — cache hit ~0.4s on repeats
pipeline_runs                    logging  — every safe-wrapper run inserts a row
Phase-3 template fallback        wired    — fires when generate_text returns ""
```

### Known gaps

- **`$0.10/mo free credits exhaust in ~3-5 days** at 20 prospects/day × 2
  calls. After that the writer returns `""` and the template fallback
  takes over — every prospect still gets a Gmail draft, just less
  personalised. Options: HF PRO ($9/mo → $2 credits), pay-as-you-go
  topup, or swap to a self-hosted writer.
- **Llama doesn't always emit `Subject:` on line 1**, so `_parse_email`
  occasionally returns the default subject "Quick thought on your NYC
  expansion". Body is real Llama output. A tighter instruction in
  `writer._build_email_prompt` + `scheduler._generate_draft` would fix
  it — small change, deferred.

---

## 6. Phase 4 — Telegram bot (✅ complete)

Goal: push the daily research summary to the broker's phone after the
5am pipeline runs, mirror pipeline + warm-up failure alerts there too,
and expose a one-tap connect banner on the research page. Webhook is
ready; polling is the local-dev mirror.

### What landed

**New**
- [`telegram_bot.py`](telegram_bot.py) — fire-and-forget wrapper around
  the Telegram Bot API using plain `requests` (no `python-telegram-bot`
  dep). Public surface:
    * `send_message(chat_id, text)` — never raises
    * `broadcast(text)` — fan-out to every connected user
    * `send_morning_brief(chat_id, reports)` — formatted hot/warm/skipped
      card with hot-lead hooks and dashboard deep-link
    * `send_reply_notification(chat_id, ...)` — exposed for the future
      Gmail reply-watcher (not wired yet)
    * `send_pipeline_failed_alert` / `send_warmup_failed_alert`
    * `get_connect_url(user_id)` — `t.me/<bot>?start=<uuid>` deep link
    * `run_polling()` / `_handle_update()` — local-dev mirror of the
      webhook; writes `telegram_chat_id` + `telegram_connected=true` on
      `/start <uuid>`

**Modified**
- [`oauth_server.py`](oauth_server.py) — replaced the Phase-3 stub
  `/telegram/webhook` with the real handler. Parses `/start <user_id>`,
  upserts `users.telegram_*`, sends the "Connected" confirmation via
  `telegram_bot.send_message`.
- [`pages/5_morning_research.py`](pages/5_morning_research.py) — dark
  connect banner immediately below `page_shell()`. Hidden once
  `telegram_connected=true`; uses the user's Supabase UUID for the deep
  link.
- [`scheduler.py`](scheduler.py) — three Telegram hooks, each in its
  own `try/except` so a Telegram outage cannot crash the pipeline:
    * `run_morning_pipeline_safe` success branch loads the just-persisted
      reports via `get_most_recent_reports` and pushes a morning brief
      to every connected user
    * exception branch mirrors `alert_pipeline_failed` via Telegram
    * `_run_warmup` mirrors the warm-up failure email via Telegram

**Config**
- [`.env.example`](.env.example) — `TELEGRAM_BOT_TOKEN` +
  `TELEGRAM_BOT_USERNAME`.
- [`setup_database.sql`](setup_database.sql) already has
  `users.telegram_chat_id text` and `users.telegram_connected boolean
  default false` — confirmed at Phase 1.
- [`database.py`](database.py) already has `get_all_telegram_users()` —
  also from Phase 1.

### State right now

```
@Grey_CreBot                live (bot id 8788815105)
users.telegram_connected    true  for dixit.rahul1301@gmail.com
users.telegram_chat_id      6042841719
local polling               works — /start <uuid> captured, DB updated
production webhook          route live at /telegram/webhook, awaiting
                            setWebhook registration after Phase-5 deploy
```

### Known gaps

- **No webhook registration yet.** `setWebhook` against the public host
  is part of Phase 5. Polling is fine for laptop use; not for
  production.
- **Brief fires on every clean run**, including `no_actionable` days
  where the watchlist returned no qualifying signals. Gating on
  `summary["status"] == "success"` or `summary["actionable"] > 0` would
  trim noise. 2-line change, deferred.
- **Reply notifications are exposed but not wired.**
  `send_reply_notification` is ready; the Gmail reply-watcher that
  would call it isn't built yet.

---

## 7. How to run locally

```bash
# One-time
cp .env.example .env                  # fill in keys
pip install -r requirements.txt
# Paste setup_database.sql into Supabase SQL editor (run once, no RLS)
python migrate_json_to_db.py          # only once — see "Known gaps"

# Every dev session — two terminals
# Terminal 1
source venv/bin/activate
uvicorn oauth_server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2
source venv/bin/activate
python -m streamlit run app.py
```

Open http://localhost:8501 → Sign in with Google.

Scheduler one-off (for debugging the morning pipeline outside its cron
slot):

```bash
python scheduler.py --once
```

Telegram polling (local-dev only — production uses the webhook):

```bash
python -c "from telegram_bot import run_polling; run_polling()"
```

## 8. Phase 5 — LinkedIn signal scrapers + scoring tune (✅ complete)

Goal: surface real hiring signals from LinkedIn job postings even when
the news scrapers come back near-empty, and stop the scorer collapsing
to the `_mock_fallback` score of 20 for mid-tier health-tech prospects.
Commit: `a7db245`.

### What landed

**New**
- [`scrapers/linkedin_jobs.py`](scrapers/linkedin_jobs.py) — guest-API
  scrape of LinkedIn job search. Endpoint is
  `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search`
  (the public `/jobs/search/` page is auth-walled). Each call respects
  a **30s global rate limit** via module-level `_last_request_time`.
  On empty result the public `scrape_linkedin_jobs()` retries once after
  a `random.uniform(45, 90)` cooldown with a fresh random UA. Per-job
  flags: `is_office_signal` / `is_office_role` (kept under both names
  so the existing `_build_signal_from_label` path in `research_agent`
  picks it up) + `is_growth_signal`. Single-source-of-truth label
  constant `SOURCE_LABEL = "LinkedIn Jobs · last 7 days"` exposed for
  every signal-construction site in `research_agent`.
- [`scrapers/linkedin_google.py`](scrapers/linkedin_google.py) —
  zero-ban-risk LinkedIn snapshot via Google SERP scrape of
  `<company> site:linkedin.com/company`. Extracts follower / employee
  count text from the snippet via three regexes. Used as enrichment,
  not as a primary signal source.

**Modified**
- [`scheduler.py`](scheduler.py):
  - `_gather_signals` now calls `scrape_linkedin_jobs(company, city)`
    and `get_linkedin_snapshot(company)` after the news + Firecrawl
    scrapes; results land in `bundle["jobs"]` and
    `bundle["linkedin_snapshot"]`. The existing `_clean_web_text` +
    URL-dedup logic for the article list is preserved.
  - `run_morning_pipeline` switched from
    `ThreadPoolExecutor(max_workers=4)` to a **sequential for-loop**
    because LinkedIn's 30s rate limit is enforced as a global module
    variable inside `linkedin_jobs.py` — parallel calls would just
    serialise behind the limiter and risk concurrent mutation of
    `_last_request_time`.
- [`research_agent.py`](research_agent.py):
  - `generate_report` now appends a deterministic LinkedIn signal
    after the bart-mnli label loop, replacing any weaker LinkedIn
    signal the existing hiring-label path produced. Scoring:
    `office_signal_count >= 2 → 90`, `>= 1 → 75`,
    `total_jobs >= 3 → 55`. Dedup is by case-insensitive `linkedin`
    substring match on `Signal.source`.
  - All 4 sites that previously set `source="LinkedIn Jobs"` now import
    `SOURCE_LABEL` from `scrapers.linkedin_jobs`.
- [`database.py`](database.py): `save_research_report` switched from
  `insert()` to `upsert(row, on_conflict="run_date,prospect_id")` so a
  re-run no longer duplicates rows. Requires the matching unique
  constraint on `research_reports (run_date, prospect_id)` — run once
  via the dedup SQL in commit message.
- [`config.py`](config.py): `RESEARCH_SKIP_BELOW` lowered `30 → 15` so
  warm leads surface while the watchlist is small.
- [`data/watchlist.json`](data/watchlist.json): replaced the original
  3-company seed (Oscar Health / Ramp / Notion Labs) with **five
  health-tech NYC entries**: Northwell Health, CityMD, Ro, Cityblock,
  Quartet Health. Quartet was flipped `active=false` after the rename
  diagnostic showed it produces no real signal (small company, low
  press, no LinkedIn job velocity). Important: company names were
  iteratively trimmed to canonical forms ("Northwell Health Ventures"
  → "Northwell Health", "Cityblock Health" → "Cityblock", "Ro Health"
  → "Ro") so the news scrapers and LinkedIn search match the way the
  press actually indexes them.
- [`requirements.txt`](requirements.txt): added `beautifulsoup4` +
  `lxml` for the LinkedIn HTML parse.

### State right now

```
LinkedIn jobs scraper      working — ~50-70% success rate per call;
                                     retry-with-jitter lifts to ~85%
Sequential pipeline        ~4 active prospects × 30-90s LinkedIn budget
                           ≈ 3-7 min total wall clock per run
LinkedIn signal score      0/55/75/90 deterministic; replaces weak
                           bart-mnli score where present
Watchlist                  4 active (Northwell Health, CityMD, Ro,
                           Cityblock) + 1 inactive (Quartet Health)
Score floor                15 (was 30); warm-tier visible again
```

### Known gaps

- **LinkedIn intermittency is real.** 200 OK with empty body is the
  silent rate-limit signature. Retry helps but doesn't eliminate.
  Cushwake doesn't surface in the morning brief on a bad day. No
  in-pipeline metric tracks per-prospect LinkedIn success rate yet.
- **Firecrawl 402** (free credits exhausted) was observed during the
  scoring diagnostic. Pipeline handles it gracefully — the cleaned web
  text just contributes nothing — but the per-prospect signal density
  drops noticeably when Firecrawl is offline.
- **`AGENT_TITLE` was unused in the writer prompts** until Phase 6 —
  zero-shot Llama was told to act as "a senior tenant representation
  broker" regardless of the env value. Pre-Phase-6 drafts therefore
  carry the wrong title; existing rows in `research_reports.draft`
  must be regenerated to pick up the new identity.

---

## 9. Phase 6 — Broker-email fan-out + per-broker identity (✅ complete)

Goal: support multiple morning-digest recipients without per-broker
config rewrites, and make sure every prompt and signature actually
reflects the broker's real identity (name, title, firm) instead of
the demo placeholder. Commits: `ceefad5`, `439637c`.

### Fan-out — what landed

**New env vars**
- `BROKER_EMAILS` — comma-separated list. Every address gets the
  morning digest. Defaults to `[BROKER_EMAIL]` when only the singular
  is set (back-compat for older deploys).
- `ALERT_EMAILS` — comma-separated list for failure / warm-up alerts.
  Fallback chain on resolution:
  `ALERT_EMAILS → ALERT_EMAIL → BROKER_EMAILS → BROKER_EMAIL`.

**Code**
- [`config.py`](config.py): exposes `BROKER_EMAILS: list[str]`.
- [`monitoring.py`](monitoring.py): `ALERT_EMAILS` list; SMTP `sendmail`
  sends to every address in one session (single auth pair — Gmail
  protocol limit).
- [`scheduler.py`](scheduler.py): `run_morning_pipeline` loops
  `send_morning_digest` over `BROKER_EMAILS` with isolated try/except
  per recipient — one bad address can't kill the rest. `broker_self`
  filter (the "don't draft to the broker's own address" guard) widened
  to include the full list.
- [`check_env.py`](check_env.py): treats `BROKER_EMAIL` /
  `BROKER_EMAILS` as either-or required; reports which one is in use.

### Identity prompt fix — what landed

- [`config.py`](config.py): `EMAIL_SYSTEM_PROMPT` and
  `LINKEDIN_SYSTEM_PROMPT` previously hardcoded "a senior tenant
  representation broker" / "a senior tenant rep broker" — `AGENT_TITLE`
  was defined but never threaded into the prompt. Now both open with
  `"You are {AGENT_NAME}, {AGENT_TITLE} at {FIRM_NAME}."` Sign-off
  block expanded from two lines to three (name / title / firm).
- Fallback signatures at four sites — [`scheduler.py:327`](scheduler.py)
  + [`hf_models/writer.py:142,521,561`](hf_models/writer.py) — all
  carry `AGENT_TITLE` between name and firm.

### State right now (after Grey is set as the client)

```
AGENT_NAME    = Grey McCarthy
AGENT_TITLE   = Director, Tenant Advisory Group
FIRM_NAME     = Cushman & Wakefield
AGENT_EMAIL   = Grey.Mccarthy@cushwake.com
BROKER_EMAIL  = Grey.Mccarthy@cushwake.com   (legacy singular)
BROKER_EMAILS = dixit + soham + grey         (digest fan-out)
ALERT_EMAILS  = dixit + soham + grey         (failure alerts)
ALLOWED_EMAILS = dixit + soham + grey        (sign-in whitelist)
GMAIL_SENDER  = dixit.rahul1301@gmail.com    (operator SMTP — single
                                              auth pair, by design)
```

### Known gaps

- **Existing rows in `research_reports.draft` are stale.** Every draft
  written before commit `439637c` says "Michael Hartley, Hartley CRE
  Partners" because the demo defaults baked into the cached draft text.
  Force-regenerate via `python scheduler.py --once` after Railway env
  is correct, or `DELETE FROM research_reports WHERE run_date =
  CURRENT_DATE;` then re-run.
- **Per-broker data isolation still missing.** Multi-broker = Phase 4.5
  RLS work. Today every signed-in user sees every watchlist row.
- **`AGENT_NAME` / `AGENT_TITLE` / `FIRM_NAME` / `AGENT_EMAIL` not yet
  mirrored to Railway env vars.** Local `.env` is correct; until
  Railway is updated and services redeploy, production drafts still
  say Michael Hartley.

---

## 10. Phase 7 — Railway production deployment (✅ infra live, sign-in pending)

Goal: get the three-process app onto Railway with all env wired,
custom domains assigned, OAuth callback registered, and Telegram
webhook live. Commit chain: `560fdfa` (Phase 5 config), `620ef7c`
(untracked `data/*.json`), production deploy steps were manual on
Railway dashboard.

### Architecture in production

```
┌─────────────────────────────┐   ┌─────────────────────────────┐
│  web  (Streamlit)           │   │  api  (FastAPI sidecar)     │
│  web-production-a655b       │   │  api-production-7962b       │
│  $PORT bound by Railway     │   │  $API_PORT bound (8000)     │
└──────────────┬──────────────┘   └──────────────┬──────────────┘
               │                                 │
               └───────► Supabase ◄──────────────┘
                          (separate project)
                                 ▲
                                 │
                       ┌─────────┴─────────┐
                       │  worker (cron)    │
                       │  no public URL    │
                       │  $START_SCHEDULER │
                       └───────────────────┘
```

### What landed

**Deploy config** (committed in `560fdfa`)
- [`Procfile`](Procfile) — `web` / `api` / `worker` declarations with
  Railway-friendly flags (`streamlit --server.headless=true
  --server.enableCORS=false --server.enableXsrfProtection=false` so
  Railway's proxy doesn't trip XSRF; `uvicorn ... --port ${API_PORT:-8000}`
  so the api service is rebindable from env).
- [`railway.toml`](railway.toml) — nixpacks builder, `on_failure`
  restart with max 3 retries.
- [`runtime.txt`](runtime.txt) — `python-3.11.9` pin (matches dev venv).
- [`requirements.txt`](requirements.txt) — `pip freeze` of 115 pinned
  entries for reproducible Railway builds.
- [`.gitignore`](.gitignore) — broadened to `data/*.json` with
  `!data/.gitkeep` escape so `data/` survives a fresh clone but its
  JSON contents stay out of git.
- [`data/.gitkeep`](data/.gitkeep) — pinhole file.
- [`check_env.py`](check_env.py) — pre-deploy guard; exits non-zero
  if any required env var is missing.
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — step-by-step Railway walkthrough.

**Untrack of `data/*.json`** (committed in `620ef7c`)
- `git rm --cached data/watchlist.json data/tone_profile.json
  data/dismissed_leads.json data/tone_preferences.json`. Supabase is
  the authoritative store; the JSONs were just creating noise in
  `git status` on every local migration.

### State right now

```
web service       ONLINE      web-production-a655b.up.railway.app
api service       ONLINE      api-production-7962b.up.railway.app
worker service    ONLINE      no public URL
api /health       200 OK      {"status":"ok","database":"connected"}
streamlit boot    200 OK      ~890ms first byte
Telegram webhook  NOT YET     setWebhook curl pending
Google redirect   FIXED       api now sends Railway callback URL
                              ↳ added to Google Cloud Console too
```

### What's outstanding before sign-off

1. **Mirror Grey's identity vars on all 3 Railway services**
   (`AGENT_NAME`, `AGENT_TITLE`, `FIRM_NAME`, `AGENT_EMAIL`). Until
   then drafts in production keep saying Michael Hartley.
2. **Regenerate the stale `research_reports.draft` rows.** Either
   `DELETE FROM research_reports WHERE run_date = CURRENT_DATE;` then
   trigger a Run-Pipeline, or wait for the next 05:00 ET cron.
3. **Register the Telegram webhook** against the production api:
   ```bash
   curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
        -d "url=https://api-production-7962b.up.railway.app/telegram/webhook"
   curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"
   ```
4. **Soham + Grey first sign-in** — both need adding as **Test users**
   on Google OAuth consent screen (Soham works fine; Grey blocked
   because `Grey.Mccarthy@cushwake.com` is a Microsoft 365 account
   and Google rejects it as a Test user — needs a personal Gmail).
5. **UptimeRobot** on `/health` so the worker container stays warm
   between cron firings.

### Gotchas surfaced during the Railway deploy

| Symptom | Cause | Fix |
|---|---|---|
| Safari can't connect to `localhost:8000/oauth/login` | `FASTAPI_URL` env var unset on the **web** service — the "Sign in" link built from default `http://localhost:8000` | Set `FASTAPI_URL=https://api-production-7962b.up.railway.app` on web service |
| Safari can't connect to `localhost:8000/oauth/callback` after Google consent | `GOOGLE_REDIRECT_URI` env var unset on the **api** service — `/oauth/login` sent `redirect_uri=localhost:8000` to Google | Set `GOOGLE_REDIRECT_URI=https://api-production-7962b.up.railway.app/oauth/callback` on api service |
| `redirect_uri_mismatch` from Google | Production callback URL not registered in OAuth client | Add the Railway URL to **Authorised redirect URIs** in Google Cloud Console (leave localhost in too for local dev) |
| "Email addresses must be associated with an active Google Account" when adding Grey as Test user | `Grey.Mccarthy@cushwake.com` is Microsoft 365 (C&W) — not a Google identity | Grey signs in with a personal Gmail instead; signature still reads "Cushman & Wakefield" |
| Draft in dashboard says "Michael Hartley, Hartley CRE Partners" | `AGENT_NAME` / `AGENT_TITLE` / `FIRM_NAME` not set on Railway → falls back to `config.py` defaults | Mirror the four identity env vars on all 3 services, then regenerate the draft row |
| Streamlit "JavaScript origins" field error in Google Cloud Console | Pasting the full callback URL in the origins field (origins must be host-only) | Leave JavaScript origins empty — origins aren't used by the server-side OAuth code flow |

---

## 11. Debugging notes — quick reference for future-me

### Where to look first

| Symptom | First thing to check |
|---|---|
| Pipeline crashed at 05:00 ET | `pipeline_runs` table — `error` column, `status='failed'` row for today |
| Pipeline ran but no drafts in Gmail | `BROKER_EMAILS` populated? Gmail service auth succeed? `data/error_log.json` `scope=scheduler.gmail_auth` or `scope=scheduler.digest[*]` |
| Telegram brief missing on phone | `users.telegram_connected=true`? Webhook URL set? Test with `curl .../getWebhookInfo` |
| Every prospect scoring exactly 20 | `_mock_fallback` fingerprint — scrapers + bart-mnli both empty. `data/error_log.json` `scope=scheduler.no_articles` rows tell you which prospect |
| Draft signature says Michael Hartley | Either (a) draft row is stale from before commit `439637c`, or (b) Railway env vars missing `AGENT_NAME` / `AGENT_TITLE` / `FIRM_NAME` |
| LinkedIn 0 jobs across the board | Either (a) the global rate limiter is still cooling from a prior run, or (b) LinkedIn's silent rate limit hit your IP. Check error_log for `scope=linkedin_jobs.scrape`. Retry-with-jitter usually recovers on the next cron firing |
| `redirect_uri_mismatch` on sign-in | (a) `GOOGLE_REDIRECT_URI` on api service value vs (b) Google Cloud Console "Authorised redirect URIs" — these two must match character-for-character |
| Streamlit cold-start ~20s on first request | Normal; Railway suspends idle containers. UptimeRobot ping every 5min on `/health` prevents this |

### Useful one-liners

```bash
# Force-regenerate today's drafts (after identity / prompt change)
python -c "from database import _db; from datetime import date;
db=_db(); db.table('research_reports').delete().eq('run_date',
date.today().isoformat()).execute()"
python scheduler.py --once

# Inspect what redirect_uri the api is currently sending Google
curl -s -o /dev/null -D - "$FASTAPI_URL/oauth/login" | grep -i location

# Health check + DB connectivity
curl -s "$FASTAPI_URL/health"

# Telegram webhook status
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getWebhookInfo"

# All today's reports + LinkedIn signal count per prospect
python -c "
from database import get_most_recent_reports
for r in get_most_recent_reports():
    li = [s for s in (r['signals'] or [])
          if 'linkedin' in (s.get('source','') or '').lower()]
    print(f\"{r['company']:24} score={r['composite_score']:3}\"
          f\" tier={r['tier']:7} linkedin={len(li)}\")"
```

### Files where the demo placeholders still live (for forensic edits)

- `config.py` lines ~39-43: `AGENT_NAME`, `AGENT_TITLE`, `FIRM_NAME`,
  `AGENT_PHONE`, `AGENT_EMAIL` defaults. Any env not set on Railway
  falls back to these.
- Prompts that reference identity: `EMAIL_SYSTEM_PROMPT`,
  `LINKEDIN_SYSTEM_PROMPT`, `FOLLOWUP_SYSTEM_PROMPT` in
  [`config.py`](config.py).
- Fallback signature sites: `scheduler.py` `_generate_draft` template
  path; `hf_models/writer.py` `generate`, `_fallback_email`,
  `_fallback_linkedin`.

---

## 12. Phase 8 — Per-user Google action routing (✅ complete)

**Why this phase existed.** Phase 2 stood up the OAuth flow correctly
(token-per-user in `users.google_token`), but every UI page called
`authenticate_gmail()` / `authenticate_sheets()` / `authenticate_calendar()`
*without* passing the logged-in user's credentials. With no `credentials=`
argument, those helpers fell through to `google_auth_loader.load_user_credentials_from_db`,
which did `db.table("users").select("...").limit(1).execute()` — i.e. they
always grabbed whichever user happened to be row 1 (the primary broker).
Net result: when a second broker signed in on the web, every draft they
created, every Send-now they fired, every research doc they generated,
every follow-up event they triggered, every sheet row they appended landed
in the *primary broker's* Google account — not theirs.

The same shape of bug also lived in the **Send-now** SMTP path: it
authenticated via `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` (single
env-var pair = the primary broker's app password), so even after fixing
the OAuth fallthrough, every web user's sends would still leave from
the primary mailbox.

### What landed

**Credential plumbing — every helper now takes per-user creds.**
- [`google_auth_loader.py`](google_auth_loader.py) — `load_user_credentials_from_db(default_scopes, user_id=None)`.
  Resolution order is **explicit `user_id` → `PRIMARY_USER_ID` env →
  `PRIMARY_BROKER_EMAIL`/`BROKER_EMAIL` env (matched against `users.google_email`)
  → row-1 fallback**. The row-1 fallback is preserved so the cron keeps
  working when no user is logged in, but the UI now never reaches it.
- [`gmail_drafts.py`](gmail_drafts.py),
  [`google_sheets.py`](google_sheets.py),
  [`google_calendar.py`](google_calendar.py),
  [`google_docs.py`](google_docs.py) — every `authenticate_*` signature is
  now `(credentials=None, user_id=None)`. When `credentials` is passed in
  (UI path), it's used as-is. When omitted (scheduler / cron path), the
  loader resolves `user_id` or falls back to the env pin.
- [`google_docs.create_research_doc`](google_docs.py) — also accepts
  `credentials=` and `user_id=` so the on-demand "Generate research doc"
  button on page 5 lands the dossier in the *signed-in* user's Drive.

**Pages now pass the logged-in user's creds.**
Each page reads `_creds = get_google_credentials(_user)` once at the top
(where `_user = st.session_state.get("current_user")`), and passes
`credentials=_creds` to every `authenticate_*` call:
- [`pages/3_draft_review.py`](pages/3_draft_review.py) — Gmail draft + Send-now
  + Sheets log + Calendar follow-up + auto-rename of contact.
- [`pages/5_morning_research.py`](pages/5_morning_research.py) — sent-today
  lookup + on-demand research-doc generator.
- [`pages/6_sent_tracker.py`](pages/6_sent_tracker.py) — sent feed.
- [`pages/7_followups.py`](pages/7_followups.py) — calendar list + Mark-replied.

**Send-now now uses the Gmail API, not SMTP.**
The new `gmail_drafts.send_email_now(service, to, subject, body)` posts
via `users.messages.send` with `userId="me"`, so the email leaves from
whoever is signed in. The SMTP + shared-app-password path in
[`pages/3_draft_review.py`](pages/3_draft_review.py) is gone. The
`From:` header forcing in `gmail_drafts._build_message` is also gone
(sender defaults to `"me"` — the Gmail API picks up the credential
owner). `GMAIL_APP_PASSWORD` is still used by `monitoring.py` for SMTP
failure alerts (correct — alerts always come from the ops mailbox).

**OAuth scope expansion + forced re-consent.**
`oauth_server.GOOGLE_SCOPES` and `session_manager.GOOGLE_SCOPES` both
gained `https://www.googleapis.com/auth/documents` and
`https://www.googleapis.com/auth/drive.file`. The "Generate research
doc" button was 403'ing with `ACCESS_TOKEN_SCOPE_INSUFFICIENT` because
the Docs API isn't covered by Gmail / Sheets / Calendar scopes. After
this change every existing user has to sign out + sign in again so
Google re-issues a token bound to the wider scope set — old tokens
won't silently widen.

**Per-user Google Sheets (no more shared sent-tracker).**
- New nullable `users.sheets_spreadsheet_id TEXT` column. Migration:
  ```sql
  ALTER TABLE users ADD COLUMN IF NOT EXISTS sheets_spreadsheet_id TEXT;
  ```
- New helpers in [`google_sheets.py`](google_sheets.py):
  - `get_user_sheet_id(user) -> str` — read-only lookup, used on every
    read path (sent-tracker, morning-research lookup, follow-ups Mark-replied).
  - `ensure_user_sheet(service, user, title=…)` — lazily creates a new
    spreadsheet in the signed-in user's Drive on first Send-now, renames
    the default `Sheet1` tab to `Sent Emails`, writes the header row, and
    persists the new ID to `users.sheets_spreadsheet_id` + the in-memory
    `session_state["current_user"]` so the rest of this Streamlit run
    can reuse it without an API round-trip.
- Every write path on [`pages/3_draft_review.py`](pages/3_draft_review.py)
  routes through `ensure_user_sheet`. Every read path routes through
  `get_user_sheet_id` (returns `""` for users who haven't sent yet — those
  pages show an empty state rather than paying the cost of creating a
  sheet they may never write to).
- The scheduler / `gmail_sync` keeps using `config.SHEETS_SPREADSHEET_ID`
  — the cron is single-tenant by design (runs as the env-pinned primary
  broker), and that env-var sheet is the master broker log.

**Gated on credentials instead of a local file.**
Page guards used to read `if os.path.exists(config.GOOGLE_CREDENTIALS_PATH):`
which was only ever true on the developer's laptop (the file is gitignored).
On Railway and for every web user other than the dev, the guard was
silently False — Calendar follow-ups never fired, Sheets logging never
ran, the sent-tracker and follow-ups pages showed "Drop credentials.json"
empty states even though OAuth creds were perfectly valid in Supabase.
Every gate now checks `_creds is not None` instead.

**Dashboard quick-links toolbar + research-doc button promotion.**
- [`pages/5_morning_research.py`](pages/5_morning_research.py) gained a
  three-button toolbar immediately under the morning-brief header:
  **📅 Calendar follow-ups · 📄 Research docs · Google Docs · 📊 Sent tracker · Sheet**.
  Each opens in a new tab and is colour-accented (cobalt / gold / sage).
  The Sheet button greys out until the user has sent their first email
  and `ensure_user_sheet` has assigned them an ID.
- The on-demand "Generate research doc" button now flips in-place to a
  gold-accented "Open research doc ↗" button the moment the doc exists,
  in the same slot — instead of quietly disappearing and leaving only a
  small italic chip at the top.
- [`ui_components.render_sidebar`](ui_components.py) gained a matching
  "Quick links" section with the same three deep-links — collapsed text
  style for sidebar density.

**Admin: ALLOWED_EMAILS expanded.**
The whitelist now covers four addresses (primary broker, the two ops
users, and a stakeholder). New addresses must be added to
`ALLOWED_EMAILS` on all three Railway services *and* as Test users on
the Google Cloud OAuth consent screen, otherwise Google blocks the
sign-in before the in-app whitelist check ever runs.

### New env vars (Phase 8)

| Var | Service(s) | Purpose |
|---|---|---|
| `PRIMARY_USER_ID` | worker | UUID of the broker the 5am cron acts as. Overrides everything else. |
| `PRIMARY_BROKER_EMAIL` | worker | Fallback when `PRIMARY_USER_ID` is unset — match against `users.google_email`. Falls back to `BROKER_EMAIL` if unset. |

If both are unset the worker falls back to the legacy row-1 behaviour,
which still works while there's only one user in the table.

### Required follow-ups when deploying Phase 8

1. **Run the Supabase migration** (one-time):
   ```sql
   ALTER TABLE users ADD COLUMN IF NOT EXISTS sheets_spreadsheet_id TEXT;
   ```
2. **Google Cloud Console → OAuth consent screen → Scopes → Add or remove
   scopes**: add `auth/documents` and `auth/drive.file`. Confirm Google
   Docs API and Google Drive API are both enabled under **Library**.
3. **Every user signs out + signs in again** so Google issues a token
   with the new scope set. Old tokens hit `ACCESS_TOKEN_SCOPE_INSUFFICIENT`
   the moment they touch `docs.googleapis.com`.
4. **Set `PRIMARY_BROKER_EMAIL` on the worker** so the cron's identity
   is pinned explicitly instead of relying on row-1.

### What didn't change

- The scheduler's morning pipeline is still single-tenant. Discovery,
  scoring, drafting, Drive doc creation, digest fan-out all happen
  under the env-pinned primary broker's identity. Phase 4.5 (RLS +
  user-scoped tenant tables) is still the prerequisite for the
  morning pipeline to be truly multi-tenant.
- `data/watchlist.json`, `tone_profile.json`, and every Supabase
  tenant-scoped table (`prospects`, `research_reports`, `sent_emails`,
  …) are still shared across users. Multi-tenant data isolation is
  Phase 4.5 work and not in scope for Phase 8.

---

## 13. Deferred decisions / next phases

**RLS plan (Phase 4.5, before onboarding the 2nd client).** Every
tenant-scoped table (`prospects`, `research_reports`, `sent_emails`,
`approved_emails`, `tone_profiles`, `pipeline_runs`, `dismissed_leads`,
`score_cache`) still has no `user_id` column and RLS is off. Multi-tenant
safe ordering is:
1. Add a nullable `user_id uuid references users(id)` column to every
   tenant-scoped table + an index.
2. Backfill the existing rows to the single existing user.
3. Make `user_id` NOT NULL.
4. Enable RLS on each table with `using (auth.uid() = user_id)`.
5. Switch the Streamlit DB calls to use the user's JWT instead of the
   service-role / publishable key, so `auth.uid()` is populated.

Doing it any earlier than Phase 2 would have made the app appear empty —
RLS without authentication = closed policies = nothing readable.

**Microsoft 365 sign-in path.** Grey at `@cushwake.com` cannot complete
Google OAuth because C&W runs Microsoft 365. For now the workaround is
"Grey uses a personal Gmail for sign-in; signature still says C&W."
A proper fix needs MS Graph OAuth alongside Google OAuth and Outlook
send/draft endpoints alongside the Gmail API calls. Roughly 2-3 days
of code.

**Reply-watcher.** `telegram_bot.send_reply_notification` is exposed
but unwired. A daily Gmail thread scan + reply detector would close
the loop.

**Tone-learning loop.** Weekly job mines `data/tone_archive.json`
(now in Supabase via `tone_profiles` table) to update the tone
profile based on broker edits to drafts.

**Compound-signal scoring.** Replace the linear weighted mean with a
learnt model trained on the broker's approve/skip history. Cold-start
with the current formula; switch once enough labelled examples exist.

## 9. Files you can safely delete

After Phase 2 cutover, these old local-token files in `data/` are dead
weight (the new auth never reads them):
- `data/gmail_token.json`
- `data/sheets_token.json`
- `data/calendar_token.json`
- `data/docs_token.json`

Leave them in place until you're confident nothing regresses.
