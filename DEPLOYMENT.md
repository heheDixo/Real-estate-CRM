# Deployment notes — CRE Outreach Intelligence

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
- All vars from `.env.example`
- `GOOGLE_REDIRECT_URI` → the public HTTPS URL for `/oauth/callback`
- `FASTAPI_URL` → the public URL of the `api` service
- `STREAMLIT_URL` → the public URL of the `web` service
