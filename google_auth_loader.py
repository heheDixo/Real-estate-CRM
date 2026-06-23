"""
google_auth_loader.py
Helper used by gmail_drafts / google_sheets / google_calendar to load a
Credentials object from the Supabase `users` table when no credentials are
passed explicitly (scheduler background path).

Streamlit-free — safe to import from the scheduler thread.
"""

from __future__ import annotations

import os
import json
from typing import Optional


def load_user_credentials_from_db(
    default_scopes: list,
    user_id: Optional[str] = None,
):
    """
    Load a user's google_token from Supabase, refresh if expired,
    persist the refreshed token, and return a
    google.oauth2.Credentials instance.

    Returns None if:
    - user not found
    - refresh token missing
    - auth refresh fails
    - DB unavailable
    """

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from database import _db, _log_error, _retry_on_disconnect
    except ImportError:
        return None

    def _select_user_row(db):
        # 1. Explicit user_id
        if user_id:
            res = (
                db.table("users")
                .select("id, google_token")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0]

        # 2. PRIMARY_USER_ID env
        env_uid = os.getenv("PRIMARY_USER_ID", "").strip()
        if env_uid:
            res = (
                db.table("users")
                .select("id, google_token")
                .eq("id", env_uid)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0]

        # 3. PRIMARY_BROKER_EMAIL fallback
        env_email = (
            os.getenv("PRIMARY_BROKER_EMAIL", "").strip()
            or os.getenv("BROKER_EMAIL", "").strip()
        )
        if env_email:
            res = (
                db.table("users")
                .select("id, google_token")
                .eq("google_email", env_email)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0]

        # 4. Legacy fallback: first user
        res = (
            db.table("users")
            .select("id, google_token")
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    try:
        row = _retry_on_disconnect(lambda: _select_user_row(_db()))
    except Exception as exc:
        _log_error("google_auth_loader.load", str(exc))
        return None

    if row is None:
        return None

    # ── Parse token safely ──────────────────────────────
    token_data = row.get("google_token")
    if not token_data:
        return None

    # Supabase may return JSON as string
    if isinstance(token_data, str):
        try:
            token_data = json.loads(token_data)
        except Exception:
            return None

    if not isinstance(token_data, dict):
        return None

    if not token_data.get("refresh_token"):
        return None

    # ── Build credentials ───────────────────────────────
    creds = Credentials(
        token=token_data.get("token"),
        refresh_token=token_data.get("refresh_token"),
        token_uri=token_data.get(
            "token_uri", "https://oauth2.googleapis.com/token"
        ),
        client_id=token_data.get("client_id"),
        client_secret=token_data.get("client_secret"),
        scopes=token_data.get("scopes") or default_scopes,
    )

    # ── Refresh expired token ───────────────────────────
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            _log_error("google_auth_loader.refresh", str(exc))
            return None

        new_token_data = {
            **token_data,
            "token": creds.token,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        }

        try:
            _retry_on_disconnect(
                lambda: (
                    _db().table("users")
                    .update({"google_token": new_token_data})
                    .eq("id", row["id"])
                    .execute()
                )
            )
        except Exception as exc:
            _log_error("google_auth_loader.persist_refreshed", str(exc))

    return creds