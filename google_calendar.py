"""
Google Calendar integration for 5-day follow-up reminders.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Dict, List, Optional

import config

SCOPES     = ["https://www.googleapis.com/auth/calendar"]
TOKEN_PATH = os.path.join("data", "calendar_token.json")
ERROR_LOG  = os.path.join("data", "error_log.json")


# ── Error logging ───────────────────────────────────────────────────────────


def _log_error(scope: str, exc: Exception) -> None:
    os.makedirs("data", exist_ok=True)
    try:
        with open(ERROR_LOG) as f:
            log = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        log = []
    log.append({
        "at":     datetime.datetime.now().isoformat(),
        "scope":  scope,
        "error":  str(exc),
        "type":   type(exc).__name__,
    })
    with open(ERROR_LOG, "w") as f:
        json.dump(log[-200:], f, indent=2)


# ── Auth ────────────────────────────────────────────────────────────────────


def authenticate_calendar():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        _log_error("calendar.import", exc)
        return None

    creds = None
    os.makedirs("data", exist_ok=True)

    if os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception as exc:
            _log_error("calendar.token_read", exc)
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as exc:
                _log_error("calendar.refresh", exc)
                creds = None

        if not creds:
            if not os.path.exists(config.GOOGLE_CREDENTIALS_PATH):
                _log_error(
                    "calendar.credentials_missing",
                    FileNotFoundError(config.GOOGLE_CREDENTIALS_PATH),
                )
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    config.GOOGLE_CREDENTIALS_PATH, SCOPES,
                )
                creds = flow.run_local_server(port=0)
            except Exception as exc:
                _log_error("calendar.oauth_flow", exc)
                return None

        try:
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
        except Exception as exc:
            _log_error("calendar.token_write", exc)

    try:
        return build("calendar", "v3", credentials=creds,
                     cache_discovery=False)
    except Exception as exc:
        _log_error("calendar.build", exc)
        return None


# ── Events ──────────────────────────────────────────────────────────────────


def create_followup_event(service, calendar_id: str,
                            prospect: Dict,
                            sent_date: datetime.datetime,
                            email_subject: str,
                            email_body: str,
                            new_angle: str,
                            research_brief: str = "") -> str:
    """
    Create a follow-up event 5 days after sent_date.

    Returns the new event ID, or empty string on failure.
    """
    if service is None or not calendar_id:
        return ""

    followup_dt   = sent_date + datetime.timedelta(days=5)
    first_name    = (prospect.get("contact_first_name") or
                     prospect.get("contact_name", "").split(" ")[0])
    last_name     = (prospect.get("contact_last_name") or
                     " ".join(prospect.get("contact_name", "").split(" ")[1:]))
    company       = prospect.get("company") or prospect.get("company_name", "")
    contact_title = prospect.get("contact_title", "")

    description = (
        f"Original email sent: {sent_date.strftime('%Y-%m-%d %H:%M')}\n"
        f"Subject: {email_subject}\n"
        f"Top signal used: {prospect.get('top_signal', '—')}\n"
        f"Their role: {contact_title}\n\n"
        f"Quick context:\n{research_brief or '—'}\n\n"
        f"Suggested follow-up angle:\n{new_angle}\n\n"
        f"── Original email body ──\n{email_body[:1500]}"
    )

    event = {
        "summary": f"Follow up — {first_name} {last_name} · {company}",
        "description": description,
        "location": prospect.get("linkedin_url", ""),
        "start": {
            "dateTime": followup_dt.replace(
                hour=9, minute=30, second=0, microsecond=0,
            ).isoformat(),
            "timeZone": config.TIMEZONE,
        },
        "end": {
            "dateTime": followup_dt.replace(
                hour=10, minute=0, second=0, microsecond=0,
            ).isoformat(),
            "timeZone": config.TIMEZONE,
        },
        "reminders": {
            "useDefault": False,
            "overrides":  [{"method": "popup", "minutes": 30}],
        },
    }

    try:
        created = service.events().insert(
            calendarId=calendar_id, body=event,
        ).execute()
        return created.get("id", "")
    except Exception as exc:
        _log_error("calendar.create_event", exc)
        return ""


def delete_event(service, calendar_id: str, event_id: str) -> bool:
    """Delete a follow-up event (e.g. after the prospect replies)."""
    if service is None or not event_id:
        return False
    try:
        service.events().delete(
            calendarId=calendar_id, eventId=event_id,
        ).execute()
        return True
    except Exception as exc:
        _log_error("calendar.delete_event", exc)
        return False


def get_upcoming_followups(service, calendar_id: str,
                             days_ahead: int = 14) -> List[Dict]:
    """List follow-up events for the next N days."""
    if service is None or not calendar_id:
        return []

    now    = datetime.datetime.utcnow().isoformat() + "Z"
    future = (datetime.datetime.utcnow() +
               datetime.timedelta(days=days_ahead)).isoformat() + "Z"

    try:
        result = service.events().list(
            calendarId   = calendar_id,
            timeMin      = now,
            timeMax      = future,
            singleEvents = True,
            orderBy      = "startTime",
            q            = "Follow up",
        ).execute()
    except Exception as exc:
        _log_error("calendar.list_events", exc)
        return []

    out: List[Dict] = []
    for ev in result.get("items", []):
        start = ev.get("start", {})
        date  = start.get("dateTime") or start.get("date") or ""
        out.append({
            "event_id":    ev.get("id", ""),
            "title":       ev.get("summary", ""),
            "date":        date,
            "description": ev.get("description", ""),
            "location":    ev.get("location", ""),
        })
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    svc = authenticate_calendar()
    if svc is None:
        print("[calendar] not authenticated — see data/error_log.json")
    else:
        evid = create_followup_event(
            svc, config.CALENDAR_ID,
            {"contact_first_name": "Rachel",
             "contact_last_name":  "Kim",
             "company":            "HealthAxis",
             "contact_title":      "VP of Operations",
             "linkedin_url":       "https://linkedin.com/in/rachelkim-ops",
             "top_signal":         "headcount growth"},
            sent_date     = datetime.datetime.now(),
            email_subject = "Test follow up",
            email_body    = "Hi Rachel — quick note on your NYC expansion.",
            new_angle     = "Mention the new office postings from last week.",
        )
        print(f"created event: {evid}")
        if evid:
            print(f"https://calendar.google.com/calendar/u/0/r/eventedit/{evid}")
