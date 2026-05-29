# Architecture & code walkthrough

A file-by-file map of how this codebase fits together: what each module does, what it depends on, and how data flows through the pipeline from a watchlist row to an approved Gmail draft.

---

## 1. The layers

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 8 · pages/         Streamlit UI                           │
│      ↓ require_login() → reads Supabase + morning_run JSON       │
├──────────────────────────────────────────────────────────────────┤
│  Layer 7 · oauth_server.py / session_manager.py / loader         │
│      ↓ FastAPI sidecar + dark login + non-UI creds rehydrator    │
├──────────────────────────────────────────────────────────────────┤
│  Layer 6 · scheduler.py   APScheduler + safe wrapper + warm-up   │
│      ↓ parallel ThreadPool over watchlist + discovered leads     │
├──────────────────────────────────────────────────────────────────┤
│  Layer 5 · research_agent.py + lead_discovery.py + hf_models/    │
│      ↓ bart-mnli scoring · Llama drafting · new-lead candidates  │
├──────────────────────────────────────────────────────────────────┤
│  Layer 4 · scrapers/ · gmail_drafts/sheets/calendar/docs ·       │
│            telegram_bot · monitoring · hf_client                 │
│      ↓ Google News RSS · NewsAPI · Firecrawl · Google · Telegram │
├──────────────────────────────────────────────────────────────────┤
│  Layer 3 · tone_learner.py                                       │
│      ↓ records broker edits, builds the tone injection           │
├──────────────────────────────────────────────────────────────────┤
│  Layer 2 · models/        Prospect / Enrichment / ScoreResult    │
│      ↓ shared dataclasses used by the writer + scheduler         │
├──────────────────────────────────────────────────────────────────┤
│  Layer 1 · config.py + database.py                               │
│      env vars, prompts, thresholds, theme · Supabase CRUD        │
└──────────────────────────────────────────────────────────────────┘
```

The single rule: **pages read Supabase (with JSON as fallback), the scheduler writes Supabase**. Every connector is behind its own module so one missing key can't crash the rest. Every HF call goes through `hf_client.py` so a timeout or rate-limit never crashes the pipeline.

---

## 2. Layer 1 — `config.py` + `database.py`

### `config.py`
Pure constants. Reads `.env`, exposes typed module-level globals.

- **HuggingFace** — `HF_TOKEN`, `HF_API_BASE = "https://router.huggingface.co/hf-inference/models"` (legacy CPU/classification path — only bart-mnli still works here), `HF_CHAT_URL = "https://router.huggingface.co/v1/chat/completions"` (OpenAI-style endpoint for chat models — used by `hf_client.generate_text`), `SCORING_MODEL = "facebook/bart-large-mnli"`, `WRITING_MODEL = "meta-llama/Llama-3.1-8B-Instruct"` (was Mistral-7B-Instruct-v0.2 until HF retired it from the free `hf-inference` provider in mid-2025), `SCORING_TIMEOUT`.
- **Broker identity** — `AGENT_NAME`, `AGENT_TITLE`, `FIRM_NAME`, `AGENT_EMAIL`, `AGENT_PHONE`. **Phase 6**: `EMAIL_SYSTEM_PROMPT` / `LINKEDIN_SYSTEM_PROMPT` now interpolate `AGENT_TITLE` instead of hardcoding "senior tenant representation broker"; sign-off rule is three lines (name / title / firm). Fallback signatures across `scheduler._generate_draft` and `hf_models/writer.py` (`generate`, `_fallback_email`, `_fallback_linkedin`) all carry the same name / title / firm block.
- **Email fan-out** (Phase 6) — `BROKER_EMAILS` (digest recipients, defaults to `[BROKER_EMAIL]`); `ALERT_EMAILS` (failure alert recipients, resolution chain `ALERT_EMAILS → ALERT_EMAIL → BROKER_EMAILS → BROKER_EMAIL`). SMTP authentication is still single-pair (`GMAIL_SENDER` + `GMAIL_APP_PASSWORD`) — Gmail protocol doesn't allow multi-account auth in one session.
- **Data source keys** — `NEWSAPI_KEY`, `FIRECRAWL_API_KEY`, `HUNTER_API_KEY`. Each is treated as optional; the relevant scraper short-circuits when its key is missing.
- **Google integration** — `GOOGLE_CREDENTIALS_PATH`, `SHEETS_SPREADSHEET_ID`, `CALENDAR_ID`, `BROKER_EMAIL`. All Gmail / Sheets / Calendar APIs share one OAuth client; each service caches its own token under `data/`.
- **Scheduling** — `TIMEZONE`, `RESEARCH_CRON_HOUR`, `RESEARCH_CRON_MINUTE`, `DIGEST_SEND_HOUR`, `START_SCHEDULER`.
- **Research labels & thresholds** — `RESEARCH_SIGNAL_LABELS` (the five natural-language hypotheses fed to bart-mnli), `RESEARCH_SIGNAL_LABEL_TYPES` (label → signal type), `RESEARCH_TIER_HOT = 75`, `RESEARCH_TIER_WARM = 50`, `RESEARCH_SKIP_BELOW = 30`.
- **Prompts** — `EMAIL_SYSTEM_PROMPT`, `LINKEDIN_SYSTEM_PROMPT`, `TONE_VARIANT_PREFIXES` (Direct / Warm / Consultative), `SCORE_EXPLANATIONS`.
- **UI** — `DARK_THEME_CSS`, `TIER_COLORS` (hot / warm / nurture).
- **Identity** — `AGENT_NAME`, `FIRM_NAME`, `AGENT_EMAIL` (used in draft signature blocks).

No logic. No imports from anything else in the project.

### `database.py`
Thin wrapper around the Supabase Python client. Pattern used everywhere:
**try Supabase → on any exception, `_log_error` to `data/error_log.json` and fall back to a local JSON read/write**. The UI never crashes because of a DB error.

Notable functions:
- `_db()` — lazily builds a client from `SUPABASE_URL` + `SUPABASE_ANON_KEY`
- `get_watchlist` / `upsert_prospect` / `dismiss_prospect` / `approve_prospect` / `get_dismissed_ids`
- `save_research_report` / `get_todays_reports` / `get_most_recent_reports`
- `log_sent_email` / `update_email_status` / `get_sent_emails` / `get_email_stats`
- `get_tone_profile` / `save_tone_profile` / `save_approved_email` / `get_approved_emails`
- `log_pipeline_run` / `get_pipeline_runs`
- `get_cached_score` / `save_cached_score` / `make_cache_key` — used by `hf_client.classify_zero_shot`
- `get_user_by_email` / `update_user` / `get_all_telegram_users`

RLS is off (deferred to Phase 4.5 — see [PROGRESS.md](PROGRESS.md) §8).

---

## 3. Layer 2 — `models/`

Plain dataclasses. Re-exported through `models/__init__.py`.

### `models/prospect.py`
The `Prospect` dataclass — one company + contact row. Carries everything the writer needs: company / domain / contact (name, title, email, LinkedIn) / city / industry. Methods:
- `funding_months_ago()` — derived from `last_funding_date`
- `is_in_deployment_window()` — true if `10 ≤ months_since_funding ≤ 20`
- `from_apollo_record()` — kept as a static factory for completeness, though Apollo enrichment is not currently wired up

### `models/enrichment.py`
- `JobPosting` — one job row (title, location, posted_at, `is_office_role`)
- `NewsSignal` — one article (headline, source, signal_type, excerpt)
- `EnrichmentResult` — decorates a `Prospect` with headcount history + signal flags + `hf_description` (the natural-language paragraph fed to the scorer when one is needed)

### `models/score_result.py`
`ScoreResult` — minimal score container kept around so the email-fallback path can construct one when the real Mistral call fails. The richer per-signal data lives in `research_agent.ResearchReport` (Layer 5).

---

## 4. Layer 4 — `scrapers/`

Each scraper is a single `scrape()` function returning a list of dicts. Each handles its own auth, timeouts, retries, empty-result behaviour. No cross-imports between scrapers.

### `scrapers/google_news.py`
Google News RSS via `feedparser`. **`hours_back=168`** (7 days — was 24h, which produced near-zero hits for niche companies). No API key. Returns dicts with `title`, `description`, `url`, `published_at`, `source_name="Google News"`.

### `scrapers/newsapi_scraper.py`
NewsAPI free tier. **`hours_back=168`** (the free tier supports up to 30 days, 7 is the sweet spot for "fresh-enough" without diluting). Returns the same dict shape, `source_name="NewsAPI"`.

### `scrapers/firecrawl_scraper.py`
Firecrawl over the company website. Crawls `/`, `/about`, `/news` (best-effort). Returns `{"home": str, "about": str, "news": str}` — raw markdown. **Important:** this raw markdown contains nav chrome, image markdown, login links — `scheduler._clean_web_text()` strips that before classification.

### `scrapers/hunter_verify.py`
Optional Hunter.io domain-search for email enrichment on discovered leads. No-op when `HUNTER_API_KEY` is missing.

### `scrapers/linkedin_jobs.py` (Phase 5)
Guest-API scrape of LinkedIn's public job search. Endpoint is `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search` — the older `/jobs/search/` page is now auth-walled and returns a "Sign in" landing page with no job cards. Each call respects a **30s global rate limit** via a module-level `_last_request_time`. Public entry point `scrape_linkedin_jobs(company, city)` calls an inner `_scrape_attempt(...)` once; on empty result it sleeps `random.uniform(RETRY_SLEEP_MIN_SECONDS=45, RETRY_SLEEP_MAX_SECONDS=90)` and retries with a fresh random User-Agent. Per-job dict carries `is_office_signal` / `is_office_role` (both names — the existing `_build_signal_from_label` hiring branch checks `is_office_role`) and `is_growth_signal`. Module-level constant `SOURCE_LABEL = "LinkedIn Jobs · last 7 days"` is imported by `research_agent` so every signal card shows one consistent source string. `summarise_jobs(jobs, company)` returns the aggregate dict (total / office count / growth count / top_signal) used by the explicit injection block in `generate_report`.

### `scrapers/linkedin_google.py` (Phase 5)
Zero-LinkedIn-ban-risk snapshot via Google SERP scrape of `<company> site:linkedin.com/company`. Extracts follower / employee count text from the result snippet with three regex patterns (`X followers`, `X employees`, `X connections`). Returns `{found, employee_count_text, linkedin_url, snippet}`. Used as enrichment context, not as a primary signal.

---

## 5. Layer 5 — research, drafting, discovery

### `research_agent.py`
The heart of the scoring pipeline.

**Dataclasses:**
- `Signal{type, title, description, source, strength, score, url}` — one signal card on the UI
- `ResearchReport{prospect_id, company, signals, composite_score, tier, top_hook, skip_today, raw_articles, raw_jobs, draft, ...}` — one row of the morning run

**HF wrapper — `_classify(text, labels)`:** Now a one-liner that delegates to `hf_client.classify_zero_shot(text, labels, fallback_scores=[1.0/n]*n)`. The previous ~75 lines of inline `requests` + 503-retry + auth-error logging were extracted into [`hf_client.py`](hf_client.py) in Phase 3. The fallback `{}` return shape is preserved so the rest of `research_agent` is untouched.

**Per-label keyword cues — `_LABEL_KEYWORDS`:** Five keyword lists (hiring / funding / expansion / lease / space_need). Used by `_snippet_for_label()` to pick the sentence from the winning article that actually mentions the label — so the five signal cards on the UI don't all show the same article body text.

**Signal construction — `_build_signal_from_label()`:** For each label,
1. Pick the best article via `_best_article_for()` (which re-classifies each article against the single label).
2. If the winning article is `"Company website"` and the body contains zero keywords for this label, **return None** — that's a phantom score on bland marketing copy, not a real signal.
3. Otherwise build a `Signal` whose description comes from `_snippet_for_label()`.

**Composite score:** weighted mean of the top-two signal scores (weight 0.7) and the rest (weight 0.3), bounded 0–100. Tier from `_tier_for()`.

**`_mock_fallback()`:** When scrapers + bart-mnli both come back empty, synthesise plausible signals from `enrichment.months_since_funding` and `enrichment.headcount_growth_pct`. The score is always 20 — that's the fingerprint of "no real signal today".

**Persistence helpers:** `save_morning_run()`, `load_morning_run()` (tolerates older saved-bundle shapes, marks stale runs), `save_discovered_leads()`, `load_discovered_leads()`.

### `lead_discovery.py`
`discover_new_leads(icp_profile, max_results=10)` returns a list of unapproved candidate dicts. Sources: Google News RSS (queries built from `icp_profile.sectors[0] + icp_profile.geographies[0]`), NewsAPI, BuiltInNYC company listings, Hacker News Jobs.

**Noise filters — `_COMMON_ENGLISH_CAPS` and `_looks_like_company()`:** Hard-coded lowercase deny list of cities, tech-stack tokens, job-title plurals, HTML chrome. Rejects ALL-CAPS strings, single-token short words, and any name that matches the deny list case-folded. Without this filter the discovery output was full of "Front", "You", "Please", "Software Engineer", etc.

### `hf_models/writer.py`
Llama-3.1-8B-Instruct wrapper for email and LinkedIn drafting (was Mistral-7B-Instruct — see [config.py](config.py) and Phase 3 in [PROGRESS.md](PROGRESS.md)).

- `OutreachWriter._call_hf_api(prompt, max_tokens=...)` — now delegates to `hf_client.generate_text` (Phase 3). The prompt is still built with the original `[INST]…[/INST]` Mistral template; `hf_client.generate_text` strips those markers before sending the rest as a chat user-message, so the prompt builders here didn't need rewrites.
- `OutreachWriter._parse_email(raw)` — extracts subject + body from the model output (looks for `Subject:` on line 1). Falls back to `"Quick thought on your NYC expansion"` when Llama doesn't emit a subject line.
- `OutreachWriter._fallback_email(prospect, enrichment, score)` — template fallback when the HF call returns empty.
- `OutreachWriter.generate(brief, tone_prefix, tone_injection)` — convenience entrypoint returning a `SimpleNamespace`.
- `_build_fallback_draft(prospect_name, top_hook, sign_off)` — module-level helper added in Phase 3; the deepest-fallback template, used when even `_fallback_email` can't be built (e.g. when free HF credits exhaust).

`DraftWriter = OutreachWriter` is kept as an alias because earlier code referenced both names.

### `hf_client.py` (Phase 3)
Resilient wrapper around every HF Inference call. Public surface:
- `classify_zero_shot(text, candidate_labels, model=SCORER_MODEL, use_cache=True, fallback_scores=None)` — POSTs to `{HF_API_BASE}/{model}`. 3 retries with 2s/4s/8s exponential backoff. 30s timeout. Caches results in Supabase via `make_cache_key`/`get_cached_score`/`save_cached_score` keyed on `text[:200]|labels`. On all-retries-failure: returns `fallback_scores` (or equal distribution) so the caller never sees an exception.
- `generate_text(prompt, model=WRITER_MODEL, max_new_tokens=400, temperature=0.7, fallback_text="")` — POSTs OpenAI-style chat completions to `config.HF_CHAT_URL` (`/v1/chat/completions`) — the legacy `/hf-inference/models/{model}` endpoint is CPU/legacy-only and no longer routes Mistral/Llama/Qwen/etc. Strips Mistral `[INST]/[/INST]/<s>/</s>` markers so the existing prompt builders work unchanged. 3 retries with the same backoff. Returns `fallback_text` if all retries fail.
- `warm_up_models()` — pings scorer + writer with minimal inputs; returns `{"scorer": bool, "writer": bool}`. Called by `scheduler._run_warmup` at 4:50am.

### `monitoring.py` (Phase 3)
- `send_alert(subject, body)` — `SMTP_SSL` to `smtp.gmail.com:465` using `GMAIL_SENDER` + `GMAIL_APP_PASSWORD` → `ALERT_EMAIL` (or `BROKER_EMAIL` fallback). Silently no-ops when any of those env vars are missing.
- `alert_pipeline_failed(error, run_date)` — convenience wrapper used by `scheduler.run_morning_pipeline_safe` on exception.

### `telegram_bot.py` (Phase 4)
Fire-and-forget wrapper around the Telegram Bot API using plain `requests` (no `python-telegram-bot` dependency).
- `send_message(chat_id, text, parse_mode="Markdown")` — never raises; returns `True/False`.
- `broadcast(text)` — fan-out to every `get_all_telegram_users()`.
- `send_morning_brief(chat_id, reports)` — Markdown-formatted hot/warm/skipped card with hot-lead hooks and dashboard deep-link.
- `send_reply_notification(chat_id, ...)` — exposed for the future Gmail reply-watcher.
- `send_pipeline_failed_alert(chat_id, error)` / `send_warmup_failed_alert(chat_id, failed_models)`.
- `get_connect_url(user_id)` — returns `https://t.me/<BOT_USERNAME>?start=<user_id>` for the connect banner on page 5.
- `run_polling()` / `_handle_update(update)` — local-dev mirror of the production webhook. Processes `/start <user_id>` by upserting `users.telegram_chat_id` + `telegram_connected=true` and sending a "Connected" confirmation.

---

## 6. Layer 4 — Google integrations

Each module: minimal API surface. Credentials no longer live in per-service `data/*_token.json` files — Phase 2 moved them to `users.google_token` (JSONB) in Supabase, rehydrated by `google_auth_loader.py`. All `authenticate_*` functions now accept an optional `credentials` parameter; when omitted they call the shared loader (used by the scheduler since it has no Streamlit session).

### `gmail_drafts.py`
`authenticate_gmail(credentials=None)` returns a Gmail service. `create_draft(service, to, subject, body, prospect_name)` builds a MIME message and posts to `users.drafts.create`. `send_morning_digest(service, broker_email, reports)` builds an HTML digest and `users.messages.send` to the broker. Also exposes `send_email_now()` for the **Send now** button on page 3.

### `google_sheets.py`
`authenticate_sheets(credentials=None)`. `append_sent_row(service, spreadsheet_id, row)` appends to the configured sheet. `list_sent(service, spreadsheet_id)` reads the same sheet for the sent-tracker page. Empty sheet / missing ID → empty list.

### `google_calendar.py`
`authenticate_calendar(credentials=None)`. `create_followup_event(service, calendar_id, summary, description, when, attendees=...)` creates a one-shot reminder. `list_upcoming(service, calendar_id, max_results=...)` powers the follow-ups page.

### `google_docs.py`
`authenticate_docs(credentials=None)`. `create_research_doc(report)` produces a per-prospect editorial dossier — one Google Doc with the company, signals, top hook, draft, and supporting articles. Linked from the morning research page so the broker can share or annotate.

### `oauth_server.py` (Phase 2 / Phase 4)
FastAPI sidecar on port 8000. Routes:
- `GET /oauth/login` — Google consent redirect with PKCE verifier stored in `_PKCE_STORE` keyed by OAuth `state`
- `GET /oauth/callback` — code exchange, userinfo lookup, whitelist check, upsert `users.google_token`, create a 30-day `sessions` row, redirect to `STREAMLIT_URL/?session=<token>`
- `GET /health` — JSON `{status, ts, database}` for uptime monitoring
- `POST /telegram/webhook` — Phase-4 real handler. Processes `/start <user_id>`, upserts `users.telegram_chat_id` + `telegram_connected=true`, sends a "Connected" message via `telegram_bot.send_message`.

### `session_manager.py` (Phase 2)
- `require_login()` — called by `ui_components.page_shell`. Checks `st.session_state["current_user"]`, validates `?session=` query param against `sessions` table, renders the dark login page (with a Sign-in-with-Google link pointing at `FASTAPI_URL/oauth/login`) when no valid session exists.
- `get_google_credentials(user)` — builds a `google.oauth2.Credentials` from the user's `google_token` JSONB, refreshing silently if expired and persisting the new access token back to Supabase.
- `logout()` — deletes the session row + clears session state.

### `google_auth_loader.py` (Phase 2)
Streamlit-free helper used by all Google API helpers (and `monitoring.py` if needed) to source credentials from Supabase in non-UI contexts. `load_user_credentials_from_db(user_id=None)` returns a refreshed `Credentials` object — the scheduler relies on this so the 5am cron can talk to Gmail / Sheets / Calendar / Docs without a browser session.

---

## 7. Layer 3 — tone learning

`tone_learner.py`:
- `load_tone_profile()` reads `data/tone_profile.json`. Initial profile shipped is empty.
- `archive_sent_draft(original_draft, edited_draft)` — diffs subject + body, appends both to `data/tone_archive.json` for offline analysis.
- `build_tone_injection(profile)` — compiles the current profile into a `<TONE_RULES>` block prepended to the writer prompt.

Triggered from `pages/3_draft_review.py` after every **Send now**.

---

## 8. Layer 6 — `scheduler.py`

The orchestrator. Phase 3 added a safe wrapper + warm-up; Phase 4 added Telegram mirrors for the morning brief and the two failure alerts.

### Helpers
- `_write_progress(pct, message)` → `data/pipeline_progress.json` (polled by the UI for the live progress bar).
- `_log_error(scope, exc)` → `data/error_log.json` (capped at 200 entries).
- `_clean_web_text(text)` — strips markdown images, markdown links, bare URLs, US phone numbers, navigation chrome phrases (Skip to main content, Log in, Sign up, Menu, cookie / privacy boilerplate, language toggles). Applied before the Firecrawl text is injected into the article list.

### `_gather_signals(prospect)`
For one prospect, runs Google News, NewsAPI, and Firecrawl. Folds the cleaned website text into the article list as a synthesised `Company website` entry **only if** the cleaned text is ≥120 chars (else it's just a tagline, useless for classification). Dedupes by URL, caps at 12 articles. Logs `scheduler.no_articles` when every source comes back empty. **Phase 5 addition:** after the news + Firecrawl scrapes, also calls `scrape_linkedin_jobs(company, city)` and `get_linkedin_snapshot(company)`; results land in `bundle["jobs"]` and `bundle["linkedin_snapshot"]`. Both LinkedIn calls are guarded — exceptions log and return `[]` / `{}` so the rest of the bundle is unaffected.

### `_generate_draft(report, prospect, tone_injection, variant)`
Builds a tone-prefixed Mistral prompt from the top hook + the three strongest signals, calls `OutreachWriter._call_hf_api()`, parses subject + body, falls back to the writer's template path on failure. Also generates a LinkedIn variant under 300 chars.

### `_process_prospect(prospect, tone_injection, variant)`
Per-prospect work unit. Calls `_gather_signals` → `research_agent.generate_report` → `_generate_draft`. Returns a `ResearchReport`. All exceptions go to `data/error_log.json`.

### `run_morning_pipeline()`
1. Write progress 0%. Load active ICP from the watchlist. Run `lead_discovery.discover_new_leads()`. Save to `data/discovered_leads_<date>.json`.
2. Write progress 20%. Concat watchlist (active) + discovered. Build the tone injection.
3. Write progress 40%. Submit every prospect to a 4-worker `ThreadPoolExecutor` running `_process_prospect`.
4. Write progress 80%. Sort by composite, tally actionable / hot / warm / skipped.
5. Push every actionable draft to Gmail Drafts. Send broker digest if `BROKER_EMAIL` set.
6. Finalise summary status (success / partial / no_actionable / no_prospects), save the bundle to `data/morning_run_<date>.json`, append to scheduler_log, write progress 100%.

Returns the summary dict.

### Safe wrapper + warm-up (Phase 3)
- `run_morning_pipeline_safe()` — the cron always calls this, never `run_morning_pipeline` directly. Catches every exception, logs a `failed` row to `pipeline_runs`, calls `monitoring.alert_pipeline_failed(error, run_date)`, and mirrors the alert to Telegram via `send_pipeline_failed_alert` for every connected user. **On success**, loads the just-persisted reports via `database.get_most_recent_reports`, wraps each in a `SimpleNamespace`, and pushes a `send_morning_brief` to every Telegram-connected user. Both Telegram side-effects sit in their own `try/except` so a Telegram outage can't crash the pipeline.
- `_run_warmup()` — APScheduler job at 04:50. Calls `hf_client.warm_up_models()`. If either model is unreachable, sends an email alert via `monitoring.send_alert` and mirrors it to Telegram via `send_warmup_failed_alert`.

### Scheduler daemons
- `start_scheduler()` — `BlockingScheduler`, used by `python scheduler.py` for the foreground daemon.
- `start_scheduler_background()` — `BackgroundScheduler` with `daemon=True`, used by `app.py` when `START_SCHEDULER=true`.

Both register two jobs:
- `model_warmup` at 04:50 → `_run_warmup`
- `morning_research` at `RESEARCH_CRON_HOUR:RESEARCH_CRON_MINUTE` → `run_morning_pipeline_safe`, `misfire_grace_time=1800`.

### Sequential prospect processing (Phase 5)
Pre-Phase-5, `run_morning_pipeline` ran prospects through a `ThreadPoolExecutor(max_workers=4)`. Phase 5 switched to a **sequential for-loop** because LinkedIn's 30-second global rate limit is enforced in `scrapers/linkedin_jobs.py` via a module-level `_last_request_time` mutex. Running prospects in parallel would (a) just serialise behind the rate limiter anyway and (b) race on the shared `_last_request_time` state. Sequential is the honest model. At 4 active prospects × ~30-90s of LinkedIn budget per prospect, the morning run takes 3-7 minutes — well under the 1800s misfire grace, and the broker doesn't see results until ~07:00 ET anyway.

### Broker-email fan-out (Phase 6)
The digest send step loops over `config.BROKER_EMAILS` with a per-recipient `try/except` so one bad address doesn't stop the rest. `broker_self` (the filter that strips the broker's own address from draft "To" fields when the watchlist entry has no real contact) is widened to include the full `BROKER_EMAILS` list plus `AGENT_EMAIL` and `GMAIL_SENDER`. Resolution chain when only the singular is set: `BROKER_EMAILS = [BROKER_EMAIL]`.

---

## 9. Layer 7 — Streamlit pages

### `app.py`
The entrypoint. Injects the dark theme, optionally starts the background scheduler thread, then `st.switch_page("pages/5_morning_research.py")`.

### `ui_components.py`
Shared widgets used across every page. Highlights:
- `inject_theme()` — single CSS injection point (uses `config.DARK_THEME_CSS`).
- `bootstrap_session_state()` — initialises the session keys read elsewhere.
- `render_sidebar()` — left rail with active-profile, API status, navigation links.
- `page_shell(title)` — header + sidebar + theme in one call.
- `tier_badge`, `score_bar`, `strength_dots`, `signal_icon`, `signal_type_label`, `status_badge`, `new_badge`, `draft_ready_badge`, `sent_badge`, `info_row`, `section_header`, `metric_card`, `empty_state`, `api_status_row`, `pulse_dot`.

### `pages/5_morning_research.py`
The home screen. **Phase 4 Telegram connect banner** sits immediately below `page_shell()` — hidden once `current_user.telegram_connected=true`, deep-links to `t.me/<BOT_USERNAME>?start=<user_uuid>`. Top bar with status pulse + **Run pipeline**. Polls `data/pipeline_progress.json` for the live bar. Primary data source is Supabase (`database.get_most_recent_reports`); falls back to `data/morning_run_<today>.json` (then stale banner). Filter pills (All / Hot / Warm / Nurture / New leads). 40/60 split: lead list with tier accent and badges (NEW / Draft ready / Sent) on the left, detail pane with signal cards on the right. Discovered leads have **Approve** / **Dismiss** actions; approved ones get promoted to the watchlist.

### `pages/3_draft_review.py`
Breadcrumb back to research. 35/65 split. Left: research brief expander + opening-hook callout + contact info row with inline-editable email field (persists back to `data/watchlist.json` and surfaces an amber warning when the email is blank). Right: tone radio (Direct / Warm / Consultative — auto-regenerates on change), subject + body + LinkedIn editor with colour-coded character counts, four actions: **Regenerate** / **Copy** / **Save to Gmail draft** / **Send now**. Send now: SMTP send → Sheets log → Calendar follow-up created → `tone_learner.archive_sent_draft` → return to research.

### `pages/6_sent_tracker.py`
Reads from Google Sheets via `google_sheets.list_sent`. Custom dark HTML table with status pills, four metric cards (Total / Open rate / Reply rate / Meetings). Empty states for missing credentials or empty spreadsheet.

### `pages/7_followups.py`
Reads from Google Calendar via `google_calendar.list_upcoming`. Blue date badges, purple suggested-angle callouts derived from the original signal stored on the event description. **Mark replied** + **Delete** buttons.

---

## 10. Data flow — one prospect from cron to send

```
04:50 ET   cron fires _run_warmup
           │   hf_client.warm_up_models — bart + Llama pings
           │   on failure → monitoring.send_alert + telegram_bot.send_warmup_failed_alert

05:00 ET   cron fires run_morning_pipeline_safe
           │   try: run_morning_pipeline()
           │   except: log_pipeline_run(status=failed) + alert_pipeline_failed + telegram_bot.send_pipeline_failed_alert
           │
           ├─ lead_discovery.discover_new_leads(icp)
           │   → database.upsert_prospect × N
           │   → data/discovered_leads_2026-05-21.json (gitignored)
           │
           ├─ for each prospect in (watchlist + discovered) in parallel (4 workers):
           │   ├─ scheduler._gather_signals
           │   │   ├─ scrapers.scrape_google_news
           │   │   ├─ scrapers.scrape_newsapi
           │   │   └─ scrapers.scrape_firecrawl  → _clean_web_text
           │   ├─ research_agent.generate_report
           │   │   ├─ _classify(all article text, 5 labels)
           │   │   │   └─ hf_client.classify_zero_shot (Supabase cache → router)
           │   │   └─ _build_signal_from_label × 5
           │   │       └─ _snippet_for_label (per-label sentence)
           │   └─ scheduler._generate_draft
           │       └─ writer._call_hf_api
           │           └─ hf_client.generate_text  (Llama via /v1/chat/completions)
           │       → ResearchReport with .draft set (or template fallback)
           │
           ├─ database.save_research_report × N
           ├─ research_agent.save_morning_run → data/morning_run_2026-05-21.json
           ├─ gmail_drafts.create_draft × actionable
           ├─ google_docs.create_research_doc × actionable
           ├─ gmail_drafts.send_morning_digest (broker email)
           ├─ database.log_pipeline_run(status=success/partial/no_actionable)
           └─ telegram_bot.send_morning_brief → every connected user

07:00 ET   broker opens Streamlit
           │
           ├─ session_manager.require_login() — Supabase sessions check
           ├─ pages/5 reads database.get_most_recent_reports (Supabase first, JSON fallback)
           │   shows Telegram connect banner if not yet connected
           │   shows lead list + signal cards
           │
           └─ broker clicks a lead → pages/3
               edits subject/body/LinkedIn
               clicks Send now:
                 ├─ gmail_drafts.send_email_now
                 ├─ database.log_sent_email
                 ├─ google_sheets.append_sent_row
                 ├─ google_calendar.create_followup_event
                 └─ tone_learner.archive_sent_draft → database.save_approved_email
```

Every per-run disk write is gitignored (`data/morning_run_*.json`, `data/discovered_leads_*.json`, `data/error_log.json`, `data/scheduler_log.json`, `data/pipeline_progress.json`). OAuth tokens used to live under `data/*_token.json` (gitignored) but Phase 2 moved them to `users.google_token` JSONB in Supabase. `data/approved_emails.json` was untracked in Phase 4 (real broker correspondence). Only `data/watchlist.json` and `data/tone_profile.json` remain committed.

---

## 11. What got removed (and what got retired upstream)

For posterity — the codebase used to contain:

- `pages/1_icp_setup.py`, `pages/2_prospect_found.py`, `pages/3-wizard variants`, `pages/4_audit_summary.py` — a four-step wizard. Replaced by the morning-research home + draft review.
- `connectors/apollo.py`, `connectors/proxycurl.py`, `connectors/newsapi.py` — paid third-party enrichment. Removed because (a) Apollo and Proxycurl are paid and (b) Proxycurl LinkedIn scraping was deemed unnecessary.
- `mock_data/` — pre-built demo prospects. Replaced by `data/watchlist.json` (three real NYC companies).
- `pipeline/` — multi-stage enrichment/scoring/drafting orchestrator. Collapsed into the single `scheduler.run_morning_pipeline` function.
- `models/icp_profile.py`, `models/draft_result.py`, `hf_models/scorer.py`, `hf_models/briefer.py` — wizard-era abstractions.
- Per-service `data/gmail_token.json` / `data/sheets_token.json` / `data/calendar_token.json` / `data/docs_token.json` — Phase 2 moved OAuth to the FastAPI sidecar + Supabase JSONB. Old files can be deleted; nothing reads them.

Retired **upstream** (not by us):
- `mistralai/Mistral-7B-Instruct-v0.2` as a writer — HF narrowed the free `hf-inference` provider to CPU/legacy models in mid-2025. Every text-generation model returns `{"error":"Model not supported by provider hf-inference"}` from `/hf-inference/models/{model}`. Phase 3 swapped to `meta-llama/Llama-3.1-8B-Instruct` via the OpenAI-style `/v1/chat/completions` endpoint. bart-mnli still works on the legacy path — that's why scoring kept functioning while drafting silently broke.

The deletions appear in the git history; the current architecture is the one in this document.
