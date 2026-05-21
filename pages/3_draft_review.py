"""
Draft Review — dark focused full-width.

Expects ``st.session_state["active_lead"]`` to be a ResearchReport dict
set by pages/5_morning_research.py on the "Start outreach" click.
"""

import datetime
import json
import os
import smtplib
import ssl
import time as _time
from email.mime.text import MIMEText

import streamlit as st

import config
from research_agent import ResearchReport, load_morning_run, save_morning_run
from ui_components import (
    page_shell,
    section_header,
    signal_type_label,
    info_row,
)


page_shell("Draft")


# ── Load + guard ────────────────────────────────────────────────────────────


active = st.session_state.get("active_lead")
if not active:
    st.markdown(
        '<div style="background:#161b22;border:1px solid #30363d;'
        'border-radius:8px;padding:30px;text-align:center;">'
        '<div style="font-size:32px;margin-bottom:10px;">✏️</div>'
        '<div style="font-size:14px;color:#e6edf3;">No lead selected</div>'
        '<div style="font-size:11px;color:#8b949e;margin-top:6px;">'
        'Open a lead from the research page to start an outreach.</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div style="margin-top:12px;" class="primary-btn">',
                unsafe_allow_html=True)
    if st.button("← Back to research", use_container_width=True):
        st.switch_page("pages/5_morning_research.py")
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

lead = ResearchReport.from_dict(active)


def _persist_lead(updated: ResearchReport) -> None:
    """Persist into both today's bundle and the watchlist (where applicable)."""
    try:
        reports = load_morning_run()
        for i, r in enumerate(reports):
            if r.prospect_id == updated.prospect_id:
                reports[i] = updated
                break
        else:
            reports.append(updated)
        save_morning_run(reports)
        st.session_state["active_lead"] = updated.to_dict()
    except Exception:
        pass

    # Mirror the edit to watchlist.json so the next pipeline run sees it too.
    try:
        wl_path = os.path.join("data", "watchlist.json")
        if os.path.exists(wl_path):
            with open(wl_path) as f:
                wl = json.load(f) or []
            for i, w in enumerate(wl):
                if (w.get("id") == updated.prospect_id
                        or w.get("company") == updated.company):
                    wl[i]["contact_email"] = updated.contact_email
                    wl[i]["contact_name"]  = (updated.contact_name
                                                or w.get("contact_name", ""))
                    wl[i]["contact_title"] = (updated.contact_title
                                                or w.get("contact_title", ""))
                    with open(wl_path, "w") as f:
                        json.dump(wl, f, indent=2)
                    break
    except Exception:
        pass


# ── Breadcrumb / header ─────────────────────────────────────────────────────


col_back, col_title = st.columns([1, 5])
with col_back:
    if st.button("← Research", use_container_width=True, key="back_btn"):
        st.switch_page("pages/5_morning_research.py")
with col_title:
    st.markdown(
        f'<div style="padding-top:6px;font-size:16px;font-weight:500;color:#e6edf3;">'
        f'{lead.company}  '
        f'<span style="color:#8b949e;font-weight:400;font-size:13px;">'
        f'· {lead.contact_name or "—"} · {lead.contact_title or "—"}</span></div>',
        unsafe_allow_html=True,
    )

st.markdown('<div style="margin:10px 0 16px;"></div>', unsafe_allow_html=True)


# ── Two-pane layout ────────────────────────────────────────────────────────


brief_col, draft_col = st.columns([0.35, 0.65], gap="medium")


# ── Left — research brief + summary ────────────────────────────────────────


with brief_col:
    section_header("Research brief", f"{len(lead.signals)} signals")

    with st.expander("View signals", expanded=False):
        if not lead.signals:
            st.markdown(
                '<div style="font-size:11px;color:#484f58;">'
                'No signals attached to this lead.</div>',
                unsafe_allow_html=True,
            )
        for s in lead.signals[:6]:
            st.markdown(
                f'<div style="padding:8px 0;border-bottom:1px solid #21262d;">'
                f'{signal_type_label(s.type)}'
                f'<div style="font-size:12px;color:#e6edf3;margin-top:4px;">'
                f'{s.title}</div>'
                f'<div style="font-size:11px;color:#8b949e;margin-top:2px;">'
                f'{s.source} · {s.score:.0f}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    if lead.top_hook:
        st.markdown(
            f'<div style="margin-top:14px;background:#0d1f3d;border:1px solid '
            f'#1c3a5e;border-radius:6px;padding:10px 12px;">'
            f'<div style="font-size:10px;color:#58a6ff;text-transform:uppercase;'
            f'letter-spacing:0.5px;margin-bottom:4px;">Opening hook</div>'
            f'<div style="font-size:12px;color:#e6edf3;line-height:1.6;">'
            f'{lead.top_hook}</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="margin-top:16px;"></div>', unsafe_allow_html=True)
    tier_color = config.TIER_COLORS.get(
        lead.tier, config.TIER_COLORS["nurture"]
    )["bar"]
    st.markdown(
        info_row("Score", f"{lead.composite_score}/100", tier_color)
        + info_row("Tier", lead.tier.capitalize(), tier_color)
        + info_row("Signals", str(len(lead.signals)))
        + info_row("Source", lead.source.capitalize()),
        unsafe_allow_html=True,
    )

    # Editable contact email — required to send. Persists back to the lead.
    section_header("Contact email", "Required for Gmail draft / Send now")
    new_email = st.text_input(
        "Contact email",
        value=lead.contact_email or "",
        placeholder="firstname.lastname@company.com",
        key=f"contact_email_{lead.prospect_id}",
        label_visibility="collapsed",
    )
    if new_email != lead.contact_email:
        lead.contact_email = new_email.strip()
        _persist_lead(lead)


# ── Right — draft editor ───────────────────────────────────────────────────


def _regen_for_variant(variant: str) -> dict:
    from scheduler    import _generate_draft
    from tone_learner import load_tone_profile, build_tone_injection
    injection = build_tone_injection(load_tone_profile())
    return _generate_draft(
        lead,
        {"company": lead.company,
         "domain":  lead.prospect_id.replace("-", "") + ".com",
         "city":    "New York",
         "sector":  lead.sector},
        injection, variant,
    )


with draft_col:
    section_header("Tone variant",
                   "Switching tone regenerates the draft with Mistral.")

    draft = dict(lead.draft) if lead.draft else {
        "subject": "", "body": "", "linkedin": "", "variant": "Warm",
    }

    tone_variants = ["Direct", "Warm", "Consultative"]
    current_variant = draft.get("variant", "Warm")
    variant_choice = st.radio(
        "Tone", tone_variants,
        horizontal=True, label_visibility="collapsed",
        index=tone_variants.index(current_variant)
              if current_variant in tone_variants else 1,
        key=f"tone_choice_{lead.prospect_id}",
    )

    if variant_choice != draft.get("variant"):
        with st.spinner(f"Rewriting in {variant_choice} tone…"):
            try:
                draft = _regen_for_variant(variant_choice)
                lead.draft = draft
                _persist_lead(lead)
            except Exception as exc:
                st.error(f"Regeneration failed: {exc}")

    # Subject
    section_header("Subject line")
    subject = st.text_input(
        "Subject", value=draft.get("subject", ""),
        key=f"subject_{lead.prospect_id}",
        label_visibility="collapsed",
    )

    # Body
    section_header("Email body")
    body = st.text_area(
        "Body", value=draft.get("body", ""),
        height=240, key=f"body_{lead.prospect_id}",
        label_visibility="collapsed",
    )
    wc = len(body.split())
    wc_color = ("#3fb950" if wc <= 110 else
                 "#d29922" if wc <= 140 else
                 "#f85149")
    st.markdown(
        f'<div style="font-size:11px;color:{wc_color};text-align:right;'
        f'margin-top:-8px;">{wc} words</div>',
        unsafe_allow_html=True,
    )

    # LinkedIn
    section_header("LinkedIn message", "Under 300 characters")
    linkedin_msg = st.text_area(
        "LinkedIn", value=draft.get("linkedin", ""),
        height=80, key=f"li_{lead.prospect_id}",
        label_visibility="collapsed",
    )
    cc = len(linkedin_msg)
    cc_color = "#3fb950" if cc <= 300 else "#f85149"
    st.markdown(
        f'<div style="font-size:11px;color:{cc_color};text-align:right;'
        f'margin-top:-8px;">{cc}/300</div>',
        unsafe_allow_html=True,
    )

    # Actions
    st.markdown(
        '<div style="margin-top:18px;border-top:1px solid #30363d;'
        'padding-top:14px;"></div>',
        unsafe_allow_html=True,
    )

    if not lead.contact_email:
        st.markdown(
            '<div style="background:#2d1f00;border:1px solid #5a3d00;'
            'color:#d29922;border-radius:4px;padding:8px 12px;font-size:12px;'
            'margin-bottom:10px;">'
            '⚠ Add a contact email above to enable Gmail draft and Send now.'
            '</div>',
            unsafe_allow_html=True,
        )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        if st.button("↺ Regenerate", use_container_width=True, key="regen_btn"):
            with st.spinner(f"Regenerating in {variant_choice} tone…"):
                try:
                    draft = _regen_for_variant(variant_choice)
                    lead.draft = draft
                    _persist_lead(lead)
                    for k in (f"subject_{lead.prospect_id}",
                              f"body_{lead.prospect_id}",
                              f"li_{lead.prospect_id}"):
                        st.session_state.pop(k, None)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Regenerate failed: {exc}")

    with c2:
        if st.button("📋 Copy", use_container_width=True, key="copy_btn"):
            st.code(f"Subject: {subject}\n\n{body}", language="text")

    with c3:
        if st.button("📤 Gmail draft", use_container_width=True,
                     key="gmail_draft_btn",
                     disabled=not lead.contact_email):
            try:
                from gmail_drafts import authenticate_gmail, create_draft
                svc = authenticate_gmail()
                if svc is None:
                    st.error("Gmail auth failed — see data/error_log.json")
                else:
                    info = create_draft(
                        svc, lead.contact_email, subject, body,
                        prospect_name=lead.company,
                    )
                    if info:
                        lead.draft = dict(draft)
                        lead.draft.update({
                            "subject":  subject,
                            "body":     body,
                            "linkedin": linkedin_msg,
                            "draft_id":  info.get("id", ""),
                            "draft_url": info.get("url", ""),
                        })
                        _persist_lead(lead)
                        # log a Draft row to Sheets if configured
                        if config.SHEETS_SPREADSHEET_ID:
                            try:
                                from google_sheets import (
                                    authenticate_sheets, log_sent_email,
                                )
                                ssvc = authenticate_sheets()
                                if ssvc:
                                    log_sent_email(
                                        ssvc, config.SHEETS_SPREADSHEET_ID, {
                                            "Date Sent":     datetime.date.today().isoformat(),
                                            "Company":       lead.company,
                                            "Contact Name":  lead.contact_name,
                                            "Contact Title": lead.contact_title,
                                            "Contact Email": lead.contact_email,
                                            "LinkedIn URL":  lead.linkedin_url,
                                            "Email Subject": subject,
                                            "Email Body":    body,
                                            "Research Signals": json.dumps(
                                                [s.title for s in lead.signals]
                                            ),
                                            "Score":         lead.composite_score,
                                            "Tier":          lead.tier,
                                            "Source":        f"page_3 ({variant_choice})",
                                            "Status":        "Draft",
                                        },
                                    )
                            except Exception:
                                pass
                        st.success("Draft created in Gmail ✓")
                        if info.get("url"):
                            st.link_button("Open in Gmail ↗", info["url"])
                    else:
                        st.error("Draft creation failed.")
            except Exception as exc:
                st.error(f"Draft creation failed: {exc}")

    with c4:
        st.markdown('<div class="primary-btn">', unsafe_allow_html=True)
        if st.button("🚀 Send now", type="primary",
                     use_container_width=True, key="send_btn",
                     disabled=not lead.contact_email):
            if not config.GMAIL_AVAILABLE:
                st.error(
                    "Gmail SMTP not configured. Set GMAIL_ADDRESS and "
                    "GMAIL_APP_PASSWORD in .env."
                )
            else:
                try:
                    msg = MIMEText(body, "plain")
                    msg["From"]    = config.GMAIL_ADDRESS
                    msg["To"]      = lead.contact_email
                    msg["Subject"] = subject
                    with smtplib.SMTP_SSL(
                        "smtp.gmail.com", 465,
                        context=ssl.create_default_context(),
                    ) as smtp:
                        smtp.login(config.GMAIL_ADDRESS,
                                    config.GMAIL_APP_PASSWORD)
                        smtp.send_message(msg)
                    st.success(
                        f"Sent to {lead.contact_email} at "
                        f"{datetime.datetime.now().strftime('%H:%M:%S')}"
                    )
                    # Sheets log
                    if config.SHEETS_SPREADSHEET_ID:
                        try:
                            from google_sheets import (
                                authenticate_sheets, log_sent_email,
                            )
                            ssvc = authenticate_sheets()
                            if ssvc:
                                log_sent_email(
                                    ssvc, config.SHEETS_SPREADSHEET_ID, {
                                        "Date Sent":     datetime.date.today().isoformat(),
                                        "Company":       lead.company,
                                        "Contact Name":  lead.contact_name,
                                        "Contact Title": lead.contact_title,
                                        "Contact Email": lead.contact_email,
                                        "LinkedIn URL":  lead.linkedin_url,
                                        "Email Subject": subject,
                                        "Email Body":    body,
                                        "Research Signals": json.dumps(
                                            [s.title for s in lead.signals]
                                        ),
                                        "Score":         lead.composite_score,
                                        "Tier":          lead.tier,
                                        "Source":        f"page_3 ({variant_choice})",
                                        "Status":        "Sent",
                                    },
                                )
                        except Exception:
                            pass
                    # Calendar follow-up
                    if os.path.exists(config.GOOGLE_CREDENTIALS_PATH):
                        try:
                            from google_calendar import (
                                authenticate_calendar, create_followup_event,
                            )
                            csvc = authenticate_calendar()
                            if csvc:
                                first = (lead.contact_name or "").split(" ")[0] or "Contact"
                                last  = " ".join((lead.contact_name or "").split(" ")[1:]) or ""
                                create_followup_event(
                                    csvc, config.CALENDAR_ID,
                                    {"contact_first_name": first,
                                     "contact_last_name":  last,
                                     "company":            lead.company,
                                     "contact_title":      lead.contact_title,
                                     "linkedin_url":       lead.linkedin_url,
                                     "top_signal":         lead.top_hook},
                                    sent_date     = datetime.datetime.now(),
                                    email_subject = subject,
                                    email_body    = body,
                                    new_angle     = (
                                        "Pick a different signal next time — try "
                                        f"the {lead.signals[1].type if len(lead.signals) > 1 else 'market'} "
                                        "angle to avoid repeating yourself."
                                    ),
                                    research_brief = "  ·  ".join(
                                        s.title for s in lead.signals[:2]
                                    ),
                                )
                        except Exception:
                            pass
                    try:
                        from tone_learner import save_approved_email
                        save_approved_email(subject, body, lead.company)
                    except Exception:
                        pass

                    lead.draft = dict(draft)
                    lead.draft.update({
                        "subject":  subject,
                        "body":     body,
                        "linkedin": linkedin_msg,
                        "sent_at":  datetime.datetime.now().isoformat(),
                    })
                    _persist_lead(lead)

                    _time.sleep(2)
                    st.session_state.pop("active_lead", None)
                    st.switch_page("pages/5_morning_research.py")
                except Exception as exc:
                    st.error(f"Send failed: {exc}")
        st.markdown('</div>', unsafe_allow_html=True)
