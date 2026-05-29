"""
Google Docs — per-prospect research dossier generator.

For each actionable ResearchReport, create_research_doc() builds a clean
editorial doc in the broker's Drive containing:

  - Headline:   company + tier badge + composite score
  - Section:    Contact + firmographics (headcount, open roles, industry)
  - Section:    Signals (each with title, description, source, score)
  - Section:    Recommended outreach (Mistral subject + body + LinkedIn)
  - Section:    Sources & metadata

Returns the document URL so the UI can link to it.

Auth: shares ``credentials.json`` with Gmail/Sheets/Calendar; caches its
own token at ``data/docs_token.json``. Requires Docs API enabled in the
GCP project + the ``documents`` scope.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Dict, List, Optional

import config


SCOPES     = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",  # to make the doc shareable
]
TOKEN_PATH = os.path.join("data", "docs_token.json")


# ── Error logging ───────────────────────────────────────────────────────────


def _log(scope: str, exc) -> None:
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
            "error": str(exc)[:280],
            "type":  type(exc).__name__ if isinstance(exc, Exception) else "Info",
        })
        with open(path, "w") as f:
            json.dump(log[-200:], f, indent=2)
    except Exception:
        pass


# ── Auth ────────────────────────────────────────────────────────────────────


def authenticate_docs(credentials=None, user_id=None):
    """Return (docs_service, drive_service) tuple, or (None, None) on failure.

    If `credentials` is passed (from a logged-in Streamlit user), use them
    directly. Otherwise (scheduler / background job), load the token for
    `user_id` (or the env-pinned primary broker) from Supabase via
    google_auth_loader.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        _log("docs.auth.import", exc)
        return None, None

    if credentials is None:
        from google_auth_loader import load_user_credentials_from_db
        credentials = load_user_credentials_from_db(SCOPES, user_id=user_id)
        if credentials is None:
            _log("docs.auth.no_credentials",
                 RuntimeError("No Google token in Supabase — sign in first"))
            return None, None

    try:
        docs  = build("docs",  "v1", credentials=credentials, cache_discovery=False)
        drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return docs, drive
    except Exception as exc:
        _log("docs.auth.build", exc)
        return None, None


# ── Content composition ─────────────────────────────────────────────────────


def _compose_lines(report) -> List[Dict]:
    """
    Return a list of {text, style} entries that describe the doc in order.

    style ∈ {"TITLE", "HEADING_1", "HEADING_2", "BOLD", "MUTED", "BODY"}.

    Two-pass design so insertion (text only) and styling (ranges) are
    handled separately.
    """
    lines: List[Dict] = []

    def _attr(r, k, d=""):
        if isinstance(r, dict):
            return r.get(k, d)
        return getattr(r, k, d)

    company   = _attr(report, "company") or "Untitled prospect"
    tier      = (_attr(report, "tier") or "").title()
    score     = _attr(report, "composite_score", 0)
    industry  = (_attr(report, "industry") or "").title()
    headcount = _attr(report, "headcount", 0) or 0
    open_r    = _attr(report, "open_roles", 0) or 0
    office_r  = _attr(report, "office_roles", 0) or 0
    ats       = _attr(report, "ats", "")

    # ── Title block ──
    lines.append({"text": company,                                "style": "TITLE"})
    lines.append({"text": f"{tier} tier  ·  composite {score}/100" +
                          (f"  ·  {industry}" if industry else ""),
                   "style": "MUTED"})
    lines.append({"text": f"Generated {datetime.date.today().strftime('%a %d %b %Y')}",
                   "style": "MUTED"})
    lines.append({"text": "",                                     "style": "BODY"})

    # ── Contact ──
    lines.append({"text": "Contact",                              "style": "HEADING_1"})
    contact_lines = []
    name  = _attr(report, "contact_name") or "—"
    title = _attr(report, "contact_title") or "—"
    email = _attr(report, "contact_email") or "—"
    li    = _attr(report, "linkedin_url") or "—"
    contact_lines.append(f"Name:      {name}")
    contact_lines.append(f"Title:     {title}")
    contact_lines.append(f"Email:     {email}")
    contact_lines.append(f"LinkedIn:  {li}")
    for cl in contact_lines:
        lines.append({"text": cl, "style": "BODY"})
    lines.append({"text": "", "style": "BODY"})

    # ── Firmographics ──
    lines.append({"text": "Firmographics",                        "style": "HEADING_1"})
    firm_lines = []
    firm_lines.append(f"Headcount:       {headcount:,}" if headcount else
                       "Headcount:       —")
    firm_lines.append(
        f"Open roles:      {open_r}" +
        (f"  (via {ats})" if ats else "") if open_r else
        "Open roles:      —"
    )
    firm_lines.append(
        f"Office / RE:     {office_r}  (workplace, facilities, real estate)"
        if office_r else "Office / RE:     —"
    )
    for fl in firm_lines:
        lines.append({"text": fl, "style": "BODY"})
    lines.append({"text": "", "style": "BODY"})

    # ── Signals ──
    signals = _attr(report, "signals") or []
    lines.append({"text": f"Signals captured  ({len(signals)})",
                   "style": "HEADING_1"})
    if not signals:
        lines.append({"text": "No live signals captured for this prospect today.",
                       "style": "MUTED"})
    for sig in signals:
        sig_type = (_attr(sig, "type") or "signal").replace("_", " ").title()
        sig_title = _attr(sig, "title") or "Untitled signal"
        sig_desc  = _attr(sig, "description") or ""
        sig_src   = _attr(sig, "source") or "—"
        sig_score = _attr(sig, "score", 0)
        sig_url   = _attr(sig, "url") or ""

        lines.append({"text": f"{sig_type.upper()}  ·  {sig_score:.0f}/100",
                       "style": "MUTED"})
        lines.append({"text": sig_title,                          "style": "HEADING_2"})
        if sig_desc:
            lines.append({"text": sig_desc,                       "style": "BODY"})
        meta = f"Source: {sig_src}"
        if sig_url:
            meta += f"   ·   {sig_url}"
        lines.append({"text": meta,                               "style": "MUTED"})
        lines.append({"text": "",                                 "style": "BODY"})

    # ── Top hook ──
    top_hook = _attr(report, "top_hook")
    if top_hook:
        lines.append({"text": "Opening hook",                     "style": "HEADING_1"})
        lines.append({"text": top_hook,                           "style": "BODY"})
        lines.append({"text": "",                                 "style": "BODY"})

    # ── Recommended outreach ──
    draft = _attr(report, "draft")
    if draft:
        lines.append({"text": "Recommended outreach",             "style": "HEADING_1"})
        subj = (draft.get("subject")  if isinstance(draft, dict) else "") or ""
        body = (draft.get("body")     if isinstance(draft, dict) else "") or ""
        link = (draft.get("linkedin") if isinstance(draft, dict) else "") or ""
        variant = (draft.get("variant") if isinstance(draft, dict) else "") or "Warm"

        lines.append({"text": f"Tone variant: {variant}",         "style": "MUTED"})
        lines.append({"text": "",                                 "style": "BODY"})
        lines.append({"text": "Email — Subject",                  "style": "HEADING_2"})
        lines.append({"text": subj,                               "style": "BODY"})
        lines.append({"text": "",                                 "style": "BODY"})
        lines.append({"text": "Email — Body",                     "style": "HEADING_2"})
        for line in body.split("\n"):
            lines.append({"text": line,                           "style": "BODY"})
        lines.append({"text": "",                                 "style": "BODY"})
        lines.append({"text": "LinkedIn message",                 "style": "HEADING_2"})
        lines.append({"text": link,                               "style": "BODY"})
        lines.append({"text": "",                                 "style": "BODY"})

    # ── Sources / metadata ──
    lines.append({"text": "Sources & metadata",                   "style": "HEADING_1"})
    articles = _attr(report, "raw_articles") or []
    if articles:
        for a in articles[:10]:
            a_title = a.get("title", "")[:140] if isinstance(a, dict) else ""
            a_url   = a.get("url", "")        if isinstance(a, dict) else ""
            a_src   = a.get("source_name", "—") if isinstance(a, dict) else "—"
            lines.append({"text": f"·  [{a_src}] {a_title}",      "style": "BODY"})
            if a_url:
                lines.append({"text": f"   {a_url}",              "style": "MUTED"})
    else:
        lines.append({"text": "No article sources captured.",     "style": "MUTED"})
    lines.append({"text": "", "style": "BODY"})
    lines.append({
        "text": f"Generated by CRE Outreach · {_attr(report, 'generated_at','')[:19]} · "
                f"prospect_id={_attr(report, 'prospect_id','')}",
        "style": "MUTED",
    })

    return lines


# ── Doc creation ────────────────────────────────────────────────────────────


_STYLE_MAP = {
    "TITLE":     "TITLE",
    "HEADING_1": "HEADING_1",
    "HEADING_2": "HEADING_2",
    "BODY":      "NORMAL_TEXT",
    "MUTED":     "NORMAL_TEXT",   # muted has color override applied separately
}


def create_research_doc(report, folder_id: str = "",
                          credentials=None, user_id: str = "") -> str:
    """
    Create a research doc for *report* and return its public URL.

    Returns "" on failure (auth, API disabled, etc.) — never raises into
    the caller. Failures are logged to data/error_log.json.

    If folder_id is provided, the doc is moved into that Drive folder.
    When called from a Streamlit page, pass the logged-in user's
    `credentials` so the doc lands in that user's Drive — not whichever
    Google account happens to be row-1 in the users table.
    """
    docs, drive = authenticate_docs(credentials=credentials,
                                    user_id=user_id or None)
    if docs is None:
        return ""

    def _attr(r, k, d=""):
        if isinstance(r, dict):
            return r.get(k, d)
        return getattr(r, k, d)

    company = _attr(report, "company") or "Untitled prospect"
    date    = datetime.date.today().strftime("%Y-%m-%d")
    title   = f"{company} — Research · {date}"

    # ── 1. Create empty doc ───────────────────────────────────────────────
    try:
        doc = docs.documents().create(body={"title": title}).execute()
    except Exception as exc:
        _log("docs.create", exc)
        return ""

    doc_id = doc.get("documentId", "")
    if not doc_id:
        return ""

    # ── 2. Build the requests for batchUpdate ─────────────────────────────
    lines = _compose_lines(report)
    requests: List[Dict] = []
    cursor = 1   # Docs index starts at 1 (after the implicit first \n)

    # First, insert ALL the text as one big string. Track each line's range
    # so we can style it after.
    big_text = ""
    line_ranges: List[tuple] = []   # (start, end, style)
    for entry in lines:
        text = (entry.get("text") or "") + "\n"
        start = cursor + len(big_text)
        big_text += text
        end   = cursor + len(big_text) - 1   # exclude the trailing \n from the styled range
        line_ranges.append((start, end, entry["style"]))

    requests.append({
        "insertText": {
            "location": {"index": cursor},
            "text":     big_text,
        }
    })

    # Now style each line
    for (start, end, style) in line_ranges:
        if end <= start:
            continue
        named = _STYLE_MAP.get(style, "NORMAL_TEXT")
        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end + 1},
                "paragraphStyle": {"namedStyleType": named},
                "fields": "namedStyleType",
            }
        })
        if style == "MUTED":
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {
                        "foregroundColor": {
                            "color": {"rgbColor": {
                                "red": 0.45, "green": 0.47, "blue": 0.50,
                            }}
                        },
                        "fontSize": {"magnitude": 9.5, "unit": "PT"},
                    },
                    "fields": "foregroundColor,fontSize",
                }
            })
        elif style == "TITLE":
            requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            })

    # ── 3. Apply batchUpdate ──────────────────────────────────────────────
    try:
        docs.documents().batchUpdate(
            documentId = doc_id,
            body       = {"requests": requests},
        ).execute()
    except Exception as exc:
        _log("docs.batchUpdate", exc)
        # The doc was created but un-styled — still return its URL.

    # ── 4. Optionally move to a folder ────────────────────────────────────
    if folder_id and drive is not None:
        try:
            drive.files().update(
                fileId    = doc_id,
                addParents = folder_id,
                fields    = "id,parents",
            ).execute()
        except Exception as exc:
            _log("docs.move_folder", exc)

    return f"https://docs.google.com/document/d/{doc_id}/edit"


if __name__ == "__main__":
    # CLI smoke test
    import json as _json
    from research_agent import load_morning_run
    reports = load_morning_run()
    if not reports:
        print("No reports — run scheduler.py --once first.")
        raise SystemExit(0)
    hot = next((r for r in reports if r.tier == "hot"), reports[0])
    print(f"Creating research doc for {hot.company}…")
    url = create_research_doc(hot)
    print(f"URL: {url}")
