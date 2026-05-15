# CRE Outreach Intelligence

**AI-powered tenant rep prospecting — from signal to reviewed draft in under 3 minutes.**

This is a working demo of a commercial real estate prospecting pipeline. It takes a target company, pulls real-time signals from three data sources, scores the company against your ideal client profile using a HuggingFace model, drafts a personalised email and LinkedIn message, and gives you the final say on every outbound message — before anything sends.

Nothing leaves the system without your approval.

---

## What it replaces

The manual workflow this is built to replace looks like:

| Step | Time it normally takes |
|---|---|
| Building the lead list | ~15 min per prospect |
| Researching the contact and the company | ~10 min |
| Drafting the outreach email | ~10 min |
| Drafting the LinkedIn message | ~5 min |
| Logging the prospect into Salesforce | ~5 min |
| Tracking follow-ups manually | ~10 min |
| **Total** | **~55 min per prospect** |

With the system:

| Step | Time |
|---|---|
| Everything except review | runs in the background |
| Your review of the AI draft | ~5 min |
| **Total** | **~5 min per prospect** |

**~50 minutes saved per prospect. At 15–20 qualified prospects per week, that's 12–17 hours back in your week.**

---

## How it works — the four screens

The pipeline runs as a four-step wizard. Each step has its own page.

### 1. ICP setup
Define your ideal client profile — sector, geography, headcount range, funding stage, the trigger signals that matter to you, and the tone rules for outreach. You can save multiple profiles (e.g. Healthcare Tech NYC, Financial Services NYC, Tech / SaaS NYC) and switch between them with one click. Each profile keeps its own decision history and signal weights.

### 2. Prospect found — enrichment + scoring
For a selected prospect, the system runs three live data sources in sequence:

- **Apollo** — firmographic depth, headcount history, funding details
- **Proxycurl** — LinkedIn hiring signals (active job postings, office/workplace roles, hiring velocity)
- **NewsAPI** — recent news flagged for CRE signals (expansion, funding, relocation, office moves)

Once enrichment is complete, the company is scored across five dimensions using `facebook/bart-large-mnli` zero-shot classification:

1. **Hiring velocity** — are they growing fast enough to need more space?
2. **Funding timing** — are they in the 12–18 month post-funding deployment window?
3. **Expansion news** — have they publicly announced geographic growth?
4. **Lease expiry** — are signals suggesting their current lease is up?
5. **Decision maker** — is the contact senior enough to make this call?

Scores are weighted by sector preset (healthcare weights hiring velocity highest; financial services weights lease expiry highest), combined into a 0–100 composite, and bucketed into **Hot 🔥 / Warm ☀️ / Nurture ❄️** tiers.

### 3. Draft review
The system produces:

- A **5-bullet research brief** — what you need to know before reaching out (company stage, space need signal, right contact, best angle, main risk)
- An **email draft** — under 100 words, opens with one specific verifiable signal, ends with a low-pressure question
- A **LinkedIn message** — under 300 characters, conversational

Both drafts are written by `mistralai/Mistral-7B-Instruct-v0.2` using prompts calibrated to your tone rules. You can edit anything before approving. Every edit is recorded and used to improve future drafts for that profile.

### 4. Audit summary + Salesforce export
A timestamped log of every step the system took, the time savings calculation, the approved outreach copy, and a one-click **Salesforce Engage CSV export** with all the field mappings you need.

---

## What's "real" vs "mock"

The system runs in two modes depending on which API keys are present in your `.env` file:

- **Live mode** — uses real Apollo, Proxycurl, NewsAPI, and HuggingFace API calls. Every score and every draft comes from a live model.
- **Demo mode** — uses pre-built realistic data for three hand-picked prospects (a healthcare SaaS, a tech infrastructure company, a PE firm) so you can demo the full flow without spending API credits.

You can force demo mode by setting `FORCE_MOCK_MODE=true` in your `.env`. The system also falls back to demo data per-source if a specific API key is missing — so if you only have a HuggingFace key, scoring and drafting are live but enrichment uses demo data.

---

## What you need to run it

### Prerequisites

- Python 3.11
- A terminal

### One-time setup

```bash
# 1. Open a terminal in the project folder

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # macOS / Linux
# .\venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the example env file and fill in your keys
cp .env.example .env
# Open .env in any text editor and paste your keys
```

### Running the app

```bash
source venv/bin/activate
streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`.

To stop: press `Ctrl + C` in the terminal.

---

## API keys

All keys live in your local `.env` file and are never shared or hardcoded. The system runs in demo mode for any key that's missing.

| Key | Purpose | Where to get it |
|---|---|---|
| `HF_TOKEN` | Scoring + drafting via HuggingFace Inference API | huggingface.co → Settings → Access Tokens |
| `APOLLO_API_KEY` | Firmographic enrichment | app.apollo.io |
| `PROXYCURL_API_KEY` | LinkedIn hiring signals | nubela.co/proxycurl |
| `NEWSAPI_KEY` | Company news signals | newsapi.org |
| `AGENT_NAME` / `FIRM_NAME` / `AGENT_EMAIL` | Identity used in drafted emails | — |
| `FORCE_MOCK_MODE` | `true` = demo data for everything, `false` = live | — |

You can run the entire demo with **no keys at all** in mock mode — every page works end-to-end, and the drafts are produced by template fallbacks.

---

## What the AI is and isn't doing

**It is doing:**
- Reading a structured paragraph about the company and rating its space need on five separate dimensions using a public, well-known classification model.
- Writing first-touch outreach copy with prompts that enforce your tone rules — word counts, forbidden phrases, opening style, sign-off — calibrated per ICP profile.

**It is not doing:**
- Sending email automatically. You always approve every draft before it goes out.
- Posting on LinkedIn automatically. The LinkedIn message is copy-paste — automating LinkedIn risks your account.
- Making decisions for you. Every score is shown with its reasoning. Every draft is editable.

---

## What gets better with use

The system records every approval, rejection, and edit. Over time, those decisions feed into:

- **Learned rules** — plain-English patterns extracted from your approve/reject history (e.g. "skip companies under 60 employees regardless of funding") that get injected into the scoring prompt
- **Tone calibration** — the diff between the AI's draft and your edited version trains the writing prompt toward your voice

The "Decision history" tab on each ICP profile shows total decisions, approval rate, and any learned rules that have emerged.

---

## Privacy and data handling

- All credentials live in your local `.env` file. They're never sent anywhere except the API they belong to.
- No prospect data is stored on any server we control. Session state lives only in your browser tab — close it and the run is gone.
- The Salesforce CSV export is a local download. We don't push anything to Salesforce on your behalf.
- The HuggingFace Inference API receives the structured paragraph about each prospect for scoring and drafting. If that's a concern for any specific prospect, run that one in demo mode.

---

## Support

If something doesn't behave as expected, check the **API status** indicator in the left sidebar — it shows which sources are running live vs falling back to demo data. Most "the draft looks generic" or "the score seems off" issues are because a key is missing and that source is in fallback mode.

For anything else, send a note with a screenshot of the page and the API status indicator state at the time.
