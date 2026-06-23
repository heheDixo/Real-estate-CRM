"""
database.py
All Supabase CRUD operations for CRE Outreach Intelligence.

Fallback pattern used everywhere:
  - Try Supabase first
  - On any exception: log error, fall back to local JSON file
  - Never crash the app because of a database error

Connection layer (June 2026 fix):
  - Force HTTP/1.1 (http2=False) on the underlying httpx client.
    The supabase-py default builds postgrest's httpx Client with
    http2=True (postgrest/_sync/client.py). On HTTP/2 a closed/idle
    pooled connection raises RemoteProtocolError("Server disconnected")
    from httpcore/_sync/http2.py:443 AND sticks (the same exception is
    re-raised on every subsequent request on that connection). HTTP/1.1
    transparently re-opens dead sockets and does not poison the pool.
  - Defensive retry: _retry_on_disconnect() rebuilds the singleton and
    retries once on RemoteProtocolError / ConnectError / ReadError.
"""

import os
import json
import hashlib
import threading
from datetime import datetime, date
from typing import Optional, Callable, TypeVar, Any

import streamlit as st  # noqa: F401  (kept for module-level side effects elsewhere)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import httpx
    from supabase import create_client, Client
    from supabase.lib.client_options import SyncClientOptions
    print("[DEBUG] Supabase import successful")
except Exception:
    import traceback
    print("\n========== SUPABASE IMPORT ERROR ==========")
    traceback.print_exc()
    print("===========================================\n")
    httpx = None  # type: ignore
    create_client = None  # type: ignore
    Client = None  # type: ignore
    SyncClientOptions = None  # type: ignore


DATA_DIR = "data"


# ─────────────────────────────────────────
# Connection layer (singleton + retry)
# ─────────────────────────────────────────

_db_client: Optional["Client"] = None # type: ignore
_db_lock = threading.Lock()

# Network errors where the right move is "rebuild the client and try again".
# Imported lazily inside _is_disconnect() so module load doesn't depend on httpx.
_DISCONNECT_HINTS = (
    "Server disconnected",
    "ConnectionTerminated",
    "ConnectError",
    "ReadError",
    "ReadTimeout",
    "RemoteProtocolError",
    "ConnectionResetError",
    "WriteError",
)


def _is_disconnect(exc: BaseException) -> bool:
    """Best-effort detection of transport-level disconnects."""
    if httpx is None:
        return False
    if isinstance(
        exc,
        (
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.ReadTimeout,
            httpx.PoolTimeout,
        ),
    ):
        return True
    msg = f"{type(exc).__name__}: {exc}"
    return any(hint in msg for hint in _DISCONNECT_HINTS)


def _build_httpx_client():
    """
    Build the httpx.Client that supabase-py will use under the hood.

    Critical: http2=False. See module docstring for the rationale.
    """
    return httpx.Client(
        http2=False,
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,  # short keepalive avoids stale sockets
        ),
        follow_redirects=True,
    )


def _create_supabase_client() -> "Client": # type: ignore
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise ValueError("Missing SUPABASE_URL or SUPABASE_ANON_KEY")
    if create_client is None or SyncClientOptions is None or httpx is None:
        raise RuntimeError("Supabase library not importable")

    options = SyncClientOptions(httpx_client=_build_httpx_client())
    return create_client(url, key, options=options)


def _db() -> "Client": # type: ignore
    """
    Thread-safe singleton Supabase client.
    Stable for Streamlit + background threads (scheduler, telegram bot).
    """
    global _db_client
    if _db_client is not None:
        return _db_client
    with _db_lock:
        if _db_client is None:
            _db_client = _create_supabase_client()
    return _db_client


def reset_db() -> None:
    """
    Discard the cached client. The next _db() call will build a fresh one
    with a fresh httpx connection pool. Called by _retry_on_disconnect().
    Safe to call from any thread.
    """
    global _db_client
    with _db_lock:
        old = _db_client
        _db_client = None
    if old is not None:
        # best-effort close — supabase-py's sync client doesn't expose a
        # public close(), so we close the underlying httpx client directly.
        try:
            old.postgrest.session.close()
        except Exception:
            pass


T = TypeVar("T")


def _retry_on_disconnect(fn: Callable[[], T], *, attempts: int = 2) -> T:
    """
    Run a DB callable, rebuilding the client and retrying once on a
    transport-level disconnect. Application-level exceptions (PostgREST
    errors, 4xx responses, etc.) are NOT retried — they propagate to the
    caller's existing try/except + JSON fallback.
    """
    last_exc: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_disconnect(exc) or i == attempts - 1:
                raise
            print(f"[DB RETRY] transport disconnect ({type(exc).__name__}), rebuilding client...")
            reset_db()
    # Unreachable: loop either returns or raises.
    raise last_exc  # type: ignore[misc]


def _log_error(component: str, error: str) -> None:
    print(f"[DB ERROR] {component}: {error}")
    try:
        path = os.path.join(DATA_DIR, "error_log.json")
        try:
            with open(path) as f:
                log = json.load(f)
        except Exception:
            log = []
        log.append({
            "ts": datetime.now().isoformat(),
            "component": component,
            "error": str(error),
        })
        log = log[-500:]
        with open(path, "w") as f:
            json.dump(log, f)
    except Exception:
        pass


def _read_json(filename: str, default):
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(filename: str, data) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ─────────────────────────────────────────
# PROSPECTS
# ─────────────────────────────────────────

def get_watchlist(active_only: bool = True) -> list:
    try:
        def _go():
            db = _db()
            q = db.table("prospects").select("*")
            if active_only:
                q = q.eq("active", True).eq("approved", True).eq("dismissed", False)
            return q.order("added_at").execute()
        result = _retry_on_disconnect(_go)
        return result.data or []
    except Exception as e:
        _log_error("get_watchlist", str(e))
        return _read_json("watchlist.json", [])


_PROSPECT_COLUMNS = {
    "id", "company", "domain", "contact_name", "contact_title",
    "contact_email", "linkedin_url", "sector", "city", "icp_profile",
    "source", "approved", "active", "dismissed", "added_at",
    "discovered_at",
}


def upsert_prospect(prospect: dict) -> dict:
    try:
        row = {k: v for k, v in prospect.items() if k in _PROSPECT_COLUMNS}
        if not row.get("id") or not row.get("company"):
            return prospect
        if "approved" not in row:
            if row.get("source") == "discovered":
                row["approved"] = False
            else:
                row["approved"] = True
        result = _retry_on_disconnect(
            lambda: _db().table("prospects").upsert(row).execute()
        )
        return result.data[0] if result.data else prospect
    except Exception as e:
        _log_error("upsert_prospect", str(e))
        return prospect


def dismiss_prospect(prospect_id: str) -> None:
    try:
        def _go():
            db = _db()
            db.table("prospects").update({"dismissed": True, "active": False}).eq("id", prospect_id).execute()
            db.table("dismissed_leads").upsert({"id": prospect_id}).execute()
        _retry_on_disconnect(_go)
    except Exception as e:
        _log_error("dismiss_prospect", str(e))


def approve_prospect(prospect_id: str) -> None:
    try:
        _retry_on_disconnect(
            lambda: _db().table("prospects").update({"approved": True}).eq("id", prospect_id).execute()
        )
    except Exception as e:
        _log_error("approve_prospect", str(e))


def get_dismissed_ids() -> list:
    try:
        result = _retry_on_disconnect(
            lambda: _db().table("dismissed_leads").select("id").execute()
        )
        return [r["id"] for r in (result.data or [])]
    except Exception as e:
        _log_error("get_dismissed_ids", str(e))
        return []


# ─────────────────────────────────────────
# RESEARCH REPORTS
# ─────────────────────────────────────────

def save_research_report(report) -> str:
    """
    Accepts a ResearchReport dataclass instance.
    Returns the inserted uuid.
    """
    try:
        signals = [
            {
                "type":        s.type,
                "title":       s.title,
                "description": s.description,
                "source":      s.source,
                "strength":    s.strength,
                "score":       s.score,
            }
            for s in (report.signals or [])
        ]
        row = {
            "prospect_id":      report.prospect_id,
            "company":          report.company,
            "contact_name":     report.contact_name,
            "contact_title":    getattr(report, "contact_title", ""),
            "contact_email":    report.contact_email,
            "composite_score":  report.composite_score,
            "tier":             report.tier,
            "signals":          signals,
            "draft":            report.draft,
            "top_hook":         report.top_hook,
            "skip_today":       report.skip_today,
            "skip_reason":      report.skip_reason,
            "source":           getattr(report, "source", "watchlist"),
            "run_date":         date.today().isoformat(),
        }
        result = _retry_on_disconnect(
            lambda: _db().table("research_reports").upsert(
                row, on_conflict="run_date,prospect_id",
            ).execute()
        )
        return result.data[0]["id"] if result.data else ""
    except Exception as e:
        _log_error("save_research_report", str(e))
        return ""


def get_todays_reports(run_date: Optional[str] = None) -> list:
    target = run_date or date.today().isoformat()
    try:
        result = _retry_on_disconnect(
            lambda: (
                _db().table("research_reports")
                .select("*, prospects(approved)")
                .eq("run_date", target)
                .order("composite_score", desc=True)
                .execute()
            )
        )
        return result.data or []
    except Exception as e:
        _log_error("get_todays_reports", str(e))
        filename = f"morning_run_{target}.json"
        return _read_json(filename, [])


def get_most_recent_reports() -> list:
    """Returns today's reports, or most recent available if today has none."""
    reports = get_todays_reports()
    if reports:
        return reports
    try:
        latest = _retry_on_disconnect(
            lambda: (
                _db().table("research_reports")
                .select("run_date")
                .order("run_date", desc=True)
                .limit(1)
                .execute()
            )
        )
        if latest.data:
            last_date = latest.data[0]["run_date"]
            stale = get_todays_reports(last_date)
            for r in stale:
                r["stale"] = True
                r["stale_date"] = last_date
            return stale
    except Exception as e:
        _log_error("get_most_recent_reports", str(e))
    return []


# ─────────────────────────────────────────
# SENT EMAILS
# ─────────────────────────────────────────

def log_sent_email(data: dict) -> str:
    try:
        result = _retry_on_disconnect(
            lambda: _db().table("sent_emails").insert(data).execute()
        )
        return result.data[0]["id"] if result.data else ""
    except Exception as e:
        _log_error("log_sent_email", str(e))
        return ""


def update_email_status(contact_email: str, status: str,
                        reply_content: str = "",
                        reply_date: Optional[str] = None) -> None:
    try:
        update = {
            "status":        status,
            "reply_date":    reply_date or datetime.now().isoformat(),
            "reply_content": reply_content[:500] if reply_content else "",
        }
        _retry_on_disconnect(
            lambda: _db().table("sent_emails").update(update).eq("contact_email", contact_email).execute()
        )
    except Exception as e:
        _log_error("update_email_status", str(e))


def get_sent_emails(limit: int = 100) -> list:
    try:
        result = _retry_on_disconnect(
            lambda: (
                _db().table("sent_emails")
                .select("*")
                .order("sent_at", desc=True)
                .limit(limit)
                .execute()
            )
        )
        return result.data or []
    except Exception as e:
        _log_error("get_sent_emails", str(e))
        return []


def get_email_stats() -> dict:
    emails = get_sent_emails(1000)
    total   = len(emails)
    opened  = sum(1 for e in emails if e.get("status") in ("Opened", "Replied", "Meeting"))
    replied = sum(1 for e in emails if e.get("status") in ("Replied", "Meeting"))
    meeting = sum(1 for e in emails if e.get("status") == "Meeting")
    return {
        "total":      total,
        "open_rate":  round(opened  / total * 100, 1) if total else 0,
        "reply_rate": round(replied / total * 100, 1) if total else 0,
        "meetings":   meeting,
    }


# ─────────────────────────────────────────
# TONE PROFILE
# ─────────────────────────────────────────

DEFAULT_TONE_PROFILE = {
    "avg_sentence_length": 12,
    "opening_style":       "market observation",
    "cta_style":           "single question",
    "avg_word_count":      90,
    "sign_off":            "Best, Michael",
    "forbidden_phrases":   ["leverage", "circle back", "touching base", "synergy", "I hope this finds you"],
    "example_emails":      [],
}


def get_tone_profile() -> dict:
    try:
        result = _retry_on_disconnect(
            lambda: _db().table("tone_profiles").select("profile").eq("id", 1).execute()
        )
        if result.data:
            return result.data[0]["profile"]
    except Exception as e:
        _log_error("get_tone_profile", str(e))
    return _read_json("tone_profile.json", DEFAULT_TONE_PROFILE)


def save_tone_profile(profile: dict) -> None:
    try:
        _retry_on_disconnect(
            lambda: _db().table("tone_profiles").upsert({
                "id":         1,
                "profile":    profile,
                "updated_at": datetime.now().isoformat(),
            }).execute()
        )
    except Exception as e:
        _log_error("save_tone_profile", str(e))
    _write_json("tone_profile.json", profile)


# ─────────────────────────────────────────
# APPROVED EMAILS
# ─────────────────────────────────────────

def save_approved_email(subject: str, body: str,
                        company: str, tone_variant: str = "") -> None:
    try:
        _retry_on_disconnect(
            lambda: _db().table("approved_emails").insert({
                "subject":      subject,
                "body":         body,
                "company":      company,
                "tone_variant": tone_variant,
            }).execute()
        )
    except Exception as e:
        _log_error("save_approved_email", str(e))
    emails = _read_json("approved_emails.json", [])
    emails.append({"subject": subject, "body": body,
                   "company": company, "tone_variant": tone_variant,
                   "saved_at": datetime.now().isoformat()})
    _write_json("approved_emails.json", emails)


def get_approved_emails(limit: int = 50) -> list:
    try:
        result = _retry_on_disconnect(
            lambda: (
                _db().table("approved_emails")
                .select("*")
                .order("saved_at", desc=True)
                .limit(limit)
                .execute()
            )
        )
        return result.data or []
    except Exception as e:
        _log_error("get_approved_emails", str(e))
        return _read_json("approved_emails.json", [])


# ─────────────────────────────────────────
# PIPELINE RUNS
# ─────────────────────────────────────────

def log_pipeline_run(status: str, prospects_count: int,
                     drafts_count: int, skipped_count: int,
                     error: str = "", started_at: Optional[str] = None,
                     completed_at: Optional[str] = None) -> None:
    try:
        _retry_on_disconnect(
            lambda: _db().table("pipeline_runs").insert({
                "run_date":        date.today().isoformat(),
                "status":          status,
                "prospects_count": prospects_count,
                "drafts_count":    drafts_count,
                "skipped_count":   skipped_count,
                "error":           error[:500] if error else "",
                "started_at":      started_at or datetime.now().isoformat(),
                "completed_at":    completed_at or datetime.now().isoformat(),
            }).execute()
        )
    except Exception as e:
        _log_error("log_pipeline_run", str(e))


def get_pipeline_runs(limit: int = 30) -> list:
    try:
        result = _retry_on_disconnect(
            lambda: (
                _db().table("pipeline_runs")
                .select("*")
                .order("run_date", desc=True)
                .limit(limit)
                .execute()
            )
        )
        return result.data or []
    except Exception as e:
        _log_error("get_pipeline_runs", str(e))
        return []


# ─────────────────────────────────────────
# SCORE CACHE
# ─────────────────────────────────────────

def get_cached_score(cache_key: str) -> Optional[dict]:
    try:
        result = _retry_on_disconnect(
            lambda: _db().table("score_cache").select("result").eq("cache_key", cache_key).execute()
        )
        if result.data:
            return result.data[0]["result"]
    except Exception as e:
        _log_error("get_cached_score", str(e))
    return None


def save_cached_score(cache_key: str, result: dict) -> None:
    try:
        _retry_on_disconnect(
            lambda: _db().table("score_cache").upsert({
                "cache_key":  cache_key,
                "result":     result,
                "created_at": datetime.now().isoformat(),
            }).execute()
        )
    except Exception as e:
        _log_error("save_cached_score", str(e))


def make_cache_key(text: str, labels: list) -> str:
    raw = f"{text[:200]}|{'|'.join(labels)}"
    return hashlib.md5(raw.encode()).hexdigest()


# ─────────────────────────────────────────
# USERS
# ─────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[dict]:
    try:
        result = _retry_on_disconnect(
            lambda: _db().table("users").select("*").eq("google_email", email).execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        _log_error("get_user_by_email", str(e))
        return None


def update_user(user_id: str, data: dict) -> None:
    try:
        _retry_on_disconnect(
            lambda: _db().table("users").update(data).eq("id", user_id).execute()
        )
    except Exception as e:
        _log_error("update_user", str(e))


def get_all_telegram_users() -> list:
    """Returns all users with Telegram connected — used by scheduler."""
    try:
        result = _retry_on_disconnect(
            lambda: (
                _db().table("users")
                .select("id, google_email, telegram_chat_id, sign_off, firm_name")
                .eq("telegram_connected", True)
                .execute()
            )
        )
        return result.data or []
    except Exception as e:
        _log_error("get_all_telegram_users", str(e))
        return []