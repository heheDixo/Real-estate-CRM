# Deployment notes — CRE Outreach Intelligence

Covers the one-time setup for the four external services this project depends on (HuggingFace, Supabase, Google Cloud OAuth, Telegram BotFather), plus local-dev startup and production deployment notes.

---

## HuggingFace token

1. Sign in at https://huggingface.co → Settings → Access Tokens.
2. Create a token with **read** scope. Copy it (`hf_...`).
3. Add to `.env`:
   ```
   HF_TOKEN=hf_...
   ```

Scoring (bart-mnli) runs on the free `hf-inference` provider. Drafting (Llama-3.1-8B-Instruct) routes through the OpenAI-style `/v1/chat/completions` endpoint and consumes the **$0.10/mo free Inference Providers credits** per HF account ($2.00/mo on PRO). When credits run out the writer returns empty and the template fallback in `hf_models/writer._build_fallback_draft` kicks in — drafts still land in Gmail, just less personalised.

---

## Supabase project (one-time)

1. Create a free project at https://supabase.com.
2. Open SQL Editor → paste [`setup_database.sql`](setup_database.sql) → Run. Creates 11 tables + 8 indexes. **RLS is off** — multi-tenant lockdown is deferred to Phase 4.5 (see [PROGRESS.md](PROGRESS.md) §8).
3. Project Settings → API → copy:
   ```
   SUPABASE_URL=https://xxxxxxxx.supabase.co
   SUPABASE_ANON_KEY=eyJhbGciOi...
   ```
4. One-time seed migration (idempotent for prospects + tone profile; **don't re-run** for `approved_emails` — no natural unique key, will duplicate):
   ```bash
   python migrate_json_to_db.py
   ```

---

## Google OAuth setup (one-time, per Google Cloud project)

1. Go to https://console.cloud.google.com → select the CRE project.
2. **APIs & Services → Credentials → Create credentials → OAuth 2.0 Client ID**.
3. Application type: **Web application**.
4. Name: `CRE Outreach Web`.
5. Authorised redirect URIs — add both:
   - `http://localhost:8000/oauth/callback`            (local testing)
   - `https://your-api-service.railway.app/oauth/callback`  (fill in after deploy)
6. Click **Create** → download the JSON → note `client_id` and `client_secret`.
7. Add to `.env`:
   ```
   GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your_client_secret
   GOOGLE_REDIRECT_URI=http://localhost:8000/oauth/callback
   ```

### OAuth consent screen
- User type: **External**
- App name: `CRE Outreach Intelligence`
- Scopes to add (non-sensitive + sensitive Gmail/Sheets/Calendar):
  - `openid`
  - `.../auth/userinfo.email`
  - `.../auth/userinfo.profile`
  - `.../auth/gmail.compose`
  - `.../auth/gmail.readonly`
  - `.../auth/gmail.send`
  - `.../auth/spreadsheets`
  - `.../auth/calendar`
- Test users: add the client email(s) you intend to allow (e.g. `michael@hartleycre.com`).

### Whitelist
- `.env` → `ALLOWED_EMAILS=email1@x.com,email2@y.com` — only these can complete OAuth.

---

## Telegram bot setup (optional — for the morning brief notification)

1. Open Telegram → search **@BotFather** → start chat.
2. Send `/newbot` → pick a display name (e.g. `CRE Outreach`) → pick a username ending in `bot` (e.g. `CREOutreachBot`).
3. BotFather replies with a token like `7123456789:AAF...`. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=7123456789:AAF...
   TELEGRAM_BOT_USERNAME=CREOutreachBot
   ```
4. Verify:
   ```bash
   curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe"
   ```
   Should return `{"ok":true,"result":{...}}`.

**Connecting your account** (one-time): open the dashboard, the connect banner on the research page shows a one-tap deep link. Or in any Telegram client, message the bot:
```
/start <your-user-uuid-from-supabase-users-table>
```

This sets `users.telegram_chat_id` and `users.telegram_connected=true` so the scheduler's morning brief lands on your phone.

**Webhook vs polling.** For local dev, polling is fine — run `python -c "from telegram_bot import run_polling; run_polling()"` in a separate terminal. For production, register the webhook against your public FastAPI URL **once**:
```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
    -d "url=https://<your-api-host>/telegram/webhook"
```
The route handler is already in [`oauth_server.py`](oauth_server.py) — no code change needed.

---

## Running locally

Two terminals:

```bash
# Terminal 1 — OAuth callback server
uvicorn oauth_server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Streamlit UI
python -m streamlit run app.py
```

Open http://localhost:8501 → click **Sign in with Google**.

## Production deploy (Railway / Fly / Render)

Use the `Procfile` in the repo root:

```
web:    streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
api:    uvicorn oauth_server:app --host 0.0.0.0 --port 8000
worker: python scheduler.py
```

Set these env vars on the host:
- All vars from `.env.example` (including `HF_TOKEN`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ALLOWED_EMAILS`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME` if you want phone alerts)
- `GOOGLE_REDIRECT_URI` → the public HTTPS URL for `/oauth/callback`
- `FASTAPI_URL` → the public URL of the `api` service
- `STREAMLIT_URL` → the public URL of the `web` service

After the first deploy:
1. **Add the public redirect URI** to your OAuth client in Google Cloud Console (`https://<api-host>/oauth/callback`).
2. **Register the Telegram webhook** against the public `api` host (see Telegram section above). Telegram will then POST `/start` events directly to `/telegram/webhook` instead of you needing to run the polling loop.
3. **Point UptimeRobot (or similar) at `/health`** — that endpoint returns `{status, ts, database}`, useful for keeping the worker container warm.
