# pages/1_icp_setup.py

import streamlit as st
import datetime
import config
from models.icp_profile import ICPProfile, SECTOR_WEIGHT_PRESETS
from mock_data import get_all_mock_prospects, get_all_mock_profiles
from pipeline.ingestion import IngestionPipeline

st.title("⚙️ ICP setup & prospect selection")
st.caption(
    "Step 1 of 4 — define your target profile and select a prospect to run."
)

# ── Progress bar ───────────────────────────────────────────────────────────────
steps     = ["⚙️ ICP setup", "🔍 Prospect", "✏️ Draft review", "📊 Audit"]
step_cols = st.columns(len(steps))
for i, (col, label) in enumerate(zip(step_cols, steps), 1):
    color = config.AGENCY_COLOR if i == 1 else "#BDC3C7"
    col.markdown(
        f"<div style='text-align:center;color:{color};"
        f"font-weight:{'bold' if i==1 else 'normal'};font-size:13px;'>"
        f"{'●' if i==1 else '○'} {label}</div>",
        unsafe_allow_html=True,
    )
st.divider()

left, right = st.columns([1, 1.6])

# ── LEFT: Profile switcher ─────────────────────────────────────────────────────
with left:
    st.subheader("ICP profiles")
    st.caption("Click a profile to make it active.")

    profiles = st.session_state.get("all_profiles", get_all_mock_profiles())
    active   = st.session_state.get("active_profile", profiles[0])

    for profile in profiles:
        is_active = active and active.name == profile.name
        bg        = config.AGENCY_COLOR if is_active else "#F8F9FA"
        text_col  = "white" if is_active else "#2C3E50"
        border    = f"2px solid {config.AGENCY_COLOR}"

        st.markdown(
            f"<div style='background:{bg};color:{text_col};"
            f"border:{border};border-radius:8px;padding:12px;"
            f"margin-bottom:8px;cursor:pointer;'>"
            f"<div style='font-weight:bold;font-size:13px;'>"
            f"{profile.name}"
            f"{'  ✓' if is_active else ''}</div>"
            f"<div style='font-size:11px;opacity:0.85;margin-top:3px;'>"
            f"{', '.join(profile.sectors[:2])} · "
            f"{profile.headcount_min}–{profile.headcount_max} emp · "
            f"{profile.geographies[0]}</div>"
            f"<div style='font-size:11px;opacity:0.7;margin-top:2px;'>"
            f"Decisions: {profile.total_decisions} · "
            f"Approval rate: {profile.approval_rate}%</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if not is_active:
            if st.button(
                f"Switch",
                key              = f"sw_{profile.name}",
                use_container_width = True,
            ):
                st.session_state.active_profile  = profile
                st.session_state.current_prospect = None
                st.session_state.pipeline_step    = 1
                st.rerun()

    st.markdown("")
    if st.button("➕ Create new profile", use_container_width=True):
        st.session_state["creating_new_profile"] = True

# ── RIGHT: Profile form ────────────────────────────────────────────────────────
with right:
    creating = st.session_state.get("creating_new_profile", False)

    if creating:
        st.subheader("Create new profile")
        profile_name  = st.text_input("Profile name",
                                       placeholder="e.g. Law Firms — NYC")
        sector_key    = st.selectbox(
            "Sector preset (sets default signal weights)",
            ["healthcare", "tech", "financial_services", "default"],
        )
        col1, col2 = st.columns(2)
        with col1:
            new_sectors = st.multiselect(
                "Target sectors", config.SECTOR_OPTIONS,
                default=["Technology"],
            )
            new_geos = st.multiselect(
                "Geographies", config.GEOGRAPHY_OPTIONS,
                default=["New York"],
            )
            new_stages = st.multiselect(
                "Company stages", config.COMPANY_STAGE_OPTIONS,
                default=["Series B", "Series C"],
            )
        with col2:
            new_hc_min = st.number_input("Min employees", 10, 5000, 50)
            new_hc_max = st.number_input("Max employees", 10, 5000, 500)
            new_triggers = st.multiselect(
                "Trigger signals",
                config.ALL_TRIGGER_SIGNALS,
                default=config.ALL_TRIGGER_SIGNALS[:4],
                format_func=lambda x: config.TRIGGER_SIGNAL_DEFINITIONS[x]["label"],
            )

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("💾 Save profile", type="primary",
                          use_container_width=True):
                if profile_name:
                    new_profile = ICPProfile(
                        name         = profile_name,
                        sector_key   = sector_key,
                        sectors      = new_sectors,
                        geographies  = new_geos,
                        company_stages = new_stages,
                        headcount_min = new_hc_min,
                        headcount_max = new_hc_max,
                        trigger_signals = new_triggers,
                        created_at   = datetime.datetime.now().isoformat(),
                    )
                    new_profile.apply_sector_preset(sector_key)
                    st.session_state.all_profiles.append(new_profile)
                    st.session_state.active_profile = new_profile
                    st.session_state["creating_new_profile"] = False
                    st.success(f"Profile '{profile_name}' created.")
                    st.rerun()
                else:
                    st.error("Please enter a profile name.")
        with col_b:
            if st.button("Cancel", use_container_width=True):
                st.session_state["creating_new_profile"] = False
                st.rerun()

    else:
        # show active profile details
        profile = st.session_state.get("active_profile")
        if profile:
            st.subheader(f"Profile: {profile.name}")

            tab_overview, tab_weights, tab_history = st.tabs([
                "Overview", "Signal weights", "Decision history"
            ])

            with tab_overview:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**Targeting**")
                    st.caption(f"Sectors: {', '.join(profile.sectors)}")
                    st.caption(f"Geography: {', '.join(profile.geographies)}")
                    st.caption(
                        f"Headcount: "
                        f"{profile.headcount_min}–{profile.headcount_max}"
                    )
                    st.caption(f"Stages: {', '.join(profile.company_stages)}")
                with col2:
                    st.markdown("**Trigger signals**")
                    for signal in profile.trigger_signals:
                        defn = config.TRIGGER_SIGNAL_DEFINITIONS.get(signal, {})
                        icon  = defn.get("icon", "•")
                        label = defn.get("label", signal)
                        st.caption(f"{icon} {label}")
                    st.caption(
                        f"Min triggers required: "
                        f"{profile.min_triggers_required}"
                    )

                st.markdown("**Exclusions**")
                for k, v in profile.exclusions.items():
                    st.caption(f"• {k}: {v}")

            with tab_weights:
                import plotly.graph_objects as go
                weights = profile.signal_weights
                dims    = list(weights.keys())
                vals    = [round(v * 100) for v in weights.values()]
                fig = go.Figure(go.Bar(
                    x           = vals,
                    y           = [d.replace("_", " ").title() for d in dims],
                    orientation = "h",
                    marker_color = config.AGENCY_COLOR,
                    text        = [f"{v}%" for v in vals],
                    textposition = "outside",
                ))
                fig.update_layout(
                    height           = 240,
                    margin           = dict(l=0, r=40, t=10, b=10),
                    xaxis_title      = "Weight (%)",
                    plot_bgcolor     = "rgba(0,0,0,0)",
                    xaxis            = dict(range=[0, 55]),
                )
                st.plotly_chart(fig, use_container_width=True)
                st.caption(
                    f"Sector preset: {profile.sector_key}. "
                    f"Weights update automatically as you approve/reject."
                )

            with tab_history:
                col1, col2 = st.columns(2)
                col1.metric("Total decisions",  profile.total_decisions)
                col2.metric("Approval rate",    f"{profile.approval_rate}%")

                if profile.learned_rules:
                    st.markdown("**Learned rules (injected into AI prompts)**")
                    for rule in profile.learned_rules:
                        st.markdown(f"• {rule}")
                else:
                    st.info(
                        "No learned rules yet. "
                        "Rules emerge after 20+ approve/reject decisions."
                    )

st.divider()

# ── Prospect selector ──────────────────────────────────────────────────────────
st.subheader("Select a prospect to run")

# combine pre-built mock prospects with any prospects parsed from an uploaded CSV
uploaded_prospects = st.session_state.get("uploaded_prospects", [])
all_prospects = list(uploaded_prospects) + get_all_mock_prospects()
prospect_names = [
    f"{'📄 ' if p.source == 'csv' else ''}"
    f"{p.company_name} — {p.contact_name}, {p.contact_title}"
    for p in all_prospects
]

col_sel, col_info = st.columns([1, 1.5])

with col_sel:
    selected_idx = st.selectbox(
        "Choose a prospect",
        range(len(prospect_names)),
        format_func = lambda i: prospect_names[i],
        index       = 0,
    )
    selected_prospect = all_prospects[selected_idx]

    st.markdown("")
    if st.button(
        "▶ Run this prospect through the pipeline",
        type             = "primary",
        use_container_width = True,
    ):
        # reset pipeline state
        st.session_state.current_prospect   = selected_prospect
        st.session_state.current_enrichment = None
        st.session_state.current_score      = None
        st.session_state.current_draft      = None
        st.session_state.current_audit_log  = []
        st.session_state.current_timestamps = {}
        st.session_state.pipeline_step      = 2
        st.switch_page("pages/2_prospect_found.py")

with col_info:
    p = selected_prospect
    equity = p.last_funding_amount
    months = p.funding_months_ago()

    st.markdown(
        f"<div style='background:#F8F9FA;border:1px solid #E8E8E8;"
        f"border-radius:8px;padding:14px;'>"
        f"<div style='font-weight:bold;font-size:14px;"
        f"color:{config.AGENCY_COLOR};'>{p.company_name}</div>"
        f"<div style='font-size:12px;color:#666;margin-top:2px;'>"
        f"{p.industry} · {p.city}, {p.state}</div>"
        f"<div style='margin-top:10px;font-size:12px;'>"
        f"👤 {p.contact_name} — {p.contact_title}<br>"
        f"👥 {p.headcount} employees ({p.company_stage})<br>"
        f"💰 {p.last_funding_type}"
        f"{f' · ${equity:,}' if equity else ''}"
        f"{f' · {months} months ago' if months else ''}<br>"
        f"📧 {p.contact_email or 'Email TBD'}"
        f"</div></div>",
        unsafe_allow_html=True,
    )

    with st.expander("Or upload your own CSV"):
        st.caption(
            "CSV columns: company, domain, first_name, last_name, "
            "title, email, city, state, headcount, stage, industry"
        )
        uploaded = st.file_uploader("Upload CSV", type=["csv"])
        if uploaded is not None:
            # only parse once per uploaded file — keyed by name+size so the
            # same file doesn't re-parse on every rerun
            file_key = f"{uploaded.name}:{uploaded.size}"
            if st.session_state.get("csv_file_key") != file_key:
                content = uploaded.read().decode("utf-8")
                st.session_state["csv_content"] = content
                st.session_state["csv_file_key"] = file_key

                # parse CSV into Prospect objects using IngestionPipeline
                active = st.session_state.get(
                    "active_profile", get_all_mock_profiles()[0]
                )
                parsed = IngestionPipeline()._from_csv(content, active)

                if parsed:
                    st.session_state["uploaded_prospects"] = parsed
                    st.success(
                        f"✅ Parsed {len(parsed)} prospect(s) from "
                        f"{uploaded.name}. They now appear in the selector "
                        f"above with a 📄 icon."
                    )
                    st.rerun()
                else:
                    st.error(
                        f"Could not parse any prospects from {uploaded.name}. "
                        f"Make sure the file has a `domain` column."
                    )

        if st.session_state.get("uploaded_prospects"):
            count = len(st.session_state["uploaded_prospects"])
            st.caption(f"📄 {count} uploaded prospect(s) available.")
            if st.button("Clear uploaded prospects", use_container_width=True):
                st.session_state.pop("uploaded_prospects", None)
                st.session_state.pop("csv_content",       None)
                st.session_state.pop("csv_file_key",      None)
                st.rerun()