"""
session_manager.py
Used by every Streamlit page.

  user = require_login()                 # call at top of every page
  creds = get_google_credentials(user)   # when making Google API calls
"""

import os
from datetime import datetime
from typing import Optional

import streamlit as st
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from database import _db, _log_error, update_user

FASTAPI_URL   = os.getenv("FASTAPI_URL",   "http://localhost:8000")
STREAMLIT_URL = os.getenv("STREAMLIT_URL", "http://localhost:8501")

GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
    # Docs + Drive scopes — must match oauth_server.GOOGLE_SCOPES so the
    # token rebuilt here can hit docs.googleapis.com without 403'ing.
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


# ── Public API ───────────────────────────────────────────

def require_login() -> dict:
    """
    Call at the top of every page.
    Returns the user dict if logged in.
    Shows login page and stops if not.
    """
    user = _get_current_user()
    if not user:
        _show_login_page()
        st.stop()
    return user


def get_google_credentials(user: dict) -> Credentials:
    """
    Returns a valid Google Credentials object for this user.
    Auto-refreshes if expired and saves new token back to Supabase.
    """
    token_data = user.get("google_token") or {}

    creds = Credentials(
        token=         token_data.get("token"),
        refresh_token= token_data.get("refresh_token"),
        token_uri=     token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=     token_data.get("client_id"),
        client_secret= token_data.get("client_secret"),
        scopes=        token_data.get("scopes") or GOOGLE_SCOPES,
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            new_token_data = {**token_data, "token": creds.token}
            if creds.expiry:
                new_token_data["expiry"] = creds.expiry.isoformat()
            update_user(user["id"], {"google_token": new_token_data})
            if "current_user" in st.session_state:
                st.session_state["current_user"]["google_token"] = new_token_data
        except Exception as e:
            _log_error("get_google_credentials.refresh", str(e))

    return creds


def logout() -> None:
    """Call when user clicks sign out."""
    token = st.session_state.get("session_token")
    if token:
        try:
            _db().table("sessions").delete().eq("session_token", token).execute()
        except Exception:
            pass
    st.session_state.clear()
    try:
        st.query_params.clear()
    except Exception:
        pass
    st.rerun()


# ── Internal ─────────────────────────────────────────────

def _get_current_user() -> Optional[dict]:
    # Already loaded in this Streamlit session
    if "current_user" in st.session_state:
        return st.session_state["current_user"]

    # Read session token from URL
    session_token = st.query_params.get("session")
    if not session_token:
        return None

    try:
        db = _db()

        # Validate session
        result = (
            db.table("sessions")
            .select("user_id, google_email, expires_at")
            .eq("session_token", session_token)
            .execute()
        )
        if not result.data:
            return None

        session = result.data[0]

        # Check expiry — tolerate both "Z" and offset-aware ISO formats
        expires_raw = session["expires_at"].replace("Z", "+00:00")
        try:
            expires = datetime.fromisoformat(expires_raw).replace(tzinfo=None)
        except ValueError:
            return None
        if datetime.now() > expires:
            return None

        # Load full user
        user_result = (
            db.table("users")
            .select("*")
            .eq("id", session["user_id"])
            .execute()
        )
        if not user_result.data:
            return None

        user = user_result.data[0]
        st.session_state["current_user"]  = user
        st.session_state["session_token"] = session_token
        return user

    except Exception as e:
        _log_error("_get_current_user", str(e))
        return None


def _show_login_page() -> None:
    """Renders the login page.

    The dark theme CSS is already injected by `page_shell -> inject_theme()`
    via st.html() — we must NOT re-inject it via st.markdown here, because
    Streamlit's markdown preprocessor breaks pseudo-class selectors and
    dumps the stylesheet onto the page as visible text.
    """
    # Handle error states from OAuth redirect
    error = st.query_params.get("error")
    error_messages = {
        "unauthorized":    "Access restricted. This tool is private.",
        "google_denied":   "Google sign-in was cancelled. Please try again.",
        "token_failed":    "Could not get Google token. Please try again.",
        "userinfo_failed": "Could not read your Google account info. Try again.",
        "db_failed":       "Database error. Please contact support.",
        "session_failed":  "Session creation failed. Please try again.",
    }
    if error and error in error_messages:
        st.error(error_messages[error])

    st.markdown("<div style='height:10vh'></div>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 2, 1])

    with col:
        st.markdown(
            """
            <div style="text-align:center;margin-bottom:32px">
              <div style="font-size:36px;margin-bottom:10px">🏢</div>
              <div style="font-size:22px;font-weight:500;color:#e6edf3;margin-bottom:6px">
                CRE Outreach Intelligence
              </div>
              <div style="font-size:13px;color:#8b949e">
                AI-powered tenant rep prospecting
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        login_url = f"{FASTAPI_URL}/oauth/login"

        st.markdown(
            f"""
            <div style="text-align:center;margin-top:24px">
              <a href="{login_url}" target="_self" style="text-decoration:none">
                <div style="
                  display:inline-flex;align-items:center;gap:12px;
                  background:#ffffff;color:#1a1a1a;
                  border-radius:6px;padding:12px 28px;
                  font-size:15px;font-weight:500;cursor:pointer;
                  box-shadow:0 1px 3px rgba(0,0,0,0.3)">
                  <svg width="20" height="20" viewBox="0 0 18 18">
                    <path fill="#4285F4"
                      d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844
                         c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908
                         c1.702-1.567 2.684-3.875 2.684-6.615z"/>
                    <path fill="#34A853"
                      d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259
                         c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711
                         H.957v2.332C2.438 15.983 5.482 18 9 18z"/>
                    <path fill="#FBBC05"
                      d="M3.964 10.71c-.18-.54-.282-1.117-.282-1.71s.102-1.17.282-1.71
                         V4.958H.957C.347 6.173 0 7.548 0 9s.348 2.827.957 4.042
                         l3.007-2.332z"/>
                    <path fill="#EA4335"
                      d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58
                         C13.463.891 11.426 0 9 0 5.482 0 2.438 2.017.957 4.958
                         L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>
                  </svg>
                  Sign in with Google
                </div>
              </a>
            </div>
            <div style="text-align:center;margin-top:14px;font-size:11px;color:#484f58">
              Connects your Gmail, Google Sheets, and Google Calendar automatically
            </div>
            """,
            unsafe_allow_html=True,
        )
