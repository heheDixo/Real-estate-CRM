"""
CRE Outreach Intelligence — entrypoint.

The home page is the Morning Research page (pages/5). app.py just sets up
the global session state, optionally starts the background scheduler, then
redirects.
"""

import streamlit as st

import config
from ui_components import page_shell

page_shell("Home")

# Optional: background scheduler (off by default — set START_SCHEDULER=true)
if config.START_SCHEDULER and not st.session_state.get("_scheduler_started"):
    try:
        from scheduler import start_scheduler_background
        if start_scheduler_background() is not None:
            st.session_state["_scheduler_started"] = True
    except Exception as exc:
        print(f"[app] scheduler thread failed to start: {exc}")

st.switch_page("pages/5_morning_research.py")
