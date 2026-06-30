"""MTN API Intelligence — Streamlit dashboard entry point."""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import get_settings
from apigee_analysis.dashboard.views import api_intelligence, executive, incident_response, live_monitoring, opco_analytics

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
    st.divider()

    page = st.radio(
        "Navigate",
        options=["Platform Overview", "Monitoring", "Incident Response",
                 "API Intelligence", "OpCo Analytics"],
        label_visibility="collapsed",
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
elif page == "Incident Response":
    incident_response.render(settings)
elif page == "API Intelligence":
    api_intelligence.render(settings)
elif page == "OpCo Analytics":
    opco_analytics.render(settings)
