# CRE Outreach Intelligence — Prototype Documentation

## Assumptions, Limitations, and Future Improvements

---

## Current State

This prototype is a Streamlit-based demo of an AI-powered commercial real estate
tenant rep prospecting tool. It demonstrates the full pipeline workflow using
**mock enrichment data** and **real HuggingFace model inference**
(facebook/bart-large-mnli for scoring, Mistral-7B-Instruct for draft generation).

The three data sources — Apollo, Proxycurl, and NewsAPI — are simulated using
pre-built realistic prospect profiles. The AI scoring and draft generation are
real API calls to HuggingFace Inference API.

---

## Assumptions

### 1. Scoring model assumes signals are independent

The HuggingFace zero-shot classifier (`facebook/bart-large-mnli`) evaluates each
label pair against the prospect description independently. In reality, signals
compound — a company that raised funding AND is hiring fast AND announced an
expansion is not just the sum of three signals, it is exponentially more likely
to need space. The current weighted average composite does not capture that
compounding effect.

### 2. Signal weights are assumed from domain knowledge, not data

The healthcare profile weights hiring velocity at 35%, funding timing at 25%,
and so on. These numbers came from reasoning about how tenant rep deals actually
work — not from training on historical closed deals. In production the weights
would be calibrated against real won/lost deal data from the client's CRM.

### 3. Enrichment data assumes completeness

The mock data is fully populated — every field has a realistic value. Real
Apollo, Proxycurl, and NewsAPI calls will return incomplete records. Some
companies have no LinkedIn URL. Some have no recent news. Some have no funding
history. The production system needs robust handling of sparse data, which the
prototype does not fully demonstrate.

### 4. Outreach quality assumes a good HuggingFace response

Mistral-7B-Instruct on the free HuggingFace Inference API is not the same as
running the model with optimised inference settings. Output quality and
consistency vary. The prototype assumes the model returns coherent,
well-structured text — which it does most of the time but not always.

### 5. ICP profile assumes correct upfront configuration

The prototype has three pre-built profiles. In real use, a broker would need to
configure their own ICP from scratch. Bad ICP configuration produces bad scores.
The prototype does not validate whether the ICP definition makes sense.

---

## Limitations

### 1. No real API calls except HuggingFace

Apollo, Proxycurl, and NewsAPI are all mocked. The enrichment data — headcount
growth, job postings, news headlines — is pre-written in
`mock_data/enrichment.py`. It does not reflect any real company's actual current
state. The demo shows the workflow correctly but not real-world data quality or
coverage.

### 2. No persistence across sessions

Everything lives in Streamlit session state. Refresh the browser and all
decisions, scores, and drafts are gone. A production system needs a database
(Postgres) storing every lead, enrichment record, score, draft, and decision
permanently.

### 3. No learning model yet

The ICP profile has `record_approval()`, `record_rejection()`, and
`learned_rules` fields built into the dataclass. The infrastructure for the
learning loop is designed. But the actual pattern extraction — the weekly job
that reads decision history and produces plain-English rules — is not
implemented. The `learned_rules` list stays empty. In production this is the
feature that makes the system compound in value over time.

### 4. No real email or LinkedIn sending

The prototype generates drafts and shows them in the UI. Nothing actually sends.
A production system would integrate with SendGrid for email and provide a
structured LinkedIn copy-paste flow with character count enforcement.

### 5. No Salesforce write-back

The CSV export is Salesforce Engage formatted but requires manual import. Direct
API integration with Salesforce is not implemented — partly because corporate
policy may block it, as the client mentioned, and partly because it is production
infrastructure work that belongs after the demo is validated.

### 6. No follow-up sequence engine

The audit page mentions "a follow-up draft will be generated automatically in
the full system." That engine does not exist yet. Follow-ups are manually
initiated — the broker has to come back to the app and run the prospect again.

### 7. HuggingFace free tier is rate limited and slow

The Inference API cold-starts models that haven't been used recently. First call
can take 30–45 seconds. The free tier has usage limits that would be hit quickly
in production. A production system would use a paid inference endpoint or
self-hosted models.

### 8. No multi-user support

The app is single-user. One session, one browser, one pipeline run at a time. A
production system needs multi-tenant authentication, role-based access, and
workspace isolation so multiple brokers at the same firm can use it
simultaneously without seeing each other's data.

### 9. Signal monitoring is not implemented

The design describes a nightly job that watches 500+ companies and surfaces ones
that just crossed a trigger threshold. That job does not exist. The prototype is
reactive — you pick a company and run it. The production system should be
proactive — it tells you which companies just became worth contacting.

---

## Future Improvements

### Phase 1 — Real data layer (immediate next step)

| Improvement | Detail |
|---|---|
| Real Apollo enrichment | Connect live API — company headcount, funding history, contacts |
| Real Proxycurl enrichment | Live LinkedIn job postings and hiring velocity |
| Real NewsAPI signals | Live funding, expansion, and office news detection |
| CoStar / CompStak integration | Lease expiry data — hardest to get, most valuable for tenant rep |
| Sparse data handling | Graceful degradation when fields are missing from any source |

### Phase 2 — Persistence and learning (core production value)

| Improvement | Detail |
|---|---|
| Postgres database | Every lead, enrichment, score, draft, and decision stored permanently |
| Decision learning loop | Weekly job extracts approve/reject patterns into plain-English rules injected into scoring prompt |
| Tone calibration session | 10-email preference survey before first draft — removes cold-start quality problem |
| Score drift detection | Alert when approval rate drops — signals ICP needs recalibration |

### Phase 3 — Execution and automation

| Improvement | Detail |
|---|---|
| SendGrid email integration | Approved drafts send directly from the app with open and reply tracking |
| Reply classification | LLM classifies replies — interested / not interested / OOO / bounced — updates prospect status automatically |
| Follow-up sequence engine | Conditional follow-up logic — no reply in 5 days triggers a different draft than open-but-no-reply |
| Signal monitoring job | Nightly background process surfaces companies that just crossed trigger thresholds |
| Salesforce native API | Direct write-back to Salesforce Engage — bypasses manual CSV import |

### Phase 4 — Scale and quality

| Improvement | Detail |
|---|---|
| Upgrade to Claude Sonnet | Replaces Mistral-7B for draft generation — consistently higher quality, more reliably peer-level tone |
| Fine-tune scoring model | Train on client's historical CRM data — won deals, lost deals, no-shows — significantly more accurate than zero-shot |
| Multi-tenant support | Multiple brokers, shared suppression lists, role-based access, workspace isolation |
| Self-hosted model inference | Eliminates HuggingFace rate limits and cold-start latency |
| A/B testing on drafts | Track which subject lines and opening hooks produce the highest reply rates |

---

## Technology Stack

### Prototype (current)

| Layer | Technology |
|---|---|
| UI | Streamlit |
| Scoring model | facebook/bart-large-mnli via HuggingFace Inference API |
| Draft generation | mistralai/Mistral-7B-Instruct-v0.2 via HuggingFace Inference API |
| Enrichment | Mock data (pre-built realistic profiles) |
| Persistence | Streamlit session state (in-memory, lost on refresh) |
| Export | Salesforce Engage-formatted CSV download |

### Production (target)

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python) |
| Frontend | Next.js (React) |
| Database | Postgres (Supabase hosted) |
| Job queue | Celery + Redis |
| Scoring | Claude Haiku (structured JSON output) |
| Draft generation | Claude Sonnet (Anthropic API) |
| Email sending | SendGrid API |
| Enrichment | Apollo + Proxycurl + NewsAPI + CoStar |
| CRM | Salesforce Engage native API |
| Auth | Clerk or Supabase Auth |
| Hosting | AWS / Render / Fly.io |

---

## Build Roadmap

| Phase | What gets built | Estimated time |
|---|---|---|
| Prototype (done) | Mock enrichment + HF scoring + Streamlit UI | 2 weeks |
| MVP v1 | Real APIs + FastAPI + Postgres + HubSpot/Salesforce | 4–6 weeks |
| MVP v2 | Celery queue + SendGrid + sequence engine | 3–4 weeks |
| Production | Fine-tuned model + multi-tenant + monitoring | 2–3 months |

---

## Running the Prototype

### Requirements

- Python 3.11 or 3.12 (not 3.14 — too new for some dependencies)
- HuggingFace account with a free Read token
- No other API keys needed in demo mode

### Setup

```bash
# Create virtual environment with Python 3.11
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Add your HF_TOKEN to .env
# Set FORCE_MOCK_MODE=true for demo mode

# Run
python -m streamlit run app.py
```

### Environment variables

```env
HF_TOKEN=hf_your_token_here
FORCE_MOCK_MODE=true
AGENT_NAME=Michael Hartley
AGENT_TITLE=Senior Director, Tenant Representation
FIRM_NAME=Hartley CRE Partners
AGENT_PHONE=+1 (212) 555-0147
AGENT_EMAIL=michael@hartleycre.com
```

### Demo flow

1. **Home** — view three pre-built ICP profiles, click "Start pipeline run"
2. **ICP Setup** — select Healthcare Tech profile, choose HealthAxis prospect
3. **Prospect Found** — watch enrichment load, read the AI score and signal bullets
4. **Draft Review** — read the research brief, review email and LinkedIn drafts, approve
5. **Audit Summary** — see the full pipeline audit log, time savings, download Salesforce CSV
