"""MTN API Intelligence — Streamlit dashboard entry point."""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import get_settings
from apigee_analysis.dashboard.views import (
    agentic_sdlc,
    api_intelligence,
    enterprise_integration,
    executive,
    live_monitoring,
    opco_analytics,
)

st.set_page_config(
    page_title="MTN API Intelligence",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.html("""
<style>
    [data-testid="stSidebar"] {
        background-color: #1B2A4A;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] div {
        color: #E2E8F0 !important;
    }
    [data-testid="stSidebar"] .stRadio > label {
        color: #FFCB05 !important;
        font-weight: 600;
        font-size: 11px;
        letter-spacing: 0.07em;
        text-transform: uppercase;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1 {
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        color: #94A3B8 !important;
    }
    .block-container { padding-top: 3rem; }
</style>
""")

settings = get_settings()

with st.sidebar:
    st.markdown("# MTN API Intelligence")
    st.caption("AI-powered API health monitoring across 15 Operating Companies")

    # Microsoft Entra ID sign-in mockup — no live tenant connection yet.
    st.html("""
<div style="background:#0F1B33;border:1px solid #2D3E5C;border-radius:8px;
            padding:10px 12px;margin:8px 0 4px 0;">
    <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:16px;">🔐</span>
        <div>
            <div style="font-size:11px;color:#FFCB05;font-weight:700;">Microsoft Entra ID</div>
            <div style="font-size:11px;color:#CBD5E1;">chris.walley@mtn.com</div>
            <div style="font-size:10px;color:#64748B;">Role: Developer (preview)</div>
        </div>
    </div>
</div>
""")
    st.caption("Preview only — tenant integration not yet connected. See **Enterprise Integration**.")

    st.divider()

    page = st.radio(
        "Navigate",
        options=["Platform Overview", "Monitoring", "API Intelligence",
                 "OpCo Analytics", "Agentic SDLC", "Enterprise Integration"],
        label_visibility="collapsed",
    )

    st.divider()

    st.link_button(
        "📊  View Pitch Deck",
        "app/static/agentic-development-lifecycle.html",
        use_container_width=True,
    )

    st.divider()

    if st.button("⟳  Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption("Data auto-expires every 60 seconds")
    st.caption(f"Bucket: `{settings.anomaly_bucket}`")

if page == "Platform Overview":
    executive.render(settings)
elif page == "Monitoring":
    live_monitoring.render(settings)
elif page == "API Intelligence":
    api_intelligence.render(settings)
elif page == "OpCo Analytics":
    opco_analytics.render(settings)
elif page == "Agentic SDLC":
    agentic_sdlc.render(settings)
elif page == "Enterprise Integration":
    enterprise_integration.render(settings)
