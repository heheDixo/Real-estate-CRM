# Architecture & code walkthrough

A file-by-file map of how this codebase fits together: what each module does, what it depends on, and how data flows through the pipeline from a watchlist row to an approved Gmail draft.

---

## 1. The layers

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 7 · pages/         Streamlit UI                           │
│      ↓ reads data/morning_run_*.json, calls scheduler.run_now    │
├──────────────────────────────────────────────────────────────────┤
│  Layer 6 · scheduler.py   APScheduler cron + orchestrator        │
│      ↓ parallel ThreadPool over watchlist + discovered leads     │
├──────────────────────────────────────────────────────────────────┤
│  Layer 5 · research_agent.py + lead_discovery.py + hf_models/    │
│      ↓ bart-mnli scoring · Mistral drafting · new-lead candidates│
├──────────────────────────────────────────────────────────────────┤
│  Layer 4 · scrapers/ + gmail_drafts/sheets/calendar              │
│      ↓ Google News RSS · NewsAPI · Firecrawl · Google APIs       │
├──────────────────────────────────────────────────────────────────┤
│  Layer 3 · tone_learner.py                                       │
│      ↓ records broker edits, builds the tone injection           │
├──────────────────────────────────────────────────────────────────┤
│  Layer 2 · models/        Prospect / Enrichment / ScoreResult    │
│      ↓ shared dataclasses used by the writer + scheduler         │
├──────────────────────────────────────────────────────────────────┤
│  Layer 1 · config.py      env vars, prompts, thresholds, theme   │
└──────────────────────────────────────────────────────────────────┘
```

The single rule: **pages read JSON, the scheduler writes JSON**. Every connector is behind its own module so one missing key can't crash the rest.

---

## 2. Layer 1 — `config.py`

Pure constants. Reads `.env`, exposes typed module-level globals.

- **HuggingFace** — `HF_TOKEN`, `HF_API_BASE = "https://router.huggingface.co/hf-inference/models"` (the old `api-inference.huggingface.co` was deprecated in 2025 — the router endpoint must be used), `SCORING_MODEL`, `WRITER_MODEL`, `SCORING_TIMEOUT`.
- **Data source keys** — `NEWSAPI_KEY`, `FIRECRAWL_API_KEY`, `HUNTER_API_KEY`. Each is treated as optional; the relevant scraper short-circuits when its key is missing.
- **Google integration** — `GOOGLE_CREDENTIALS_PATH`, `SHEETS_SPREADSHEET_ID`, `CALENDAR_ID`, `BROKER_EMAIL`. All Gmail / Sheets / Calendar APIs share one OAuth client; each service caches its own token under `data/`.
- **Scheduling** — `TIMEZONE`, `RESEARCH_CRON_HOUR`, `RESEARCH_CRON_MINUTE`, `DIGEST_SEND_HOUR`, `START_SCHEDULER`.
- **Research labels & thresholds** — `RESEARCH_SIGNAL_LABELS` (the five natural-language hypotheses fed to bart-mnli), `RESEARCH_SIGNAL_LABEL_TYPES` (label → signal type), `RESEARCH_TIER_HOT = 75`, `RESEARCH_TIER_WARM = 50`, `RESEARCH_SKIP_BELOW = 30`.
- **Prompts** — `EMAIL_SYSTEM_PROMPT`, `LINKEDIN_SYSTEM_PROMPT`, `TONE_VARIANT_PREFIXES` (Direct / Warm / Consultative), `SCORE_EXPLANATIONS`.
- **UI** — `DARK_THEME_CSS`, `TIER_COLORS` (hot / warm / nurture).
- **Identity** — `AGENT_NAME`, `FIRM_NAME`, `AGENT_EMAIL` (used in draft signature blocks).

No logic. No imports from anything else in the project.

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

---

## 5. Layer 5 — research, drafting, discovery

### `research_agent.py`
The heart of the scoring pipeline.

**Dataclasses:**
- `Signal{type, title, description, source, strength, score, url}` — one signal card on the UI
- `ResearchReport{prospect_id, company, signals, composite_score, tier, top_hook, skip_today, raw_articles, raw_jobs, draft, ...}` — one row of the morning run

**HF wrapper — `_classify(text, labels)`:** POSTs to `{HF_API_BASE}/{SCORING_MODEL}` with `multi_label=True`. Handles both the new router response shape (list of `{label, score}` objects) and the old shape (`{labels: [...], scores: [...]}`) for backwards compatibility. 503 → wait 20s and retry once. 401/403/4xx/5xx all log to `data/error_log.json` via `_log_hf_error()` and return `{}` so the caller can fall back.

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
Mistral-7B-Instruct wrapper for email and LinkedIn drafting.

- `OutreachWriter._call_hf_api(prompt, max_tokens=...)` — POSTs to the router for the writer model.
- `OutreachWriter._parse_email(raw)` — extracts subject + body from the model output (looks for `Subject:` on line 1).
- `OutreachWriter._fallback_email(prospect, enrichment, score)` — template fallback when the HF call fails.
- `OutreachWriter.generate(brief, tone_prefix, tone_injection)` — convenience entrypoint returning a `SimpleNamespace`.

`DraftWriter = OutreachWriter` is kept as an alias because earlier code referenced both names.

---

## 6. Layer 4 — Google integrations

Each module: own auth, own token cache, own minimal API surface.

### `gmail_drafts.py`
`authenticate_gmail()` runs the OAuth flow once, caches `data/gmail_token.json`. `create_draft(service, to, subject, body, prospect_name)` builds a MIME message and posts to `users.drafts.create`. `send_morning_digest(service, broker_email, reports)` builds an HTML digest and `users.messages.send` to the broker. Also exposes `send_email_now()` for the **Send now** button on page 3.

### `google_sheets.py`
`authenticate_sheets()` caches `data/sheets_token.json`. `append_sent_row(service, spreadsheet_id, row)` appends to the configured sheet. `list_sent(service, spreadsheet_id)` reads the same sheet for the sent-tracker page. Empty sheet / missing ID → empty list.

### `google_calendar.py`
`authenticate_calendar()` caches `data/calendar_token.json`. `create_followup_event(service, calendar_id, summary, description, when, attendees=...)` creates a one-shot reminder. `list_upcoming(service, calendar_id, max_results=...)` powers the follow-ups page.

---

## 7. Layer 3 — tone learning

`tone_learner.py`:
- `load_tone_profile()` reads `data/tone_profile.json`. Initial profile shipped is empty.
- `archive_sent_draft(original_draft, edited_draft)` — diffs subject + body, appends both to `data/tone_archive.json` for offline analysis.
- `build_tone_injection(profile)` — compiles the current profile into a `<TONE_RULES>` block prepended to the writer prompt.

Triggered from `pages/3_draft_review.py` after every **Send now**.

---

## 8. Layer 6 — `scheduler.py`

The orchestrator.

### Helpers
- `_write_progress(pct, message)` → `data/pipeline_progress.json` (polled by the UI for the live progress bar).
- `_log_error(scope, exc)` → `data/error_log.json` (capped at 200 entries).
- `_clean_web_text(text)` — strips markdown images, markdown links, bare URLs, US phone numbers, navigation chrome phrases (Skip to main content, Log in, Sign up, Menu, cookie / privacy boilerplate, language toggles). Applied before the Firecrawl text is injected into the article list.

### `_gather_signals(prospect)`
For one prospect, runs Google News, NewsAPI, and Firecrawl. Folds the cleaned website text into the article list as a synthesised `Company website` entry **only if** the cleaned text is ≥120 chars (else it's just a tagline, useless for classification). Dedupes by URL, caps at 12 articles. Logs `scheduler.no_articles` when every source comes back empty.

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

### Scheduler daemons
- `start_scheduler()` — `BlockingScheduler`, used by `python scheduler.py` for the foreground daemon.
- `start_scheduler_background()` — `BackgroundScheduler` with `daemon=True`, used by `app.py` when `START_SCHEDULER=true`.

Both fire `run_morning_pipeline` at `RESEARCH_CRON_HOUR:RESEARCH_CRON_MINUTE`, `misfire_grace_time=1800`.

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
The home screen. Top bar with status pulse + **Run pipeline**. Polls `data/pipeline_progress.json` for the live bar. Reads `data/morning_run_<today>.json` (falls back to most-recent + stale banner). Filter pills (All / Hot / Warm / Nurture / New leads). 40/60 split: lead list with tier accent and badges (NEW / Draft ready / Sent) on the left, detail pane with signal cards on the right. Discovered leads have **Approve** / **Dismiss** actions; approved ones get promoted to the watchlist.

### `pages/3_draft_review.py`
Breadcrumb back to research. 35/65 split. Left: research brief expander + opening-hook callout + contact info row with inline-editable email field (persists back to `data/watchlist.json` and surfaces an amber warning when the email is blank). Right: tone radio (Direct / Warm / Consultative — auto-regenerates on change), subject + body + LinkedIn editor with colour-coded character counts, four actions: **Regenerate** / **Copy** / **Save to Gmail draft** / **Send now**. Send now: SMTP send → Sheets log → Calendar follow-up created → `tone_learner.archive_sent_draft` → return to research.

### `pages/6_sent_tracker.py`
Reads from Google Sheets via `google_sheets.list_sent`. Custom dark HTML table with status pills, four metric cards (Total / Open rate / Reply rate / Meetings). Empty states for missing credentials or empty spreadsheet.

### `pages/7_followups.py`
Reads from Google Calendar via `google_calendar.list_upcoming`. Blue date badges, purple suggested-angle callouts derived from the original signal stored on the event description. **Mark replied** + **Delete** buttons.

---

## 10. Data flow — one prospect from cron to send

```
05:00 ET   cron fires run_morning_pipeline
           │
           ├─ lead_discovery.discover_new_leads(icp)
           │   → data/discovered_leads_2026-05-21.json
           │
           ├─ for each prospect in (watchlist + discovered) in parallel:
           │   ├─ scheduler._gather_signals
           │   │   ├─ scrapers.scrape_google_news
           │   │   ├─ scrapers.scrape_newsapi
           │   │   └─ scrapers.scrape_firecrawl  → _clean_web_text
           │   ├─ research_agent.generate_report
           │   │   ├─ _classify(all article text, 5 labels)
           │   │   └─ _build_signal_from_label × 5
           │   │       └─ _snippet_for_label (per-label sentence)
           │   └─ scheduler._generate_draft (Mistral)
           │       → ResearchReport with .draft set
           │
           ├─ gmail_drafts.create_draft × actionable
           ├─ gmail_drafts.send_morning_digest (broker)
           └─ research_agent.save_morning_run
               → data/morning_run_2026-05-21.json

07:00 ET   broker opens Streamlit
           │
           ├─ pages/5 reads morning_run_2026-05-21.json
           │   shows lead list + signal cards
           │
           └─ broker clicks a lead → pages/3
               edits subject/body/LinkedIn
               clicks Send now:
                 ├─ gmail_drafts.send_email_now
                 ├─ google_sheets.append_sent_row
                 ├─ google_calendar.create_followup_event
                 └─ tone_learner.archive_sent_draft
```

Every disk write in the diagram is gitignored (`data/morning_run_*.json`, `data/discovered_leads_*.json`, `data/*_token.json`, `data/error_log.json`, `data/scheduler_log.json`, `data/pipeline_progress.json`). Only `data/watchlist.json` and `data/tone_profile.json` are committed.

---

## 11. What got removed

For posterity — the codebase used to contain:

- `pages/1_icp_setup.py`, `pages/2_prospect_found.py`, `pages/3-wizard variants`, `pages/4_audit_summary.py` — a four-step wizard. Replaced by the morning-research home + draft review.
- `connectors/apollo.py`, `connectors/proxycurl.py`, `connectors/newsapi.py` — paid third-party enrichment. Removed because (a) Apollo and Proxycurl are paid and (b) Proxycurl LinkedIn scraping was deemed unnecessary.
- `mock_data/` — pre-built demo prospects. Replaced by `data/watchlist.json` (three real NYC companies).
- `pipeline/` — multi-stage enrichment/scoring/drafting orchestrator. Collapsed into the single `scheduler.run_morning_pipeline` function.
- `models/icp_profile.py`, `models/draft_result.py`, `hf_models/scorer.py`, `hf_models/briefer.py` — wizard-era abstractions.

The deletions appear in the git history; the current architecture is the one in this document.
