# Architecture & code walkthrough

A file-by-file map of how this codebase fits together: what each module does, what it depends on, and how data flows through the pipeline from a raw company to an approved draft.

---

## 1. The seven layers

The codebase is intentionally split into seven layers. Each layer only depends on the ones above it. The arrows point in the direction of "uses".

```
┌─────────────────────────────────────────────────────────┐
│  Layer 7 · pages/         (Streamlit UI — 4 wizard steps)│
│      ↓ calls pipeline functions, reads/writes session    │
├─────────────────────────────────────────────────────────┤
│  Layer 6 · pipeline/      (orchestration)                │
│      ↓ calls connectors + hf_models                      │
├─────────────────────────────────────────────────────────┤
│  Layer 5 · hf_models/     (HuggingFace API wrappers)     │
│      ↓ reads models, posts to api-inference.hf.co        │
├─────────────────────────────────────────────────────────┤
│  Layer 4 · connectors/    (real third-party API wrappers)│
│      ↓ reads models, falls back to mock_data on failure  │
├─────────────────────────────────────────────────────────┤
│  Layer 3 · mock_data/     (pre-built realistic records)  │
│      ↓ uses models to instantiate demo data              │
├─────────────────────────────────────────────────────────┤
│  Layer 2 · config.py      (constants, prompts, keys)     │
│      ↓ pure data — no logic                              │
├─────────────────────────────────────────────────────────┤
│  Layer 1 · models/        (dataclasses — the data shapes)│
│      ↓ no dependencies on anything else in the project   │
└─────────────────────────────────────────────────────────┘
```

The single rule that keeps the project clean: **pages talk to pipeline, pipeline talks to connectors and hf_models, and nothing skips a layer**. The model dataclasses ride through every layer as the common currency.

---

## 2. Layer 1 — `models/` (the data shapes)

Pure Python dataclasses. No dependencies on anything else in the project. Every other layer reads and writes instances of these classes — they're how data moves through the pipeline.

### [models/icp_profile.py](models/icp_profile.py)
The `ICPProfile` dataclass — one complete sector campaign definition. Contains:
- **Targeting filters** (sectors, geographies, headcount min/max, company stages)
- **Signal weights** for the five scoring dimensions (must sum to 1.0)
- **Trigger signals** the prospect must fire (e.g. `raised_funding_last_18_months`)
- **Exclusions** (min employees, excluded domains, max lease age)
- **Tone rules** that get injected into the Mistral writing prompt
- **Decision history** — approved/rejected prospects, edited drafts, learned rules

Key methods:
- `apply_sector_preset(sector_key)` — loads default weights from `SECTOR_WEIGHT_PRESETS`
- `record_approval / record_rejection / record_edit` — append to history and bump metadata
- `get_system_prompt_rules()` — compiles `learned_rules` into a prompt block for the scorer
- `get_tone_prompt_block()` — compiles `tone_rules` into a prompt block for the writer
- `to_dict / from_dict` — JSON serialisation (not used for session state — instances are stored directly)

Also defines `SECTOR_WEIGHT_PRESETS`, `TIER_HOT`, `TIER_WARM` as module-level constants re-exported through `models/__init__.py`.

### [models/prospect.py](models/prospect.py)
The `Prospect` dataclass — one company + contact record. Contains company fields (domain, headcount, stage, funding), contact fields (name, title, email, LinkedIn), and pipeline state (`status`, `icp_profile_name`, timestamps).

Key methods:
- `advance_status(new_status)` — moves through `PROSPECT_STATUSES` (new → enriched → scored → drafted → approved → sent)
- `funding_months_ago()` — calculated from `last_funding_date`
- `is_in_deployment_window()` — true if 10 ≤ months_since_funding ≤ 20
- `from_apollo_record(record)` — class method that builds a `Prospect` from a raw Apollo API response

### [models/enrichment.py](models/enrichment.py)
Three dataclasses:

- **`JobPosting`** — one LinkedIn job (title, location, date, `is_office_related`)
- **`NewsSignal`** — one news article (headline, source, signal_type, excerpt)
- **`EnrichmentResult`** — the big one. Decorates a `Prospect` with everything discovered:
  - **Apollo block** — headcount history, founded year, technologies, keywords, revenue
  - **Proxycurl block** — job postings, hiring velocity, LinkedIn follower count
  - **NewsAPI block** — news signals, strongest signal headline, boolean flags for each signal type
  - **Computed fields** — `headcount_growth_pct`, `months_since_funding`, `triggers_fired`, `hf_description` (the natural-language paragraph fed to the model)

Key methods (called by `pipeline/enrichment.py` after each source runs):
- `compute_headcount_growth()` — `(current - 6mo_ago) / 6mo_ago * 100`
- `compute_hiring_velocity()` — `(jobs / headcount) * 100`, capped at 100
- `check_triggers(trigger_signals, months_since_funding)` — sets `triggers_fired`
- `build_hf_description(prospect)` — the natural-language paragraph for the scorer

### [models/score_result.py](models/score_result.py)
The `ScoreResult` dataclass — output of scoring.

- Five dimension scores (0–100 each): hiring velocity, funding timing, expansion news, lease expiry, decision maker
- `composite` (weighted average) and `tier` ("Hot" / "Warm" / "Nurture")
- `positive_signals` and `risk_signals` — human-readable bullet lists
- `top_signal_type` and `top_signal_text` — the strongest signal, used as the email's opening hook
- `raw_label_confidences` — the unprocessed dict from HuggingFace, shown in UI for transparency
- `used_fallback_scoring` flag — true if the HF API was unavailable and rules ran instead

Helper methods: `tier_color()`, `tier_emoji()`, `tier_badge()`, `dimension_scores()`.

### [models/draft_result.py](models/draft_result.py)
The `DraftResult` dataclass — output of drafting.

- `brief_bullets` — the 5-bullet research brief
- `email_subject`, `email_body`, `linkedin_message` — the AI-generated copy
- `personalisation_tags` — chips shown in the UI (e.g. "📈 Headcount growth: +58%")
- `opening_signal` — the specific signal the email opens with
- **Approval tracking** — `approval_status` ("pending" / "approved" / "edited_approved" / "rejected"), `approved_at`, `rejected_at`, `rejection_reason`
- **Edit tracking** — `was_edited`, `edited_subject`, `edited_body`, `edited_linkedin`
- **Final versions** — what actually gets exported (his edits if any, else originals)

Key methods: `approve()` (with optional edits), `reject(reason)`, `email_word_count()`, `linkedin_char_count()`.

### [models/__init__.py](models/__init__.py)
Re-exports everything so pages can do `from models import EnrichmentResult` instead of `from models.enrichment import EnrichmentResult`.

---

## 3. Layer 2 — `config.py`

[config.py](config.py) is the single source of truth for every constant in the project. It loads `.env` once via `python-dotenv` and exposes:

- **API credentials** — `HF_TOKEN`, `APOLLO_API_KEY`, `PROXYCURL_API_KEY`, `NEWSAPI_KEY`
- **Availability flags** — `HF_AVAILABLE`, `APOLLO_AVAILABLE`, etc. (just `bool(KEY)`)
- **HuggingFace settings** — model URLs, timeouts, generation parameters (temperature, max_new_tokens)
- **Scoring constants** — `SCORING_LABEL_PAIRS` (the six positive/negative label pairs), `SECTOR_SIGNAL_WEIGHTS`, `TIER_HOT` (75), `TIER_WARM` (50), `SIGNAL_STRONG` (65), `SIGNAL_WEAK` (40)
- **Trigger signals** — `TRIGGER_SIGNAL_DEFINITIONS` maps trigger names to UI labels and the enrichment fields they check
- **Mistral prompt templates** — `BRIEFING_SYSTEM_PROMPT`, `EMAIL_SYSTEM_PROMPT`, `LINKEDIN_SYSTEM_PROMPT`, `FOLLOWUP_SYSTEM_PROMPT`
- **UI constants** — `SECTOR_OPTIONS`, `GEOGRAPHY_OPTIONS`, `COMPANY_STAGE_OPTIONS`, `TIER_CONFIG`, `AGENCY_COLOR`, `APP_TITLE`, `APP_ICON`
- **Time savings** — `MANUAL_TIME_PER_PROSPECT`, `SYSTEM_TIME_PER_PROSPECT`
- **Salesforce export field map** — `SALESFORCE_EXPORT_FIELDS` maps internal field names to Salesforce Engage column headers
- **`FORCE_MOCK_MODE`** flag

Everything else in the project imports `config` and reads from it. **Tuning the system is almost entirely a matter of editing `config.py`** — change a prompt, a weight, a threshold, a label pair, and the next pipeline run uses it.

---

## 4. Layer 3 — `mock_data/`

Pre-built realistic records for demo mode. Three hand-picked prospects engineered to demonstrate the full range of tier outcomes.

### [mock_data/prospects.py](mock_data/prospects.py)
Three `Prospect` instances:

| Constant | Company | Sector | Expected score |
|---|---|---|---|
| `HEALTHAXIS` | HealthAxis (health tech, Series B) | Healthcare | **Hot** 🔥 |
| `MERIDIAN_ANALYTICS` | Meridian Analytics (data infra, Series C) | Tech | **Warm** ☀️ |
| `VANTAGE_CAPITAL` | Vantage Capital Partners (PE) | Financial services | **Warm/Hot** |

Plus `ALL_MOCK_PROSPECTS`, `MOCK_PROSPECT_BY_DOMAIN`, `get_mock_prospect(domain)`, `get_all_mock_prospects()`.

### [mock_data/enrichment.py](mock_data/enrichment.py)
One fully-populated `EnrichmentResult` for each mock prospect (`HEALTHAXIS_ENRICHMENT`, `MERIDIAN_ENRICHMENT`, `VANTAGE_ENRICHMENT`). Includes pre-baked `hf_description` so the scorer can run immediately without re-computing fields. Plus `get_mock_enrichment(prospect_id)`.

### [mock_data/icp_profiles.py](mock_data/icp_profiles.py)
Three `ICPProfile` instances (`HEALTHCARE_NYC`, `TECH_NYC`, `FINSERV_NYC`) wired to the matching sector weight presets and tone rules. Plus `get_all_mock_profiles()` and `get_active_mock_profile()`.

### [mock_data/__init__.py](mock_data/__init__.py)
Re-exports all three mock prospects, all three enrichments, all three profiles, and the lookup functions.

---

## 5. Layer 4 — `connectors/`

Wrappers around real third-party APIs. Each connector:

1. Reads its API key from `config.py`
2. Sets `self.available = config.X_AVAILABLE and not config.FORCE_MOCK_MODE`
3. Falls back to safe defaults (mock data for Apollo's search; empty results for Proxycurl and NewsAPI) when unavailable
4. Implements exponential backoff (3 retries, doubling wait) for 429 rate-limit responses
5. Returns dataclass instances (`Prospect`, `JobPosting`, `NewsSignal`) — never raw dicts to upstream code

### [connectors/apollo.py](connectors/apollo.py)
`ApolloConnector` — wraps the Apollo.io API.

- **`search_prospects(icp, max_results)`** → `list[Prospect]`. Builds a search payload from the ICP (titles, geographies, headcount range, funding stages), POSTs `/mixed_people/search`, converts each result via `Prospect.from_apollo_record`, applies ICP exclusions.
- **`enrich_org(domain)`** → `dict`. GETs `/organizations/enrich` for deeper firmographics: founded year, description, technologies, headcount history.

Private helpers: `_build_search_payload`, `_passes_exclusions`, `_post_with_retry`, `_get_with_retry`.

### [connectors/proxycurl.py](connectors/proxycurl.py)
`ProxycurlConnector` — wraps Proxycurl for LinkedIn data.

- **`get_job_postings(linkedin_url, target_geo)`** → `list[JobPosting]`. Detects office-related roles via `OFFICE_ROLE_KEYWORDS` (e.g. "office manager", "workplace", "facilities").
- **`get_company_profile(linkedin_url)`** → `dict`. Follower count, employee count, description, HQ.
- **`get_hiring_summary(linkedin_url, target_geo, headcount)`** → `dict` — combines the above into the single call `pipeline/enrichment.py` uses. Computes velocity = `(jobs / headcount) * 100`.

### [connectors/newsapi.py](connectors/newsapi.py)
`NewsAPIConnector` — wraps NewsAPI.

- **`get_company_signals(company_name, days)`** → `list[NewsSignal]`. Searches `/everything`, runs `_detect_signal_type` over each article's headline + excerpt to classify it as `expansion`, `relocation`, `office`, `funding`, or `hiring`. Discards articles with no CRE signal.
- **`get_signals_summary(company_name, days)`** → `dict` — used by `pipeline/enrichment.py`. Picks the "strongest" signal by `SIGNAL_PRIORITY` (expansion > relocation > office > funding > hiring).

### [connectors/__init__.py](connectors/__init__.py)
Re-exports `ApolloConnector`, `ProxycurlConnector`, `NewsAPIConnector`.

---

## 6. Layer 5 — `hf_models/`

HuggingFace Inference API wrappers. One class per task. Each class:

1. Builds a URL from `config.HF_API_BASE + config.<MODEL_NAME>`
2. POSTs JSON with `Authorization: Bearer ${HF_TOKEN}` header
3. Handles 503 "model loading" by sleeping 20s and retrying once
4. Falls back to deterministic logic (rule-based scoring or template drafts) on any failure

### [hf_models/scorer.py](hf_models/scorer.py)
`ProspectScorer` — scores an `EnrichmentResult` against an `ICPProfile`.

`score(enrichment, icp)` → `ScoreResult`. Flow:

1. Takes the `hf_description` paragraph that `pipeline/enrichment.py` built
2. Flattens `config.SCORING_LABEL_PAIRS` (6 positive/negative pairs) into 12 labels
3. Sends ALL 12 to `facebook/bart-large-mnli` in one request with `multi_label=False`
4. Receives `{labels: [...], scores: [...]}` (HF reorders by score, so we zip into a dict for name-based lookup)
5. For each pair: dimension_score = `(positive_conf / (positive_conf + negative_conf)) * 100`
6. First five pairs map to `hiring_velocity_score`, `funding_timing_score`, `expansion_news_score`, `lease_expiry_score`, `decision_maker_score`. Sixth pair (overall space need) is used for validation only — not weighted into the composite.
7. Composite = weighted average of the five dimensions using `icp.signal_weights`
8. Tier from `TIER_HOT` (≥75) / `TIER_WARM` (≥50) / Nurture
9. `_extract_signals()` builds positive bullets (dim ≥ 65) and risk bullets (dim ≤ 40)
10. `_identify_top_signal()` picks the highest-scoring dimension for the email opening hook

Fallback `_populate_from_rules()` produces sensible scores from computed enrichment fields (deployment window, hiring velocity, has_expansion_news, etc.) without any model call.

### [hf_models/briefer.py](hf_models/briefer.py)
`ProspectBriefer` — generates the 5-bullet research brief.

`generate_brief(prospect, enrichment, score)` → `list[str]`. Flow:

1. Builds a `[INST]…[/INST]` Mistral prompt using `config.BRIEFING_SYSTEM_PROMPT` plus all the enrichment facts (funding line, headcount line, jobs line, news line, score line)
2. POSTs to `mistralai/Mistral-7B-Instruct-v0.2` with `temperature=0.4` (low — factual)
3. `_parse_bullets()` extracts bullets handling multiple formats (•, -, 1., **Category:** ...)
4. Returns the first 5 (or falls back if fewer than 3 came back)

Fallback `_rule_based_brief()` constructs the 5 bullets directly from enrichment fields with rule-based phrasing — never as good as the model but always informative.

### [hf_models/writer.py](hf_models/writer.py)
`OutreachWriter` — generates the email + LinkedIn copy.

Three public methods:
- **`generate_email(prospect, enrichment, score, icp, brief)`** → `(subject, body)`
- **`generate_linkedin(prospect, enrichment, score, icp)`** → `str` (≤300 chars)
- **`generate_followup(prospect, enrichment, score, icp)`** → `(subject, body)` for day-5 follow-up

Prompt construction layers three things into every call:
1. The fixed system prompt from `config` (`EMAIL_SYSTEM_PROMPT`, `LINKEDIN_SYSTEM_PROMPT`, `FOLLOWUP_SYSTEM_PROMPT`) — non-negotiable rules
2. `icp.get_tone_prompt_block()` — profile-specific tone (forbidden phrases, sign-off, word limits)
3. `icp.get_system_prompt_rules()` — rules learned from past approve/reject decisions

`_get_top_signal_sentence()` builds the one-sentence opening hook based on `score.top_signal_type` — different phrasing for expansion news vs hiring velocity vs funding timing vs lease expiry.

Fallback templates (`_fallback_email`, `_fallback_linkedin`, `_fallback_followup`) rotate through multiple subject/opening/middle/closing variants using `random.choice()` so successive regenerations produce visibly different copy even without a live model.

### [hf_models/__init__.py](hf_models/__init__.py)
Re-exports `ProspectScorer`, `ProspectBriefer`, `OutreachWriter`.

---

## 7. Layer 6 — `pipeline/`

The orchestration layer. **Pages only ever talk to pipeline.** Pipeline functions are the only place that combines connectors + hf_models + models. This layer is where business logic lives.

### [pipeline/ingestion.py](pipeline/ingestion.py)
`IngestionPipeline.ingest(source, icp, existing_domains, csv_content, max_results)` — returns a list of `Prospect` instances. Source can be `"apollo"`, `"csv"`, or `"mock"`.

- `_from_apollo` calls `ApolloConnector.search_prospects`
- `_from_csv` parses a CSV string into `Prospect` records (lowercased column lookup, skips rows without a domain) — also used by [pages/1_icp_setup.py](pages/1_icp_setup.py) directly when the user uploads a CSV
- `_from_mock` returns the three pre-built mock prospects

Deduplicates by domain against `existing_domains`. Sets `icp_profile_name` on each returned prospect.

### [pipeline/enrichment.py](pipeline/enrichment.py)
`EnrichmentPipeline.enrich(prospect, icp)` — runs the three-source waterfall and returns a fully-populated `EnrichmentResult`.

Flow:
1. If `FORCE_MOCK_MODE`: return `get_mock_enrichment(prospect.domain)` directly, advance prospect to `"enriched"`, done
2. Otherwise, instantiate an empty `EnrichmentResult` and run three sources in sequence:
   - `_run_apollo(result, prospect)` — calls `ApolloConnector.enrich_org`, populates Apollo block
   - `_run_proxycurl(result, prospect, icp)` — calls `ProxycurlConnector.get_hiring_summary`, populates Proxycurl block
   - `_run_newsapi(result, prospect)` — calls `NewsAPIConnector.get_signals_summary`, populates NewsAPI block
3. Compute derived fields in order:
   - `result.compute_headcount_growth()`
   - `result.compute_hiring_velocity()`
   - `months = prospect.funding_months_ago()` → `result.months_since_funding`, `result.is_in_deployment_window`
   - `result.check_triggers(icp.trigger_signals, months)`
   - `result.build_hf_description(prospect)` — natural language paragraph for the scorer
4. `prospect.advance_status("enriched")`

The private `_run_*` methods append source names to `result.sources_used` (success) or `result.sources_failed` (failure). They handle missing API keys, missing LinkedIn URLs, and request exceptions without raising — pipeline always produces an `EnrichmentResult`, never throws.

**[pages/2_prospect_found.py](pages/2_prospect_found.py) calls the private `_run_*` methods directly**, not the public `enrich()` method. This is intentional — it makes the waterfall visible in the UI with individual spinners and per-source result panels. The compute and check_triggers calls happen at the end of the live branch, matching what `enrich()` would do.

### [pipeline/scoring.py](pipeline/scoring.py)
`ScoringPipeline` — thin orchestration wrapper around `ProspectScorer`.

`score(prospect, enrichment, icp)` → `ScoreResult`. Flow:
1. Call `ProspectScorer.score(enrichment, icp)` (note: scorer doesn't need the prospect)
2. `prospect.advance_status("scored")` on success
3. On any exception: log + return a safe Nurture-tier default `ScoreResult` so the demo never crashes

This wrapper exists so pages have a consistent `(prospect, enrichment, icp) → ScoreResult` interface and don't need to know about `hf_models` internals.

### [pipeline/drafting.py](pipeline/drafting.py)
`DraftingPipeline.draft(prospect, enrichment, score, icp)` → `DraftResult`.

Six steps:
1. Generate research brief via `ProspectBriefer.generate_brief` — falls back to hardcoded bullets if the brief call raises
2. Generate email via `OutreachWriter.generate_email` — falls back to `_fallback_email` on exception
3. Generate LinkedIn via `OutreachWriter.generate_linkedin` — falls back to `_fallback_linkedin` on exception
4. `_build_tags(enrichment, score)` — assembles the chip list shown in the UI (📈 headcount growth, 💼 jobs, 🏢 office roles, 💰 deployment window, 📰 expansion, 💵 funding, 🔍 news headline, ⭐ top signal)
5. `result.opening_signal = writer._get_top_signal_sentence(...)` — the one-line hook
6. `prospect.advance_status("drafted")`

### [pipeline/audit.py](pipeline/audit.py)
`AuditBuilder` — pure logic, no API calls.

- **`build_log(timestamps, sources_used, sources_failed, score_composite, tier, used_hf)`** → `list[dict]`. Pairs `*_start` / `*_end` timestamp keys, computes durations in ms, formats result text per step (✅ success, ⚠️ failure with reason, model used).
- **`calculate_time_savings(prospect_count)`** → `dict` of metrics. Combines `MANUAL_TIME_PER_PROSPECT` and `SYSTEM_TIME_PER_PROSPECT` from config into per-prospect, session, and weekly figures (at 15–20 prospects/week).
- **`build_salesforce_csv(prospects_data)`** → CSV string ready for Salesforce import. Maps internal fields to Salesforce columns per `config.SALESFORCE_EXPORT_FIELDS`. Uses `getattr()` on dataclass instances throughout.

### [pipeline/__init__.py](pipeline/__init__.py)
Re-exports all five pipeline classes: `IngestionPipeline`, `EnrichmentPipeline`, `ScoringPipeline`, `DraftingPipeline`, `AuditBuilder`.

---

## 8. Layer 7 — `pages/` and `app.py`

The Streamlit UI. Four wizard pages plus the home/entry-point.

### [app.py](app.py)
- Calls `st.set_page_config` with `APP_TITLE`, `APP_ICON`
- Defines `DEFAULTS` dict — **every session state key any page reads must be initialised here** (missing keys would crash on first load)
- On first run: loads mock profiles, sets the first as `active_profile`
- Renders the sidebar (active profile indicator, navigation, API status dots, session counter)
- Renders the home page: profile switcher cards, "Start a pipeline run" CTA, session summary metrics, the seven-step pipeline diagram

### [pages/1_icp_setup.py](pages/1_icp_setup.py)
**Step 1 — define ICP, select prospect.**

Three blocks:
1. **Profile switcher** (left column) — clickable cards for each saved profile. Switching writes `active_profile` to session state and resets the current prospect.
2. **Profile form** (right column) — three tabs: Overview (targeting + triggers + exclusions), Signal weights (Plotly horizontal bar chart from `profile.signal_weights`), Decision history (total decisions, approval rate, learned rules). A "Create new profile" form is available.
3. **Prospect selector** (bottom) — selectbox combining `get_all_mock_prospects()` with any prospects uploaded via CSV (parsed through `IngestionPipeline()._from_csv` and stored in `st.session_state.uploaded_prospects`). Click "Run this prospect" → resets all pipeline session keys → `st.switch_page("pages/2_prospect_found.py")`.

### [pages/2_prospect_found.py](pages/2_prospect_found.py)
**Step 2 — enrichment + scoring.**

Guard: bounces back to step 1 if no `current_prospect`. Then:

1. **Profile card** — initials avatar, contact details, company line, funding line
2. **Enrichment**:
   - If `FORCE_MOCK_MODE`: loads `get_mock_enrichment(prospect.domain)`, fills all timestamps to now, shows summary metrics
   - Else: runs three expanders, one per source, each calling the matching private `EnrichmentPipeline._run_*` method directly so the spinners are visible. After all three: computes derived fields, calls `check_triggers`, `build_hf_description`, advances prospect status.
3. **Scoring** — calls `ScoringPipeline().score(prospect, enrichment, profile)` under a spinner
4. **Score display** — composite hero with tier colour/emoji, per-dimension metrics with progress bars, positive vs risk signal lists, raw confidence chart (Plotly), the exact text sent to the model (collapsible)
5. **Nav** — back / next buttons

Writes `current_enrichment`, `current_score`, `current_timestamps` to session state.

### [pages/3_draft_review.py](pages/3_draft_review.py)
**Step 3 — review and approve.**

Guard: bounces back if no `current_prospect` / enrichment / score. Then:

1. **Draft generation** — if `current_draft` is None, calls `DraftingPipeline().draft(prospect, enrichment, score, profile)` under a spinner, fills `briefing_*` and `writing_*` timestamps. Shows a `st.toast` if the user just clicked Regenerate.
2. **Research brief** — renders the 5 brief bullets, the opening hook callout, the personalisation chips
3. **Email tab** — `text_input` for subject (keyed `email_subject_input`), `text_area` for body (keyed `email_body_input`), word count indicator coloured by length
4. **LinkedIn tab** — `text_area` for message (keyed `linkedin_input`), character count, dark "phone" preview mockup
5. **Regenerate button** — sets `current_draft = None`, **pops the three widget-bound keys** so the text fields refresh from the new draft's `value=` parameter (otherwise Streamlit's session-state persistence would keep showing the stale text), sets a flag for the toast, reruns
6. **Approve** — reads current widget values, calls `draft.approve(edited_body, edited_subject, edited_linkedin)`, records `profile.record_approval` (with `enrichment.triggers_fired`) and `profile.record_edit` if edits were made, appends the result to `st.session_state.all_results` (as dicts via `.to_dict()`), switches to page 4
7. **Reject** — calls `draft.reject(reason)`, calls `profile.record_rejection`, clears the current run, returns to page 1

### [pages/4_audit_summary.py](pages/4_audit_summary.py)
**Step 4 — audit log + Salesforce export.**

1. **Audit log** — calls `AuditBuilder.build_log(...)` from the session timestamps. Renders as a `pd.DataFrame` with columns Time / Action / Result / Duration. Falls back to a mock log if no timestamps exist.
2. **Time savings** — calls `AuditBuilder.calculate_time_savings(...)`. Renders four metric cards and a per-step manual-vs-system bar chart (Plotly).
3. **Approved outreach preview** — side-by-side email + LinkedIn cards. Uses the local `_get(obj, attr, default)` helper that handles both dataclass instances and dicts (because `all_results` items are dicts but the active draft is a dataclass).
4. **Salesforce CSV download** — `AuditBuilder.build_salesforce_csv([...])` produces the string; `st.download_button` serves it.
5. **Nav** — back / run another / home buttons. "Run another" resets all `current_*` keys to empty.

The `_get` helper is the bridge between two storage conventions: the **active** prospect/enrichment/score/draft live in session state as dataclass instances, while items in `all_results` are stored as dicts (because `page 3` calls `.to_dict()` before appending). Both must be readable from this page.

---

## 9. Data flow — one prospect, end to end

```
User selects HEALTHAXIS on page 1
    ↓
st.session_state.current_prospect = HEALTHAXIS (Prospect instance)
st.session_state.pipeline_step = 2
st.switch_page("pages/2_prospect_found.py")
    ↓
page 2 runs EnrichmentPipeline:
  ApolloConnector.enrich_org → fills Apollo block of EnrichmentResult
  ProxycurlConnector.get_hiring_summary → fills Proxycurl block
  NewsAPIConnector.get_signals_summary → fills NewsAPI block
  compute_headcount_growth / compute_hiring_velocity
  check_triggers(profile.trigger_signals, months)
  build_hf_description(prospect)  →  natural language paragraph
prospect.advance_status("enriched")
    ↓
st.session_state.current_enrichment = EnrichmentResult instance
    ↓
page 2 runs ScoringPipeline:
  ProspectScorer.score(enrichment, icp):
    POST hf_description + 12 candidate labels to bart-large-mnli
    receive {labels: [...], scores: [...]}
    normalise each pair to 0-100, weight, tier
    extract positive/risk signal bullets
    identify top_signal_type for the email opener
prospect.advance_status("scored")
    ↓
st.session_state.current_score = ScoreResult instance
    ↓
User clicks "Next → Generate drafts" → switches to page 3
    ↓
page 3 runs DraftingPipeline:
  ProspectBriefer.generate_brief → 5 bullets via Mistral-7B
  OutreachWriter.generate_email → (subject, body) via Mistral-7B
  OutreachWriter.generate_linkedin → message via Mistral-7B
  build personalisation tags
  set opening_signal
prospect.advance_status("drafted")
    ↓
st.session_state.current_draft = DraftResult instance
    ↓
User edits subject/body/LinkedIn text in the widgets, clicks Approve
    ↓
draft.approve(edited_subject, edited_body, edited_linkedin)
  → sets approval_status, was_edited, final_* fields
profile.record_approval(prospect.domain, enrichment.triggers_fired)
profile.record_edit(...) if edited
st.session_state.all_results.append({
  "prospect":   prospect.to_dict(),
  "enrichment": enrichment.to_dict(),
  "score":      score.to_dict(),
  "draft":      draft.to_dict(),
})
    ↓
switch to page 4
    ↓
page 4 builds:
  AuditBuilder.build_log(timestamps, sources_used, sources_failed, ...) → DataFrame
  AuditBuilder.calculate_time_savings(1) → metrics + bar chart
  AuditBuilder.build_salesforce_csv([{prospect, score, draft}]) → CSV download
```

---

## 10. Session state contract

Every key any page reads is defined in `DEFAULTS` at the top of [app.py](app.py). If you add a new key, **add it to `DEFAULTS` first** or the first page that reads it will throw `AttributeError` on a cold load.

| Key | Type | Set by | Read by |
|---|---|---|---|
| `active_profile` | `ICPProfile` | app.py initial load, pages 1 (switch) | pages 1, 2, 3, sidebar |
| `all_profiles` | `list[ICPProfile]` | app.py initial load, page 1 (create new) | app.py, page 1 |
| `current_prospect` | `Prospect` | page 1 (select) | pages 2, 3, 4 |
| `current_enrichment` | `EnrichmentResult` | page 2 | pages 2, 3, 4 |
| `current_score` | `ScoreResult` | page 2 | pages 2, 3, 4 |
| `current_draft` | `DraftResult` | page 3 | pages 3, 4 |
| `current_timestamps` | `dict[str, str]` | pages 2, 3 | page 4 |
| `current_audit_log` | `list[dict]` | (reserved — currently unused, page 4 builds on demand) | — |
| `all_results` | `list[dict]` | page 3 (on approve) | app.py, page 4 |
| `pipeline_step` | `int` | pages 1–4 | — |
| `demo_mode` | `bool` | app.py | sidebar |
| `uploaded_prospects` | `list[Prospect]` | page 1 (CSV upload) | page 1 |
| `csv_content` / `csv_file_key` | `str` | page 1 (CSV upload) | page 1 |
| `creating_new_profile` | `bool` | page 1 | page 1 |
| `email_subject_input` / `email_body_input` / `linkedin_input` | `str` | page 3 widgets | page 3 |
| `rejection_reason` | `str` | page 3 widget | page 3 |
| `just_regenerated` | `bool` | page 3 (button) | page 3 (toast) |

Two **storage conventions** coexist:

- The **active** run (`current_prospect`, `current_enrichment`, `current_score`, `current_draft`) stores **dataclass instances** directly. Pages read these with attribute access (`prospect.domain`) or `getattr()`.
- The **historical** `all_results` list stores **dicts** (created via `.to_dict()` on each model). Pages reading from `all_results` use `.get()` accordingly.

Page 4 has a small `_get(obj, attr, default)` helper that handles both — necessary because it reads the active draft (dataclass) and old session results (dicts) from the same code path.

---

## 11. Mock vs live mode — the fallback ladder

Every API touchpoint has a graceful fallback. The system runs end-to-end with **zero API keys**.

```
config.FORCE_MOCK_MODE = true
    ↓
ALL connectors and HF models return False from .available
    ↓
ApolloConnector.search_prospects     → get_all_mock_prospects()
ApolloConnector.enrich_org           → {}
ProxycurlConnector.get_hiring_summary → returns dict of zeros / empty lists
NewsAPIConnector.get_signals_summary → returns dict of zeros / empty lists
    ↓
pipeline/enrichment.py: enrich() returns get_mock_enrichment(domain)
                       (the page 2 manual waterfall has its own mock shortcut)
    ↓
ProspectScorer.score → _populate_from_rules() — rule-based scoring
ProspectBriefer.generate_brief → _rule_based_brief() — bullets from enrichment fields
OutreachWriter.generate_email → _fallback_email() — randomised template
OutreachWriter.generate_linkedin → _fallback_linkedin() — randomised template
```

Per-source fallback also works: if `HF_TOKEN` is set but `APOLLO_API_KEY` is not, scoring and drafting are live but enrichment uses mock Apollo data while still calling live Proxycurl and NewsAPI.

---

## 12. Where to make common changes

| You want to… | Edit |
|---|---|
| Tune scoring weights for a sector | `SECTOR_SIGNAL_WEIGHTS` in [config.py](config.py) |
| Change the tier thresholds | `TIER_HOT` / `TIER_WARM` / `SIGNAL_STRONG` / `SIGNAL_WEAK` in [config.py](config.py) |
| Add a new trigger signal | Append to `TRIGGER_SIGNAL_DEFINITIONS` in [config.py](config.py); add the check in `EnrichmentResult.check_triggers` in [models/enrichment.py](models/enrichment.py) |
| Change the scoring labels | `SCORING_LABEL_PAIRS` in [config.py](config.py) — order must match `SCORING_DIMENSIONS` |
| Tweak the email tone | `EMAIL_SYSTEM_PROMPT` in [config.py](config.py) or the `tone_rules` dict on the active `ICPProfile` |
| Add a new mock prospect | [mock_data/prospects.py](mock_data/prospects.py) + matching enrichment in [mock_data/enrichment.py](mock_data/enrichment.py) |
| Change the Salesforce export columns | `SALESFORCE_EXPORT_FIELDS` in [config.py](config.py) + matching row construction in [pipeline/audit.py](pipeline/audit.py) |
| Switch HuggingFace models | `SCORING_MODEL` / `WRITING_MODEL` / `BRIEFING_MODEL` in [config.py](config.py) |
| Adjust manual-time baselines for the savings calc | `MANUAL_TIME_PER_PROSPECT` / `SYSTEM_TIME_PER_PROSPECT` in [config.py](config.py) |
| Add a UI sidebar widget | [app.py](app.py) sidebar block |
| Add a new wizard page | Create `pages/N_*.py`; add the key it reads to `DEFAULTS` in [app.py](app.py); add navigation in the sidebar |

The architectural rule of thumb: **if you're tempted to call a connector or hf_model from a page, route it through a pipeline class instead**. Keep pages thin.
