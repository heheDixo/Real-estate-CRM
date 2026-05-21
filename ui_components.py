"""
Reusable HTML helpers for the dark-theme UI. Pure functions — no Streamlit
state, no side effects. Each returns a markdown string suitable for
``st.markdown(html, unsafe_allow_html=True)`` (or pushes one in the case of
the renderers).
"""

from __future__ import annotations

import streamlit as st

from config import TIER_COLORS


# ── Badges ─────────────────────────────────────────────────────────────────


def tier_badge(tier: str) -> str:
    tier = (tier or "nurture").lower()
    c = TIER_COLORS.get(tier, TIER_COLORS["nurture"])
    label = {
        "hot":     "🔥 Hot",
        "warm":    "☀ Warm",
        "nurture": "❄ Nurture",
    }.get(tier, tier.title())
    return (
        f'<span style="background:{c["bg"]};color:{c["text"]};'
        f'border:1px solid {c["border"]};border-radius:10px;'
        f'padding:2px 10px;font-size:11px;font-weight:500;">{label}</span>'
    )


def status_badge(status: str) -> str:
    palette = {
        "sent":    ("#3d2800", "#d29922"),
        "opened":  ("#0d1f3d", "#58a6ff"),
        "replied": ("#0d2b1a", "#3fb950"),
        "draft":   ("#2d1f5e", "#a371f7"),
        "pending": ("#21262d", "#484f58"),
        "no response": ("#21262d", "#8b949e"),
    }
    bg, text = palette.get((status or "").lower(), ("#21262d", "#8b949e"))
    label = (status or "—").capitalize() if status else "—"
    return (
        f'<span style="background:{bg};color:{text};border-radius:4px;'
        f'padding:2px 8px;font-size:11px;font-weight:500;">{label}</span>'
    )


def new_badge() -> str:
    return (
        '<span style="background:#2d1f5e;color:#a371f7;'
        'border:1px solid #3d2b6e;border-radius:10px;padding:2px 8px;'
        'font-size:10px;font-weight:500;">NEW</span>'
    )


def draft_ready_badge() -> str:
    return (
        '<span style="background:#0d2b1a;color:#3fb950;'
        'border:1px solid #1a5e35;border-radius:10px;padding:2px 8px;'
        'font-size:10px;font-weight:500;">Draft ready</span>'
    )


def sent_badge() -> str:
    return (
        '<span style="background:#0d1f3d;color:#58a6ff;'
        'border:1px solid #1c3a5e;border-radius:10px;padding:2px 8px;'
        'font-size:10px;font-weight:500;">Sent ✓</span>'
    )


# ── Bars / dots ────────────────────────────────────────────────────────────


def score_bar(score: int, tier: str) -> str:
    tier = (tier or "nurture").lower()
    color = TIER_COLORS.get(tier, TIER_COLORS["nurture"])["bar"]
    pct = max(0, min(100, int(score)))
    return (
        f'<div style="background:#21262d;border-radius:2px;height:4px;width:100%;">'
        f'<div style="background:{color};width:{pct}%;height:4px;border-radius:2px;"></div>'
        f'</div>'
    )


def strength_dots(strength: int) -> str:
    strength = max(0, min(5, int(strength or 0)))
    out = ""
    for i in range(1, 6):
        color = "#3fb950" if i <= strength else "#30363d"
        out += (
            f'<span style="display:inline-block;width:7px;height:7px;'
            f'border-radius:50%;background:{color};margin-right:3px;"></span>'
        )
    return out


# ── Pills ──────────────────────────────────────────────────────────────────


_SIGNAL_TYPE_COLOURS = {
    "expansion":  ("#0d2b1a", "#3fb950"),
    "hiring":     ("#0d1f3d", "#58a6ff"),
    "funding":    ("#3d2800", "#d29922"),
    "lease":      ("#2d1f5e", "#a371f7"),
    "space_need": ("#3d0f0f", "#f85149"),
    "space need": ("#3d0f0f", "#f85149"),
}

_SIGNAL_TYPE_ICONS = {
    "expansion":  "📰",
    "hiring":     "💼",
    "funding":    "💰",
    "lease":      "🏢",
    "space_need": "📍",
    "space need": "📍",
}


def signal_type_label(signal_type: str) -> str:
    key  = (signal_type or "").lower().replace(" ", "_")
    bg, text = _SIGNAL_TYPE_COLOURS.get(key, ("#21262d", "#8b949e"))
    display = (signal_type or "signal").replace("_", " ").upper()
    return (
        f'<span style="background:{bg};color:{text};border-radius:4px;'
        f'font-size:10px;padding:2px 8px;text-transform:uppercase;'
        f'letter-spacing:0.5px;font-weight:500;">{display}</span>'
    )


def signal_icon(signal_type: str) -> str:
    key = (signal_type or "").lower().replace(" ", "_")
    return _SIGNAL_TYPE_ICONS.get(key, "📊")


# ── Composite renderers ────────────────────────────────────────────────────


def info_row(label: str, value: str, value_color: str = "#e6edf3") -> str:
    return (
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'padding:6px 0;border-bottom:1px solid #21262d;">'
        f'<span style="font-size:12px;color:#8b949e;">{label}</span>'
        f'<span style="font-size:12px;color:{value_color};font-weight:500;">{value}</span>'
        f'</div>'
    )


def section_header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div style="margin:16px 0 12px;">'
        f'<div style="font-size:13px;font-weight:500;color:#e6edf3;">{title}</div>'
        + (f'<div style="font-size:11px;color:#8b949e;margin-top:2px;">'
           f'{subtitle}</div>' if subtitle else "")
        + f'</div>',
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str, delta: str = "",
                delta_up: bool = True,
                value_color: str = "#e6edf3") -> None:
    delta_color = "#3fb950" if delta_up else "#f85149"
    st.markdown(
        f'<div style="background:#161b22;border:1px solid #30363d;'
        f'border-radius:8px;padding:14px 16px;">'
        f'<div style="font-size:10px;color:#8b949e;text-transform:uppercase;'
        f'letter-spacing:0.5px;margin-bottom:6px;">{label}</div>'
        f'<div style="font-size:22px;font-weight:500;color:{value_color};">{value}</div>'
        + (f'<div style="font-size:11px;color:{delta_color};margin-top:4px;">'
           f'{delta}</div>' if delta else "")
        + f'</div>',
        unsafe_allow_html=True,
    )


def empty_state(icon: str, title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div style="background:#161b22;border:1px solid #30363d;'
        f'border-radius:8px;padding:40px;text-align:center;color:#484f58;">'
        f'<div style="font-size:32px;margin-bottom:12px;">{icon}</div>'
        f'<div style="font-size:14px;color:#8b949e;">{title}</div>'
        + (f'<div style="font-size:12px;color:#484f58;margin-top:6px;">'
           f'{subtitle}</div>' if subtitle else "")
        + f'</div>',
        unsafe_allow_html=True,
    )


def api_status_row(name: str, connected: bool) -> str:
    color = "#3fb950" if connected else "#484f58"
    return (
        f'<div style="padding:2px 0;font-size:10px;color:#8b949e;">'
        f'<span style="color:{color}">●</span> {name}</div>'
    )


def pulse_dot(color: str = "#3fb950") -> str:
    return (
        f'<span style="display:inline-block;width:8px;height:8px;'
        f'border-radius:50%;background:{color};margin-right:6px;'
        f'box-shadow:0 0 6px {color};"></span>'
    )


# ── Sidebar — call from every page ─────────────────────────────────────────


def render_sidebar() -> None:
    """
    Render the shared sidebar. Each multipage script must call this in its
    own ``with st.sidebar:`` block (Streamlit doesn't share sidebar state
    across pages).
    """
    import config

    with st.sidebar:
        st.markdown(
            '<div style="padding:0 0 16px;border-bottom:1px solid #30363d;'
            'margin-bottom:14px;">'
            '<div style="font-size:15px;font-weight:600;color:#e6edf3;">CRE Outreach</div>'
            '<div style="color:#3b82f6;font-size:11px;margin-top:2px;">'
            'Intelligence platform</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div style="font-size:10px;color:#484f58;text-transform:uppercase;'
            'letter-spacing:0.8px;padding:8px 0 4px;">Main</div>',
            unsafe_allow_html=True,
        )
        st.page_link("pages/5_morning_research.py", label="Research",     icon="🔬")
        st.page_link("pages/3_draft_review.py",     label="Drafts",       icon="📬")
        st.page_link("pages/6_sent_tracker.py",     label="Sent tracker", icon="📊")
        st.page_link("pages/7_followups.py",        label="Follow-ups",   icon="📅")

        # Active ICP — derived live from the watchlist now (no mock data layer).
        import os, json
        try:
            wl_path = os.path.join("data", "watchlist.json")
            if os.path.exists(wl_path):
                with open(wl_path) as _f:
                    wl = json.load(_f) or []
                active = next((w for w in wl if w.get("active", True)), None)
                if active:
                    profile_name = active.get("icp_profile") or "Watchlist"
                    sector = active.get("sector", "—")
                    city   = active.get("city",   "—")
                    st.markdown(
                        f'<div style="margin-top:20px;padding-top:14px;'
                        f'border-top:1px solid #30363d;">'
                        f'<div style="font-size:10px;color:#484f58;'
                        f'text-transform:uppercase;letter-spacing:0.8px;'
                        f'margin-bottom:4px;">Active profile</div>'
                        f'<div style="font-size:12px;color:#3fb950;">'
                        f'● {profile_name}</div>'
                        f'<div style="font-size:11px;color:#8b949e;margin-top:2px;">'
                        f'{sector} · {city}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
        except Exception:
            pass

        st.markdown(
            '<div style="margin-top:14px;padding-top:14px;'
            'border-top:1px solid #30363d;">'
            + api_status_row("HuggingFace",  config.HF_AVAILABLE)
            + api_status_row("Google OAuth", config.GOOGLE_OAUTH_AVAILABLE)
            + api_status_row("Gmail SMTP",   config.GMAIL_AVAILABLE)
            + api_status_row("NewsAPI",      config.NEWSAPI_AVAILABLE)
            + api_status_row("Hunter",       config.HUNTER_AVAILABLE)
            + api_status_row("Firecrawl",    config.FIRECRAWL_AVAILABLE)
            + '</div>',
            unsafe_allow_html=True,
        )

        if config.FORCE_MOCK_MODE:
            st.markdown(
                '<div style="margin-top:12px;background:#2d1f00;'
                'border:1px solid #5a3d00;color:#d29922;border-radius:4px;'
                'padding:6px 8px;font-size:11px;">'
                '⚠ FORCE_MOCK_MODE=true</div>',
                unsafe_allow_html=True,
            )


def inject_theme() -> None:
    """Inject the dark theme CSS. Call at the top of every page script."""
    from config import DARK_THEME_CSS
    st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)


def bootstrap_session_state() -> None:
    """
    Seed st.session_state with the defaults every page expects. Safe to call
    at the top of any page (Streamlit pages don't share execution with app.py
    when navigated to directly).
    """
    import datetime as _dt
    import config as _config

    defaults = {
        "active_lead":       None,
        "research_running":  False,
        "research_error":    "",
        "selected_report_id": None,
        "demo_mode":         _config.FORCE_MOCK_MODE,
        "last_updated":      _dt.datetime.now().isoformat(),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def page_shell(page_title: str) -> None:
    """
    One-call setup for every page. Does:
      - st.set_page_config
      - inject_theme()
      - bootstrap_session_state()
      - render_sidebar()

    Call as the first Streamlit statement in each page script.
    """
    import config as _config
    st.set_page_config(
        layout            = "wide",
        page_title        = f"{page_title} · CRE",
        page_icon         = _config.APP_ICON,
        initial_sidebar_state = "expanded",
    )
    inject_theme()
    bootstrap_session_state()
    render_sidebar()
