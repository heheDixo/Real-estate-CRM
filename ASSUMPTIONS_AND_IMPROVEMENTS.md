# CRE Outreach Intelligence — Assumptions, Limitations, and Future Improvements

This is a working prototype of an overnight research agent for tenant rep brokers. The cron runs at 05:00 ET, scrapes free signal sources, scores prospects via HuggingFace `facebook/bart-large-mnli`, drafts outreach with `mistralai/Mistral-7B-Instruct-v0.2`, and pushes drafts to Gmail. The broker reviews and sends manually.

This document captures the assumptions baked into that pipeline, the current limitations, and what production-grade improvements would look like.

---

## Current state

- **Real:** scraping (Google News RSS, NewsAPI free tier, Firecrawl), HuggingFace inference (router endpoint), Gmail Drafts + send, Google Sheets logging, Google Calendar follow-ups, watchlist persistence, tone learning archive.
- **Mock-free:** there is no `mock_data/` module any more. The watchlist seeds three real NYC companies (Oscar Health, Ramp, Notion Labs) so a first run produces real signals immediately.
- **Removed:** Apollo, Proxycurl, LinkedIn scraping, Salesforce export, the four-step wizard, the per-source mock fallback layer (only the per-prospect `_mock_fallback` inside `research_agent` remains, and only fires when scrapers + bart-mnli both come back empty).

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

### 5. Mistral's output is consistent enough

Mistral-7B on the free HuggingFace Inference API is not the same as running the same model with carefully tuned inference settings. Output varies. The writer's `_parse_email()` looks for `Subject:` on line 1; when Mistral returns malformed output the system falls back to a template. That fallback is good enough for the prototype but not on-brand enough for production.

### 6. The broker is the ground truth

Every approval, every edit, every "Send now" is recorded by `tone_learner.archive_sent_draft()`. The system treats the broker's edits as the calibration target. This is intentional — but it also means a single bad week of edits will start steering the writer in the wrong direction. There is no smoothing or outlier rejection.

### 7. Watchlist contacts are accurate

`data/watchlist.json` carries the broker's chosen decision-maker per company. The system does not re-verify the contact. If the contact changes jobs the draft still goes to the old address.

### 8. The HuggingFace router stays up

`config.HF_API_BASE = "https://router.huggingface.co/hf-inference/models"` is the only inference path. There is no second provider. When the router is down (or has rate-limited the token) every prospect falls back to the per-prospect mock, which produces a `score=20` skip.

### 9. Free-tier quotas hold

NewsAPI free tier: ~100 requests/day. Firecrawl free tier: limited monthly credits. HuggingFace free Inference: rate-limited per token. The pipeline assumes these limits are not exceeded by one morning run over a watchlist of ~20 prospects. At the limit it would need a paid tier or local model hosting.

---

## Limitations

### 1. No persistence beyond JSON files

Everything lives under `data/`. Run JSON, OAuth tokens, error logs, progress files. There is no Postgres / SQLite layer; there is no concurrent-write protection beyond the implicit single-process model. Two morning runs starting at the same time would race on `data/morning_run_<date>.json`.

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

### 7. No graceful degradation for the HF rate limit

The `_classify` retry path waits 20s on 503 and retries once. There is no exponential back-off, no second provider, no local model fallback. Under sustained HF outages the pipeline emits zero real signals and the day is effectively lost (every prospect skipped via `_mock_fallback`).

### 8. No multi-user / multi-broker support

The pipeline is single-tenant. All state lives at the project root. `BROKER_EMAIL` is a single config value. There is no notion of "broker A's watchlist vs broker B's".

### 9. No instrumentation beyond JSON logs

`data/error_log.json` and `data/scheduler_log.json` carry the basics. There is no Sentry, no structured tracing, no per-prospect timing breakdown. Debugging a slow morning run means reading two JSON files and squinting at the timestamps.

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

### Medium-term (1–2 months)

6. **Tone learning loop** — weekly job reads `data/tone_archive.json`, extracts patterns (preferred openers, banned phrases, sentence-length distribution), updates `data/tone_profile.json`. Surface the proposed change to the broker before applying.
7. **Compound-signal scoring** — replace the linear weighted mean with a learnt model trained on the broker's approve/skip history. Cold-start with the current formula; switch once enough labelled examples exist.
8. **Real database** — move from JSON files to SQLite (or Postgres if multi-broker). Schema mirrors the current `ResearchReport` / `Signal` dataclasses. Concurrent writes become safe.
9. **Per-source confidence calibration** — Google News content vs Firecrawl-cleaned about page vs NewsAPI body have different baseline reliability. Each source should have a learnt prior that adjusts the bart-mnli score before composite.
10. **Follow-up draft generation** — when a Calendar reminder fires, automatically generate a follow-up draft using the original signal + "no reply yet" template. Land in Gmail Drafts the same way.

### Long-term (3+ months)

11. **Self-hosted Mistral** — eliminate the HF Inference dependency for drafting. Spinning Mistral-7B-Instruct on a single A10G is enough volume for a 20-prospect daily run.
12. **Self-hosted bart-mnli** — same logic for the scorer. Removes the per-request HF latency that bottlenecks parallel runs.
13. **Multi-broker tenant model** — proper user accounts, per-user watchlists, per-user tone profiles, shared signal cache.
14. **Closed-loop deal tracking** — after a send, track the prospect through reply → meeting booked → deal closed in the broker's CRM (Salesforce, HubSpot, whatever they use). Surface "predicted vs actual" delta on the scoring screen.
15. **Adversarial filtering** — train a small classifier specifically to detect bart-mnli's confident wrongs (the bland marketing copy → "hiring aggressively" 0.93 failure mode). Run as a post-filter on every signal.

---

## Out of scope (deliberately)

- **LinkedIn automation.** Posting / messaging via LinkedIn risks the broker's account. The LinkedIn message stays copy-paste, with the system providing the text and character-count enforcement.
- **Email open / click tracking pixels.** Open-rate tracking via pixels is increasingly unreliable (Apple Mail Privacy, corporate proxies). The system records sends; reply tracking is the more reliable signal.
- **Sending without broker approval.** The pipeline is explicitly review-before-send. Even with perfect drafts, every outbound goes through the broker.
- **Re-introducing Apollo / Proxycurl.** Both were removed because the free-source path produces enough signal for the prototype's use case. They could be added back if the broker subscribes, but the architecture should not depend on them.
- **A general-purpose CRM.** This is a research + outreach agent, not a CRM. Sheets is enough for the sent log; Calendar is enough for follow-ups. Anything richer belongs in the broker's existing CRM.
