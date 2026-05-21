"""
Morning Research — dark split-panel home.

Left column = lead list. Right column = signal detail + Start outreach.
"""

import datetime
import json
import os
import threading

import streamlit as st

import config
from research_agent import (
    ResearchReport,
    load_morning_run,
    load_discovered_leads,
    save_morning_run,
)
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


def _persist_reports(reports):
    try:
        save_morning_run(reports)
    except Exception:
        pass


def _run_pipeline_background():
    if st.session_state.get("research_running"):
        return
    st.session_state["research_running"] = True
    st.session_state["research_error"]   = ""

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
            st.session_state["research_error"] = str(exc)
        finally:
            st.session_state["research_running"] = False

    threading.Thread(target=_runner, daemon=True).start()


reports  = load_morning_run()
is_stale = bool(reports and reports[0].stale)
today_label = datetime.date.today().strftime("%a, %b %d")


# ── Top bar ─────────────────────────────────────────────────────────────────


title_col, status_col, btn_col = st.columns([3, 2, 1])

with title_col:
    st.markdown(
        '<div style="font-size:18px;font-weight:600;color:#e6edf3;">'
        'Morning research</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="font-size:12px;color:#8b949e;margin-top:2px;">'
        f'Today · {today_label} · {len(reports)} prospects enriched</div>',
        unsafe_allow_html=True,
    )

with status_col:
    if st.session_state.get("research_error"):
        st.markdown(
            f'<div style="font-size:12px;color:#f85149;padding-top:6px;">'
            f'{pulse_dot("#f85149")}Last run failed — see error log</div>',
            unsafe_allow_html=True,
        )
    elif st.session_state.get("research_running"):
        st.markdown(
            f'<div style="font-size:12px;color:#d29922;padding-top:6px;">'
            f'{pulse_dot("#d29922")}Research running…</div>',
            unsafe_allow_html=True,
        )
    elif reports:
        st.markdown(
            f'<div style="font-size:12px;color:#3fb950;padding-top:6px;">'
            f'{pulse_dot()}Research complete</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div style="font-size:12px;color:#8b949e;padding-top:6px;">'
            f'{pulse_dot("#484f58")}No research yet</div>',
            unsafe_allow_html=True,
        )

with btn_col:
    st.markdown('<div class="primary-btn">', unsafe_allow_html=True)
    if st.button(
        "▶ Run now",
        use_container_width=True,
        disabled=st.session_state.get("research_running", False),
        key="run_now_btn",
    ):
        _run_pipeline_background()
        st.toast("Research running…")
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


# ── Progress bar while running ──────────────────────────────────────────────


if st.session_state.get("research_running"):
    prog = _read_progress()
    pct = max(0, min(100, int(prog.get("pct", 0))))
    st.progress(pct / 100, text=prog.get("message", "Running…"))
    if pct >= 100:
        st.session_state["research_running"] = False
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


sent_today: set = set()
try:
    if config.SHEETS_SPREADSHEET_ID and os.path.exists(config.GOOGLE_CREDENTIALS_PATH):
        from google_sheets import authenticate_sheets, get_all_sent_emails
        svc = authenticate_sheets()
        if svc:
            for row in get_all_sent_emails(svc, config.SHEETS_SPREADSHEET_ID):
                if row.get("Date Sent") == datetime.date.today().isoformat():
                    sent_today.add((row.get("Contact Email") or "").lower())
except Exception:
    pass


def _is_sent(rep: ResearchReport) -> bool:
    return rep.contact_email.lower() in sent_today


# ── Filter pills ────────────────────────────────────────────────────────────


filter_choice = st.radio(
    "Filter",
    ["All", "Hot", "Warm", "Nurture", "New leads"],
    horizontal=True, label_visibility="collapsed",
    key="research_filter",
)

filter_fn = {
    "All":       lambda r: True,
    "Hot":       lambda r: r.tier == "hot"  and not r.skip_today,
    "Warm":      lambda r: r.tier == "warm" and not r.skip_today,
    "Nurture":   lambda r: r.tier == "nurture",
    "New leads": lambda r: r.source == "discovered",
}[filter_choice]

filtered = sorted(
    [r for r in reports if filter_fn(r)],
    key=lambda r: r.composite_score, reverse=True,
)


# ── Split panel ─────────────────────────────────────────────────────────────


left, right = st.columns([0.4, 0.6], gap="medium")


# Left — lead list
with left:
    st.markdown(
        '<div style="font-size:11px;color:#8b949e;text-transform:uppercase;'
        'letter-spacing:0.5px;margin-bottom:8px;">'
        f'Lead list  ·  {len(filtered)} '
        f'result{"s" if len(filtered) != 1 else ""}</div>',
        unsafe_allow_html=True,
    )

    if not filtered:
        empty_state("📭", "No leads match this filter.")

    selected_id = st.session_state.get("selected_report_id")

    for idx, rep in enumerate(filtered):
        is_selected = (rep.prospect_id == selected_id)
        tier_color  = config.TIER_COLORS.get(rep.tier, config.TIER_COLORS["nurture"])["bar"]
        accent      = tier_color if is_selected else "#30363d"
        card_bg     = "#1f2937" if is_selected else "#161b22"

        badges = tier_badge(rep.tier)
        if rep.source == "discovered" and not rep.approved:
            badges += " " + new_badge()
        if rep.draft:
            badges += " " + draft_ready_badge()
        if _is_sent(rep):
            badges += " " + sent_badge()

        st.markdown(
            f'<div style="background:{card_bg};border:1px solid #30363d;'
            f'border-left:3px solid {accent};border-radius:6px;'
            f'padding:10px 14px;margin-bottom:8px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:start;">'
            f'<div style="font-size:13px;font-weight:600;color:#e6edf3;">'
            f'{rep.company}</div>'
            f'<div style="font-size:18px;font-weight:600;color:{tier_color};">'
            f'{rep.composite_score}</div>'
            f'</div>'
            f'<div style="font-size:11px;color:#8b949e;margin-top:2px;">'
            f'{rep.contact_name or "—"} · {rep.contact_title or "—"}</div>'
            f'<div style="margin:6px 0;display:flex;gap:5px;flex-wrap:wrap;">'
            f'{badges}</div>'
            f'<div style="margin-top:6px;">{score_bar(rep.composite_score, rep.tier)}</div>'
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
        st.markdown(
            '<div style="height:220px;display:flex;align-items:center;'
            'justify-content:center;color:#484f58;font-size:13px;">'
            'Select a lead from the list to view research</div>',
            unsafe_allow_html=True,
        )
        st.stop()

    tier_color = config.TIER_COLORS.get(sel.tier, config.TIER_COLORS["nurture"])["bar"]

    # Header block
    st.markdown(
        f'<div style="background:#1c2128;border:1px solid #30363d;'
        f'border-radius:8px;padding:14px 16px;margin-bottom:12px;">'
        f'<div style="font-size:17px;font-weight:600;color:#e6edf3;">'
        f'{sel.company}</div>'
        f'<div style="font-size:12px;color:#8b949e;margin-top:4px;">'
        f'{sel.contact_name or "—"} · {sel.contact_title or "—"}</div>'
        + (f'<div style="font-size:11px;margin-top:6px;">'
           f'<a href="mailto:{sel.contact_email}" style="color:#58a6ff;">'
           f'{sel.contact_email}</a>'
           + (f'  ·  <a href="{sel.linkedin_url}" target="_blank" '
              f'style="color:#58a6ff;">LinkedIn ↗</a>' if sel.linkedin_url else "")
           + '</div>' if sel.contact_email else "")
        + f'</div>',
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

    # Approve / dismiss for discovered leads
    if sel.source == "discovered" and not sel.approved:
        st.markdown(
            '<div style="margin-top:14px;background:#2d1f5e;border:1px solid '
            '#3d2b6e;border-radius:6px;padding:10px 14px;font-size:12px;'
            'color:#a371f7;">'
            f'NEW lead — discovered via '
            f'{getattr(sel, "discovered_via", "Google News RSS")}. '
            'Approve to add to your watchlist, or dismiss.'
            '</div>',
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
        st.markdown(
            f'<div style="border-bottom:1px solid #21262d;padding:12px 0;">'
            f'<div style="display:flex;gap:10px;">'
            f'<div style="font-size:20px;flex-shrink:0;">{signal_icon(s.type)}</div>'
            f'<div style="flex:1;">'
            f'{signal_type_label(s.type)}'
            f'<div style="font-size:12px;font-weight:500;color:#e6edf3;margin:5px 0 3px;">'
            f'{s.title}</div>'
            f'<div style="font-size:11px;color:#8b949e;line-height:1.6;">'
            f'{s.description}</div>'
            f'<div style="display:flex;justify-content:space-between;'
            f'align-items:center;margin-top:6px;">'
            f'<span style="font-size:10px;color:#484f58;">{s.source} · {s.score:.0f}</span>'
            f'<span>{strength_dots(s.strength)}</span>'
            f'</div></div></div></div>',
            unsafe_allow_html=True,
        )

    # Start outreach
    st.markdown(
        '<div style="margin-top:16px;border-top:1px solid #30363d;'
        'padding-top:14px;"></div>',
        unsafe_allow_html=True,
    )

    already_sent = _is_sent(sel)
    btn_label = "Sent ✓" if already_sent else "✉  Start outreach →"
    st.markdown('<div class="primary-btn">', unsafe_allow_html=True)
    if st.button(
        btn_label,
        type="primary",
        use_container_width=True,
        disabled=already_sent,
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
                         "city":    "New York",
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
