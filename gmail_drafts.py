"""
Gmail integration via the official Google API client.

Functions:
    authenticate_gmail()           → service
    create_draft(...)              → {"id", "url"}
    send_morning_digest(...)
    check_for_replies(...)
    watch_sent_folder(...)

The first call to authenticate_gmail() opens a browser for OAuth consent.
The token is cached at data/gmail_token.json for silent reuse.

All Google API calls catch HttpError and log to data/error_log.json so
they never crash the morning pipeline.
"""

from __future__ import annotations

import base64
import datetime
import json
import os
from email.mime.text import MIMEText
from typing import Dict, List

import config

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

TOKEN_PATH    = os.path.join("data", "gmail_token.json")
ERROR_LOG     = os.path.join("data", "error_log.json")


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


def authenticate_gmail(credentials=None, user_id=None):
    """
    Build and return an authenticated Gmail API service.

    If `credentials` is passed (from a logged-in Streamlit user), use them
    directly. Otherwise (scheduler / background job), load the token for
    `user_id` (or the env-pinned primary broker, or row-1) from Supabase
    via google_auth_loader.

    Returns None (and logs) if no credentials can be sourced or the OAuth
    library is not installed.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        _log_error("gmail.import", exc)
        return None

    if credentials is None:
        from google_auth_loader import load_user_credentials_from_db
        credentials = load_user_credentials_from_db(SCOPES, user_id=user_id)
        if credentials is None:
            _log_error("gmail.no_credentials",
                       RuntimeError("No Google token in Supabase — sign in first"))
            return None

    try:
        return build("gmail", "v1", credentials=credentials,
                     cache_discovery=False)
    except Exception as exc:
        _log_error("gmail.build", exc)
        return None


# ── Drafts / send ───────────────────────────────────────────────────────────


def _build_message(to_email: str, subject: str, body: str,
                    sender: str = "me") -> Dict:
    msg = MIMEText(body, "plain")
    msg["to"]      = to_email
    # Only set the From header explicitly when the caller passed a real
    # address. The Gmail API treats `userId="me"` as the authenticated
    # user; if we set From to a *different* address (the env-var sender)
    # the message gets sent from that other account, which is exactly
    # the bug where every web user's drafts/sends went out of the
    # primary broker's mailbox. Default sender stays "me" so the API
    # picks up whoever owns the credential.
    if sender and sender != "me":
        msg["from"] = sender
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}


def create_draft(service, to_email: str, subject: str, body: str,
                 prospect_name: str = "") -> Dict:
    """
    Create a Gmail draft (does NOT send).

    Returns:
        {"id": draft_id, "url": gmail_url} on success; empty dict on failure.
    """
    if service is None:
        return {}

    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        return {}

    # sender="me" so the draft is created in the *authenticated* user's
    # mailbox. Using config.GMAIL_SENDER here forced the From header to a
    # single env-var address, which is why every web user's drafts ended
    # up in the primary broker's Drafts folder.
    message = _build_message(to_email, subject, body, sender="me")

    try:
        draft = service.users().drafts().create(
            userId="me",
            body={"message": message},
        ).execute()
    except Exception as exc:
        _log_error("gmail.create_draft", exc)
        return {}

    draft_id = draft.get("id", "")
    msg_id   = (draft.get("message") or {}).get("id", "")
    url      = f"https://mail.google.com/mail/u/0/#drafts/{msg_id}" if msg_id else ""

    return {
        "id":       draft_id,
        "message_id": msg_id,
        "url":      url,
        "prospect_name": prospect_name,
    }


def send_email_now(service, to_email: str, subject: str, body: str) -> Dict:
    """
    Send an email immediately as the authenticated Gmail user.

    Used by the "Send now" button on the draft-review page so the message
    goes out of the logged-in user's mailbox (not whichever Gmail SMTP
    app-password sits in the .env file).

    Returns:
        {"sent": bool, "message_id": str, "thread_id": str}.
    """
    if service is None or not to_email:
        return {"sent": False, "message_id": "", "thread_id": ""}

    message = _build_message(to_email, subject, body, sender="me")
    try:
        sent = service.users().messages().send(
            userId="me", body=message,
        ).execute()
        return {
            "sent":       True,
            "message_id": sent.get("id", ""),
            "thread_id":  sent.get("threadId", ""),
        }
    except Exception as exc:
        _log_error("gmail.send_now", exc)
        return {"sent": False, "message_id": "", "thread_id": ""}


def send_morning_digest(service, broker_email: str,
                         reports: List) -> Dict:
    """
    Send the broker a summary email at 7:00 AM listing all reports.

    `reports` is a list of ResearchReport instances (or their dicts).
    Returns {"sent": bool, "message_id": str}.
    """
    if service is None or not broker_email:
        return {"sent": False, "message_id": ""}

    today = datetime.date.today().strftime("%a, %b %d %Y")

    def _attr(r, key, default=""):
        if isinstance(r, dict):
            return r.get(key, default)
        return getattr(r, key, default)

    actionable = [r for r in reports if not _attr(r, "skip_today", False)]
    hot        = [r for r in actionable if _attr(r, "tier", "") == "hot"]

    subject = (
        f"CRE Morning Research — {today} — "
        f"{len(actionable)} prospect{'s' if len(actionable) != 1 else ''} ready"
    )

    lines = [
        f"Good morning {config.AGENT_NAME.split()[0]},",
        "",
        f"Research run complete. {len(actionable)} prospects with material signals today.",
        "",
    ]

    if hot:
        lines.append("🔥 HOT LEADS — act today")
        lines.append("─" * 40)
        for r in hot:
            lines.append(
                f"• {_attr(r, 'company')} — {_attr(r, 'composite_score')}/100"
            )
            lines.append(f"  {_attr(r, 'top_hook')}")
            lines.append("")
        lines.append("")

    warm = [r for r in actionable if _attr(r, "tier", "") == "warm"]
    if warm:
        lines.append("☀️  WARM — contact this week")
        lines.append("─" * 40)
        for r in warm:
            lines.append(
                f"• {_attr(r, 'company')} — {_attr(r, 'composite_score')}/100  "
                f"·  {_attr(r, 'top_hook')}"
            )
        lines.append("")

    skipped = [r for r in reports if _attr(r, "skip_today", False)]
    if skipped:
        lines.append(
            f"Skipped today ({len(skipped)}): no actionable signals."
        )

    lines.append("")
    lines.append("Drafts are ready in your Gmail Drafts folder.")
    lines.append("")
    lines.append(f"— {config.AGENT_NAME}'s research agent")

    body = "\n".join(lines)
    message = _build_message(broker_email, subject, body, sender="me")

    try:
        sent = service.users().messages().send(
            userId="me", body=message,
        ).execute()
        return {"sent": True, "message_id": sent.get("id", "")}
    except Exception as exc:
        _log_error("gmail.digest_send", exc)
        return {"sent": False, "message_id": ""}


def check_for_replies(service, sent_message_ids: List[str]) -> List[Dict]:
    """
    For each message id we previously sent, look for a reply in the inbox.

    Returns list of {message_id, replied, reply_snippet}.
    """
    if service is None or not sent_message_ids:
        return []

    out: List[Dict] = []
    for mid in sent_message_ids:
        record = {"message_id": mid, "replied": False, "reply_snippet": ""}
        try:
            original = service.users().messages().get(
                userId="me", id=mid, format="metadata",
                metadataHeaders=["Subject", "To"],
            ).execute()
        except Exception as exc:
            _log_error("gmail.check_replies.fetch", exc)
            out.append(record)
            continue

        headers = {h["name"]: h["value"]
                   for h in original.get("payload", {}).get("headers", [])}
        thread_id = original.get("threadId", "")

        if not thread_id:
            out.append(record)
            continue

        try:
            thread = service.users().threads().get(
                userId="me", id=thread_id,
            ).execute()
        except Exception as exc:
            _log_error("gmail.check_replies.thread", exc)
            out.append(record)
            continue

        messages = thread.get("messages", [])
        # any message that isn't ours is a reply
        for m in messages:
            label_ids = m.get("labelIds", [])
            if "SENT" not in label_ids:
                record["replied"]       = True
                record["reply_snippet"] = m.get("snippet", "")[:240]
                break

        out.append(record)

    return out


def watch_sent_folder(service) -> str:
    """
    Register a Gmail push notification on the sent folder.

    NOTE: requires Cloud Pub/Sub topic configuration outside this app.
    Returns the watch expiry ISO timestamp or "" if not configured.
    """
    topic = os.getenv("GMAIL_PUBSUB_TOPIC", "")
    if service is None or not topic:
        return ""
    try:
        resp = service.users().watch(
            userId="me",
            body={"labelIds": ["SENT"], "topicName": topic},
        ).execute()
        # expiration is ms since epoch
        exp_ms = int(resp.get("expiration", 0))
        if exp_ms:
            return datetime.datetime.fromtimestamp(exp_ms / 1000).isoformat()
        return ""
    except Exception as exc:
        _log_error("gmail.watch", exc)
        return ""


# ── CLI ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    svc = authenticate_gmail()
    if svc is None:
        print("[gmail_drafts] not authenticated — see data/error_log.json")
    else:
        d = create_draft(
            svc,
            to_email = config.DEMO_RECIPIENT or config.BROKER_EMAIL or "you@example.com",
            subject  = "Test draft from gmail_drafts.py",
            body     = "Hello — this is a test draft created by the CRE pipeline.",
            prospect_name = "Test Prospect",
        )
        print(json.dumps(d, indent=2))
