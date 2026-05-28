"""
telegram_bot.py
All Telegram message sending for CRE Outreach Intelligence.

Uses plain requests — no extra library needed.
All functions are fire-and-forget: they never crash the caller.
"""

import os
import time
import requests
from datetime import datetime

from database import _log_error, get_all_telegram_users

BOT_TOKEN     = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_USERNAME  = os.getenv("TELEGRAM_BOT_USERNAME", "CREOutreachBot")
API_BASE      = f"https://api.telegram.org/bot{BOT_TOKEN}"
STREAMLIT_URL = os.getenv("STREAMLIT_URL", "http://localhost:8501")


# ─────────────────────────────────────────
# CORE SEND
# ─────────────────────────────────────────

def send_message(chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
    """
    Sends one Telegram message. Returns True on success, False on failure.
    Never raises — always safe to call.
    """
    if not BOT_TOKEN:
        print("[telegram] BOT_TOKEN not set — skipping")
        return False
    if not chat_id:
        return False
    try:
        resp = requests.post(
            f"{API_BASE}/sendMessage",
            json={
                "chat_id":    chat_id,
                "text":       text[:4000],
                "parse_mode": parse_mode,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            _log_error(
                "telegram.send_message",
                f"Status {resp.status_code}: {resp.text[:200]}",
            )
            return False
        return True
    except Exception as e:
        _log_error("telegram.send_message", str(e))
        return False


def broadcast(text: str) -> None:
    """Sends a message to every user with Telegram connected."""
    for user in get_all_telegram_users():
        chat_id = user.get("telegram_chat_id")
        if chat_id:
            send_message(chat_id, text)


# ─────────────────────────────────────────
# MORNING BRIEF
# ─────────────────────────────────────────

def send_morning_brief(chat_id: str, reports: list) -> bool:
    """
    Sends today's research summary to the broker on Telegram.
    Called by the scheduler after the pipeline completes.
    `reports` is a list of ResearchReport-like objects (anything that
    supports getattr for company / contact_name / tier / etc).
    """
    if not chat_id or not reports:
        return False

    date_str     = datetime.now().strftime("%a %d %b")
    active       = [r for r in reports if not getattr(r, "skip_today", False)]
    hot          = [r for r in active  if getattr(r, "tier", "") == "hot"]
    warm         = [r for r in active  if getattr(r, "tier", "") == "warm"]
    drafts_ready = [r for r in active  if getattr(r, "draft", None)]

    lines = [
        f"🏢 *CRE Morning Brief — {date_str}*",
        f"_{len(active)} prospects · {len(hot)} hot · {len(warm)} warm · "
        f"{len(drafts_ready)} drafts in Gmail_",
        "",
    ]

    if hot:
        lines.append("🔥 *Hot leads*")
        for r in hot:
            company = getattr(r, "company", "Unknown")
            contact = getattr(r, "contact_name", "") or ""
            title   = getattr(r, "contact_title", "") or ""
            score   = getattr(r, "composite_score", 0)
            hook    = getattr(r, "top_hook", "") or ""
            who     = f"{contact} ({title})" if contact and title else (contact or title)
            lines.append(f"• *{company}* · {who} · Score: {score}")
            if hook:
                lines.append(f"  _{hook}_")

    if warm:
        lines.append("")
        lines.append(f"☀ *Warm leads ({len(warm)})*")
        for r in warm:
            company = getattr(r, "company", "Unknown")
            contact = getattr(r, "contact_name", "") or ""
            score   = getattr(r, "composite_score", 0)
            lines.append(f"• {company} · {contact} · {score}/100")

    skipped = [r for r in reports if getattr(r, "skip_today", False)]
    if skipped:
        lines.append("")
        lines.append(f"_Skipped {len(skipped)} prospects — signals below threshold_")

    lines += [
        "",
        f"[Open dashboard]({STREAMLIT_URL})",
    ]

    return send_message(chat_id, "\n".join(lines))


# ─────────────────────────────────────────
# REPLY NOTIFICATION
# ─────────────────────────────────────────

def send_reply_notification(
    chat_id: str,
    company: str,
    contact_name: str,
    reply_snippet: str,
    sent_date: str,
) -> bool:
    """
    Sent when Gmail detects a reply to an outreach email. Currently exposed
    for the reply checker to be wired into in a later phase.
    """
    snippet = reply_snippet[:300] if reply_snippet else "No preview available"
    text = (
        f"📬 *Reply received*\n"
        f"*{contact_name}* · {company}\n\n"
        f'"{snippet}"\n\n'
        f"_Sent: {sent_date} · Follow\\-up reminder deleted automatically_"
    )
    return send_message(chat_id, text)


# ─────────────────────────────────────────
# ALERTS
# ─────────────────────────────────────────

def send_pipeline_failed_alert(chat_id: str, error: str) -> bool:
    text = (
        f"⚠️ *Morning pipeline failed*\n\n"
        f"The research didn't run this morning\\.\n"
        f"Error: `{error[:200]}`\n\n"
        f"Log in to run manually\\."
    )
    return send_message(chat_id, text)


def send_warmup_failed_alert(chat_id: str, failed_models: list) -> bool:
    models = ", ".join(failed_models)
    text = (
        f"⚠️ *HuggingFace models unreachable*\n\n"
        f"Warm\\-up failed for: {models}\n"
        f"Drafts this morning will use template fallback\\."
    )
    return send_message(chat_id, text)


# ─────────────────────────────────────────
# CONNECT URL
# ─────────────────────────────────────────

def get_connect_url(user_id: str) -> str:
    """
    Deep link for the connect button in the app. When the broker clicks it,
    Telegram opens the bot, they tap Start, the bot receives /start <user_id>,
    and the webhook captures their chat_id into users.telegram_chat_id.
    """
    return f"https://t.me/{BOT_USERNAME}?start={user_id}"


# ─────────────────────────────────────────
# LOCAL POLLING (testing only — production uses the webhook)
# ─────────────────────────────────────────

def run_polling() -> None:
    """
    Polls Telegram for updates — LOCAL TESTING ONLY. Production uses the
    /telegram/webhook FastAPI route. Run with:
        python -c "from telegram_bot import run_polling; run_polling()"
    """
    if not BOT_TOKEN:
        print("[telegram] BOT_TOKEN not set")
        return

    print("[telegram] Polling for updates... (Ctrl+C to stop)")
    offset = 0

    while True:
        try:
            resp = requests.get(
                f"{API_BASE}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            )
            data = resp.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                _handle_update(update)
        except KeyboardInterrupt:
            print("\n[telegram] Polling stopped")
            break
        except Exception as e:
            _log_error("telegram.run_polling", str(e))
            time.sleep(5)


def _handle_update(update: dict) -> None:
    """Process one Telegram update — same logic as the webhook handler."""
    message = update.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text    = message.get("text", "")

    if not chat_id or not text.startswith("/start"):
        return

    parts   = text.split()
    user_id = parts[1] if len(parts) > 1 else None

    if user_id:
        try:
            from database import _db
            db = _db()
            db.table("users").update({
                "telegram_chat_id":   chat_id,
                "telegram_connected": True,
            }).eq("id", user_id).execute()
            print(f"[telegram] Connected chat_id {chat_id} to user {user_id}")
            send_message(
                chat_id,
                "✅ *Connected\\!*\n\n"
                "You'll receive your morning CRE brief here every day at 7am\\.\n\n"
                "I'll also notify you when prospects reply to your outreach\\.",
            )
        except Exception as e:
            _log_error("telegram._handle_update", str(e))
    else:
        send_message(
            chat_id,
            "Please connect via the dashboard — "
            f"open {STREAMLIT_URL} and click 'Connect Telegram'\\.",
        )
