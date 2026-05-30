# Deployment Guide — CRE Outreach Intelligence

## Architecture

- **web**: Streamlit app (the broker's UI) — Railway service 1
- **api**: FastAPI (Google OAuth callback + Telegram webhook) — Railway service 2
- **worker**: APScheduler daemon (04:50 warm-up + 05:00 pipeline) — Railway service 3
- **database**: Supabase Postgres (always on, separate from Railway)

The [`Procfile`](Procfile) declares all three processes; Railway picks them up automatically and creates three services from a single repo deploy.

---

## One-time Railway setup

### 1. Push to GitHub

```bash
git init  # if not already a git repo
git add .
git commit -m "Initial production build"
git remote add origin https://github.com/yourusername/cre-outreach.git
git push -u origin main
```

### 2. Create Railway project

1. Go to [railway.app](https://railway.app) → **New Project**
2. **Deploy from GitHub repo** → select your repo
3. Railway detects the [Procfile](Procfile) and creates 3 services:
   - `web` (Streamlit)
   - `api` (FastAPI)
   - `worker` (scheduler)

### 3. Set environment variables

In the Railway dashboard → each service → **Variables** tab.
Set **all** of these on **all three** services (Railway doesn't share env between services by default):

```
# ── Core ──────────────────────────────────────────────
HF_TOKEN=hf_...
FORCE_MOCK_MODE=false

# ── Broker identity (appears in drafts) ───────────────
AGENT_NAME=Michael Hartley
FIRM_NAME=Hartley CRE Partners
BROKER_EMAIL=michael@hartleycre.com
# Optional fan-out for the morning digest — comma-separated. Every address
# receives the digest; one bad recipient doesn't stop the others. Leave
# unset to default to just BROKER_EMAIL.
# BROKER_EMAILS=michael@hartleycre.com,partner@hartleycre.com

# ── Phase 8 — pin the cron's identity ─────────────────
# The 5am cron has no logged-in user, so it has to pick *some* row in the
# users table to act as. Without one of these pins, the loader falls
# through to "row 1" — which silently breaks the moment a second user
# signs in and gets inserted before the primary broker. Set ONE of:
#   PRIMARY_USER_ID=<uuid-of-primary-broker>     # exact match (preferred)
#   PRIMARY_BROKER_EMAIL=michael@hartleycre.com  # email match on users.google_email
# PRIMARY_USER_ID stays unset by default; the email fallback chain
# PRIMARY_BROKER_EMAIL → BROKER_EMAIL is enough for a single-broker prod.
PRIMARY_BROKER_EMAIL=michael@hartleycre.com

# ── Gmail SMTP (alert mirror + Send-now) ──────────────
GMAIL_SENDER=michael@hartleycre.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

# ── Google OAuth (Web-app client) ─────────────────────
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=https://YOUR_API_SERVICE.railway.app/oauth/callback

# ── Public URLs (fill once Railway assigns them) ──────
FASTAPI_URL=https://YOUR_API_SERVICE.railway.app
STREAMLIT_URL=https://YOUR_WEB_SERVICE.railway.app

# ── Supabase ──────────────────────────────────────────
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...

# ── Email whitelist (comma-separated) ─────────────────
ALLOWED_EMAILS=michael@hartleycre.com

# ── Telegram ──────────────────────────────────────────
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_BOT_USERNAME=YourBotName

# ── Scheduling ────────────────────────────────────────
RESEARCH_CRON_HOUR=5
RESEARCH_CRON_MINUTE=0
DIGEST_SEND_HOUR=7
TIMEZONE=America/New_York
START_SCHEDULER=true

# ── Monitoring ────────────────────────────────────────
ALERT_EMAIL=michael@hartleycre.com
# Optional fan-out for failure alerts — comma-separated. Defaults to
# ALERT_EMAIL, then BROKER_EMAILS, then BROKER_EMAIL.
# ALERT_EMAILS=ops@hartleycre.com,michael@hartleycre.com
HEALTH_PORT=8000

# ── Optional data sources (graceful degradation) ──────
NEWSAPI_KEY=...
HUNTER_API_KEY=...
FIRECRAWL_API_KEY=...
SHEETS_SPREADSHEET_ID=...
CALENDAR_ID=primary
```

### 4. Capture your Railway URLs

After the first deploy Railway assigns each service a public URL:

- `web`:    `https://cre-outreach-web-production.up.railway.app`
- `api`:    `https://cre-outreach-api-production.up.railway.app`
- `worker`: no public URL needed

Update three env vars with the real values:

| Var | Value |
|---|---|
| `FASTAPI_URL`          | the **api** service URL |
| `STREAMLIT_URL`        | the **web** service URL |
| `GOOGLE_REDIRECT_URI`  | the **api** service URL + `/oauth/callback` |

Redeploy after editing variables (Railway auto-triggers on save).

### 5. Update Google Cloud Console

Add the real Railway redirect URI to your OAuth client:

1. [console.cloud.google.com](https://console.cloud.google.com) → **APIs & Services → Credentials**
2. Edit your OAuth 2.0 Client ID
3. Add to **Authorised redirect URIs**: `https://YOUR_API_SERVICE.railway.app/oauth/callback`
4. **Save**

**Then add the Phase 8 scopes** so the "Generate research doc" button doesn't 403 with `ACCESS_TOKEN_SCOPE_INSUFFICIENT`:

5. **APIs & Services → OAuth consent screen → Scopes → Add or remove scopes** — add:
   - `https://www.googleapis.com/auth/documents`
   - `https://www.googleapis.com/auth/drive.file`
6. **APIs & Services → Library** — confirm **Google Docs API** and **Google Drive API** are both enabled (alongside Gmail, Sheets, Calendar).
7. **APIs & Services → OAuth consent screen → Test users → Add user** — every email in `ALLOWED_EMAILS` must also be a Test user here until the app moves out of Testing status. Otherwise Google blocks the sign-in before the in-app whitelist check runs.

After a scope change, every user must sign out + sign in again so Google re-issues a token bound to the new scope set. Existing tokens don't silently widen.

### 5b. Supabase — Phase 8 migration

Run once in **Supabase → SQL editor → New query** so each user can have their own per-account Sent-Emails spreadsheet:

```sql
ALTER TABLE users
ADD COLUMN IF NOT EXISTS sheets_spreadsheet_id TEXT;
```

Existing rows get `NULL`; the first Send-now per user lazily creates a sheet in *their* Drive (titled "CRE Outreach — Sent Emails", renamed default tab, headers seeded) and persists the ID here. The scheduler / `gmail_sync` keeps using the single `SHEETS_SPREADSHEET_ID` env-var sheet as the master broker log.

### 6. Register the Telegram webhook

Run once after deploy (replace `{TOKEN}` and the URL):

```bash
curl -X POST "https://api.telegram.org/bot{YOUR_BOT_TOKEN}/setWebhook" \
  -d "url=https://YOUR_API_SERVICE.railway.app/telegram/webhook"
```

Expected: `{"ok":true,"result":true,"description":"Webhook was set"}`

### 7. Verify deployment

```bash
# API health
curl https://YOUR_API_SERVICE.railway.app/health
# Expected: {"status":"ok","ts":"...","database":"connected"}

# Streamlit loads
# Open https://YOUR_WEB_SERVICE.railway.app in a browser
# Expected: dark login page with "Sign in with Google" button
```

### 8. First login

1. Open the Streamlit URL
2. Click **Sign in with Google**
3. Sign in with a whitelisted email (`michael@hartleycre.com`)
4. Should land on the research dashboard
5. Click **Connect Telegram** banner → tap **Start** in the bot
6. Click **Run pipeline** to verify end-to-end flow before the 5am cron fires

---

## Ongoing maintenance

### Redeploy after code changes

```bash
git add <specific files>
git commit -m "your message"
git push
# Railway auto-deploys on push to the tracked branch
```

### Check the scheduler ran this morning

- Open app → sidebar → **Pipeline history**
- Today's run should show status `success` (or `no_actionable` on a quiet day)

### If OAuth token expires

Rare — Google refresh tokens are long-lived. If `session_manager.get_google_credentials()` starts returning `None`:
1. Sign out of the app
2. Sign in again — fresh `refresh_token` persists to `users.google_token` JSONB

### Add a second client (Phase 4.5 prerequisite)

Multi-tenant requires the RLS work from [PROGRESS.md](PROGRESS.md) §8. Until that lands the per-user data isolation isn't enforced. Sequence once RLS is on:

1. New client creates a Telegram bot via BotFather and shares the token
2. Add their email to `ALLOWED_EMAILS` on **all three** Railway services
3. They sign in via the Streamlit URL — their `users` row is created
4. They `/start <user_id>` the bot to connect Telegram
5. Send them the Streamlit URL

---

## Verify locally before pushing

```bash
# 1. All required env vars present
python check_env.py

# 2. Streamlit boots
python -m streamlit run app.py
# Open http://localhost:8501 — dark login page

# 3. FastAPI boots
uvicorn oauth_server:app --host 0.0.0.0 --port 8000
# curl http://localhost:8000/health — JSON

# 4. Scheduler runs end-to-end
python scheduler.py --once

# 5. No secrets staged
git status
# .env should NOT appear
# data/*.json (except .gitkeep) should NOT appear
# credentials.json should NOT appear

# 6. Push
git add <files>
git commit -m "Production build — phases 1-5 complete"
git push

# 7. Post-deploy health
curl https://YOUR_API_SERVICE.railway.app/health

# 8. Post-deploy webhook
curl -X POST "https://api.telegram.org/bot{TOKEN}/setWebhook" \
  -d "url=https://YOUR_API_SERVICE.railway.app/telegram/webhook"

curl "https://api.telegram.org/bot{TOKEN}/getWebhookInfo"
# Verifies the webhook URL was accepted
```

---

## What comes after deployment (Phase 6)

- UptimeRobot pinging `/health` every 5 min so the worker container stays warm
- Pipeline-history page in the Streamlit UI
- Hand the Streamlit URL to the broker
- Watch the first 05:00 ET run succeed (Telegram brief lands ~05:05)
