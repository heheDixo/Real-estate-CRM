"""
Sent Tracker — dark-themed read-only view of the Google Sheets log.
"""

import datetime
import os
from typing import Dict, List

import streamlit as st

import config
import database
from session_manager import get_google_credentials
from ui_components import (
    page_shell,
    metric_card,
    status_badge,
    empty_state,
)


page_shell("Sent Tracker")

# Logged-in user credentials — ensure the Sheets read is scoped to the
# signed-in user's drive, not the row-1 fallback.
_user  = st.session_state.get("current_user") or {}
_creds = get_google_credentials(_user) if _user else None


def _db_row_to_ui(r: Dict) -> Dict:
    """Map a sent_emails DB row into the Sheets-style schema the UI expects."""
    sent_at = (r.get("sent_at") or "")[:10]
    reply_at = (r.get("reply_date") or "")[:10]
    return {
        "Date Sent":     sent_at,
        "Company":       r.get("company") or "",
        "Contact Name":  r.get("contact_name") or "",
        "Contact Title": r.get("contact_title") or "",
        "Contact Email": r.get("contact_email") or "",
        "Email Subject": r.get("email_subject") or "",
        "Score":         r.get("score") or "",
        "Status":        r.get("status") or "",
        "Reply Date":    reply_at,
        "Notes":         r.get("notes") or "",
    }


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_rows() -> List[Dict]:
    # Supabase first
    try:
        db_rows = database.get_sent_emails(limit=500)
        if db_rows:
            return [_db_row_to_ui(r) for r in db_rows]
    except Exception as exc:
        st.warning(f"Database fetch failed: {exc}")
    # Sheets fallback
    if not config.SHEETS_SPREADSHEET_ID:
        return []
    try:
        from google_sheets import authenticate_sheets, get_all_sent_emails
        svc = authenticate_sheets(credentials=_creds)
        if svc is None:
            return []
        return get_all_sent_emails(svc, config.SHEETS_SPREADSHEET_ID)
    except Exception as exc:
        st.warning(f"Could not fetch Sheets data: {exc}")
        return []


# ── Header ──────────────────────────────────────────────────────────────────


title_col, sync_col = st.columns([5, 1])
with title_col:
    st.markdown(
        '<div style="font-size:18px;font-weight:600;color:#e6edf3;">Sent tracker</div>'
        '<div style="font-size:12px;color:#8b949e;margin-top:2px;">'
        'Every outbound email logged to your Google Sheet. Replies sync from inbox.</div>',
        unsafe_allow_html=True,
    )
with sync_col:
    if st.button("⟳ Sync", use_container_width=True, key="sync_btn"):
        _fetch_rows.clear()
        st.rerun()

st.markdown('<div style="margin:14px 0;"></div>', unsafe_allow_html=True)


# ── Guards ──────────────────────────────────────────────────────────────────


if _creds is None:
    empty_state(
        "📊",
        "Google Sheets not connected",
        "Sign out and sign back in with Google to authorise Sheets access.",
    )
    st.stop()

if not config.SHEETS_SPREADSHEET_ID:
    empty_state(
        "📊",
        "Spreadsheet ID not set",
        "Set SHEETS_SPREADSHEET_ID in .env to your spreadsheet ID.",
    )
    st.stop()


rows = _fetch_rows()
if not rows:
    empty_state(
        "📭",
        "No sent emails yet",
        "Send a draft from the Draft Review page and it will appear here.",
    )
    st.stop()


# ── Metrics row ─────────────────────────────────────────────────────────────


total    = len(rows)
opened   = sum(1 for r in rows if (r.get("Status") or "").lower() == "opened")
replied  = sum(1 for r in rows if (r.get("Status") or "").lower() == "replied")
meetings = sum(1 for r in rows
               if "meeting" in (r.get("Notes") or "").lower())

m1, m2, m3, m4 = st.columns(4)
with m1: metric_card("Total sent",      str(total))
with m2: metric_card("Open rate",
                     f"{(opened / total * 100):.1f}%" if total else "—",
                     value_color="#58a6ff" if opened else "#e6edf3")
with m3: metric_card("Reply rate",
                     f"{(replied / total * 100):.1f}%" if total else "—",
                     value_color="#3fb950" if replied else "#e6edf3")
with m4: metric_card("Meetings", str(meetings),
                     value_color="#3fb950" if meetings else "#e6edf3")

st.markdown('<div style="margin:18px 0;"></div>', unsafe_allow_html=True)


# ── Sent table (custom HTML for dark styling) ──────────────────────────────


def _trunc(s: str, n: int = 60) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


header_cells = ["Company", "Contact", "Subject", "Sent",
                "Score", "Status", "Reply"]
header_html = "".join(
    f'<th style="padding:10px 12px;font-size:10px;color:#8b949e;'
    f'text-align:left;text-transform:uppercase;letter-spacing:0.5px;'
    f'font-weight:500;">{h}</th>'
    for h in header_cells
)

rows_html = ""
for row in rows:
    rows_html += (
        f'<tr style="border-bottom:1px solid #21262d;">'
        f'<td style="padding:10px 12px;font-size:12px;font-weight:500;'
        f'color:#e6edf3;">{row.get("Company") or "—"}</td>'
        f'<td style="padding:10px 12px;font-size:11px;color:#c9d1d9;">'
        f'{row.get("Contact Name") or "—"}<br>'
        f'<span style="color:#484f58;">{row.get("Contact Title") or ""}</span></td>'
        f'<td style="padding:10px 12px;font-size:11px;color:#8b949e;'
        f'max-width:220px;">{_trunc(row.get("Email Subject"))}</td>'
        f'<td style="padding:10px 12px;font-size:11px;color:#8b949e;">'
        f'{row.get("Date Sent") or "—"}</td>'
        f'<td style="padding:10px 12px;font-size:11px;color:#e6edf3;'
        f'font-weight:500;">{row.get("Score") or "—"}</td>'
        f'<td style="padding:10px 12px;">{status_badge(row.get("Status") or "pending")}</td>'
        f'<td style="padding:10px 12px;font-size:11px;color:#8b949e;">'
        f'{row.get("Reply Date") or "—"}</td>'
        f'</tr>'
    )

st.markdown(
    f'<div style="background:#161b22;border:1px solid #30363d;'
    f'border-radius:8px;overflow:hidden;">'
    f'<table style="width:100%;border-collapse:collapse;">'
    f'<thead style="background:#1c2128;"><tr>{header_html}</tr></thead>'
    f'<tbody>{rows_html}</tbody></table></div>',
    unsafe_allow_html=True,
)


# ── External link ──────────────────────────────────────────────────────────


st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)
sheet_url = (
    f"https://docs.google.com/spreadsheets/d/"
    f"{config.SHEETS_SPREADSHEET_ID}/edit"
)
st.link_button("Open Google Sheet ↗", sheet_url, use_container_width=False)
