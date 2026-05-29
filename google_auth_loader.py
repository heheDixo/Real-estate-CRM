"""
google_auth_loader.py
Helper used by gmail_drafts / google_sheets / google_calendar to load a
Credentials object from the Supabase `users` table when no credentials are
passed explicitly (scheduler background path).

Streamlit-free — safe to import from the scheduler thread.
"""

from __future__ import annotations

import os
from typing import Optional


def load_user_credentials_from_db(default_scopes: list, user_id: Optional[str] = None):
    """
    Load a user's google_token from Supabase, refresh if expired, persist
    the refreshed token, and return a google.oauth2.Credentials instance —
    or None if the user can't be found / no refresh_token / any failure.

    Resolution order for which user's token to load:
      1. Explicit ``user_id`` argument (always wins — used by UI pages).
      2. ``PRIMARY_USER_ID`` env var (scheduler / cron pinning).
      3. ``PRIMARY_BROKER_EMAIL`` / ``BROKER_EMAIL`` env var lookup against
         ``users.google_email`` (scheduler fallback by email).
      4. The first row in ``users`` (legacy behaviour — only kicks in when
         no other resolution is set and only one user exists).

    The point: never silently fall through to row-1 when the UI is the caller
    — that's the bug that routed every web user's Gmail/Drafts/Sheets/Calendar
    actions through whichever account happened to sign in first.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from database import _db, _log_error
    except ImportError:
        return None

    try:
        db = _db()
    except Exception as exc:
        try:
            from database import _log_error as _log
            _log("google_auth_loader.db", str(exc))
        except Exception:
            pass
        return None

    try:
        row = None

        if user_id:
            res = (db.table("users")
                     .select("id, google_token")
                     .eq("id", user_id).limit(1).execute())
            row = res.data[0] if res.data else None

        if row is None:
            env_uid = os.getenv("PRIMARY_USER_ID", "").strip()
            if env_uid:
                res = (db.table("users")
                         .select("id, google_token")
                         .eq("id", env_uid).limit(1).execute())
                row = res.data[0] if res.data else None

        if row is None:
            env_email = (
                os.getenv("PRIMARY_BROKER_EMAIL", "").strip()
                or os.getenv("BROKER_EMAIL", "").strip()
            )
            if env_email:
                res = (db.table("users")
                         .select("id, google_token")
                         .eq("google_email", env_email).limit(1).execute())
                row = res.data[0] if res.data else None

        if row is None:
            res = (db.table("users")
                     .select("id, google_token")
                     .limit(1).execute())
            row = res.data[0] if res.data else None

        if row is None:
            return None
        token_data = row.get("google_token") or {}
        if not token_data.get("refresh_token"):
            return None

        creds = Credentials(
            token=         token_data.get("token"),
            refresh_token= token_data.get("refresh_token"),
            token_uri=     token_data.get("token_uri",
                                          "https://oauth2.googleapis.com/token"),
            client_id=     token_data.get("client_id"),
            client_secret= token_data.get("client_secret"),
            scopes=        token_data.get("scopes") or default_scopes,
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            new_token_data = {
                **token_data,
                "token":  creds.token,
                "expiry": creds.expiry.isoformat() if creds.expiry else None,
            }
            try:
                db.table("users").update(
                    {"google_token": new_token_data}
                ).eq("id", row["id"]).execute()
            except Exception as exc:
                _log_error("google_auth_loader.persist_refreshed", str(exc))

        return creds
    except Exception as exc:
        _log_error("google_auth_loader.load", str(exc))
        return None
