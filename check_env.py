"""
check_env.py

Pre-deploy guard. Run with:
    python check_env.py

Exits non-zero if any required env var is missing. Required vars are the
ones the production app cannot start without (auth, database, HF, Telegram).
Optional vars enable graceful-degradation paths — the app boots without
them but the relevant feature is disabled.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

REQUIRED = [
    "HF_TOKEN",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "FASTAPI_URL",
    "STREAMLIT_URL",
    "GMAIL_SENDER",
    "GMAIL_APP_PASSWORD",
    "ALLOWED_EMAILS",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_BOT_USERNAME",
    "BROKER_EMAIL",
    "TIMEZONE",
]

OPTIONAL = [
    "NEWSAPI_KEY",
    "HUNTER_API_KEY",
    "FIRECRAWL_API_KEY",
    "ALERT_EMAIL",
    "SHEETS_SPREADSHEET_ID",
    "CALENDAR_ID",
]


def main() -> int:
    print("Checking required env vars...")
    missing = []
    for var in REQUIRED:
        val = os.getenv(var)
        if val:
            print(f"  ✅ {var}")
        else:
            print(f"  ❌ {var} — MISSING")
            missing.append(var)

    print("\nChecking optional env vars...")
    for var in OPTIONAL:
        val = os.getenv(var)
        if val:
            print(f"  ✅ {var}")
        else:
            print(f"  ⚠️  {var}  (not set — feature disabled)")

    if missing:
        print(
            f"\n❌ {len(missing)} required var(s) missing — fix before deploying:\n"
            + "\n".join(f"  - {v}" for v in missing)
        )
        return 1

    print("\n✅ All required vars set — ready to deploy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
