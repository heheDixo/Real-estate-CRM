"""
Follow-ups — dark-themed calendar event list.
"""

import datetime
import os

import streamlit as st

import config
from session_manager import get_google_credentials
from ui_components import page_shell, empty_state


page_shell("Follow-ups")

# Logged-in user credentials — calendar + sheets actions on this page must
# hit the signed-in user's data, not the row-1 fallback.
_user  = st.session_state.get("current_user") or {}
_creds = get_google_credentials(_user) if _user else None


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_events():
    try:
        from google_calendar import authenticate_calendar, get_upcoming_followups
        svc = authenticate_calendar(credentials=_creds)
        if svc is None:
            return None
        return get_upcoming_followups(
            svc, config.CALENDAR_ID, days_ahead=14,
        )
    except Exception as exc:
        st.warning(f"Could not fetch calendar events: {exc}")
        return None


# ── Header ──────────────────────────────────────────────────────────────────


title_col, refresh_col = st.columns([5, 1])
with title_col:
    st.markdown(
        '<div style="font-size:18px;font-weight:600;color:#e6edf3;">Follow-ups</div>'
        '<div style="font-size:12px;color:#8b949e;margin-top:2px;">'
        'Calendar events created 5 days after each outbound. '
        'Mark replied to clear the reminder.</div>',
        unsafe_allow_html=True,
    )
with refresh_col:
    if st.button("⟳ Refresh", use_container_width=True, key="refresh_btn"):
        _fetch_events.clear()
        st.rerun()

st.markdown('<div style="margin:14px 0;"></div>', unsafe_allow_html=True)


# ── Guards ──────────────────────────────────────────────────────────────────


if _creds is None:
    empty_state(
        "📅",
        "Google Calendar not connected",
        "Sign out and sign back in with Google to authorise Calendar access.",
    )
    st.stop()

events = _fetch_events()
if events is None:
    empty_state(
        "🔌",
        "Calendar auth incomplete",
        "See data/error_log.json for details.",
    )
    st.stop()

if not events:
    empty_state(
        "📭",
        "No follow-ups in the next 14 days",
        "They appear here automatically after you send an email from the Draft Review page.",
    )
    st.stop()


# ── Events ──────────────────────────────────────────────────────────────────


def _parse_date(s: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(
            (s or "").replace("Z", "+00:00")
        )
    except Exception:
        return None


for ev in events:
    dt = _parse_date(ev.get("date", ""))
    if not dt:
        continue
    days_until = (dt.date() - datetime.date.today()).days

    title = ev.get("title", "")
    desc  = ev.get("description", "")

    # extract "Suggested follow-up angle"
    angle = ""
    if "suggested follow-up angle" in desc.lower():
        idx = desc.lower().find("suggested follow-up angle")
        angle = desc[idx:].split(":", 1)[-1].split("──")[0].strip()[:280]

    col_date, col_info, col_actions = st.columns([1, 4, 2])

    with col_date:
        st.markdown(
            f'<div style="background:#1d3a5f;color:#58a6ff;'
            f'border:1px solid #1c3a5e;border-radius:6px;padding:10px;'
            f'text-align:center;min-width:48px;">'
            f'<div style="font-size:20px;font-weight:600;line-height:1;">{dt.day}</div>'
            f'<div style="font-size:10px;opacity:0.8;margin-top:3px;'
            f'text-transform:uppercase;letter-spacing:0.5px;">'
            f'{dt.strftime("%b")}</div></div>',
            unsafe_allow_html=True,
        )

    with col_info:
        st.markdown(
            f'<div style="padding:4px 0;">'
            f'<div style="font-size:13px;font-weight:500;color:#e6edf3;">'
            f'{title}</div>'
            f'<div style="font-size:11px;color:#8b949e;margin-top:2px;">'
            f'In {days_until} day{"s" if days_until != 1 else ""} · '
            f'{dt.strftime("%a %d %b · %I:%M %p")}'
            f'</div>'
            + (f'<div style="margin-top:6px;background:#1a1030;color:#a371f7;'
               f'border-radius:4px;font-size:11px;padding:4px 8px;'
               f'display:inline-block;line-height:1.5;max-width:480px;">'
               f'💡 {angle}</div>' if angle else "")
            + (f'<div style="margin-top:6px;font-size:11px;">'
               f'<a href="{ev["location"]}" target="_blank" '
               f'style="color:#58a6ff;">LinkedIn ↗</a></div>'
               if ev.get("location") else "")
            + f'</div>',
            unsafe_allow_html=True,
        )

    with col_actions:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Mark replied",
                         key=f"replied_{ev['event_id']}",
                         use_container_width=True):
                try:
                    from google_sheets   import (
                        authenticate_sheets, update_email_status,
                        get_user_sheet_id,
                    )
                    from google_calendar import authenticate_calendar, delete_event
                    ssvc  = authenticate_sheets(credentials=_creds)
                    csvc  = authenticate_calendar(credentials=_creds)
                    _sid  = get_user_sheet_id(_user)
                    if ssvc and _sid:
                        update_email_status(
                            ssvc, _sid,
                            contact_email=title.split("·")[-1].strip(),
                            status="Replied",
                        )
                    if csvc:
                        delete_event(csvc, config.CALENDAR_ID, ev["event_id"])
                    _fetch_events.clear()
                    st.success("Marked replied")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {exc}")
        with c2:
            if st.button("Delete",
                         key=f"del_{ev['event_id']}",
                         use_container_width=True):
                try:
                    from google_calendar import authenticate_calendar, delete_event
                    csvc = authenticate_calendar(credentials=_creds)
                    if csvc and delete_event(csvc, config.CALENDAR_ID, ev["event_id"]):
                        _fetch_events.clear()
                        st.success("Deleted")
                        st.rerun()
                    else:
                        st.error("Could not delete")
                except Exception as exc:
                    st.error(f"Failed: {exc}")

    st.markdown(
        '<hr style="border-color:#21262d;margin:8px 0;">',
        unsafe_allow_html=True,
    )
