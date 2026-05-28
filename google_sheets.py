"""
Google Sheets integration for the "Sent Emails" log.

All functions are defensive: returns None/empty rather than crashing the
morning pipeline if credentials are missing or quota is hit.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Dict, List, Optional

import config

SCOPES     = ["https://www.googleapis.com/auth/spreadsheets"]
TOKEN_PATH = os.path.join("data", "sheets_token.json")
ERROR_LOG  = os.path.join("data", "error_log.json")

SHEET_NAME = "Sent Emails"

HEADERS = [
    "Date Sent", "Company", "Contact Name", "Contact Title",
    "Contact Email", "LinkedIn URL", "Email Subject", "Email Body",
    "Research Signals", "Score", "Tier", "Source", "Status",
    "Reply Date", "Reply Content", "Follow-up Date", "Notes",
]


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


def authenticate_sheets(credentials=None):
    """
    Build and return an authenticated Sheets API service.

    If `credentials` is passed (from a logged-in Streamlit user), use them
    directly. Otherwise (scheduler / background job), load the first user's
    token from Supabase via google_auth_loader.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        _log_error("sheets.import", exc)
        return None

    if credentials is None:
        from google_auth_loader import load_user_credentials_from_db
        credentials = load_user_credentials_from_db(SCOPES)
        if credentials is None:
            _log_error("sheets.no_credentials",
                       RuntimeError("No Google token in Supabase — sign in first"))
            return None

    try:
        return build("sheets", "v4", credentials=credentials,
                     cache_discovery=False)
    except Exception as exc:
        _log_error("sheets.build", exc)
        return None


# ── Sheet helpers ───────────────────────────────────────────────────────────


def get_or_create_sheet(service, spreadsheet_id: str) -> str:
    """
    Ensure the "Sent Emails" tab exists with the correct header row.
    Returns the tab name. Empty string on failure.
    """
    if service is None or not spreadsheet_id:
        return ""

    try:
        meta = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
        ).execute()
    except Exception as exc:
        _log_error("sheets.get_metadata", exc)
        return ""

    sheet_names = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if SHEET_NAME not in sheet_names:
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": [{
                    "addSheet": {"properties": {"title": SHEET_NAME}}
                }]},
            ).execute()
        except Exception as exc:
            _log_error("sheets.add_tab", exc)
            return ""

    # check / write headers
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{SHEET_NAME}!A1:Q1",
        ).execute()
    except Exception as exc:
        _log_error("sheets.header_read", exc)
        return SHEET_NAME

    if not result.get("values"):
        try:
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{SHEET_NAME}!A1",
                valueInputOption="RAW",
                body={"values": [HEADERS]},
            ).execute()
        except Exception as exc:
            _log_error("sheets.header_write", exc)

    return SHEET_NAME


def log_sent_email(service, spreadsheet_id: str, data: Dict) -> bool:
    """
    Append one row to the Sent Emails sheet. Returns True on success.
    """
    if service is None or not spreadsheet_id:
        return False

    tab = get_or_create_sheet(service, spreadsheet_id)
    if not tab:
        return False

    row = [
        data.get("Date Sent",     datetime.date.today().isoformat()),
        data.get("Company",        ""),
        data.get("Contact Name",  ""),
        data.get("Contact Title", ""),
        data.get("Contact Email", ""),
        data.get("LinkedIn URL",  ""),
        data.get("Email Subject", ""),
        data.get("Email Body",    ""),
        data.get("Research Signals", ""),
        data.get("Score",          ""),
        data.get("Tier",           ""),
        data.get("Source",         "morning_research"),
        data.get("Status",         "Sent"),
        data.get("Reply Date",     ""),
        data.get("Reply Content",  ""),
        data.get("Follow-up Date", ""),
        data.get("Notes",          ""),
    ]

    try:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        return True
    except Exception as exc:
        _log_error("sheets.append", exc)
        return False


def update_email_status(service, spreadsheet_id: str,
                          contact_email: str, status: str,
                          reply_content: str = "") -> bool:
    """
    Locate a row by Contact Email and update Status / Reply Date / Reply Content.
    """
    if service is None or not spreadsheet_id or not contact_email:
        return False

    try:
        rows = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{SHEET_NAME}!A1:Q1000",
        ).execute().get("values", [])
    except Exception as exc:
        _log_error("sheets.update_status.read", exc)
        return False

    if not rows:
        return False

    headers = rows[0]
    try:
        email_col   = headers.index("Contact Email")
        status_col  = headers.index("Status")
        reply_col   = headers.index("Reply Date")
        content_col = headers.index("Reply Content")
    except ValueError as exc:
        _log_error("sheets.update_status.header", exc)
        return False

    for idx, row in enumerate(rows[1:], start=2):  # sheet rows are 1-indexed
        if len(row) > email_col and row[email_col].lower() == contact_email.lower():
            updates = [
                {"range": f"{SHEET_NAME}!{chr(65 + status_col)}{idx}",
                 "values": [[status]]},
                {"range": f"{SHEET_NAME}!{chr(65 + reply_col)}{idx}",
                 "values": [[datetime.date.today().isoformat()]]},
            ]
            if reply_content:
                updates.append({
                    "range":  f"{SHEET_NAME}!{chr(65 + content_col)}{idx}",
                    "values": [[reply_content[:480]]],
                })
            try:
                service.spreadsheets().values().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"valueInputOption": "RAW", "data": updates},
                ).execute()
                return True
            except Exception as exc:
                _log_error("sheets.update_status.write", exc)
                return False

    return False


def get_all_sent_emails(service, spreadsheet_id: str) -> List[Dict]:
    """Return every row in the Sent Emails sheet as a list of dicts."""
    if service is None or not spreadsheet_id:
        return []
    try:
        rows = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{SHEET_NAME}!A1:Q1000",
        ).execute().get("values", [])
    except Exception as exc:
        _log_error("sheets.get_all", exc)
        return []
    if not rows:
        return []
    headers = rows[0]
    return [
        {headers[i]: (row[i] if i < len(row) else "")
         for i in range(len(headers))}
        for row in rows[1:]
    ]


# ── CLI ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    svc = authenticate_sheets()
    if svc is None:
        print("[sheets] not authenticated — see data/error_log.json")
    elif not config.SHEETS_SPREADSHEET_ID:
        print("[sheets] SHEETS_SPREADSHEET_ID not set in .env")
    else:
        tab = get_or_create_sheet(svc, config.SHEETS_SPREADSHEET_ID)
        ok  = log_sent_email(svc, config.SHEETS_SPREADSHEET_ID, {
            "Company":       "Test Co",
            "Contact Name":  "Test Contact",
            "Email Subject": "Test row",
            "Email Body":    "This is a test row from google_sheets.py",
            "Score":         77,
            "Tier":          "Hot",
        })
        print(f"tab={tab} appended={ok}")
