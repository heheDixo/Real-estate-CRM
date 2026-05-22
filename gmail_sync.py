"""
Gmail Sent-folder watcher.

When the broker sends an email from Gmail itself (rather than the page-3
"Send now" button), the Sheets log and Calendar follow-up don't fire
automatically. This module closes that gap.

The watcher:
  1. Lists messages in the user's Gmail Sent folder over the last N days
  2. For each message: extracts the recipient + subject + date
  3. Matches the recipient domain against the watchlist
  4. Dedupes against rows already in the Sent Emails sheet (by Gmail msg id)
  5. For each new match: appends a row to the sheet AND creates a 3-day
     Calendar follow-up event

Safe to call repeatedly — dedupe by Gmail message id ensures each send is
recorded exactly once. Cached at the call site (Streamlit) to avoid spam.
"""

from __future__ import annotations

import base64
import datetime
import email.utils
import json
import os
import re
from typing import Dict, List, Optional, Set

import config


# ── Error logging ───────────────────────────────────────────────────────────


def _log(scope: str, exc_or_msg) -> None:
    try:
        path = os.path.join("data", "error_log.json")
        os.makedirs("data", exist_ok=True)
        log: List[Dict] = []
        if os.path.exists(path):
            try:
                with open(path) as f:
                    log = json.load(f) or []
            except (json.JSONDecodeError, OSError):
                log = []
        log.append({
            "at":    datetime.datetime.now().isoformat(),
            "scope": scope,
            "error": str(exc_or_msg)[:280],
            "type":  type(exc_or_msg).__name__ if isinstance(exc_or_msg, Exception) else "Info",
        })
        with open(path, "w") as f:
            json.dump(log[-200:], f, indent=2)
    except Exception:
        pass


# ── Watchlist / domain matching ─────────────────────────────────────────────


def _load_watchlist_index() -> Dict[str, Dict]:
    """domain (lowercased, no www.) → watchlist entry."""
    out: Dict[str, Dict] = {}
    path = os.path.join("data", "watchlist.json")
    if not os.path.exists(path):
        return out
    try:
        with open(path) as f:
            wl = json.load(f) or []
    except (json.JSONDecodeError, OSError):
        return out
    for w in wl:
        d = (w.get("domain") or "").lower().strip().replace("www.", "")
        if d:
            out[d] = w
    return out


def _recipient_domain(to_header: str) -> str:
    """Extract the domain from a To header (`Name <addr@domain>`)."""
    if not to_header:
        return ""
    name, addr = email.utils.parseaddr(to_header)
    if not addr or "@" not in addr:
        return ""
    return addr.split("@", 1)[1].lower().strip().replace(">", "")


def _match_prospect(to_header: str,
                     index: Dict[str, Dict]) -> Optional[Dict]:
    """Match recipient against watchlist by exact domain or suffix."""
    domain = _recipient_domain(to_header)
    if not domain:
        return None
    if domain in index:
        return index[domain]
    # Suffix match — covers subdomains (e.g. mail.ramp.com → ramp.com)
    for d, entry in index.items():
        if domain.endswith("." + d):
            return entry
    return None


# ── Sheet dedupe ────────────────────────────────────────────────────────────


def _existing_message_ids(sheets_svc) -> Set[str]:
    """Pull the set of Gmail message ids already logged so we don't double-write."""
    if not sheets_svc or not config.SHEETS_SPREADSHEET_ID:
        return set()
    try:
        from google_sheets import get_all_sent_emails
        rows = get_all_sent_emails(sheets_svc, config.SHEETS_SPREADSHEET_ID) or []
    except Exception as exc:
        _log("gmail_sync.read_sheet", exc)
        return set()
    out: Set[str] = set()
    for r in rows:
        mid = (r.get("Gmail Message ID") or
               r.get("Message ID")        or
               r.get("message_id")        or "")
        if mid:
            out.add(mid.strip())
    return out


# ── Gmail message parsing ───────────────────────────────────────────────────


def _decode_body(payload: Dict) -> str:
    """Best-effort plain-text body extraction from a Gmail payload."""
    if not payload:
        return ""
    if payload.get("mimeType", "").startswith("text/plain"):
        data = (payload.get("body") or {}).get("data") or ""
        try:
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
        except Exception:
            return ""
    for part in payload.get("parts") or []:
        body = _decode_body(part)
        if body:
            return body
    return ""


def _header(headers: List[Dict], name: str) -> str:
    for h in headers or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


# ── Main entry ──────────────────────────────────────────────────────────────


def sync_recent_sends(lookback_days: int = 2) -> Dict:
    """
    Pull Gmail sends from the last N days, log any that hit a watchlist
    prospect, and create a 3-day Calendar follow-up for each.

    Returns a summary dict:
        {checked: int, matched: int, new_rows: int, new_followups: int,
         errors: int}
    """
    summary = {"checked": 0, "matched": 0, "new_rows": 0,
               "new_followups": 0, "errors": 0}

    # ── Auth all three services up front ──────────────────────────────────
    try:
        from gmail_drafts    import authenticate_gmail
        from google_sheets   import authenticate_sheets, log_sent_email
        from google_calendar import authenticate_calendar, create_followup_event
        gmail_svc  = authenticate_gmail()
        sheets_svc = authenticate_sheets()
        cal_svc    = authenticate_calendar()
    except Exception as exc:
        _log("gmail_sync.auth", exc)
        summary["errors"] += 1
        return summary

    if gmail_svc is None:
        return summary

    # ── Index ─────────────────────────────────────────────────────────────
    wl_index    = _load_watchlist_index()
    if not wl_index:
        return summary
    seen_msgids = _existing_message_ids(sheets_svc)

    # ── List recent sends ─────────────────────────────────────────────────
    query = f"in:sent newer_than:{lookback_days}d"
    try:
        listing = gmail_svc.users().messages().list(
            userId="me", q=query, maxResults=50,
        ).execute()
    except Exception as exc:
        _log("gmail_sync.list", exc)
        summary["errors"] += 1
        return summary

    msg_ids = [m.get("id") for m in (listing.get("messages") or [])]
    summary["checked"] = len(msg_ids)

    for mid in msg_ids:
        if not mid or mid in seen_msgids:
            continue

        try:
            msg = gmail_svc.users().messages().get(
                userId="me", id=mid, format="full",
            ).execute()
        except Exception as exc:
            _log("gmail_sync.get_msg", exc)
            summary["errors"] += 1
            continue

        payload = msg.get("payload") or {}
        headers = payload.get("headers") or []
        to_hdr  = _header(headers, "To")
        subject = _header(headers, "Subject")
        date_hdr = _header(headers, "Date")

        if not to_hdr or not subject:
            continue

        match = _match_prospect(to_hdr, wl_index)
        if not match:
            continue
        summary["matched"] += 1

        # ── Append row to Sheets ──────────────────────────────────────────
        # Parse the Gmail date header to a datetime
        try:
            sent_dt = email.utils.parsedate_to_datetime(date_hdr)
        except Exception:
            sent_dt = datetime.datetime.now()
        sent_iso = sent_dt.strftime("%Y-%m-%d %H:%M")

        body_text = _decode_body(payload)
        contact_email = email.utils.parseaddr(to_hdr)[1]

        try:
            ok = log_sent_email(
                sheets_svc, config.SHEETS_SPREADSHEET_ID, {
                    "Date Sent":         sent_iso,
                    "Company":           match.get("company", ""),
                    "Contact Name":      match.get("contact_name", ""),
                    "Contact Title":     match.get("contact_title", ""),
                    "Contact Email":     contact_email,
                    "LinkedIn URL":      match.get("linkedin_url", ""),
                    "Email Subject":     subject,
                    "Email Body":        body_text[:2000],
                    "Source":            "gmail_sync",
                    "Status":            "Sent",
                    "Gmail Message ID":  mid,
                },
            )
            if ok:
                summary["new_rows"] += 1
                seen_msgids.add(mid)
        except Exception as exc:
            _log("gmail_sync.log_row", exc)
            summary["errors"] += 1
            continue

        # ── Create 3-day Calendar follow-up ───────────────────────────────
        try:
            first = (match.get("contact_name") or "").split(" ")[0] or "Contact"
            last  = " ".join((match.get("contact_name") or "").split(" ")[1:]) or ""
            create_followup_event(
                service       = cal_svc,
                calendar_id   = config.CALENDAR_ID,
                prospect      = {
                    "contact_first_name": first,
                    "contact_last_name":  last,
                    "company":            match.get("company", ""),
                    "contact_title":      match.get("contact_title", ""),
                    "linkedin_url":       match.get("linkedin_url", ""),
                    "top_signal":         "Original outreach — review the thread before re-engaging.",
                },
                sent_date     = sent_dt,
                email_subject = subject,
                email_body    = body_text[:1000],
                new_angle     = "If no reply yet, try a softer one-liner referencing the same signal.",
                research_brief = f"Sent via Gmail · {match.get('sector','')}",
            )
            summary["new_followups"] += 1
        except Exception as exc:
            _log("gmail_sync.create_followup", exc)
            summary["errors"] += 1

    _log("gmail_sync.summary",
         f"checked={summary['checked']} matched={summary['matched']} "
         f"rows+{summary['new_rows']} followups+{summary['new_followups']} "
         f"errors={summary['errors']}")
    return summary


if __name__ == "__main__":
    import json as _json
    print(_json.dumps(sync_recent_sends(lookback_days=2), indent=2))
