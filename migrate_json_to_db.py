"""
migrate_json_to_db.py
Run once: python migrate_json_to_db.py
Moves all existing JSON data into Supabase.
Safe to run multiple times — upserts, doesn't duplicate.
"""
import sys
from database import (
    upsert_prospect, save_tone_profile, save_approved_email,
    _read_json,
)

DATA_DIR = "data"


def migrate_watchlist():
    prospects = _read_json("watchlist.json", [])
    if not prospects:
        print("  watchlist.json empty or missing — skipping")
        return
    for p in prospects:
        upsert_prospect(p)
    print(f"  Migrated {len(prospects)} prospects")


def migrate_tone_profile():
    profile = _read_json("tone_profile.json", None)
    if not profile:
        print("  tone_profile.json missing — skipping")
        return
    save_tone_profile(profile)
    print("  Migrated tone profile")


def migrate_approved_emails():
    emails = _read_json("approved_emails.json", [])
    if not emails:
        print("  approved_emails.json empty — skipping")
        return
    for e in emails:
        save_approved_email(
            e.get("subject", ""),
            e.get("body", ""),
            e.get("company", "") or e.get("prospect_name", ""),
            e.get("tone_variant", ""),
        )
    print(f"  Migrated {len(emails)} approved emails")


if __name__ == "__main__":
    print("Migrating JSON data to Supabase...")
    try:
        migrate_watchlist()
        migrate_tone_profile()
        migrate_approved_emails()
        print("\nMigration complete. Verify data in Supabase dashboard.")
    except Exception as e:
        print(f"\nMigration failed: {e}")
        sys.exit(1)
