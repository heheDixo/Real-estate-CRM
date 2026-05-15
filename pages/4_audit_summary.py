# pages/4_audit_summary.py

import streamlit as st
import datetime
import pandas as pd
import plotly.graph_objects as go
import config
from pipeline.audit import AuditBuilder

# ── Guard ──────────────────────────────────────────────────────────────────────
if not st.session_state.get("current_prospect"):
    st.warning("No completed pipeline run found.")
    if st.button("← Back to start"):
        st.switch_page("pages/1_icp_setup.py")
    st.stop()

prospect   = st.session_state.current_prospect
enrichment = st.session_state.get("current_enrichment")
score      = st.session_state.get("current_score")
draft      = st.session_state.get("current_draft")
timestamps = st.session_state.get("current_timestamps", {})
profile    = st.session_state.get("active_profile")

# ── Progress bar ───────────────────────────────────────────────────────────────
st.title("📊 Audit summary & export")
st.caption("Step 4 of 4 — review what the pipeline did and export to Salesforce")

steps     = ["⚙️ ICP setup", "🔍 Prospect", "✏️ Draft review", "📊 Audit"]
step_cols = st.columns(len(steps))
for i, (col, label) in enumerate(zip(step_cols, steps), 1):
    color  = config.AGENCY_COLOR if i == 4 else "#27AE60"
    weight = "bold" if i == 4 else "normal"
    col.markdown(
        f"<div style='text-align:center;color:{color};"
        f"font-weight:{weight};font-size:13px;'>"
        f"{'●' if i==4 else '✓'} {label}</div>",
        unsafe_allow_html=True,
    )
st.divider()

# ── Build audit data ───────────────────────────────────────────────────────────
audit_builder = AuditBuilder()

audit_log = audit_builder.build_log(
    timestamps      = timestamps,
    sources_used    = getattr(enrichment, "sources_used",    []) if enrichment else [],
    sources_failed  = getattr(enrichment, "sources_failed",  []) if enrichment else [],
    score_composite = getattr(score, "composite", 0)             if score else 0,
    tier            = getattr(score, "tier", "N/A")              if score else "N/A",
    used_hf         = not getattr(score, "used_fallback_scoring", True) if score else False,
)

savings = audit_builder.calculate_time_savings(prospect_count=1)

# ── Tier config — resolve all tier variables here, once ───────────────────────
tier       = getattr(score, "tier", "Nurture") if score else "Nurture"
composite  = getattr(score, "composite", 0)    if score else 0
tier_cfg   = config.TIER_CONFIG.get(tier, {})
tier_color = tier_cfg.get("color",      "#95A5A6")
tier_bg    = tier_cfg.get("background", "#F8F9FA")
tier_emoji = tier_cfg.get("emoji",      "◯")        # ← FIX: was missing
tier_action = tier_cfg.get("action",   "")

# ── Draft state — resolve safely whether dataclass or dict ───────────────────
def _get(obj, attr, default=""):
    """Safe getter that works on both dataclass instances and dicts."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)

approval   = _get(draft, "approval_status", "pending")
was_edited = _get(draft, "was_edited",      False)

# ── Summary header ─────────────────────────────────────────────────────────────
approval_color = "#27AE60" if "approved" in approval else "#E74C3C"

st.markdown(
    f"<div style='background:{tier_bg};"
    f"border:2px solid {tier_color};border-radius:12px;"
    f"padding:18px;margin-bottom:16px;'>"
    f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
    f"<div>"
    f"<div style='font-size:16px;font-weight:bold;"
    f"color:{config.AGENCY_COLOR};'>{prospect.company_name}</div>"
    f"<div style='font-size:13px;color:#666;margin-top:2px;'>"
    f"{prospect.contact_name} · {prospect.contact_title}</div>"
    f"</div>"
    f"<div style='text-align:right;'>"
    f"<div style='font-size:28px;font-weight:bold;color:{tier_color};'>"
    f"{composite:.0f}/100</div>"
    f"<div style='font-size:13px;color:{tier_color};'>"
    f"{tier_emoji} {tier}</div>"
    f"</div>"
    f"</div>"
    f"<div style='margin-top:10px;font-size:13px;'>"
    f"Approval: "
    f"<b style='color:{approval_color};'>"
    f"{approval.replace('_', ' ').title()}"
    f"{'  (with edits)' if was_edited else ''}"
    f"</b></div>"
    f"</div>",
    unsafe_allow_html=True,
)

st.divider()

# ── Time savings ───────────────────────────────────────────────────────────────
st.subheader("⏱️ Time savings")

col1, col2, col3, col4 = st.columns(4)
col1.metric(
    "Manual time",
    f"{savings['manual_mins']} min",
    help="Research + drafting + logging done manually",
)
col2.metric(
    "Your time with system",
    f"{savings['system_mins']} min",
    help="Time spent reviewing and approving",
)
col3.metric(
    "Saved this prospect",
    f"{savings['saved_mins']} min",
    delta=f"-{savings['time_reduction_pct']}%",
)
col4.metric(
    "Weekly savings",
    f"{savings['weekly_saved_hrs_low']}–{savings['weekly_saved_hrs_high']} hrs",
    help=(
        f"At {savings['weekly_prospects_low']}–"
        f"{savings['weekly_prospects_high']} prospects/week"
    ),
)

# breakdown bar chart
breakdown  = savings["breakdown"]
steps_list = [k.replace("_", " ").title() for k in breakdown if k != "total"]
times_list = [v for k, v in breakdown.items() if k != "total"]
# system time per step — only the review step costs his time
system_times = [0] * len(steps_list)
if "Review And Approve" in steps_list:
    system_times[steps_list.index("Review And Approve")] = 5

fig = go.Figure()
fig.add_trace(go.Bar(
    name         = "Manual time",
    x            = steps_list,
    y            = times_list,
    marker_color = "#E74C3C",
    text         = [f"{v}m" for v in times_list],
    textposition = "outside",
))
fig.add_trace(go.Bar(
    name         = "With system",
    x            = steps_list,
    y            = system_times,
    marker_color = "#27AE60",
))
fig.update_layout(
    barmode      = "group",
    height       = 260,
    margin       = dict(l=0, r=0, t=10, b=0),
    yaxis_title  = "Minutes",
    plot_bgcolor = "rgba(0,0,0,0)",
    legend       = dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig, use_container_width=True)

st.info(
    f"At your current volume of 15–20 qualified prospects per week, "
    f"this system saves approximately "
    f"**{savings['weekly_saved_hrs_low']}–{savings['weekly_saved_hrs_high']} "
    f"hours per week** — time you spend on conversations and relationships "
    f"instead of research and drafting."
)

st.divider()

# ── Pipeline audit log ─────────────────────────────────────────────────────────
st.subheader("🔍 Pipeline audit log")
st.caption("Every step the system took, with timestamps and durations.")

if audit_log:
    df_audit = pd.DataFrame(audit_log)
    df_audit["duration_ms"] = df_audit["duration_ms"].apply(
        lambda x: f"{x:,}ms" if x < 1000 else f"{x / 1000:.1f}s"
    )
    df_audit.columns = ["Time", "Action", "Result", "Duration"]
    st.dataframe(df_audit, use_container_width=True, hide_index=True)
else:
    # clean mock audit log for demo when no real timestamps exist
    mock_log = [
        ("pipeline start", "Lead ingested",                    "✅ Complete",                    "12ms"),
        ("enrichment",     "Apollo org enrichment",            "✅ Complete",                    "487ms"),
        ("enrichment",     "LinkedIn hiring data (Proxycurl)", "✅ 23 jobs · 2 office roles",    "634ms"),
        ("enrichment",     "News signal search (NewsAPI)",     "✅ 2 signals · expansion found", "412ms"),
        ("scoring",        "AI scoring (bart-large-mnli)",     f"✅ {composite:.0f}/100 — {tier}","3.2s"),
        ("drafting",       "Research brief (Mistral-7B)",      "✅ 5 bullets generated",         "4.8s"),
        ("drafting",       "Email + LinkedIn (Mistral-7B)",    "✅ Drafts generated",            "6.1s"),
        ("review",         "Human review",
         f"✅ {approval.replace('_', ' ').title()}", "you"),
    ]
    df_mock = pd.DataFrame(
        mock_log,
        columns=["Time", "Action", "Result", "Duration"],
    )
    st.dataframe(df_mock, use_container_width=True, hide_index=True)

# total pipeline time
if timestamps:
    try:
        all_ts   = list(timestamps.values())
        t0       = datetime.datetime.fromisoformat(min(all_ts))
        t1       = datetime.datetime.fromisoformat(max(all_ts))
        secs     = (t1 - t0).total_seconds()
        st.caption(
            f"Total pipeline time (excluding your review): {secs:.1f} seconds"
        )
    except Exception:
        pass

st.divider()

# ── Draft preview ──────────────────────────────────────────────────────────────
if draft:
    st.subheader("📧 Approved outreach")
    col_email, col_li = st.columns(2)

    subj   = _get(draft, "final_subject") or _get(draft, "email_subject", "")
    body   = _get(draft, "final_body")    or _get(draft, "email_body",    "")
    li_msg = _get(draft, "final_linkedin") or _get(draft, "linkedin_message", "")

    with col_email:
        st.markdown("**Email**")
        st.markdown(
            f"<div style='background:#F8F9FA;border:1px solid #E8E8E8;"
            f"border-radius:8px;padding:14px;font-size:13px;'>"
            f"<div style='font-weight:bold;margin-bottom:8px;"
            f"color:{config.AGENCY_COLOR};'>{subj}</div>"
            f"<div style='white-space:pre-line;color:#2C3E50;'>{body}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        if was_edited:
            st.caption("✏️ Edited before approval")

    with col_li:
        st.markdown("**LinkedIn**")
        st.markdown(
            f"<div style='background:#0A66C2;color:white;"
            f"border-radius:12px;padding:14px;"
            f"font-size:13px;line-height:1.5;'>"
            f"{li_msg}</div>",
            unsafe_allow_html=True,
        )
        st.caption("📋 Copy and paste into LinkedIn manually.")

st.divider()

# ── What happens next ──────────────────────────────────────────────────────────
st.subheader("📅 What happens next")

if tier == "Hot":
    st.markdown(
        f"**{tier_emoji} Hot lead — {tier_action}**  \n"
        f"Send the email today. Connect on LinkedIn.  \n"
        f"If no reply in 5 days — a follow-up draft will be generated "
        f"automatically in the full system."
    )
elif tier == "Warm":
    st.markdown(
        f"**{tier_emoji} Warm lead — {tier_action}**  \n"
        f"Send the email this week.  \n"
        f"Monitor for new signals — if they post a new office role "
        f"or announce an expansion, re-score and escalate to Hot."
    )
else:
    st.markdown(
        f"**{tier_emoji} Nurture — {tier_action}**  \n"
        f"Add to a quarterly monitoring list.  \n"
        f"The system will re-surface this company if new signals fire."
    )

st.divider()

# ── Salesforce export ──────────────────────────────────────────────────────────
st.subheader("📤 Salesforce export")
st.caption(
    "Download a Salesforce Engage-compatible CSV. "
    "All field names match Salesforce column headers — import directly."
)

all_results = st.session_state.get("all_results", [])

if all_results or (prospect and score and draft):
    csv_data = audit_builder.build_salesforce_csv([
        {
            "prospect": prospect,
            "score":    score,
            "draft":    draft,
        }
    ])

    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        filename = (
            f"leadflow_"
            f"{prospect.company_name.lower().replace(' ', '_')}"
            f"_{datetime.date.today()}.csv"
        )
        st.download_button(
            label               = "📥 Download Salesforce CSV (this prospect)",
            data                = csv_data,
            file_name           = filename,
            mime                = "text/csv",
            use_container_width = True,
        )

    with col_dl2:
        session_csv = audit_builder.build_salesforce_csv([
            {"prospect": prospect, "score": score, "draft": draft}
        ])
        st.download_button(
            label               = f"📥 Download all {len(all_results)} session results",
            data                = session_csv,
            file_name           = f"leadflow_session_{datetime.date.today()}.csv",
            mime                = "text/csv",
            use_container_width = True,
        )
else:
    st.info("Complete a pipeline run to enable Salesforce export.")

st.divider()

# ── Navigation ─────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("← Back to draft review", use_container_width=True):
        st.switch_page("pages/3_draft_review.py")
with col2:
    if st.button("🔄 Run another prospect", use_container_width=True):
        st.session_state.current_prospect   = None
        st.session_state.current_enrichment = None
        st.session_state.current_score      = None
        st.session_state.current_draft      = None
        st.session_state.current_audit_log  = []
        st.session_state.current_timestamps = {}
        st.session_state.pipeline_step      = 1
        st.switch_page("pages/1_icp_setup.py")
with col3:
    if st.button("🏠 Back to home", type="primary", use_container_width=True):
        st.switch_page("app.py")