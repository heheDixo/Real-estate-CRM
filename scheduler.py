"""
Morning research orchestrator.

Run with:
    python scheduler.py            # starts the APScheduler daemon
    python -c "from scheduler import run_morning_pipeline; run_morning_pipeline()"

The job runs at config.RESEARCH_CRON_HOUR:config.RESEARCH_CRON_MINUTE
(default 05:00) in config.TIMEZONE. The digest is sent to the broker at
config.DIGEST_SEND_HOUR (default 07:00).
"""

from __future__ import annotations

import datetime
import json
import os
import re
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import config
import database

DATA_DIR        = "data"
WATCHLIST_PATH  = os.path.join(DATA_DIR, "watchlist.json")
LOG_PATH        = os.path.join(DATA_DIR, "scheduler_log.json")
ERROR_LOG_PATH  = os.path.join(DATA_DIR, "error_log.json")
PROGRESS_PATH   = os.path.join(DATA_DIR, "pipeline_progress.json")


def _write_progress(pct: int, message: str) -> None:
    """Write pipeline progress percent + message so the UI can poll it."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(PROGRESS_PATH, "w") as f:
            json.dump({
                "pct":     int(pct),
                "message": message,
                "ts":      datetime.datetime.now().isoformat(),
            }, f, indent=2)
    except OSError:
        pass


# ── File helpers ────────────────────────────────────────────────────────────


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_json(path: str, default):
    _ensure_dir()
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _append_log(entry: Dict):
    log = _read_json(LOG_PATH, [])
    log.append(entry)
    with open(LOG_PATH, "w") as f:
        json.dump(log[-200:], f, indent=2)


def _log_error(scope: str, exc: Exception):
    log = _read_json(ERROR_LOG_PATH, [])
    log.append({
        "at":    datetime.datetime.now().isoformat(),
        "scope": scope,
        "error": str(exc),
        "type":  type(exc).__name__,
    })
    with open(ERROR_LOG_PATH, "w") as f:
        json.dump(log[-200:], f, indent=2)


# ── Per-prospect work ───────────────────────────────────────────────────────


# Generic web/marketing chrome that bart-mnli will otherwise score high on
# every label. Stripped from Firecrawl text before classification.
_NAV_CHROME_PATTERNS = [
    r"\bSkip to main content\b",
    r"\bLog ?in\b",
    r"\bSign ?in\b",
    r"\bSign ?up\b",
    r"\bSubscribe\b",
    r"\bMenu\b",
    r"\bClose\b",
    r"\bSearch\b",
    r"\bToggle navigation\b",
    r"\bCookie[s]? policy\b",
    r"\bAccept (all )?cookies?\b",
    r"\bPrivacy policy\b",
    r"\bTerms of (use|service)\b",
    r"\bAll rights reserved\b",
    r"\b(English|Español|Spanish|Français|French|Deutsch|German)\b",
]


def _clean_web_text(text: str) -> str:
    """Strip markdown chrome, images, links, phone numbers, navigation phrases."""
    if not text:
        return ""
    # Remove markdown images (![alt](url)) entirely
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    # Replace markdown links ([text](url)) with just the link text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Strip bare URLs
    text = re.sub(r"https?://\S+", " ", text)
    # Strip phone numbers (US formats)
    text = re.sub(r"\b1[-.\s]\d{3}[-.\s]\d{3}[-.\s]\d{4}\b", " ", text)
    text = re.sub(r"\(\d{3}\)\s*\d{3}[-.\s]?\d{4}", " ", text)
    text = re.sub(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b", " ", text)
    # Strip markdown heading markers (### / #### / ##) — leave the text after.
    # Match leading hashes at start-of-line OR after whitespace; collapse the
    # entire `#+` run plus the trailing space.
    text = re.sub(r"(^|\s)#{1,6}\s+", r"\1", text)
    # Strip lingering bold/italic markdown markers (** __ * _) — not the
    # content, just the markers.
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__",     r"\1", text)
    text = re.sub(r"(?<!\w)\*([^*\s][^*]*[^*\s]?)\*(?!\w)", r"\1", text)
    # Strip leftover blockquote markers
    text = re.sub(r"(^|\s)>\s+", r"\1", text)
    # Strip navigation chrome phrases
    for patt in _NAV_CHROME_PATTERNS:
        text = re.sub(patt, " ", text, flags=re.IGNORECASE)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _gather_signals(prospect: Dict) -> Dict:
    """Run all scrapers for one prospect and return a bundle of raw data."""
    from scrapers import (
        scrape_google_news, scrape_newsapi, scrape_firecrawl,
        scrape_linkedin_jobs, get_linkedin_snapshot,
    )

    company = prospect.get("company", "")
    website = prospect.get("website", "")
    city    = prospect.get("city", "Atlanta")

    bundle = {
        "articles":          [],
        "jobs":              [],
        "website":           {},
        "linkedin_snapshot": {},
    }

    n_gnews, n_newsapi = 0, 0

    try:
        gn = scrape_google_news(company) or []
        n_gnews = len(gn)
        bundle["articles"].extend(gn)
    except Exception as exc:
        _log_error("scheduler.google_news", exc)

    try:
        nn = scrape_newsapi(company) or []
        n_newsapi = len(nn)
        bundle["articles"].extend(nn)
    except Exception as exc:
        _log_error("scheduler.newsapi", exc)

    if website:
        try:
            bundle["website"] = scrape_firecrawl(website) or {}
        except Exception as exc:
            _log_error("scheduler.firecrawl", exc)

    # LinkedIn jobs — rate-limited to 1 req per 30s globally inside the
    # scraper. Sequential by definition; do not call from a thread pool.
    try:
        bundle["jobs"] = scrape_linkedin_jobs(company, city) or []
    except Exception as exc:
        _log_error("scheduler.linkedin_jobs", exc)

    # Google snippet for LinkedIn company page — defensive, low-risk.
    try:
        bundle["linkedin_snapshot"] = get_linkedin_snapshot(company) or {}
    except Exception as exc:
        _log_error("scheduler.linkedin_google", exc)

    # Fold the company website into the article list as a synthesized
    # "Company website" entry so research_agent's classifier picks it up.
    # Clean the Firecrawl markdown first — otherwise bart-mnli scores nav
    # chrome ("Skip to main content", login links, image markdown) high on
    # every label and every signal card ends up showing the same blob.
    web = bundle.get("website") or {}
    cleaned_about = _clean_web_text(web.get("about", ""))
    cleaned_news  = _clean_web_text(web.get("news",  ""))
    cleaned_home  = _clean_web_text(web.get("home",  ""))
    combined_web  = " ".join(
        s for s in (cleaned_about, cleaned_news, cleaned_home) if s
    ).strip()
    # Drop the home blurb if too short to be informative (it's usually a
    # tagline — useless for signal classification).
    if combined_web and len(combined_web) >= 120:
        bundle["articles"].append({
            "title":        f"{company} — company website",
            "description":  combined_web[:1500],
            "url":          website,
            "published_at": "",
            "source_name":  "Company website",
        })

    # de-dupe articles by URL (empty URLs treated as distinct)
    seen, deduped = set(), []
    for art in bundle["articles"]:
        url = art.get("url", "")
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        deduped.append(art)
    bundle["articles"] = deduped[:12]

    # If absolutely nothing came back from any source, log it once so the
    # broker can see why this prospect produced no signals.
    if n_gnews == 0 and n_newsapi == 0 and not combined_web:
        _log_error(
            "scheduler.no_articles",
            RuntimeError(f"All sources empty for {company or '<no-name>'}"),
        )

    return bundle


def _enrich_for_research(prospect: Dict) -> Dict:
    """
    Lightweight enrichment passthrough. The mock-data fallback layer has been
    removed; the morning pipeline now relies on real signals from scrapers +
    website text. Kept as a hook for a future enrichment source (Apollo,
    Hunter, etc.) without forcing a signature change downstream.
    """
    return {
        "months_since_funding": prospect.get("months_since_funding"),
        "headcount_growth_pct": prospect.get("headcount_growth_pct", 0),
        "headcount_current":    prospect.get("headcount", 0),
    }


def _generate_draft(report, prospect: Dict,
                     tone_injection: str,
                     variant: str = "Warm") -> Dict:
    """Generate email subject/body and LinkedIn variant via Mistral."""
    from hf_models.writer import OutreachWriter
    from models.prospect import Prospect

    writer = OutreachWriter()
    tone_prefix = config.TONE_VARIANT_PREFIXES.get(variant, "")

    # Build a minimal "synthetic" Prospect for the writer's interface
    syn = Prospect(
        company_name       = report.company,
        domain             = prospect.get("domain", ""),
        contact_name       = report.contact_name,
        contact_first_name = (report.contact_name or "").split(" ")[0],
        contact_last_name  = " ".join((report.contact_name or "").split(" ")[1:]),
        contact_title      = report.contact_title,
        contact_email      = report.contact_email,
        contact_linkedin   = report.linkedin_url,
        city               = prospect.get("city", "Atlanta"),
        industry           = prospect.get("sector", ""),
        last_funding_type  = "",
        last_funding_amount = 0,
        headcount          = 0,
    )

    # Inject the top hook into the prompt by using a small text-only prompt
    prefix_block = (tone_prefix + "\n\n") if tone_prefix else ""
    prompt = (
        f"[INST] {prefix_block}{config.EMAIL_SYSTEM_PROMPT}\n\n"
        f"{tone_injection}\n\n"
        f"Prospect:\n"
        f"Company: {syn.company_name}\n"
        f"Contact: {syn.contact_name}, {syn.contact_title}\n"
        f"City: {syn.city}\n\n"
        f"Key signal to open with:\n{report.top_hook}\n\n"
        f"Supporting signals (do not quote — use as context):\n"
        + "\n".join(f"- {s.title}" for s in report.signals[:3])
        + "\n\nNow write the email. Start with 'Subject:' on line 1.\n[/INST]"
    )

    subject, body = "", ""
    try:
        raw = writer._call_hf_api(prompt) if writer.available else ""
        if raw:
            subject, body = writer._parse_email(raw)
    except Exception as exc:
        _log_error("scheduler.email_generate", exc)

    if not subject or not body:
        # graceful fallback to template — feed the REAL firmographic numbers
        # we now have (Apollo headcount + Greenhouse/Ashby open roles) so
        # the fallback doesn't print "0% growth, 0 active postings" lies.
        try:
            from models.enrichment   import EnrichmentResult
            from models.score_result import ScoreResult
            stub_enrich = EnrichmentResult(
                prospect_id          = report.prospect_id,
                headcount_current    = report.headcount,
                total_jobs_posted    = report.open_roles,
                headcount_growth_pct = 0,   # no time-series source yet
            )
            stub_score = ScoreResult(prospect_id=report.prospect_id)
            subject, body = writer._fallback_email(syn, stub_enrich, stub_score)
        except Exception as exc:
            _log_error("scheduler.email_fallback", exc)
            subject = f"Quick thought on {report.company}"
            body    = (
                f"Hi {syn.contact_first_name},\n\n"
                f"{report.top_hook}\n\n"
                f"Worth a short conversation, even if only to put a marker down?\n\n"
                f"{config.AGENT_NAME}\n{config.AGENT_TITLE}\n{config.FIRM_NAME}"
            )

    # LinkedIn variant — re-use the writer
    linkedin = ""
    if writer.available:
        li_prompt = (
            f"[INST] {config.LINKEDIN_SYSTEM_PROMPT}\n\n"
            f"Prospect: {syn.contact_first_name} at {syn.company_name}.\n"
            f"Signal: {report.top_hook}\n\n"
            f"Write the LinkedIn message now. Under 300 characters. No subject.\n"
            f"[/INST]"
        )
        try:
            raw_li = writer._call_hf_api(li_prompt, max_tokens=120)
            linkedin = (raw_li or "").strip()[:300]
        except Exception as exc:
            _log_error("scheduler.linkedin_generate", exc)

    if not linkedin:
        linkedin = (
            f"Hi {syn.contact_first_name} — {report.top_hook[:200]} "
            f"Curious whether space planning is already on the table."
        )[:300]

    return {
        "subject":  subject,
        "body":     body,
        "linkedin": linkedin,
        "variant":  variant,
    }


# ── Pipeline ────────────────────────────────────────────────────────────────


def _enrich_firmographics(prospect: Dict) -> Dict:
    """
    Populate firmographic fields the report needs (headcount, industry,
    LinkedIn URL, open-role count) from free sources:

      - Apollo `organizations/enrich` for headcount + industry + LinkedIn
      - Greenhouse / Ashby / Lever public APIs for open-role counts

    Returns a possibly-mutated prospect dict. All sources are best-effort.
    """
    prospect = dict(prospect)
    domain = (prospect.get("domain") or "").strip()
    if not domain:
        return prospect

    # ── Apollo enrich (free plan endpoint) ─────────────────────────────────
    if config.APOLLO_AVAILABLE and not prospect.get("headcount"):
        try:
            from scrapers import apollo_enrich_org
            org = apollo_enrich_org(domain)
        except Exception as exc:
            _log_error("scheduler.apollo_enrich", exc)
            org = {}
        if org:
            if org.get("headcount") and not prospect.get("headcount"):
                prospect["headcount"] = org["headcount"]
            if org.get("industry") and not prospect.get("industry"):
                prospect["industry"] = org["industry"]
            if org.get("linkedin_url") and not prospect.get("linkedin_url"):
                prospect["linkedin_url"] = org["linkedin_url"]

    # ── Open-roles count via Greenhouse / Ashby / Lever ────────────────────
    if not prospect.get("open_roles"):
        try:
            from scrapers import scrape_jobs_board
            bundle = scrape_jobs_board(
                prospect.get("company", ""),
                domain,
            )
        except Exception as exc:
            _log_error("scheduler.jobs_board", exc)
            bundle = {}
        if bundle:
            prospect["open_roles"]   = bundle.get("count", 0)
            prospect["office_roles"] = bundle.get("office_count", 0)
            prospect["ats"]          = bundle.get("source", "")

    return prospect


def _process_prospect(prospect: Dict, tone_injection: str, variant: str = "Warm"):
    """Wraps signal-gathering + research-agent for one prospect, with errors caught."""
    from research_agent import generate_report
    try:
        prospect = _enrich_firmographics(prospect)
        bundle = _gather_signals(prospect)
        enrich = _enrich_for_research(prospect)
        report = generate_report(
            prospect, enrichment=enrich,
            articles=bundle["articles"],
            jobs=bundle["jobs"],
        )
        if not report.skip_today:
            report.draft = _generate_draft(report, prospect, tone_injection, variant)
        return report
    except Exception as exc:
        _log_error("scheduler.process_prospect", exc)
        return None


def _load_active_icp_profile() -> Dict:
    """
    Derive a usable ICP profile for lead discovery from the watchlist itself
    — the sector / city of the first active watchlist entry seeds the search
    queries. Falls back to a neutral default if the watchlist is empty.
    """
    wl = database.get_watchlist(active_only=True)
    active = next((w for w in wl if w.get("active", True)), {})
    sector = active.get("sector") or "Technology"
    city   = active.get("city")   or "Atlanta"
    name   = active.get("icp_profile") or f"{sector} — {city}"
    return {
        "id":          name,
        "name":        name,
        "sectors":     [sector],
        "geographies": [city],
    }


def run_morning_pipeline(triggered_by_email: str = "") -> Dict:
    """
    Discover new leads, research watchlist + discovered, generate drafts,
    push to Gmail, send digest. Progress is written to
    data/pipeline_progress.json so the UI can show a live bar.

    The morning digest is sent to whoever ran the pipeline:
      - ``triggered_by_email`` — set when a logged-in user clicks "Run
        pipeline" in the UI; the digest goes to that user.
      - empty (cron / ``--once``) — the digest goes to the Google account
        the pipeline is authenticated as (see the digest step below).
    """
    started_at = datetime.datetime.now()
    summary: Dict = {
        "started_at":    started_at.isoformat(),
        "completed_at":  "",
        "status":        "running",
        "watchlist":     0,
        "discovered":    0,
        "prospects":     0,
        "actionable":    0,
        "drafts_created": 0,
        "hot":           0,
        "warm":          0,
        "skipped":       0,
        "errors":        [],
        "today_file":    "",
    }

    _write_progress(0, "Starting pipeline…")

    # ── 1. Load ICP + discover new leads ─────────────────────────────────
    icp = _load_active_icp_profile()
    discovered: List[Dict] = []
    try:
        from lead_discovery import discover_new_leads
        from research_agent import save_discovered_leads
        discovered = discover_new_leads(icp, max_results=8)
        save_discovered_leads(discovered)
        for lead in discovered:
            try:
                database.upsert_prospect(lead)
            except Exception as exc:
                _log_error("scheduler.upsert_discovered", exc)
    except Exception as exc:
        _log_error("scheduler.discover", exc)
    summary["discovered"] = len(discovered)
    _write_progress(20, f"Discovery done — {len(discovered)} candidates.")

    # ── 2. Combine watchlist + discovered (discovered marked approved=False) ─
    watchlist = database.get_watchlist(active_only=True)
    active    = [p for p in watchlist if p.get("active", True)]
    summary["watchlist"] = len(active)

    for w in active:
        w.setdefault("source", "watchlist")
        w.setdefault("approved", True)

    all_prospects: List[Dict] = active + discovered
    summary["prospects"] = len(all_prospects)

    if not all_prospects:
        summary["status"]       = "no_prospects"
        summary["completed_at"] = datetime.datetime.now().isoformat()
        _append_log(summary)
        _write_progress(100, "No prospects to research.")
        return summary

    # ── 3. Research each prospect (parallel) ─────────────────────────────
    from tone_learner import load_tone_profile, build_tone_injection
    tone_profile   = load_tone_profile()
    tone_injection = build_tone_injection(tone_profile)

    _write_progress(40, f"Scraping signals for {len(all_prospects)} prospects…")

    # Sequential — LinkedIn enforces a 30s minimum between scraper calls
    # globally; running prospects in parallel would just serialise behind
    # the rate limiter and risk concurrent-access bugs in the shared
    # _last_request_time state inside scrapers/linkedin_jobs.py.
    reports: List = []
    for p in all_prospects:
        try:
            rep = _process_prospect(p, tone_injection, "Warm")
        except Exception as exc:
            _log_error("scheduler.process_prospect", exc)
            rep = None
        if rep is None:
            summary["errors"].append({
                "prospect": p.get("company"),
                "error":    "process_prospect returned None",
            })
            continue
        reports.append(rep)

    _write_progress(80, "Drafts generated.")

    # ── 4. Sort + summary counts ─────────────────────────────────────────
    reports.sort(key=lambda r: r.composite_score, reverse=True)
    actionable = [r for r in reports if not r.skip_today]
    summary["actionable"] = len(actionable)
    summary["hot"]        = sum(1 for r in actionable if r.tier == "hot")
    summary["warm"]       = sum(1 for r in actionable if r.tier == "warm")
    summary["skipped"]    = len(reports) - len(actionable)

    # ── 5. Push to Gmail Drafts (best-effort) ────────────────────────────
    try:
        from gmail_drafts import (
            authenticate_gmail, create_draft, send_morning_digest,
        )
        service = authenticate_gmail()
    except Exception as exc:
        _log_error("scheduler.gmail_auth", exc)
        service = None

    # Push HOT leads only to Gmail Drafts. Warm/nurture drafts stay inside
    # the morning_run JSON so the broker can promote them from the UI if a
    # hot lead doesn't pan out. The "To" field is left empty whenever the
    # stored contact_email is missing OR equals the broker's own address
    # (the watchlist placeholder) — Gmail's compose window then shows an
    # empty "To" so the broker pastes the real client email before sending.
    broker_self = {
        e.lower().strip()
        for e in (
            *config.BROKER_EMAILS,
            config.BROKER_EMAIL,
            config.AGENT_EMAIL,
            config.GMAIL_SENDER,
        )
        if e
    }
    if service:
        for report in actionable:
            if report.tier != "hot" or not report.draft:
                continue
            recipient = (report.contact_email or "").strip()
            if recipient.lower() in broker_self:
                recipient = ""
            try:
                info = create_draft(
                    service,
                    recipient,
                    report.draft["subject"],
                    report.draft["body"],
                    prospect_name=report.company,
                )
            except Exception as exc:
                _log_error("scheduler.create_draft", exc)
                continue
            if info:
                report.draft["draft_id"]  = info.get("id", "")
                report.draft["draft_url"] = info.get("url", "")
                summary["drafts_created"] += 1

    # ── 5b. Per-prospect research dossier (Google Doc) ────────────────────
    # Create one editorial dossier per actionable lead so the broker has a
    # shareable, durable summary they can open from the dashboard. Skipped
    # on prospects that already have a doc URL (re-runs don't duplicate).
    summary["docs_created"] = 0
    try:
        from google_docs import create_research_doc
        for report in actionable:
            if getattr(report, "research_doc_url", ""):
                continue
            try:
                url = create_research_doc(report)
            except Exception as exc:
                _log_error("scheduler.create_doc", exc)
                continue
            if url:
                report.research_doc_url = url
                summary["docs_created"] += 1
    except ImportError:
        pass

    # ── 6. Digest — goes to whoever ran the pipeline ─────────────────────
    # UI runs pass the logged-in user's address via ``triggered_by_email``.
    # For an unattended run (cron / --once) there is no interactive runner,
    # so we send to the Google account the pipeline is actually authenticated
    # as — that address is guaranteed real, which avoids bouncing off a demo
    # placeholder like the old static BROKER_EMAILS list did.
    if service:
        recipient = (triggered_by_email or "").strip()
        if not recipient:
            try:
                profile = service.users().getProfile(userId="me").execute()
                recipient = (profile.get("emailAddress") or "").strip()
            except Exception as exc:
                _log_error("scheduler.digest.whoami", exc)
                recipient = (
                    os.getenv("PRIMARY_BROKER_EMAIL", "").strip()
                    or config.BROKER_EMAIL
                )
        if recipient:
            try:
                send_morning_digest(service, recipient, reports)
            except Exception as exc:
                _log_error(f"scheduler.digest[{recipient}]", exc)

    # ── 6b. Sync yesterday's Gmail sends into Sheets + Calendar ──────────
    # Picks up anything the broker sent from Gmail directly that the
    # streamlit auto-sync missed (e.g. weekend sends with the app closed).
    try:
        from gmail_sync import sync_recent_sends
        sync_summary = sync_recent_sends(lookback_days=2)
        summary["gmail_sync"] = sync_summary
    except Exception as exc:
        _log_error("scheduler.gmail_sync", exc)

    # ── 7. Finalise summary + persist (status must be final before save) ─
    summary["completed_at"] = datetime.datetime.now().isoformat()
    summary["status"]       = (
        "success" if summary["drafts_created"] else
        "partial" if actionable else
        "no_actionable"
    )

    try:
        from research_agent import save_morning_run
        out_path = save_morning_run(reports, summary=summary)
        summary["today_file"] = out_path
    except Exception as exc:
        _log_error("scheduler.write_bundle", exc)

    # Persist each report to Supabase (best-effort — JSON above is fallback)
    for rep in reports:
        try:
            database.save_research_report(rep)
        except Exception as exc:
            _log_error("scheduler.save_research_report", exc)

    # Log the pipeline run row
    try:
        database.log_pipeline_run(
            status          = summary["status"],
            prospects_count = summary["prospects"],
            drafts_count    = summary["drafts_created"],
            skipped_count   = summary["skipped"],
            started_at      = summary["started_at"],
            completed_at    = summary["completed_at"],
        )
    except Exception as exc:
        _log_error("scheduler.log_pipeline_run", exc)

    _append_log(summary)
    _write_progress(100, summary["status"])
    return summary


def run_now() -> Dict:
    """Synonym for run_morning_pipeline — exposed for Streamlit triggers."""
    return run_morning_pipeline()


from monitoring import alert_pipeline_failed
from database import log_pipeline_run

def run_morning_pipeline_safe():
    """
    Safe wrapper around run_morning_pipeline().
    Catches all exceptions, sends alert, logs to database.
    The scheduler always calls this — never the raw function.
    """
    started_at = datetime.datetime.now().isoformat()
    print(f"[scheduler] Pipeline starting at {started_at}")

    try:
        summary = run_morning_pipeline()
        print(f"[scheduler] Pipeline complete — {summary.get('prospects', 0)} prospects")

        # Phase 4 — push the morning brief to every connected Telegram user.
        # Reports were just persisted to Supabase by run_morning_pipeline.
        try:
            from telegram_bot import send_morning_brief
            from database import get_all_telegram_users, get_most_recent_reports
            from types import SimpleNamespace

            tg_users = get_all_telegram_users()
            if tg_users:
                reports = [SimpleNamespace(**r) for r in get_most_recent_reports()]
                for tg_user in tg_users:
                    chat_id = tg_user.get("telegram_chat_id")
                    if chat_id and send_morning_brief(chat_id, reports):
                        print(f"[scheduler] Morning brief sent to Telegram {chat_id}")
        except Exception as tg_exc:
            _log_error("scheduler.telegram_brief", tg_exc)

    except Exception as e:
        completed_at = datetime.datetime.now().isoformat()
        error_str = str(e)
        print(f"[scheduler] Pipeline FAILED: {error_str}")
        _log_error("scheduler.run_morning_pipeline_safe", error_str)
        alert_pipeline_failed(error_str, datetime.date.today().isoformat())

        # Phase 4 — same alert via Telegram for users with bot connected.
        try:
            from telegram_bot import send_pipeline_failed_alert
            from database import get_all_telegram_users
            for tg_user in get_all_telegram_users():
                chat_id = tg_user.get("telegram_chat_id")
                if chat_id:
                    send_pipeline_failed_alert(chat_id, error_str)
        except Exception as tg_exc:
            _log_error("scheduler.telegram_failure_alert", tg_exc)

        log_pipeline_run(
            status          = "failed",
            prospects_count = 0,
            drafts_count    = 0,
            skipped_count   = 0,
            error           = error_str,
            started_at      = started_at,
            completed_at    = completed_at,
        )


from hf_client import warm_up_models

def _run_warmup():
    """Wakes HF models from cold start before the 5am pipeline."""
    print("[scheduler] Running model warm-up at 4:50 AM...")
    status = warm_up_models()
    print(f"[scheduler] Warm-up complete: {status}")

    # Alert if models are unreachable
    if not all(status.values()):
        failed = [k for k, v in status.items() if not v]
        from monitoring import send_alert
        send_alert(
            subject="HuggingFace models unreachable before pipeline",
            body=(
                f"Warm-up failed for: {', '.join(failed)}\n"
                f"The 5am pipeline will use fallback drafts this morning."
            )
        )

        # Phase 4 — mirror the alert to Telegram.
        try:
            from telegram_bot import send_warmup_failed_alert
            from database import get_all_telegram_users
            for tg_user in get_all_telegram_users():
                chat_id = tg_user.get("telegram_chat_id")
                if chat_id:
                    send_warmup_failed_alert(chat_id, failed)
        except Exception as tg_exc:
            _log_error("scheduler.telegram_warmup_alert", tg_exc)


# ── Scheduler daemon ────────────────────────────────────────────────────────


def start_scheduler():
    """Block forever, firing the pipeline at the configured cron time."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        print("[scheduler] apscheduler not installed.")
        return

    sched = BlockingScheduler(timezone=config.TIMEZONE)
    sched.add_job(
        _run_warmup,
        "cron",
        hour=4,
        minute=50,
        timezone=config.TIMEZONE,
        id="model_warmup",
    )
    sched.add_job(
        run_morning_pipeline_safe,
        "cron",
        hour     = config.RESEARCH_CRON_HOUR,
        minute   = config.RESEARCH_CRON_MINUTE,
        id       = "morning_research",
        name     = "CRE morning research",
        misfire_grace_time = 1800,
    )
    print(
        f"[scheduler] morning research scheduled for "
        f"{config.RESEARCH_CRON_HOUR:02d}:{config.RESEARCH_CRON_MINUTE:02d} "
        f"{config.TIMEZONE} (digest goes out around "
        f"{config.DIGEST_SEND_HOUR:02d}:00)."
    )
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        print("[scheduler] stopped.")


def start_scheduler_background():
    """Start the scheduler in a daemon thread (called from app.py)."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        return None

    sched = BackgroundScheduler(timezone=config.TIMEZONE, daemon=True)
    sched.add_job(
        _run_warmup,
        "cron",
        hour=4,
        minute=50,
        timezone=config.TIMEZONE,
        id="model_warmup",
    )
    sched.add_job(
        run_morning_pipeline_safe,
        "cron",
        hour   = config.RESEARCH_CRON_HOUR,
        minute = config.RESEARCH_CRON_MINUTE,
        id     = "morning_research",
        misfire_grace_time = 1800,
    )
    sched.start()
    return sched


# ── CLI ─────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        print("Running pipeline once...")
        run_morning_pipeline_safe()
        print("Done.")
    else:
        start_scheduler()
