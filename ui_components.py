"""
Editorial-terminal UI components for the CRE Outreach app.

All helpers return HTML strings (or push them via st.markdown) styled with
the CSS variables defined in config.DARK_THEME_CSS — `--accent-vermillion`,
`--font-display` (Fraunces), `--font-mono` (JetBrains Mono), etc.

Design principle: small-caps monospace for labels and metadata, serif
display for numbers and headings, sharp single-rule accents over flat
ground. No rounded corners, no gradient buttons.
"""

from __future__ import annotations

import datetime
import streamlit as st


# ── Tier / status chips ────────────────────────────────────────────────────


def tier_badge(tier: str) -> str:
    """Monospace small-caps chip, single accent border, no fill."""
    tier_key = (tier or "nurture").lower()
    label = {"hot": "Hot", "warm": "Warm", "nurture": "Nurture"}.get(
        tier_key, tier_key.title()
    )
    return f'<span class="cre-chip {tier_key}">{label}</span>'


def status_badge(status: str) -> str:
    s = (status or "").lower().strip()
    label = (status or "—").capitalize() if status else "—"
    klass = {
        "sent": "warm",  "opened": "nurture", "replied": "new",
        "draft": "nurture", "pending": "sent",
        "no response": "sent",
    }.get(s, "sent")
    return f'<span class="cre-chip {klass}">{label}</span>'


def new_badge() -> str:
    return '<span class="cre-chip new">New</span>'


def draft_ready_badge() -> str:
    return '<span class="cre-chip warm">Draft</span>'


def sent_badge() -> str:
    return '<span class="cre-chip sent">Sent</span>'


# ── Bars / dots ────────────────────────────────────────────────────────────


_TIER_ACCENT = {
    "hot":     "var(--accent-vermillion)",
    "warm":    "var(--accent-gold)",
    "nurture": "var(--accent-cobalt)",
}


def score_bar(score: int, tier: str) -> str:
    """Thin 2px horizontal rule, tier-tinted, with a tabular-figure label."""
    tier_key = (tier or "nurture").lower()
    color = _TIER_ACCENT.get(tier_key, _TIER_ACCENT["nurture"])
    pct = max(0, min(100, int(score)))
    return (
        f'<div style="height:2px;background:var(--border);width:100%;position:relative;">'
        f'<div style="background:{color};width:{pct}%;height:2px;'
        f'transition:width 0.5s ease;"></div>'
        f'</div>'
    )


def strength_dots(strength: int) -> str:
    """Square tick marks instead of round dots — more architectural."""
    strength = max(0, min(5, int(strength or 0)))
    out = ""
    for i in range(1, 6):
        color = (
            "var(--accent-vermillion)" if i <= strength else "var(--border)"
        )
        out += (
            f'<span style="display:inline-block;width:9px;height:2px;'
            f'background:{color};margin-right:3px;"></span>'
        )
    return out


# ── Signal labels ──────────────────────────────────────────────────────────


_SIGNAL_TYPE_KLASS = {
    "expansion":  "new",
    "hiring":     "nurture",
    "funding":    "warm",
    "lease":      "hot",
    "space_need": "hot",
    "space need": "hot",
}

_SIGNAL_TYPE_ICONS = {
    "expansion":  "▲",
    "hiring":     "■",
    "funding":    "◆",
    "lease":      "□",
    "space_need": "●",
    "space need": "●",
}


def signal_type_label(signal_type: str) -> str:
    key = (signal_type or "").lower().replace(" ", "_")
    klass = _SIGNAL_TYPE_KLASS.get(key, "sent")
    display = (signal_type or "signal").replace("_", " ").title()
    return f'<span class="cre-chip {klass}">{display}</span>'


def signal_icon(signal_type: str) -> str:
    """Returns a small geometric glyph rather than an emoji."""
    key = (signal_type or "").lower().replace(" ", "_")
    glyph = _SIGNAL_TYPE_ICONS.get(key, "◇")
    return (
        f'<span style="color:var(--accent-vermillion);font-family:var(--font-mono);'
        f'font-size:10px;margin-right:8px;vertical-align:middle;">{glyph}</span>'
    )


# ── Composite renderers ────────────────────────────────────────────────────


def info_row(label: str, value: str,
             value_color: str = "var(--text-primary)") -> str:
    """Editorial key/value row — label in monospace small-caps, value mono."""
    return (
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
        f'padding:8px 0;border-bottom:1px solid var(--border-faint);">'
        f'<span style="font-family:var(--font-mono);font-size:9.5px;'
        f'text-transform:uppercase;letter-spacing:0.18em;color:var(--text-muted);">'
        f'{label}</span>'
        f'<span style="font-family:var(--font-mono);font-size:12px;'
        f'color:{value_color};font-variant-numeric:tabular-nums;">{value}</span>'
        f'</div>'
    )


def section_header(title: str, subtitle: str = "") -> None:
    """Small-caps monospace section rule with trailing horizontal line."""
    st.markdown(
        f'<div class="cre-section-rule">'
        f'<span class="cre-mark">{title}</span>'
        + (f'<span style="color:var(--text-muted);letter-spacing:0.04em;'
           f'text-transform:none;margin-left:8px;font-size:10.5px;">'
           f'· {subtitle}</span>' if subtitle else "")
        + f'</div>',
        unsafe_allow_html=True,
    )


def metric_card(label: str, value: str, delta: str = "",
                delta_up: bool = True,
                value_color: str = "var(--text-primary)") -> None:
    """Editorial metric — vermillion top-rule, mono label, serif value."""
    delta_color = (
        "var(--accent-sage)" if delta_up else "var(--accent-rust)"
    )
    st.markdown(
        f'<div style="background:var(--bg-surface);border:1px solid var(--border);'
        f'padding:16px 18px;position:relative;">'
        f'<div style="position:absolute;top:0;left:0;height:1px;width:32px;'
        f'background:var(--accent-vermillion);"></div>'
        f'<div class="cre-stat-label">{label}</div>'
        f'<div class="cre-stat" style="color:{value_color};">{value}</div>'
        + (f'<div style="font-family:var(--font-mono);font-size:10px;'
           f'color:{delta_color};margin-top:4px;letter-spacing:0.08em;">'
           f'{delta}</div>' if delta else "")
        + f'</div>',
        unsafe_allow_html=True,
    )


def empty_state(icon: str, title: str, subtitle: str = "") -> None:
    """Empty state — oversized serif quote mark, italic title, no card."""
    st.markdown(
        f'<div style="padding:60px 24px;text-align:center;border:1px dashed '
        f'var(--border);background:transparent;">'
        f'<div style="font-family:var(--font-display);font-size:64px;'
        f'color:var(--border-strong);line-height:1;margin-bottom:14px;'
        f'font-style:italic;font-variation-settings:\'opsz\' 144,\'SOFT\' 100;">"</div>'
        f'<div style="font-family:var(--font-display);font-size:15px;'
        f'color:var(--text-secondary);font-style:italic;">{title}</div>'
        + (f'<div style="font-family:var(--font-mono);font-size:10px;'
           f'color:var(--text-muted);margin-top:10px;'
           f'text-transform:uppercase;letter-spacing:0.18em;">'
           f'{subtitle}</div>' if subtitle else "")
        + f'</div>',
        unsafe_allow_html=True,
    )


def api_status_row(name: str, connected: bool) -> str:
    color = (
        "var(--accent-sage)" if connected else "var(--text-muted)"
    )
    return (
        f'<div style="padding:3px 0;font-family:var(--font-mono);'
        f'font-size:10px;color:var(--text-muted);letter-spacing:0.1em;'
        f'text-transform:uppercase;">'
        f'<span style="color:{color};margin-right:8px;">●</span>{name}'
        f'</div>'
    )


def pulse_dot(color: str = "var(--accent-sage)") -> str:
    """Breathing dot — uses the keyframe animation defined in the CSS."""
    if color in ("#3fb950", "var(--accent-sage)"):
        klass = "ok"
    elif color in ("#d29922", "var(--accent-gold)", "var(--accent-vermillion)",
                    "#f85149"):
        klass = "live"
    else:
        klass = "idle"
    return f'<span class="cre-pulse {klass}"></span>'


# ── Sidebar — call from every page ─────────────────────────────────────────


def render_sidebar() -> None:
    """Editorial sidebar — serif wordmark, monospace nav, accent rules."""
    import config

    with st.sidebar:
        # Wordmark — serif italic accent on "CRE"
        st.markdown(
            '<div style="padding:0 0 18px;border-bottom:1px solid var(--border);'
            'margin-bottom:18px;">'
            '<div class="cre-wordmark" style="font-size:18px;">'
            '<em>CRE</em> Outreach</div>'
            '<div style="font-family:var(--font-mono);font-size:9px;'
            'color:var(--text-muted);text-transform:uppercase;'
            'letter-spacing:0.22em;margin-top:6px;">'
            'Intelligence · Manhattan</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # Greeting — derived from the logged-in user
        _user = st.session_state.get("current_user") or {}
        _full_name = _user.get("full_name") or ""
        _first_name = _full_name.split()[0] if _full_name else (
            _user.get("google_email", "").split("@")[0] or "there"
        )
        st.markdown(
            f'<div style="padding:0 0 14px;font-family:var(--font-mono);'
            f'font-size:10px;color:var(--text-muted);text-transform:uppercase;'
            f'letter-spacing:0.16em;">'
            f'Signed in <span style="color:var(--text-secondary);'
            f'text-transform:none;letter-spacing:0;">as '
            f'<em style="color:var(--text-primary);font-style:italic;">'
            f'{_first_name}</em></span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Nav header
        st.markdown(
            '<div style="font-family:var(--font-mono);font-size:9px;'
            'color:var(--text-muted);text-transform:uppercase;'
            'letter-spacing:0.22em;padding:4px 0 8px;">— Sections</div>',
            unsafe_allow_html=True,
        )
        st.page_link("pages/5_morning_research.py", label="Research")
        st.page_link("pages/3_draft_review.py",     label="Drafts")
        st.page_link("pages/6_sent_tracker.py",     label="Sent")
        st.page_link("pages/7_followups.py",        label="Follow-ups")

        # Active profile — derived from watchlist
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
                        f'<div style="margin-top:24px;padding-top:16px;'
                        f'border-top:1px solid var(--border);">'
                        f'<div style="font-family:var(--font-mono);font-size:9px;'
                        f'color:var(--text-muted);text-transform:uppercase;'
                        f'letter-spacing:0.22em;margin-bottom:8px;">— Profile</div>'
                        f'<div style="font-family:var(--font-display);'
                        f'font-size:14px;color:var(--text-primary);'
                        f'font-style:italic;">{profile_name}</div>'
                        f'<div style="font-family:var(--font-mono);font-size:10px;'
                        f'color:var(--text-muted);margin-top:4px;'
                        f'letter-spacing:0.08em;">{sector} · {city}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
        except Exception:
            pass

        # Connection status
        st.markdown(
            '<div style="margin-top:18px;padding-top:16px;'
            'border-top:1px solid var(--border);">'
            '<div style="font-family:var(--font-mono);font-size:9px;'
            'color:var(--text-muted);text-transform:uppercase;'
            'letter-spacing:0.22em;margin-bottom:8px;">— Connections</div>'
            + api_status_row("HuggingFace",  config.HF_AVAILABLE)
            + api_status_row("Google OAuth", config.GOOGLE_OAUTH_AVAILABLE)
            + api_status_row("Gmail SMTP",   config.GMAIL_AVAILABLE)
            + api_status_row("NewsAPI",      config.NEWSAPI_AVAILABLE)
            + api_status_row("Hunter",       config.HUNTER_AVAILABLE)
            + api_status_row("Firecrawl",    config.FIRECRAWL_AVAILABLE)
            + api_status_row("Apollo",       config.APOLLO_AVAILABLE)
            + '</div>',
            unsafe_allow_html=True,
        )

        # Sign-out
        st.markdown(
            '<div style="margin-top:24px;padding-top:14px;'
            'border-top:1px solid var(--border);"></div>',
            unsafe_allow_html=True,
        )
        if st.button("Sign out", use_container_width=True, key="_signout_btn"):
            from session_manager import logout
            logout()

        # Footer colophon
        st.markdown(
            '<div style="margin-top:18px;padding-top:14px;'
            'border-top:1px solid var(--border);'
            'font-family:var(--font-mono);font-size:9px;color:var(--text-muted);'
            'letter-spacing:0.16em;text-transform:uppercase;line-height:1.6;">'
            'Vol. I · Issue '
            + datetime.date.today().strftime("%j")
            + '<br>'
            + datetime.date.today().strftime("%a · %d %b %Y")
            + '</div>',
            unsafe_allow_html=True,
        )


def inject_theme() -> None:
    """Inject the editorial-terminal CSS.

    Uses st.html() (Streamlit 1.33+) instead of st.markdown(unsafe_allow_html)
    because the markdown preprocessor (a) wraps <style> content in <p> tags
    so the browser can't apply it, and (b) treats `:hover`, `:nth-child`,
    `:has(input:checked)` as emoji shortcodes and silently deletes them.
    """
    from config import DARK_THEME_CSS
    if hasattr(st, "html"):
        st.html(DARK_THEME_CSS)
    else:
        st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)


def bootstrap_session_state() -> None:
    import datetime as _dt
    import threading
    import config as _config

    defaults = {
        "active_lead":        None,
        "research_running":   False,
        "research_error":     "",
        "selected_report_id": None,
        "demo_mode":          _config.FORCE_MOCK_MODE,
        "last_updated":       _dt.datetime.now().isoformat(),
        "_last_gmail_sync_at": 0.0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # ── Auto-sync Gmail Sent folder into Sheets + Calendar ────────────────
    # Every page load triggers this (cached at 60s) so the broker can send
    # from Gmail directly and still get Sheets log + 3-day Calendar follow-up
    # without thinking about it.
    import time
    now = time.time()
    since_last = now - st.session_state.get("_last_gmail_sync_at", 0)
    if since_last < 60:
        return
    st.session_state["_last_gmail_sync_at"] = now

    def _do_sync():
        try:
            from gmail_sync import sync_recent_sends
            sync_recent_sends(lookback_days=2)
        except Exception:
            pass   # already logged inside sync_recent_sends

    # Run in a daemon thread so it doesn't block page render
    threading.Thread(target=_do_sync, daemon=True).start()


def masthead(section: str = "") -> None:
    """Editorial masthead — serif wordmark on the left, monospace volume
    line + section title on the right. Call near the top of each page."""
    today = datetime.date.today()
    vol   = today.strftime("Vol. I · %a %d %b %Y").upper()
    st.markdown(
        f'<div class="cre-masthead">'
        f'<div class="cre-wordmark"><em>CRE</em> Outreach <span '
        f'style="font-family:var(--font-mono);font-size:10px;'
        f'text-transform:uppercase;letter-spacing:0.22em;'
        f'color:var(--text-muted);margin-left:14px;font-weight:400;'
        f'vertical-align:middle;">{section}</span></div>'
        f'<div class="cre-volume">{vol}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def page_shell(page_title: str) -> None:
    """Top-of-page setup + masthead. Enforces login before anything else."""
    import config as _config
    st.set_page_config(
        layout                = "wide",
        page_title            = f"{page_title} · CRE",
        page_icon             = _config.APP_ICON,
        initial_sidebar_state = "expanded",
    )
    inject_theme()
    # Auth gate — renders the login page and stops if no valid session
    from session_manager import require_login
    require_login()
    bootstrap_session_state()
    render_sidebar()
    masthead(page_title.upper())
