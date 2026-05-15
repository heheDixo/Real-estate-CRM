# pages/2_prospect_found.py

import streamlit as st
import datetime
import time
import plotly.graph_objects as go
import config
from models              import EnrichmentResult
from pipeline.enrichment import EnrichmentPipeline
from pipeline.scoring    import ScoringPipeline
from mock_data           import get_mock_enrichment

# ── Guard ──────────────────────────────────────────────────────────────────────
if not st.session_state.get("current_prospect"):
    st.warning("No prospect selected. Go back to ICP Setup.")
    if st.button("← Back to ICP setup"):
        st.switch_page("pages/1_icp_setup.py")
    st.stop()

prospect = st.session_state.current_prospect
profile  = st.session_state.get("active_profile")
if not profile:
    st.error("No active ICP profile. Go back to ICP Setup.")
    st.stop()

# ── Progress bar ───────────────────────────────────────────────────────────────
st.title(f"🔍 {prospect.company_name}")
st.caption(f"Step 2 of 4 — enrichment + AI scoring")

steps     = ["⚙️ ICP setup", "🔍 Prospect", "✏️ Draft review", "📊 Audit"]
step_cols = st.columns(len(steps))
for i, (col, label) in enumerate(zip(step_cols, steps), 1):
    color  = config.AGENCY_COLOR if i == 2 else (
        "#27AE60" if i < 2 else "#BDC3C7"
    )
    weight = "bold" if i == 2 else "normal"
    col.markdown(
        f"<div style='text-align:center;color:{color};"
        f"font-weight:{weight};font-size:13px;'>"
        f"{'●' if i==2 else ('✓' if i<2 else '○')} {label}</div>",
        unsafe_allow_html=True,
    )
st.divider()

# ── Run enrichment + scoring if not already done ───────────────────────────────
if not st.session_state.get("current_enrichment"):

    timestamps = {}

    # ── Step 1: Profile card ────────────────────────────────────────────────
    st.subheader("Step 1 · Lead profile")
    col1, col2 = st.columns(2)
    with col1:
        initials = (
            f"{prospect.contact_first_name[:1]}"
            f"{prospect.contact_last_name[:1]}"
        )
        st.markdown(
            f"<div style='width:64px;height:64px;border-radius:50%;"
            f"background:{config.AGENCY_COLOR};display:flex;"
            f"align-items:center;justify-content:center;"
            f"color:white;font-size:22px;font-weight:bold;"
            f"margin-bottom:10px;'>{initials}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(f"### {prospect.contact_name}")
        st.markdown(f"*{prospect.contact_title}*")
        st.caption(f"📧 {prospect.contact_email or 'Email TBD'}")
        st.caption(f"🏢 {prospect.company_name} · {prospect.city}")

    with col2:
        st.markdown(f"**{prospect.company_name}**")
        st.caption(f"{prospect.industry} · {prospect.company_stage}")
        st.caption(f"👥 {prospect.headcount} employees")
        funding_text = ""
        if prospect.last_funding_type:
            months = prospect.funding_months_ago()
            amount = (f"${prospect.last_funding_amount:,}"
                      if prospect.last_funding_amount else "")
            funding_text = (
                f"💰 {prospect.last_funding_type}"
                f"{' · ' + amount if amount else ''}"
                f"{' · ' + str(months) + ' months ago' if months else ''}"
            )
            st.caption(funding_text)

    st.divider()

    # ── Step 2: Enrichment ──────────────────────────────────────────────────
    st.subheader("Step 2 · Enrichment — 3 data sources")

    if config.FORCE_MOCK_MODE:
        # ── MOCK MODE SHORTCUT ──────────────────────────────────────────────
        # Load pre-built enrichment directly; skip the per-source waterfall
        # so the demo isn't empty when no API keys are configured.
        enrichment = get_mock_enrichment(prospect.domain)

        now = datetime.datetime.now().isoformat()
        timestamps["ingestion_start"] = now
        timestamps["apollo_start"]    = now
        timestamps["apollo_end"]      = now
        timestamps["proxycurl_start"] = now
        timestamps["proxycurl_end"]   = now
        timestamps["newsapi_start"]   = now
        timestamps["newsapi_end"]     = now
        timestamps["ingestion_end"]   = now

        prospect.advance_status("enriched")

        st.success(
            "✅ Enrichment loaded from demo data "
            "(set FORCE_MOCK_MODE=false to use live APIs)"
        )

        col1, col2, col3 = st.columns(3)
        col1.metric("Headcount",    enrichment.headcount_current)
        col2.metric("Job postings", enrichment.total_jobs_posted)
        col3.metric("News signals", enrichment.total_news_signals)

        if enrichment.office_roles_posted > 0:
            st.success(
                f"🏢 {enrichment.office_roles_posted} office/workplace "
                f"role(s) detected — direct space signal"
            )
        if enrichment.strongest_signal_headline:
            st.info(f"📰 {enrichment.strongest_signal_headline}")

        st.divider()

    else:
        # ── LIVE API WATERFALL ──────────────────────────────────────────────
        enricher   = EnrichmentPipeline()
        timestamps["ingestion_start"] = datetime.datetime.now().isoformat()

        # Source 1: Apollo
        with st.expander("📊 Source 1 — Apollo (firmographics)", expanded=True):
            with st.spinner("Calling Apollo org enrichment..."):
                timestamps["apollo_start"] = datetime.datetime.now().isoformat()
                time.sleep(0.5)   # simulate latency for demo
                enrichment = enricher._run_apollo(
                    EnrichmentResult(
                        prospect_id       = prospect.domain,
                        enriched_at       = datetime.datetime.now().isoformat(),
                        headcount_current = prospect.headcount,
                    ),
                    prospect,
                )
                timestamps["apollo_end"] = datetime.datetime.now().isoformat()

            col1, col2, col3 = st.columns(3)
            col1.metric("Current headcount", enrichment.headcount_current or prospect.headcount)
            col2.metric("Founded", enrichment.founded_year or "N/A")
            col3.metric("Est. ARR", f"${enrichment.annual_revenue:,}" if enrichment.annual_revenue else "N/A")

            if enrichment.technologies:
                st.caption(f"Tech stack: {', '.join(enrichment.technologies[:6])}")
            if enrichment.description:
                st.caption(enrichment.description[:200] + "...")

        # Source 2: Proxycurl
        with st.expander("💼 Source 2 — LinkedIn via Proxycurl (hiring signals)", expanded=True):
            with st.spinner("Fetching LinkedIn job postings..."):
                timestamps["proxycurl_start"] = datetime.datetime.now().isoformat()
                time.sleep(0.5)
                enrichment = enricher._run_proxycurl(enrichment, prospect, profile)
                timestamps["proxycurl_end"] = datetime.datetime.now().isoformat()

            col1, col2, col3 = st.columns(3)
            col1.metric("Total job postings",    enrichment.total_jobs_posted)
            col2.metric("Jobs in target geo",    enrichment.jobs_in_target_geo)
            col3.metric("Office/workplace roles",enrichment.office_roles_posted)

            if enrichment.office_roles_posted > 0:
                st.success(
                    f"🏢 {enrichment.office_roles_posted} office/workplace "
                    f"role(s) detected — direct space signal"
                )

            if enrichment.top_job_titles:
                st.caption(
                    f"Top titles: {', '.join(enrichment.top_job_titles)}"
                )

        # Source 3: NewsAPI
        with st.expander("📰 Source 3 — News signals via NewsAPI", expanded=True):
            with st.spinner("Searching for company news signals..."):
                timestamps["newsapi_start"] = datetime.datetime.now().isoformat()
                time.sleep(0.5)
                enrichment = enricher._run_newsapi(enrichment, prospect)
                timestamps["newsapi_end"] = datetime.datetime.now().isoformat()

            if enrichment.total_news_signals > 0:
                col1, col2 = st.columns(2)
                col1.metric("News signals found",  enrichment.total_news_signals)
                col2.metric("Strongest signal",    enrichment.strongest_signal_type or "N/A")

                if enrichment.strongest_signal_headline:
                    signal_color = {
                        "expansion":  "#27AE60",
                        "funding":    "#2980B9",
                        "office":     "#8E44AD",
                        "relocation": "#E67E22",
                        "hiring":     "#16A085",
                    }.get(enrichment.strongest_signal_type, config.AGENCY_COLOR)

                    st.markdown(
                        f"<div style='background:#EBF5FB;"
                        f"border-left:4px solid {signal_color};"
                        f"padding:10px 14px;border-radius:4px;margin-top:8px;'>"
                        f"<div style='font-size:11px;color:#666;"
                        f"text-transform:uppercase;'>"
                        f"{enrichment.strongest_signal_type} signal · "
                        f"{enrichment.strongest_signal_date}</div>"
                        f"<div style='font-size:13px;font-weight:bold;"
                        f"color:{signal_color};margin-top:4px;'>"
                        f"{enrichment.strongest_signal_headline}</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No significant news signals detected in the last 6 months.")

        # ── Compute derived fields ──────────────────────────────────────────
        enrichment.compute_headcount_growth()
        enrichment.compute_hiring_velocity()
        months = prospect.funding_months_ago()
        enrichment.months_since_funding    = months
        enrichment.is_in_deployment_window = (
            months is not None and
            config.DEPLOYMENT_WINDOW_MIN <= months <= config.DEPLOYMENT_WINDOW_MAX
        )
        enrichment.check_triggers(profile.trigger_signals, months)
        enrichment.build_hf_description(prospect)
        prospect.advance_status("enriched")
        timestamps["ingestion_end"] = datetime.datetime.now().isoformat()

        st.divider()

    # ── Step 3: AI Scoring ──────────────────────────────────────────────────
    st.subheader("Step 3 · AI scoring — facebook/bart-large-mnli")

    with st.spinner(
        "Running zero-shot classification... "
        "(real HuggingFace API call)"
    ):
        timestamps["scoring_start"] = datetime.datetime.now().isoformat()
        scorer = ScoringPipeline()
        score  = scorer.score(prospect, enrichment, profile)
        timestamps["scoring_end"] = datetime.datetime.now().isoformat()

    # save to session state
    st.session_state.current_enrichment  = enrichment
    st.session_state.current_score       = score
    st.session_state.current_timestamps  = timestamps

else:
    # already scored — read from session state
    enrichment = st.session_state.current_enrichment
    score      = st.session_state.current_score

# ── Score display ──────────────────────────────────────────────────────────────
tier       = score.tier
composite  = score.composite
tier_cfg   = config.TIER_CONFIG.get(tier, {})
tier_color = tier_cfg.get("color", "#95A5A6")
tier_bg    = tier_cfg.get("background", "#F8F9FA")
tier_emoji = tier_cfg.get("emoji", "◯")

# composite score hero
st.markdown(
    f"<div style='background:{tier_bg};border:2px solid {tier_color};"
    f"border-radius:12px;padding:20px;text-align:center;margin:16px 0;'>"
    f"<div style='font-size:52px;font-weight:bold;"
    f"color:{tier_color};'>{composite:.0f}</div>"
    f"<div style='font-size:18px;color:{tier_color};margin-top:4px;'>"
    f"/ 100 — {tier_emoji} {tier}</div>"
    f"<div style='font-size:13px;color:#666;margin-top:6px;'>"
    f"{tier_cfg.get('action','')}</div>"
    f"</div>",
    unsafe_allow_html=True,
)

# dimension scores
dim_scores = score.dimension_scores()
d_cols = st.columns(len(dim_scores))
for col, (dim, val) in zip(d_cols, dim_scores.items()):
    bar_color = (
        "#2ECC71" if val >= config.SIGNAL_STRONG else
        "#F39C12" if val >= config.TIER_WARM else
        "#E74C3C"
    )
    with col:
        st.metric(dim, f"{val:.0f}/100")
        st.markdown(
            f"<div style='background:#ECF0F1;border-radius:3px;height:6px;'>"
            f"<div style='background:{bar_color};width:{val}%;"
            f"height:6px;border-radius:3px;'></div></div>",
            unsafe_allow_html=True,
        )

st.markdown("")

# signal bullets
sig_col1, sig_col2 = st.columns(2)
with sig_col1:
    st.markdown("**✅ Positive signals**")
    if score.positive_signals:
        for sig in score.positive_signals:
            st.markdown(
                f"<div style='color:#27AE60;font-size:13px;"
                f"margin-bottom:4px;'>🟢 {sig}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("No strong positive signals above threshold.")

with sig_col2:
    st.markdown("**⚠️ Risk signals**")
    if score.risk_signals:
        for sig in score.risk_signals:
            st.markdown(
                f"<div style='color:#E74C3C;font-size:13px;"
                f"margin-bottom:4px;'>🔴 {sig}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            "<div style='color:#27AE60;font-size:13px;'>"
            "🟢 No significant risk signals</div>",
            unsafe_allow_html=True,
        )

# raw confidence chart
if score.raw_label_confidences:
    with st.expander("📊 Model reasoning — raw classification confidence"):
        raw    = score.raw_label_confidences
        labels = list(raw.keys())
        vals   = [round(v * 100, 1) for v in raw.values()]
        colors = [
            "#2ECC71" if v >= config.SIGNAL_STRONG else
            "#F39C12" if v >= 40 else
            "#E74C3C"
            for v in vals
        ]
        fig = go.Figure(go.Bar(
            x            = vals,
            y            = labels,
            orientation  = "h",
            marker_color = colors,
            text         = [f"{v}%" for v in vals],
            textposition = "outside",
        ))
        fig.update_layout(
            height       = max(300, len(labels) * 28),
            xaxis        = dict(range=[0, 110], title="Confidence %"),
            margin       = dict(l=10, r=50, t=10, b=10),
            plot_bgcolor = "rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("🔍 Exact text sent to bart-large-mnli"):
        st.text(score.description_sent)

if score.used_fallback_scoring:
    st.info(
        f"ℹ️ Rule-based fallback scoring used: {score.fallback_reason}. "
        f"Connect a HuggingFace token for model-based scoring."
    )

st.divider()

col1, col2 = st.columns(2)
with col1:
    if st.button("← Back to ICP setup", use_container_width=True):
        st.switch_page("pages/1_icp_setup.py")
with col2:
    if st.button(
        "Next → Generate drafts ✏️",
        type             = "primary",
        use_container_width = True,
    ):
        st.switch_page("pages/3_draft_review.py")