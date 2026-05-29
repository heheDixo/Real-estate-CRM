"""
monitoring.py
Sends email alerts when critical things fail.
Used by scheduler warm-up and pipeline failure handler.
"""
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from datetime import datetime

from database import _log_error

GMAIL_SENDER       = os.getenv("GMAIL_SENDER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# ALERT_EMAILS is the fan-out list (comma-separated). For back-compat we
# fall back to ALERT_EMAIL, then BROKER_EMAILS (also comma-separated), then
# BROKER_EMAIL. The single SMTP session sends to every address in one call.
_default_alert = (
    os.getenv("ALERT_EMAIL")
    or os.getenv("BROKER_EMAILS")
    or os.getenv("BROKER_EMAIL", "")
)
ALERT_EMAILS = [
    e.strip()
    for e in os.getenv("ALERT_EMAILS", _default_alert).split(",")
    if e.strip()
]


def send_alert(subject: str, body: str) -> bool:
    """
    Sends an email alert to every address in ALERT_EMAILS. Returns True on
    success. Silently fails if credentials not configured — never crashes
    the caller.
    """
    if not all([GMAIL_SENDER, GMAIL_APP_PASSWORD, ALERT_EMAILS]):
        print(f"[monitoring] Alert skipped (no credentials): {subject}")
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = f"[CRE Alert] {subject}"
        msg["From"]    = GMAIL_SENDER
        msg["To"]      = ", ".join(ALERT_EMAILS)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_SENDER, ALERT_EMAILS, msg.as_string())
        print(f"[monitoring] Alert sent to {len(ALERT_EMAILS)} recipient(s): {subject}")
        return True
    except Exception as e:
        _log_error("monitoring.send_alert", str(e))
        return False


def alert_pipeline_failed(error: str, run_date: str) -> None:
    send_alert(
        subject=f"Morning pipeline failed — {run_date}",
        body=(
            f"The 5am research pipeline failed on {run_date}.\n\n"
            f"Error:\n{error}\n\n"
            f"No drafts in Gmail this morning. Log in to run manually."
        )
    )
