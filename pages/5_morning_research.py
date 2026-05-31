"""
Morning Research — dark split-panel home.

Left column = lead list. Right column = signal detail + Start outreach.
"""

import datetime
import json
import os
import re
import threading
import time

import streamlit as st


def _scrub(text: str) -> str:
    """Render-time defence — strip leftover markdown markers from saved
    descriptions so older morning_run JSONs render cleanly without a re-run.
    Also collapses runs of whitespace."""
    if not text:
        return ""
    t = re.sub(r"(^|\s)#{1,6}\s+", r"\1", str(text))   # headings
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)            # bold
    t = re.sub(r"__([^_]+)__",     r"\1", t)            # bold (underscore)
    t = re.sub(r"`([^`]+)`",       r"\1", t)            # inline code
    t = re.sub(r"\s*\\\\\s*",     " ",   t)             # escaped backslashes
    t = re.sub(r"(^|\s)>\s+",     r"\1", t)             # blockquote
    return re.sub(r"\s+", " ", t).strip()

import config
import database
from research_agent import (
    ResearchReport,
    load_morning_run,
    load_discovered_leads,
    save_morning_run,
)
from session_manager import get_google_credentials


_REPORT_FIELDS = {
    "prospect_id", "company", "contact_name", "contact_email",
    "signals", "composite_score", "tier", "top_hook", "skip_today",
    "skip_reason", "source", "contact_title", "linkedin_url",
    "sector", "approved", "headcount", "industry", "open_roles",
    "office_roles", "ats", "research_doc_url", "draft", "stale",
    "raw_articles", "raw_jobs", "generated_at",
}


def _row_to_report(row: dict) -> ResearchReport:
    """Convert a Supabase research_reports row into a ResearchReport."""
    d = {k: v for k, v in row.items() if k in _REPORT_FIELDS}
    return ResearchReport.from_dict(d)


def _load_reports() -> list:
    """Prefer Supabase; fall back to the local morning_run JSON."""
    rows = database.get_most_recent_reports()
    if rows:
        return [_row_to_report(r) for r in rows]
    return load_morning_run()
from ui_components import (
    page_shell,
    section_header,
    metric_card,
    tier_badge,
    score_bar,
    strength_dots,
    signal_type_label,
    signal_icon,
    info_row,
    new_badge,
    draft_ready_badge,
    sent_badge,
    empty_state,
    pulse_dot,
)


page_shell("Research")


# ── Telegram connect banner (Phase 4) ───────────────────────────────────────
# page_shell() already ran require_login(); the user dict is in session_state.
_user = st.session_state.get("current_user") or {}
# Credentials of the logged-in user — every Google call on this page must
# use these, otherwise the action lands in row-1's account (the legacy
# fallback in google_auth_loader). That's the multi-tenant bug fix.
_creds = get_google_credentials(_user) if _user else None
if _user.get("id") and not _user.get("telegram_connected"):
    from telegram_bot import get_connect_url
    _connect_url = get_connect_url(_user["id"])
    st.markdown(
        f"""
        <div style="
            background:#1a2332; border:1px solid #2d4a6e;
            border-radius:8px; padding:12px 16px; margin-bottom:16px;
            display:flex; align-items:center; justify-content:space-between;
            flex-wrap:wrap; gap:10px">
          <div>
            <div style="font-size:13px;font-weight:500;color:#e6edf3">
              📱 Get your morning brief on Telegram
            </div>
            <div style="font-size:11px;color:#8b949e;margin-top:2px">
              Receive daily lead summaries and reply notifications on your phone
            </div>
          </div>
          <a href="{_connect_url}" target="_blank" style="text-decoration:none">
            <div style="
                background:#229ed9; color:#ffffff;
                border-radius:6px; padding:8px 18px;
                font-size:12px; font-weight:500; white-space:nowrap">
              Connect Telegram →
            </div>
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )


PROGRESS_PATH = os.path.join("data", "pipeline_progress.json")


# ── Data ────────────────────────────────────────────────────────────────────


def _read_progress() -> dict:
    if not os.path.exists(PROGRESS_PATH):
        return {"pct": 0, "message": "", "ts": None}
    try:
        with open(PROGRESS_PATH) as f:
            return json.load(f)
    except Exception:
        return {"pct": 0, "message": "", "ts": None}


def _pipeline_is_running() -> bool:
    """True if the progress file says we're between 0 and 100, recently.

    Driven off the file rather than session_state because the worker thread
    can't safely write to session_state from outside Streamlit's context.
    Any progress entry whose timestamp is older than 5 minutes is treated as
    stale (the thread died without writing 100).
    """
    prog = _read_progress()
    pct  = prog.get("pct", -1)
    ts   = prog.get("ts")
    # pct < 0 means no file yet. pct >= 100 means done. Anything in
    # [0, 100) with a recent ts is in-flight.
    if pct < 0 or pct >= 100:
        return False
    if not ts:
        return False
    try:
        last = datetime.datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return False
    return (datetime.datetime.now() - last).total_seconds() < 300


def _persist_reports(reports):
    try:
        save_morning_run(reports)
    except Exception:
        pass


def _run_pipeline_background():
    """Spawn the pipeline in a daemon thread.

    The thread does NOT touch st.session_state — Streamlit ignores those
    writes from non-Streamlit threads and the UI ends up stuck. Progress and
    completion are observed via data/pipeline_progress.json instead.
    """
    if _pipeline_is_running():
        return

    def _runner():
        try:
            from scheduler import run_morning_pipeline
            run_morning_pipeline()
        except Exception as exc:
            try:
                err_path = os.path.join("data", "error_log.json")
                log = []
                if os.path.exists(err_path):
                    with open(err_path) as f:
                        log = json.load(f) or []
                log.append({
                    "at":    datetime.datetime.now().isoformat(),
                    "scope": "page_5.run_research",
                    "error": str(exc),
                    "type":  type(exc).__name__,
                })
                with open(err_path, "w") as f:
                    json.dump(log[-200:], f, indent=2)
            except Exception:
                pass

    threading.Thread(target=_runner, daemon=True).start()


reports  = _load_reports()
is_stale = bool(reports and reports[0].stale)
today_label = datetime.date.today().strftime("%a, %b %d")


# ── Editorial subhead ───────────────────────────────────────────────────────

_running = _pipeline_is_running()

# Build the dek (editorial deck) string
if _running:
    _status_html = (
        f'{pulse_dot("var(--accent-vermillion)")}'
        f'<span style="color:var(--accent-vermillion);">In motion</span>'
    )
elif reports:
    _status_html = (
        f'{pulse_dot("var(--accent-sage)")}'
        f'<span style="color:var(--text-secondary);">Filed</span>'
    )
else:
    _status_html = (
        f'{pulse_dot("var(--text-muted)")}'
        f'<span style="color:var(--text-muted);">Awaiting first run</span>'
    )

dek_col, btn_col = st.columns([4, 1])
with dek_col:
    st.markdown(
        f'<div style="display:flex;align-items:baseline;gap:24px;'
        f'margin:-4px 0 18px;">'
        f'<div style="font-family:var(--font-display);font-size:32px;'
        f'font-style:italic;line-height:1.1;color:var(--text-primary);'
        f'font-variation-settings:\'opsz\' 144,\'SOFT\' 100;letter-spacing:-0.025em;">'
        f'The morning brief'
        f'</div>'
        f'<div style="font-family:var(--font-mono);font-size:10.5px;'
        f'color:var(--text-muted);text-transform:uppercase;'
        f'letter-spacing:0.18em;padding-bottom:6px;">'
        f'{today_label} <span class="cre-bracket">/</span> '
        f'{len(reports)} prospects enriched <span class="cre-bracket">/</span> '
        f'{_status_html}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

with btn_col:
    st.markdown('<div class="primary-btn" style="margin-top:14px;">',
                 unsafe_allow_html=True)
    if st.button(
        "Run pipeline",
        use_container_width=True,
        disabled=_running,
        key="run_now_btn",
    ):
        _run_pipeline_background()
        st.toast("Research running…")
        time.sleep(0.5)
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


# ── Quick-access toolbar (Calendar · Sheet · Drive) ────────────────────────
# These three buttons sit immediately under the header so the user can
# jump to the Google surfaces the pipeline writes into without hunting
# through the sidebar. Each opens in a new tab.

_user_sheet_id = (_user.get("sheets_spreadsheet_id") or "").strip()
_qa_sheet_href = (
    f"https://docs.google.com/spreadsheets/d/{_user_sheet_id}/edit"
    if _user_sheet_id else ""
)

# Button stylesheet — neutral surface, accent-coloured icon, hover lift.
# Sheet button is greyed out (no href, reduced opacity) until the user has
# sent their first email and the spreadsheet has been auto-created.
_qa_btn_base = (
    "display:flex;align-items:center;justify-content:center;gap:10px;"
    "background:var(--bg-surface);border:1px solid var(--border);"
    "border-radius:8px;padding:12px 18px;text-decoration:none;"
    "font-family:var(--font-mono);font-size:11px;font-weight:500;"
    "letter-spacing:0.14em;text-transform:uppercase;"
    "color:var(--text-primary);transition:all 0.15s ease;"
)

_qa_calendar = (
    f'<a href="https://calendar.google.com/calendar/u/0/r" target="_blank" '
    f'style="{_qa_btn_base}border-left:3px solid var(--accent-cobalt);">'
    f'<span style="font-size:15px;">📅</span> Calendar follow-ups'
    f'</a>'
)
_qa_drive = (
    f'<a href="https://docs.google.com/document/u/0/" target="_blank" '
    f'style="{_qa_btn_base}border-left:3px solid var(--accent-gold);">'
    f'<span style="font-size:15px;">📄</span> Research docs · Google Docs'
    f'</a>'
)
if _qa_sheet_href:
    _qa_sheet = (
        f'<a href="{_qa_sheet_href}" target="_blank" '
        f'style="{_qa_btn_base}border-left:3px solid var(--accent-sage);">'
        f'<span style="font-size:15px;">📊</span> Sent tracker · Sheet'
        f'</a>'
    )
else:
    _qa_sheet = (
        f'<div style="{_qa_btn_base}border-left:3px solid var(--border);'
        f'opacity:0.45;cursor:not-allowed;">'
        f'<span style="font-size:15px;">📊</span> Sheet · sends after first email'
        f'</div>'
    )

st.markdown(
    f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;'
    f'margin:0 0 18px;">'
    f'{_qa_calendar}{_qa_drive}{_qa_sheet}'
    f'</div>',
    unsafe_allow_html=True,
)


# ── Progress bar + auto-poll while running ──────────────────────────────────


if _running:
    prog = _read_progress()
    pct  = max(0, min(100, int(prog.get("pct", 0))))
    st.progress(pct / 100, text=prog.get("message", "Running…"))
    # Poll: re-render every 2s so the bar advances. Streamlit's run-script
    # model means without this the UI freezes at the first snapshot.
    time.sleep(2)
    st.rerun()


# ── Stale banner ────────────────────────────────────────────────────────────


if is_stale:
    st.warning(
        "Showing yesterday's research — click ‘Run now’ to refresh."
    )


# ── Metrics row ─────────────────────────────────────────────────────────────


hot_count     = sum(1 for r in reports if r.tier == "hot"     and not r.skip_today)
warm_count    = sum(1 for r in reports if r.tier == "warm"    and not r.skip_today)
new_count     = sum(1 for r in reports if r.source == "discovered")
drafts_ready  = sum(1 for r in reports if r.draft)
n_signals     = sum(len(r.signals) for r in reports)

m1, m2, m3, m4 = st.columns(4)
with m1: metric_card("Prospects today", str(len(reports)))
with m2: metric_card("Hot leads",       str(hot_count),
                     value_color="#f85149" if hot_count else "#e6edf3")
with m3: metric_card("New signals",     str(n_signals))
with m4: metric_card("Drafts ready",    str(drafts_ready),
                     value_color="#3fb950" if drafts_ready else "#e6edf3")

st.markdown('<div style="margin:18px 0 8px;"></div>', unsafe_allow_html=True)


# ── Empty state ─────────────────────────────────────────────────────────────


if not reports:
    empty_state(
        "🔬",
        "No research yet for today.",
        "Click ‘Run now’ to scrape signals across the watchlist + discover new leads.",
    )
    st.stop()


# ── Sent lookup for the badge ──────────────────────────────────────────────
# Match on (company, contact_email) so multiple watchlist entries sharing the
# same placeholder email (e.g. the broker's own address) don't all show as
# sent the moment one of them is. Company alone covers the case where the
# email was edited after send.

sent_today_pairs: set = set()    # {(company_lower, email_lower)}
sent_today_companies: set = set()  # {company_lower}
try:
    from google_sheets import (
        authenticate_sheets, get_all_sent_emails, get_user_sheet_id,
    )
    _sid = get_user_sheet_id(_user)
    if _sid and _creds is not None:
        svc = authenticate_sheets(credentials=_creds)
        today_iso = datetime.date.today().isoformat()
        if svc:
            for row in get_all_sent_emails(svc, _sid):
                date_field = (row.get("Date Sent") or "")[:10]
                if date_field != today_iso:
                    continue
                company = (row.get("Company") or "").lower().strip()
                email_  = (row.get("Contact Email") or "").lower().strip()
                if company:
                    sent_today_companies.add(company)
                if company and email_:
                    sent_today_pairs.add((company, email_))
except Exception:
    pass


def _is_sent(rep: ResearchReport) -> bool:
    co = (rep.company or "").lower().strip()
    em = (rep.contact_email or "").lower().strip()
    if not co:
        return False
    if (co, em) in sent_today_pairs:
        return True
    # Fall back to company match — covers cases where the broker edited the
    # email after send (sheet has the new addr, lead still carries the old).
    return co in sent_today_companies and bool(em) is False


# ── Filter pills ────────────────────────────────────────────────────────────


filter_choice = st.radio(
    "Filter",
    ["All", "Hot", "Warm", "Nurture", "New leads"],
    horizontal=True, label_visibility="collapsed",
    key="research_filter",
)

# A "dead" lead is one that the pipeline ran but found nothing on today —
# composite=0, zero signals. They're corpses, not leads, so they don't
# belong in the default dashboard. Users can still find them via the raw
# watchlist file if they need to.
def _is_dead(r) -> bool:
    return r.composite_score == 0 and not r.signals

filter_fn = {
    "All":       lambda r: not _is_dead(r),
    "Hot":       lambda r: r.tier == "hot"  and not r.skip_today,
    "Warm":      lambda r: r.tier == "warm" and not r.skip_today,
    "Nurture":   lambda r: r.tier == "nurture" and not _is_dead(r),
    "New leads": lambda r: r.source == "discovered" and not _is_dead(r),
}[filter_choice]

filtered = sorted(
    [r for r in reports if filter_fn(r)],
    key=lambda r: r.composite_score, reverse=True,
)


# ── Split panel ─────────────────────────────────────────────────────────────


left, right = st.columns([0.4, 0.6], gap="medium")


# Left — lead list
with left:
    section_header(
        "Dispatch",
        f'{len(filtered)} entr{"ies" if len(filtered) != 1 else "y"}',
    )

    if not filtered:
        empty_state("📭", "No leads match this filter.",
                    "Try widening the criteria or run the pipeline.")

    selected_id = st.session_state.get("selected_report_id")

    for idx, rep in enumerate(filtered):
        is_selected = (rep.prospect_id == selected_id)
        tier_key    = (rep.tier or "nurture").lower()
        accent_var  = {
            "hot":     "var(--accent-vermillion)",
            "warm":    "var(--accent-gold)",
            "nurture": "var(--accent-cobalt)",
        }.get(tier_key, "var(--accent-cobalt)")

        badges = tier_badge(rep.tier)
        if rep.source == "discovered" and not rep.approved:
            badges += new_badge()
        if rep.draft:
            badges += draft_ready_badge()
        if _is_sent(rep):
            badges += sent_badge()

        # Selected card has a stronger left rule + brighter surface
        selected_bg = "var(--bg-elevated)" if is_selected else "var(--bg-surface)"

        # Compose the byline cleanly — skip the separator when one side is
        # empty, omit the byline entirely when both are. Avoids the ugly
        # "— · —" / "— · WORKPLACE EXPERIENCE LEAD" rendering.
        bits = [b for b in (rep.contact_name, rep.contact_title) if b]
        if bits:
            byline_inner = '<span class="cre-bracket">·</span>'.join(bits)
            byline_html = (
                f'<div style="font-family:var(--font-mono);font-size:10px;'
                f'color:var(--text-muted);margin-top:6px;letter-spacing:0.04em;'
                f'text-transform:uppercase;">{byline_inner}</div>'
            )
        else:
            byline_html = (
                f'<div style="font-family:var(--font-mono);font-size:10px;'
                f'color:var(--text-muted);margin-top:6px;letter-spacing:0.16em;'
                f'text-transform:uppercase;font-style:italic;opacity:0.7;">'
                f'Contact pending</div>'
            )

        st.markdown(
            f'<div class="cre-card {tier_key}" style="background:{selected_bg};'
            f'margin-bottom:10px;padding:14px 16px 14px 18px;">'
            # Headline row — serif company + serif score
            f'<div style="display:flex;justify-content:space-between;'
            f'align-items:baseline;gap:12px;">'
            f'<div style="font-family:var(--font-display);font-size:16px;'
            f'font-weight:500;color:var(--text-primary);letter-spacing:-0.01em;'
            f'font-variation-settings:\'opsz\' 144,\'SOFT\' 50;">'
            f'{rep.company}</div>'
            f'<div style="font-family:var(--font-display);font-size:24px;'
            f'font-weight:500;color:{accent_var};font-variant-numeric:tabular-nums;'
            f'font-variation-settings:\'opsz\' 144;line-height:1;">'
            f'{rep.composite_score}</div>'
            f'</div>'
            f'{byline_html}'
            # Tag strip
            f'<div style="margin:10px 0 8px;display:flex;gap:4px;flex-wrap:wrap;'
            f'align-items:center;">{badges}</div>'
            # Score rule
            f'{score_bar(rep.composite_score, rep.tier)}'
            f'</div>',
            unsafe_allow_html=True,
        )
        if st.button(
            "Open ›" if not is_selected else "✓ Selected",
            key=f"open_{rep.prospect_id}_{idx}",
            use_container_width=True,
            type="primary" if is_selected else "secondary",
        ):
            st.session_state["selected_report_id"] = rep.prospect_id
            st.rerun()


# Right — detail pane
with right:
    sel_id = st.session_state.get("selected_report_id")
    sel = next((r for r in filtered if r.prospect_id == sel_id), None)
    if sel is None and filtered:
        sel = filtered[0]
        st.session_state["selected_report_id"] = sel.prospect_id

    if sel is None:
        empty_state(
            "·",
            "Select a lead from the dispatch on the left",
            "Detail view appears here",
        )
        st.stop()

    tier_key   = (sel.tier or "nurture").lower()
    tier_var   = {
        "hot":     "var(--accent-vermillion)",
        "warm":    "var(--accent-gold)",
        "nurture": "var(--accent-cobalt)",
    }.get(tier_key, "var(--accent-cobalt)")
    tier_color = config.TIER_COLORS.get(sel.tier, config.TIER_COLORS["nurture"])["bar"]

    # Editorial dossier header — large serif company, italic kicker, contact links.
    # Compose the byline only from non-empty fields so we never print "— · —".
    bits = [b for b in (sel.contact_name, sel.contact_title) if b]
    if sel.industry:
        bits.append(sel.industry.title())
    if bits:
        contact_line = '<span class="cre-bracket">·</span>'.join(bits)
    else:
        contact_line = (
            '<span style="font-style:italic;opacity:0.7;">Contact pending</span>'
        )
    industry_line = ""

    contact_links = ""
    link_bits = []
    if sel.contact_email:
        link_bits.append(f'<a href="mailto:{sel.contact_email}">{sel.contact_email}</a>')
    if sel.linkedin_url:
        link_bits.append(f'<a href="{sel.linkedin_url}" target="_blank">LinkedIn ↗</a>')
    if getattr(sel, "research_doc_url", ""):
        link_bits.append(
            f'<a href="{sel.research_doc_url}" target="_blank" '
            f'style="color:var(--accent-gold);">Research doc ↗</a>'
        )
    if link_bits:
        contact_links = (
            f'<div style="font-family:var(--font-mono);font-size:10px;'
            f'margin-top:10px;letter-spacing:0.04em;">'
            + '<span class="cre-bracket">·</span>'.join(link_bits)
            + '</div>'
        )

    st.markdown(
        f'<div class="cre-card {tier_key}" style="padding:20px 24px 22px;'
        f'margin-bottom:18px;animation-delay:0s;">'
        # Kicker
        f'<div style="font-family:var(--font-mono);font-size:9.5px;'
        f'text-transform:uppercase;letter-spacing:0.22em;color:{tier_var};'
        f'margin-bottom:8px;">— {sel.tier.title()} tier dossier</div>'
        # Headline company
        f'<div style="font-family:var(--font-display);font-size:34px;'
        f'font-weight:500;color:var(--text-primary);line-height:1;'
        f'letter-spacing:-0.025em;font-variation-settings:\'opsz\' 144,\'SOFT\' 50;">'
        f'{sel.company}</div>'
        # Byline
        f'<div style="font-family:var(--font-mono);font-size:10.5px;'
        f'color:var(--text-muted);margin-top:10px;letter-spacing:0.08em;'
        f'text-transform:uppercase;">{contact_line}{industry_line}</div>'
        f'{contact_links}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Mini score row
    s1, s2, s3 = st.columns(3)
    with s1:
        metric_card("Score", f"{sel.composite_score}/100",
                     value_color=tier_color)
    with s2:
        metric_card("Signals", str(len(sel.signals)),
                     value_color="#3fb950" if sel.signals else "#e6edf3")
    with s3:
        metric_card("Tier", sel.tier.title(), value_color=tier_color)

    # Firmographic row — headcount (Apollo), open roles (Greenhouse/Ashby/Lever)
    f1, f2, f3 = st.columns(3)
    with f1:
        metric_card(
            "Headcount",
            f"{sel.headcount:,}" if sel.headcount else "—",
            value_color="#e6edf3",
        )
    with f2:
        roles_label = (
            f"{sel.open_roles}"
            + (f" ({sel.ats})" if sel.ats else "")
        ) if sel.open_roles else "—"
        metric_card(
            "Open roles",
            roles_label,
            value_color="#3fb950" if sel.open_roles else "#e6edf3",
        )
    with f3:
        metric_card(
            "Office / RE roles",
            str(sel.office_roles) if sel.office_roles else "—",
            value_color="#d29922" if sel.office_roles else "#e6edf3",
        )

    # ── Research doc generator (on-demand) ────────────────────────────────
    st.markdown(
        '<div style="margin-top:14px;padding-top:14px;'
        'border-top:1px solid var(--border-faint);"></div>',
        unsafe_allow_html=True,
    )
    _doc_url = getattr(sel, "research_doc_url", "") or ""
    if not _doc_url:
        if st.button(
            "Generate research doc",
            key=f"gen_doc_{sel.prospect_id}",
            use_container_width=True,
        ):
            with st.spinner("Composing dossier in Google Docs…"):
                try:
                    from google_docs import create_research_doc
                    url = create_research_doc(sel, credentials=_creds)
                except Exception as exc:
                    st.error(f"Doc creation failed: {type(exc).__name__}: {exc}")
                    url = ""
                if url:
                    sel.research_doc_url = url
                    _persist_reports(reports)
                    st.success("Research doc created ✓")
                    time.sleep(0.6)
                    st.rerun()
                else:
                    st.warning(
                        "Couldn't create the doc — check that the Docs API is "
                        "enabled in your Google Cloud project, then try again. "
                        "Details in `data/error_log.json` under scope `docs.*`."
                    )
    else:
        # Prominent "open the doc" button shown in the same slot the
        # Generate button occupied — so the link is right where the user
        # last looked. Gold accent matches the Drive / research-docs
        # quick-link in the header for visual consistency.
        st.markdown(
            f'<a href="{_doc_url}" target="_blank" style="display:flex;'
            f'align-items:center;justify-content:center;gap:10px;'
            f'background:var(--bg-surface);border:1px solid var(--border);'
            f'border-left:3px solid var(--accent-gold);border-radius:8px;'
            f'padding:12px 18px;text-decoration:none;'
            f'font-family:var(--font-mono);font-size:11.5px;font-weight:500;'
            f'letter-spacing:0.14em;text-transform:uppercase;'
            f'color:var(--text-primary);">'
            f'<span style="font-size:15px;">📄</span> Open research doc ↗'
            f'</a>',
            unsafe_allow_html=True,
        )

    # Approve / dismiss for discovered leads
    if sel.source == "discovered" and not sel.approved:
        via = getattr(sel, "discovered_via", "Google News")
        st.markdown(
            f'<div style="margin:14px 0;padding:12px 14px;'
            f'background:var(--bg-surface);border:1px solid var(--border);'
            f'border-left:3px solid var(--accent-sage);">'
            f'<span class="cre-chip new" style="margin-right:10px;">Filed today</span>'
            f'<span style="font-family:var(--font-body);font-size:13px;'
            f'color:var(--text-secondary);">'
            f'Sourced from <em style="color:var(--text-primary);'
            f'font-style:italic;">{via}</em>. '
            f'Approve to add to the watchlist.</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
        c_yes, c_no = st.columns(2)
        with c_yes:
            if st.button("✓ Add to watchlist",
                         key=f"approve_{sel.prospect_id}",
                         use_container_width=True):
                from lead_discovery import approve_lead
                src = next(
                    (d for d in load_discovered_leads()
                     if d.get("id") == sel.prospect_id
                     or d.get("company") == sel.company),
                    None,
                )
                payload = src or {
                    "id":      sel.prospect_id,
                    "company": sel.company,
                    "domain":  sel.prospect_id.split("-", 1)[-1] + ".com",
                    "sector":  sel.sector,
                    "contact_name":  sel.contact_name,
                    "contact_title": sel.contact_title,
                    "contact_email": sel.contact_email,
                    "linkedin_url":  sel.linkedin_url,
                    "active":  True,
                }
                if approve_lead(payload):
                    sel.approved = True
                    sel.source   = "watchlist"
                    _persist_reports(reports)
                    st.success("Added to watchlist")
                    st.rerun()
        with c_no:
            if st.button("✗ Dismiss",
                         key=f"dismiss_{sel.prospect_id}",
                         use_container_width=True):
                from lead_discovery import dismiss_lead
                dismiss_lead(sel.prospect_id)
                reports[:] = [r for r in reports if r.prospect_id != sel.prospect_id]
                _persist_reports(reports)
                st.session_state["selected_report_id"] = None
                st.warning("Dismissed — won't surface again")
                st.rerun()

    section_header("Signals", f"{len(sel.signals)} captured")

    if not sel.signals:
        st.markdown(
            '<div style="font-size:12px;color:#484f58;padding:8px 0;">'
            'No signals captured for this prospect today.</div>',
            unsafe_allow_html=True,
        )

    for s in sel.signals:
        title_clean = _scrub(s.title)
        desc_clean  = _scrub(s.description)
        st.markdown(
            f'<div style="padding:14px 0;border-bottom:1px solid var(--border-faint);">'
            # Type chip + score on the same line as the kicker
            f'<div style="display:flex;justify-content:space-between;'
            f'align-items:center;margin-bottom:8px;">'
            f'<span>{signal_icon(s.type)}{signal_type_label(s.type)}</span>'
            f'<span style="font-family:var(--font-mono);font-size:9.5px;'
            f'color:var(--text-muted);letter-spacing:0.18em;text-transform:uppercase;">'
            f'{s.source} <span class="cre-bracket">·</span> '
            f'<span style="color:var(--text-data);font-variant-numeric:tabular-nums;">'
            f'{s.score:.0f}</span></span>'
            f'</div>'
            # Headline — serif, italic
            f'<div style="font-family:var(--font-display);font-size:15px;'
            f'color:var(--text-primary);line-height:1.3;letter-spacing:-0.01em;'
            f'font-variation-settings:\'opsz\' 144;margin-bottom:4px;">'
            f'{title_clean}</div>'
            # Body — body font, secondary
            f'<div style="font-family:var(--font-body);font-size:12.5px;'
            f'color:var(--text-secondary);line-height:1.55;">'
            f'{desc_clean}</div>'
            # Strength rule
            f'<div style="margin-top:8px;">{strength_dots(s.strength)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Start outreach
    st.markdown(
        '<div style="margin-top:16px;border-top:1px solid #30363d;'
        'padding-top:14px;"></div>',
        unsafe_allow_html=True,
    )

    already_sent = _is_sent(sel)
    if already_sent:
        st.markdown(
            f'<div style="margin-bottom:10px;font-family:var(--font-mono);'
            f'font-size:10px;color:var(--accent-sage);letter-spacing:0.18em;'
            f'text-transform:uppercase;">'
            f'<span class="cre-pulse ok"></span>Sent today · open again to re-engage'
            f'</div>',
            unsafe_allow_html=True,
        )
    btn_label = (
        "Open thread →" if already_sent else "✉  Start outreach →"
    )
    st.markdown('<div class="primary-btn">', unsafe_allow_html=True)
    if st.button(
        btn_label,
        type="primary",
        use_container_width=True,
        key=f"outreach_{sel.prospect_id}",
    ):
        if not sel.draft:
            with st.spinner("Generating draft with Mistral…"):
                try:
                    from scheduler    import _generate_draft
                    from tone_learner import load_tone_profile, build_tone_injection
                    injection = build_tone_injection(load_tone_profile())
                    sel.draft = _generate_draft(
                        sel,
                        {"company": sel.company,
                         "domain":  sel.prospect_id.replace("-", "") + ".com",
                         "city":    "Atlanta",
                         "sector":  sel.sector},
                        injection, "Warm",
                    )
                    _persist_reports(reports)
                except Exception as exc:
                    st.error(f"Draft generation failed: {exc}")
                    st.stop()
        st.session_state["active_lead"] = sel.to_dict()
        st.switch_page("pages/3_draft_review.py")
    st.markdown('</div>', unsafe_allow_html=True)
