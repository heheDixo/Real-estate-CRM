import streamlit as st
import datetime
import config
from mock_data import get_all_mock_profiles, get_all_mock_prospects

#  Page config 
st.set_page_config(
    page_title           = config.APP_TITLE,
    page_icon            = config.APP_ICON,
    layout               = "wide",
    initial_sidebar_state = "expanded",
)

#  Session state defaults
# Every key any page reads must be initialised here.
DEFAULTS = {
    # ICP
    "active_profile":      None,        # ICPProfile instance
    "all_profiles":        [],           # list of ICPProfile instances

    # Current pipeline run
    "current_prospect":    None,         # Prospect instance
    "current_enrichment":  None,         # EnrichmentResult instance
    "current_score":       None,         # ScoreResult instance
    "current_draft":       None,         # DraftResult instance
    "current_audit_log":   [],           # list of audit entry dicts
    "current_timestamps":  {},           # dict of step → ISO timestamp

    # All completed runs this session
    "all_results":         [],           # list of result dicts

    # UI state
    "pipeline_step":       1,            # current wizard step (1–4)
    "pipeline_type":       "buyer",      # not used in CRE — kept for compatibility
    "demo_mode":           config.FORCE_MOCK_MODE,
    "last_updated":        datetime.datetime.now().isoformat(),
}

for key, default in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

# Load mock profiles on first run 
if not st.session_state.all_profiles:
    st.session_state.all_profiles  = get_all_mock_profiles()
    st.session_state.active_profile = st.session_state.all_profiles[0]

#Sidebar 
with st.sidebar:
    st.markdown(
        f"<div style='text-align:center;padding:8px 0;'>"
        f"<div style='font-size:32px;'>🏢</div>"
        f"<div style='font-weight:bold;font-size:15px;"
        f"color:{config.AGENCY_COLOR};'>{config.APP_TITLE}</div>"
        f"<div style='font-size:11px;color:#95A5A6;margin-top:2px;'>"
        f"{config.APP_TAGLINE}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    st.divider()

    #  Active profile indicator 
    active = st.session_state.active_profile
    if active:
        tier_icon = "🟢"
        st.markdown(
            f"{tier_icon} **Active profile**  \n"
            f"`{active.name}`  \n"
            f"*{', '.join(active.sectors[:2])} · {active.geographies[0]}*",
        )

    st.divider()

    #  Navigation 
    st.markdown("**Navigation**")
    st.page_link("app.py",                   label="🏠  Home")
    st.page_link("pages/1_icp_setup.py",     label="⚙️   ICP Setup")
    st.page_link("pages/2_prospect_found.py",label="🔍  Prospect")
    st.page_link("pages/3_draft_review.py",  label="✏️   Draft review")
    st.page_link("pages/4_audit_summary.py", label="📊  Audit & export")

    st.divider()

    #  API status 
    st.markdown("**API status**")
    apis = {
        "HuggingFace": config.HF_AVAILABLE,
        "Apollo":      config.APOLLO_AVAILABLE,
        "Proxycurl":   config.PROXYCURL_AVAILABLE,
        "NewsAPI":     config.NEWSAPI_AVAILABLE,
    }
    for name, available in apis.items():
        icon  = "🟢" if available else "🟡"
        label = "live"  if available else "mock"
        st.caption(f"{icon} {name} — {label}")

    if config.FORCE_MOCK_MODE:
        st.warning("FORCE_MOCK_MODE=true — using mock data for all sources.")

    st.divider()
    st.caption(
        f"Session: {len(st.session_state.all_results)} prospects processed"
    )

#  Home page
st.title(f" {config.APP_TITLE}")
st.markdown(
    f"**{config.APP_TAGLINE}**  \n"
    f"AI-powered tenant rep prospecting — from signal to reviewed draft "
    f"in under 3 minutes. Real HuggingFace scoring. Real Mistral drafts. "
    f"Three data sources. Human approval before anything goes out."
)

st.divider()

#  ICP profile cards 
st.subheader("Active ICP profiles")
st.caption(
    "Each profile has its own targeting filters, signal weights, "
    "tone model, and decision history. Switch between them with one click."
)

profiles = st.session_state.all_profiles
cols     = st.columns(len(profiles))

for col, profile in zip(cols, profiles):
    is_active = (
        st.session_state.active_profile and
        st.session_state.active_profile.name == profile.name
    )
    border    = f"2px solid {config.AGENCY_COLOR}" if is_active else "1px solid #E8E8E8"
    bg        = "#EBF5FB" if is_active else "white"

    active_badge = (
        "<div style='margin-top:8px;font-size:11px;"
        "color:#27AE60;font-weight:bold;'>✓ ACTIVE</div>"
        if is_active else ""
    )

    with col:
        st.markdown(
            f"<div style='border:{border};background:{bg};"
            f"border-radius:10px;padding:14px;'>"
            f"<div style='font-weight:bold;font-size:14px;"
            f"color:{config.AGENCY_COLOR};'>{profile.name}</div>"
            f"<div style='font-size:12px;color:#666;margin-top:4px;'>"
            f"{profile.description[:80]}...</div>"
            f"<div style='margin-top:8px;font-size:12px;'>"
            f"📍 {', '.join(profile.geographies[:2])}<br>"
            f"👥 {profile.headcount_min}–{profile.headcount_max} employees<br>"
            f"🏢 {', '.join(profile.company_stages[:2])}</div>"
            f"{active_badge}"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown("")

        if not is_active:
            if st.button(
                f"Switch to {profile.name.split('—')[0].strip()}",
                key  = f"switch_{profile.name}",
                use_container_width = True,
            ):
                st.session_state.active_profile  = profile
                st.session_state.current_prospect = None
                st.session_state.pipeline_step    = 1
                st.rerun()
        else:
            st.button(
                "Active ✓",
                key              = f"active_{profile.name}",
                use_container_width = True,
                disabled         = True,
            )

st.divider()

#  Pipeline entry points 
st.subheader("Start a pipeline run")

col_a, col_b = st.columns(2)

with col_a:
    st.markdown(
        f"<div style='background:{config.AGENCY_COLOR};color:white;"
        f"border-radius:10px;padding:18px;'>"
        f"<div style='font-size:16px;font-weight:bold;margin-bottom:8px;'>"
        f"🔍 Run a prospect through the full pipeline</div>"
        f"<div style='font-size:13px;opacity:0.9;'>"
        f"Select a prospect → enrichment from 3 sources → "
        f"AI scoring → research brief → email + LinkedIn draft → "
        f"your review → Salesforce export</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown("")
    if st.button(
        "▶ Start pipeline run",
        type             = "primary",
        use_container_width = True,
    ):
        st.switch_page("pages/1_icp_setup.py")

with col_b:
    # session stats
    results  = st.session_state.all_results
    hot      = sum(
        1 for r in results
        if r.get("score") and r["score"].get("tier") == "Hot"
    )
    approved = sum(
        1 for r in results
        if r.get("draft") and
        r["draft"].get("approval_status") in ["approved","edited_approved"]
    )

    st.markdown(
        f"<div style='background:#F8F9FA;border:1px solid #E8E8E8;"
        f"border-radius:10px;padding:18px;'>"
        f"<div style='font-size:16px;font-weight:bold;margin-bottom:12px;"
        f"color:{config.AGENCY_COLOR};'>Session summary</div>"
        f"<div style='display:grid;grid-template-columns:1fr 1fr;"
        f"gap:10px;'>"
        f"<div style='text-align:center;'>"
        f"<div style='font-size:28px;font-weight:bold;"
        f"color:{config.AGENCY_COLOR};'>{len(results)}</div>"
        f"<div style='font-size:12px;color:#666;'>Processed</div></div>"
        f"<div style='text-align:center;'>"
        f"<div style='font-size:28px;font-weight:bold;color:#E74C3C;'>"
        f"{hot}</div>"
        f"<div style='font-size:12px;color:#666;'>Hot leads</div></div>"
        f"<div style='text-align:center;'>"
        f"<div style='font-size:28px;font-weight:bold;color:#27AE60;'>"
        f"{approved}</div>"
        f"<div style='font-size:12px;color:#666;'>Approved</div></div>"
        f"<div style='text-align:center;'>"
        f"<div style='font-size:28px;font-weight:bold;color:#F39C12;'>"
        f"{len(results) - approved if results else 0}</div>"
        f"<div style='font-size:12px;color:#666;'>Pending review</div>"
        f"</div></div></div>",
        unsafe_allow_html=True,
    )

st.divider()

#  How it works ───────────────────────────────────────────────────────────────
st.subheader("What the pipeline does")
steps = [
    ("⚙️", "ICP setup",          "Define sector, size, geography, triggers"),
    ("🔍", "Prospect selection",  "Apollo, CSV upload, or pre-loaded prospects"),
    ("📊", "Enrichment",          "Apollo → LinkedIn → News — 3 real sources"),
    ("🤖", "AI scoring",          "bart-large-mnli — space need probability"),
    ("📝", "Brief + draft",       "Mistral-7B — research brief + email + LinkedIn"),
    ("✅", "Your review",         "Approve, edit, or reject — nothing sends without you"),
    ("📤", "Export",              "Salesforce-ready CSV — one click"),
]
step_cols = st.columns(len(steps))
for col, (icon, title, desc) in zip(step_cols, steps):
    with col:
        st.markdown(
            f"<div style='text-align:center;padding:8px;'>"
            f"<div style='font-size:22px;'>{icon}</div>"
            f"<div style='font-weight:bold;font-size:12px;"
            f"margin:4px 0;color:{config.AGENCY_COLOR};'>{title}</div>"
            f"<div style='font-size:11px;color:#666;'>{desc}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )