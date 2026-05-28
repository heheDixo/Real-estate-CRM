# Progress so far — CRE Outreach Intelligence

Status as of **2026-05-28**. Covers Phase 1 (database foundation),
Phase 2 (Google OAuth login), Phase 3 (HuggingFace model hardening) and
Phase 4 (Telegram bot). Phase 5 (production deployment to Railway / Fly /
Render with public webhook) is the next thing on the list.

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

## 8. Deferred decisions / next phases

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

**Phase 5 (next).** Production deployment to Railway / Fly / Render.
Procfile already declares `web` (Streamlit), `api` (uvicorn) and
`worker` (scheduler). Outstanding work:
- Pick a host and provision the three services.
- Set every env var from `.env.example` on the host (including new
  Phase-3/4 keys: `SUPABASE_*`, `GOOGLE_*`, `FASTAPI_URL`,
  `STREAMLIT_URL`, `ALLOWED_EMAILS`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_BOT_USERNAME`).
- Update Google OAuth client to add the production
  `…/oauth/callback` redirect URI.
- Register the Telegram webhook against the public host:
  `curl -X POST "https://api.telegram.org/bot$TOKEN/setWebhook" \
      -d "url=https://<public-api-host>/telegram/webhook"`.
- UptimeRobot (or similar) pinging `/health` so the worker container
  stays warm.

**Beyond Phase 5.** Reply-watcher (call `send_reply_notification` when
Gmail detects a thread reply), tone-learning loop (mine
`data/tone_archive.json` weekly to update `data/tone_profile.json`),
compound-signal scoring trained on the broker's approve/skip history.

## 9. Files you can safely delete

After Phase 2 cutover, these old local-token files in `data/` are dead
weight (the new auth never reads them):
- `data/gmail_token.json`
- `data/sheets_token.json`
- `data/calendar_token.json`
- `data/docs_token.json`

Leave them in place until you're confident nothing regresses.
