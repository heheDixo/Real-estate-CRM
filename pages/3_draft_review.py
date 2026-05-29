"""
Draft Review — dark focused full-width.

Expects ``st.session_state["active_lead"]`` to be a ResearchReport dict
set by pages/5_morning_research.py on the "Start outreach" click.
"""

import datetime
import json
import os
import time as _time

import streamlit as st

import config
import database
from research_agent import ResearchReport, load_morning_run, save_morning_run
from session_manager import get_google_credentials
from ui_components import (
    page_shell,
    section_header,
    signal_type_label,
    info_row,
)


page_shell("Draft")

# Logged-in user (set by require_login → page_shell). Every Google call on
# this page MUST use these credentials so the action lands in *this* user's
# Gmail / Sheets / Calendar — not whoever happens to be row 1 in the users
# table. See google_auth_loader.load_user_credentials_from_db for the
# legacy "first user wins" fallback this avoids.
_user  = st.session_state.get("current_user") or {}
_creds = get_google_credentials(_user) if _user else None


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

    # Mirror the edit to the prospects table so the next pipeline run sees it too.
    try:
        database.upsert_prospect({
            "id":            updated.prospect_id,
            "company":       updated.company,
            "contact_email": updated.contact_email,
            "contact_name":  updated.contact_name,
            "contact_title": updated.contact_title,
        })
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
                svc = authenticate_gmail(credentials=_creds)
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
                        # Log a Draft row to *this user's* sheet — lazily
                        # created in their Drive on first call so each user
                        # owns their own sent-tracker spreadsheet.
                        if _user:
                            try:
                                from google_sheets import (
                                    authenticate_sheets, ensure_user_sheet,
                                    log_sent_email,
                                )
                                ssvc = authenticate_sheets(credentials=_creds)
                                if ssvc:
                                    sid = ensure_user_sheet(ssvc, _user)
                                    if sid:
                                        log_sent_email(
                                            ssvc, sid, {
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
            if _creds is None:
                st.error(
                    "Google sign-in required to send. Sign out and sign in "
                    "with Google to authorise Gmail send for your account."
                )
            else:
                # Pre-send Hunter verification — block on hard fails so the
                # broker doesn't bounce. Sets a session flag so a second
                # click overrides for cases where Hunter is wrong.
                verify_result = {"valid": True, "score": 50, "status": "unknown"}
                try:
                    from scrapers import verify_hunter_email
                    verify_result = verify_hunter_email(lead.contact_email)
                except Exception:
                    pass

                hard_bad = verify_result.get("status") in (
                    "undeliverable", "invalid_format", "invalid"
                )
                if hard_bad and not st.session_state.get("confirm_bad_email"):
                    st.error(
                        f"Hunter says this email looks "
                        f"{verify_result.get('status','undeliverable')} "
                        f"(score {verify_result.get('score', 0)}/100). "
                        f"Click **Send now** again to override and send "
                        f"anyway, or update the address above."
                    )
                    st.session_state["confirm_bad_email"] = True
                    st.stop()

                # Clear the override flag on a clean send
                st.session_state.pop("confirm_bad_email", None)

                try:
                    # Send via the Gmail API using the *logged-in* user's
                    # credentials. The previous SMTP path used a shared
                    # GMAIL_APP_PASSWORD env var, so every web user's sends
                    # left from the primary broker's mailbox — that's the
                    # exact bug this page-rewrite fixes.
                    from gmail_drafts import authenticate_gmail, send_email_now
                    gmail_svc = authenticate_gmail(credentials=_creds)
                    if gmail_svc is None:
                        st.error(
                            "Gmail auth failed for your account — "
                            "see data/error_log.json"
                        )
                        st.stop()
                    send_result = send_email_now(
                        gmail_svc, lead.contact_email, subject, body,
                    )
                    if not send_result.get("sent"):
                        st.error(
                            "Gmail send failed — see data/error_log.json "
                            "under scope gmail.send_now"
                        )
                        st.stop()
                    st.success(
                        f"Sent to {lead.contact_email} at "
                        f"{datetime.datetime.now().strftime('%H:%M:%S')} "
                        f"from your Gmail"
                    )
                    # Sheets log — into *this user's* own sheet (created
                    # lazily on first send).
                    if _user:
                        try:
                            from google_sheets import (
                                authenticate_sheets, ensure_user_sheet,
                                log_sent_email,
                            )
                            ssvc = authenticate_sheets(credentials=_creds)
                            if ssvc:
                                sid = ensure_user_sheet(ssvc, _user)
                                if sid:
                                    log_sent_email(
                                        ssvc, sid, {
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
                                            "Hunter Status": verify_result.get("status", ""),
                                            "Hunter Score":  verify_result.get("score", ""),
                                        },
                                    )
                        except Exception:
                            pass
                    # Calendar follow-up — gate on OAuth credentials, NOT
                    # on the local credentials.json file. The previous
                    # os.path.exists check meant calendar events only fired
                    # for the developer who happened to have the file on
                    # disk; on Railway and for every other web user the
                    # guard was False and the block was silently skipped.
                    if _creds is not None:
                        try:
                            from google_calendar import (
                                authenticate_calendar, create_followup_event,
                            )
                            csvc = authenticate_calendar(credentials=_creds)
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
                        except Exception as exc:
                            # Surface to error log instead of swallowing — the
                            # broker couldn't tell why follow-ups weren't appearing.
                            try:
                                from scheduler import _log_error
                                _log_error("page_3.calendar_followup", exc)
                            except Exception:
                                pass
                            st.warning(
                                f"Email sent + logged to Sheets, but the "
                                f"Calendar follow-up couldn't be created: "
                                f"{type(exc).__name__}. Check the error log."
                            )
                    try:
                        from tone_learner import save_approved_email
                        save_approved_email(subject, body, lead.company,
                                            tone_variant=variant_choice)
                    except Exception:
                        pass

                    # Log the send to the database
                    try:
                        database.log_sent_email({
                            "prospect_id":      lead.prospect_id,
                            "company":          lead.company,
                            "contact_name":     lead.contact_name,
                            "contact_title":    lead.contact_title,
                            "contact_email":    lead.contact_email,
                            "linkedin_url":     getattr(lead, "linkedin_url", ""),
                            "email_subject":    subject,
                            "email_body":       body,
                            "linkedin_message": linkedin_msg,
                            "research_signals": [s.title for s in lead.signals],
                            "score":            lead.composite_score,
                            "tier":             lead.tier,
                            "tone_variant":     variant_choice,
                            "top_signal_used":  lead.top_hook,
                            "status":           "Sent",
                            "sent_at":          datetime.datetime.now().isoformat(),
                            "followup_date":    (datetime.date.today() +
                                                 datetime.timedelta(days=5)).isoformat(),
                        })
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
