"""
oauth_server.py
FastAPI server — runs on port 8000 alongside Streamlit.

Routes:
  GET  /oauth/login      — redirects to Google consent screen
  GET  /oauth/callback   — exchanges code for token, saves to Supabase,
                            creates 30-day session, redirects to Streamlit
  GET  /health           — health check for UptimeRobot / Railway
  POST /telegram/webhook — Phase-4 stub
"""

import os
import secrets
from datetime import datetime, timedelta

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Allow Google to return scopes in any order without raising
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

# Permit http://localhost callbacks during local dev. oauthlib refuses to
# exchange a code over plain HTTP unless this is set. Auto-enabled only when
# the configured redirect URI is non-HTTPS, so production (HTTPS) stays strict.
if not os.getenv("GOOGLE_REDIRECT_URI", "").startswith("https://"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

from google_auth_oauthlib.flow import Flow

from database import _db, _log_error

app = FastAPI()

# ── env vars ────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI",
                                  "http://localhost:8000/oauth/callback")
STREAMLIT_URL        = os.getenv("STREAMLIT_URL", "http://localhost:8501")
ALLOWED_EMAILS       = [
    e.strip().lower()
    for e in os.getenv("ALLOWED_EMAILS", os.getenv("ALLOWED_EMAIL", "")).split(",")
    if e.strip()
]

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
]


# In-memory PKCE store — keyed by OAuth `state`, holds the code_verifier
# generated during /oauth/login so /oauth/callback can complete the exchange.
# Single-process, fine for local dev and our single-broker prod footprint.
_PKCE_STORE: dict = {}


# ── helpers ─────────────────────────────────────────────

def _make_flow() -> Flow:
    client_config = {
        "web": {
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=GOOGLE_SCOPES)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


def _token_dict(credentials) -> dict:
    """Converts google credentials object to a JSON-serialisable dict."""
    return {
        "token":         credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri":     credentials.token_uri,
        "client_id":     credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes":        list(credentials.scopes or []),
        "expiry":        credentials.expiry.isoformat() if credentials.expiry else None,
    }


# ── routes ──────────────────────────────────────────────

@app.get("/oauth/login")
def oauth_login():
    """Redirect the user to Google's consent screen."""
    flow = _make_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",   # ensures refresh_token is always returned
    )
    # Persist the auto-generated PKCE verifier so /oauth/callback can
    # complete the token exchange.
    if getattr(flow, "code_verifier", None):
        _PKCE_STORE[state] = flow.code_verifier
    return RedirectResponse(auth_url)


@app.get("/oauth/callback")
async def oauth_callback(request: Request):
    """
    1. Exchange auth code for tokens
    2. Get user info (email, name)
    3. Check email is in ALLOWED_EMAILS whitelist
    4. Save/update user + token in Supabase
    5. Create 30-day session token
    6. Redirect back to Streamlit with session token in query param
    """
    code  = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error or not code:
        return RedirectResponse(f"{STREAMLIT_URL}/?error=google_denied")

    try:
        flow = _make_flow()
        # Restore the PKCE verifier saved during /oauth/login
        code_verifier = _PKCE_STORE.pop(state, None) if state else None
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
        credentials = flow.credentials
    except Exception as e:
        _log_error("oauth_callback.fetch_token", str(e))
        return RedirectResponse(f"{STREAMLIT_URL}/?error=token_failed")

    # Get user info from Google
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {credentials.token}"},
                timeout=10,
            )
        user_info = resp.json()
    except Exception as e:
        _log_error("oauth_callback.userinfo", str(e))
        return RedirectResponse(f"{STREAMLIT_URL}/?error=userinfo_failed")

    email     = (user_info.get("email") or "").lower()
    full_name = user_info.get("name", "")

    # ── Email whitelist check ────────────────────────────
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        return RedirectResponse(f"{STREAMLIT_URL}/?error=unauthorized")

    token_data = _token_dict(credentials)

    # ── Save user to Supabase ────────────────────────────
    try:
        db = _db()
        existing = db.table("users").select("id").eq("google_email", email).execute()

        if existing.data:
            user_id = existing.data[0]["id"]
            db.table("users").update({
                "google_token": token_data,
                "full_name":    full_name,
                "last_login":   datetime.now().isoformat(),
            }).eq("id", user_id).execute()
        else:
            result = db.table("users").insert({
                "google_email": email,
                "full_name":    full_name,
                "google_token": token_data,
            }).execute()
            user_id = result.data[0]["id"]
    except Exception as e:
        _log_error("oauth_callback.save_user", str(e))
        return RedirectResponse(f"{STREAMLIT_URL}/?error=db_failed")

    # ── Create session token ─────────────────────────────
    try:
        session_token = secrets.token_urlsafe(32)
        db.table("sessions").insert({
            "user_id":       user_id,
            "google_email":  email,
            "session_token": session_token,
            "expires_at":    (datetime.now() + timedelta(days=30)).isoformat(),
        }).execute()
    except Exception as e:
        _log_error("oauth_callback.create_session", str(e))
        return RedirectResponse(f"{STREAMLIT_URL}/?error=session_failed")

    return RedirectResponse(f"{STREAMLIT_URL}/?session={session_token}")


@app.post("/telegram/webhook")
async def telegram_webhook_stub(request: Request):
    """Stub — implemented in Phase 4."""
    return {"ok": True}


@app.get("/health")
def health():
    status = {"status": "ok", "ts": datetime.now().isoformat()}
    try:
        _db()
        status["database"] = "connected"
    except Exception:
        status["database"] = "error"
        status["status"]   = "degraded"
    return JSONResponse(status)
