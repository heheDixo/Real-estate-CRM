# Progress so far — CRE Outreach Intelligence

Status as of **2026-05-28**. Covers the work delivered in Phase 1 (database
foundation) and Phase 2 (Google OAuth login). Phases 3 (research-pipeline
hardening) and 4 (Telegram bot) are not yet started.

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
3. **Drafts** an outreach email + LinkedIn message via Mistral (HF Inference
   API), wrapped in a tone profile learned from the broker's past approved
   emails.
4. **Pushes** hot leads to Gmail Drafts, optionally sends a 7 AM digest, and
   creates a 5-day follow-up event on Google Calendar after the broker hits
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
| LLM | HuggingFace Inference API (bart-mnli, Mistral) |
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

## 5. How to run locally

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

## 6. Deferred decisions / next phases

**RLS plan (Phase 2.5, before onboarding the 2nd client).** Today every
tenant-scoped table (`prospects`, `research_reports`, `sent_emails`,
`approved_emails`, `tone_profiles`, `pipeline_runs`, `dismissed_leads`,
`score_cache`) has no `user_id` column and RLS is off. Multi-tenant safe
ordering is:
1. Add a nullable `user_id uuid references users(id)` column to every
   tenant-scoped table + an index.
2. Backfill the existing rows to the single existing user.
3. Make `user_id` NOT NULL.
4. Enable RLS on each table with `using (auth.uid() = user_id)`.
5. Switch the Streamlit DB calls to use the user's JWT instead of the
   service-role / publishable key, so `auth.uid()` is populated.

Doing it any earlier than Phase 2 would have made the app appear empty —
RLS without authentication = closed policies = nothing readable.

**Phase 3 (next).** Research-pipeline hardening — currently TBD scope.

**Phase 4 (after Phase 3).** Telegram bot — stub already exists at
`POST /telegram/webhook` in `oauth_server.py`. Will read users from the
DB column `telegram_chat_id` (already in the schema) and broadcast the
morning digest there.

## 7. Files you can safely delete

After Phase 2 cutover, these old local-token files in `data/` are dead
weight (the new auth never reads them):
- `data/gmail_token.json`
- `data/sheets_token.json`
- `data/calendar_token.json`
- `data/docs_token.json`

Leave them in place until you're confident nothing regresses.
