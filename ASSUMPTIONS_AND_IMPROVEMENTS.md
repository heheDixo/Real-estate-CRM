# CRE Outreach Intelligence — Assumptions, Limitations, and Future Improvements

This is a working prototype of an overnight research agent for tenant rep brokers. The cron runs at 04:50 ET (HF model warm-up) and 05:00 ET (main pipeline), scrapes free signal sources, scores prospects via HuggingFace `facebook/bart-large-mnli`, drafts outreach with `meta-llama/Llama-3.1-8B-Instruct` (was Mistral-7B-Instruct-v0.2 until HF retired it from the free `hf-inference` provider in mid-2025), and pushes drafts to Gmail + a Telegram morning brief. The broker reviews and sends manually.

This document captures the assumptions baked into that pipeline, the current limitations, and what production-grade improvements would look like.

---

## Current state

- **Real:** scraping (Google News RSS, NewsAPI free tier, Firecrawl), HuggingFace inference (bart-mnli on `hf-inference`, Llama-3.1-8B on `/v1/chat/completions`), Gmail Drafts + send, Google Sheets logging, Google Calendar follow-ups, Google Docs per-prospect dossiers, watchlist persistence, tone learning archive, Supabase persistence, Google OAuth login, Telegram morning brief + alerts.
- **Mock-free:** there is no `mock_data/` module any more. The watchlist seeds three real NYC companies (Oscar Health, Ramp, Notion Labs) so a first run produces real signals immediately.
- **Removed:** Apollo, Proxycurl, LinkedIn scraping, Salesforce export, the four-step wizard, the per-source mock fallback layer (only the per-prospect `_mock_fallback` inside `research_agent` remains, and only fires when scrapers + bart-mnli both come back empty). Per-service `data/*_token.json` OAuth caches — replaced by `users.google_token` JSONB in Supabase.

---

## Assumptions

### 1. Signals are independent

bart-mnli evaluates each of the five labels independently when called with `multi_label=True`. In reality signals compound — a company that *raised funding* **and** *is hiring fast* **and** *announced a new office* is exponentially more likely to need space than the linear sum implies. The current composite (weighted mean of top-two + the rest) does not model that interaction.

### 2. Recent news ≈ current truth

The scrapers use a 7-day window. The assumption is that anything material to "do they need office space" surfaces in the trade press or company website within a week. False negatives exist (private leases never hit the news), as do false positives (a year-old funding round re-surfaced by a follow-on quote).

### 3. The website's about/news pages are honest signal

`scrapers/firecrawl_scraper.py` reads `/`, `/about`, `/news`. After `_clean_web_text()` strips chrome, the remaining prose is treated as evidence. This is true for companies that keep those pages current; less true for older sites where the about page hasn't been updated in two years.

### 4. bart-mnli is honest about confidence

When the model returns 0.93 for "company is hiring aggressively", the system trusts it. The phantom-suppression guard (drop the signal if `"Company website"` is the source and the body has zero label-keywords) is the only counter-measure. It catches the obvious case where bland marketing copy scores high on every label, but it doesn't catch subtler hallucinations.

### 5. Llama's output is consistent enough

Llama-3.1-8B via HuggingFace's routed `/v1/chat/completions` is not the same as running the model with carefully tuned inference settings. Output varies. The writer's `_parse_email()` looks for `Subject:` on line 1; when Llama returns malformed output (it doesn't always emit the subject line) the system falls back to the writer's default subject `"Quick thought on your NYC expansion"` plus the real body. Deeper fallback (full template draft) is `_build_fallback_draft` — used when the call returns empty entirely. That fallback is good enough for the prototype but not on-brand enough for production.

### 6. The broker is the ground truth

Every approval, every edit, every "Send now" is recorded by `tone_learner.archive_sent_draft()`. The system treats the broker's edits as the calibration target. This is intentional — but it also means a single bad week of edits will start steering the writer in the wrong direction. There is no smoothing or outlier rejection.

### 7. Watchlist contacts are accurate

`data/watchlist.json` carries the broker's chosen decision-maker per company. The system does not re-verify the contact. If the contact changes jobs the draft still goes to the old address.

### 8. The HuggingFace router stays up

Scoring goes through `config.HF_API_BASE` (`hf-inference` provider, CPU-class models only); drafting goes through `config.HF_CHAT_URL` (`/v1/chat/completions`, paid providers via routing). `hf_client` retries 3× with 2s/4s/8s backoff and caches scorer results in Supabase, so brief outages are absorbed. Sustained outages still degrade — every prospect falls back to either the per-prospect mock (`score=20`) or the template draft.

### 9. Free-tier quotas hold

NewsAPI free tier: ~100 requests/day. Firecrawl free tier: limited monthly credits. **HuggingFace Inference Providers: $0.10/mo free credits per HF account ($2.00/mo on PRO).** At 20 prospects/day × 2 LLM calls × 30 days ≈ $0.15-$0.30/mo — credits exhaust in roughly **3-5 days** of normal use. After that the writer returns empty and the template fallback takes over (drafts still land, just less personalised). At the limit it would need a paid tier or self-hosted models.

---

## Limitations

### 1. ~~No persistence beyond JSON files~~ — fixed in Phase 1

Supabase is now the source of truth (Phase 1). `database.py` wraps every CRUD operation with the pattern: try Supabase → on exception, fall back to local JSON. The per-run `data/morning_run_*.json` files still exist as offline mirrors. Concurrent writes are now safe.

**What's still true:** RLS is off (Phase 4.5 deferred). The pipeline is still single-tenant for now — adding a second broker needs the `user_id` column + RLS work described in [PROGRESS.md](PROGRESS.md) §8.

### 2. No learning *model* yet

`tone_learner.py` records the diff between the AI's draft and the broker's edited version. The diff is appended to `data/tone_archive.json`. The current `build_tone_injection()` compiles the tone profile into a `<TONE_RULES>` block — but the profile itself is hand-curated, not derived from the archive. The closing loop (a weekly job that mines the archive and updates the tone profile) is **not implemented**.

### 3. No reliable email-discovery for new leads

Discovered leads from `lead_discovery.py` carry the seed broker's address (`contact_email` defaults to the broker's own email). Hunter.io domain-search is wired up via `scrapers/hunter_verify.py` but the integration is best-effort — when Hunter has no match the lead reaches Page 3 with a blank email and the broker has to fill it in manually.

### 4. No A/B testing of tone variants

The broker can switch between Direct / Warm / Consultative in the draft-review screen and the writer regenerates. But the system does not record which variant was sent for which prospect, nor track reply rate per variant. Without that data the tone preference is the broker's gut, not the data.

### 5. No re-engagement logic

`pages/7_followups.py` reads Google Calendar for upcoming reminders. The broker can mark a follow-up as replied or delete it. But the system does not generate the follow-up draft automatically when the date comes due — it only schedules the reminder. Each follow-up is a new manual cycle.

### 6. No deduplication across runs

If the same article surfaces in both Google News and NewsAPI, the URL-based dedupe inside `_gather_signals` catches it. But if Tuesday's morning run and Wednesday's surface the same article a day apart, both runs will treat it as a fresh signal. A "we already saw this article" memory across runs would lift draft quality on day 2+.

### 7. ~~No graceful degradation for the HF rate limit~~ — improved in Phase 3

`hf_client` now retries every call 3× with 2s/4s/8s exponential backoff, caches scorer results in Supabase (`make_cache_key` on `text[:200]|labels`), and falls back to equal-distribution scores or template drafts when all retries fail. A 4:50am warm-up job pre-pings both models before the 5:00am pipeline. **What's still true:** there is no second inference provider — if the HF router itself goes down across all providers, the template fallback is the only path. Self-hosted Mistral / Llama would close that gap.

### 8. No multi-user / multi-broker support

The pipeline is single-tenant. Tenant-scoped tables have no `user_id` column yet (RLS is off — deferred to Phase 4.5). `BROKER_EMAIL` and `AGENT_NAME` are single config values. Google OAuth + the email whitelist gate access to one broker today; the schema is ready to support more once Phase 4.5 lands the `user_id` columns and RLS policies.

### 9. No instrumentation beyond JSON logs + email alerts + Telegram alerts

`data/error_log.json` and `data/scheduler_log.json` carry the basics. Pipeline-run rows in Supabase (`pipeline_runs` table) give a coarser audit trail. `monitoring.send_alert` emails the broker on pipeline / warm-up failure (Phase 3); `telegram_bot.send_pipeline_failed_alert` mirrors that to Telegram (Phase 4). There is still no Sentry, no structured tracing, no per-prospect timing breakdown.

### 10. The signal-card text is only as good as the article body

`_snippet_for_label()` picks the sentence with the matching keyword. If the article is one long paragraph with no clear sentence boundaries (lots of news copy is), the snippet falls back to the first sentence, which may not be the most relevant one. A proper extractive summariser would do better — but at the cost of another HF call per article.

---

## Future improvements

### Near-term (1–2 weeks)

1. **Per-prospect article memory** — track which URLs we've already shown the broker; surface new articles as "new since last run" badges; suppress repeats.
2. **Variant tracking** — record which tone variant was sent per prospect. Join with reply data from `google_sheets.list_sent` to compute per-variant reply rate.
3. **Hunter.io fallback chain** — try Hunter first, then domain-pattern guess (`{first}.{last}@{domain}`), then verify with `mailgun-validate` if available.
4. **Discovered-lead persistence** — auto-promote discovered leads the broker approved into the watchlist on the next run instead of requiring a manual click.
5. **Sentry-style error surfacing** — turn the existing `_log_error` into structured events with severity tagging so the UI can show "3 prospects failed enrichment" rather than the broker having to open `data/error_log.json`.
6. **Tighten `_parse_email` for Llama** — Llama doesn't always emit `Subject:` on line 1, so `_parse_email` occasionally falls back to the default subject. A clearer instruction in `writer._build_email_prompt` + `scheduler._generate_draft` fixes it.
7. **Gate the Telegram brief on `actionable > 0`** — currently fires on every clean run including `no_actionable` days. 2-line change in `scheduler.run_morning_pipeline_safe`.
8. **Reply-watcher wiring** — `telegram_bot.send_reply_notification` is exposed but not called. A daily Gmail thread scan + reply detector would close the loop.

### Medium-term (1–2 months)

9. **Tone learning loop** — weekly job reads `data/tone_archive.json`, extracts patterns (preferred openers, banned phrases, sentence-length distribution), updates `data/tone_profile.json`. Surface the proposed change to the broker before applying.
10. **Compound-signal scoring** — replace the linear weighted mean with a learnt model trained on the broker's approve/skip history. Cold-start with the current formula; switch once enough labelled examples exist.
11. **~~Real database~~** — ✅ done in Phase 1 (Supabase).
12. **Phase 4.5 — Row-Level Security** — add `user_id uuid references users(id)` to every tenant-scoped table, backfill, enable RLS, switch DB calls to use the user's JWT. Prerequisite for onboarding a second broker.
13. **Per-source confidence calibration** — Google News content vs Firecrawl-cleaned about page vs NewsAPI body have different baseline reliability. Each source should have a learnt prior that adjusts the bart-mnli score before composite.
14. **Follow-up draft generation** — when a Calendar reminder fires, automatically generate a follow-up draft using the original signal + "no reply yet" template. Land in Gmail Drafts the same way.

### Long-term (3+ months)

15. **Self-hosted writer (Mistral / Llama / Qwen)** — eliminate the HF Inference Providers dependency and its $0.10/mo credit ceiling for drafting. Spinning Llama-3.1-8B on a single A10G is enough volume for a 20-prospect daily run.
16. **Self-hosted bart-mnli** — same logic for the scorer. Removes the per-request HF latency that bottlenecks parallel runs.
17. **~~Multi-broker tenant model~~** — partially done: Google OAuth + `users` + `sessions` are in place (Phase 2). Per-user data isolation is the Phase 4.5 RLS work.
18. **Closed-loop deal tracking** — after a send, track the prospect through reply → meeting booked → deal closed in the broker's CRM (Salesforce, HubSpot, whatever they use). Surface "predicted vs actual" delta on the scoring screen.
19. **Adversarial filtering** — train a small classifier specifically to detect bart-mnli's confident wrongs (the bland marketing copy → "hiring aggressively" 0.93 failure mode). Run as a post-filter on every signal.

---

## Out of scope (deliberately)

- **LinkedIn automation.** Posting / messaging via LinkedIn risks the broker's account. The LinkedIn message stays copy-paste, with the system providing the text and character-count enforcement.
- **Email open / click tracking pixels.** Open-rate tracking via pixels is increasingly unreliable (Apple Mail Privacy, corporate proxies). The system records sends; reply tracking is the more reliable signal.
- **Sending without broker approval.** The pipeline is explicitly review-before-send. Even with perfect drafts, every outbound goes through the broker.
- **Re-introducing Apollo / Proxycurl.** Both were removed because the free-source path produces enough signal for the prototype's use case. They could be added back if the broker subscribes, but the architecture should not depend on them.
- **A general-purpose CRM.** This is a research + outreach agent, not a CRM. Sheets is enough for the sent log; Calendar is enough for follow-ups. Anything richer belongs in the broker's existing CRM.
