"""MTN API Intelligence — Streamlit dashboard entry point."""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import get_settings
from apigee_analysis.dashboard.views import anomalies, blast, health, incident

st.set_page_config(
    page_title="MTN API Intelligence",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar branding ──────────────────────────────────────────────────────────
st.markdown("""
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
    /* Tighten main content top padding */
    .block-container { padding-top: 1.5rem; }
</style>
""", unsafe_allow_html=True)

settings = get_settings()

with st.sidebar:
    st.markdown("# MTN API Intelligence")
    st.markdown(
        "<p style='font-size:12px;'>AI-powered API health monitoring<br>"
        "across 15 Operating Companies</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    page = st.radio(
        "Navigate",
        options=["Incident Brief", "Country Health", "Anomaly Explorer", "Blast Radius"],
        label_visibility="collapsed",
    )

    st.divider()

    if st.button("⟳  Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption("Data auto-expires every 60 seconds")
    st.caption(f"Bucket: `{settings.anomaly_bucket}`")

# ── Page routing ──────────────────────────────────────────────────────────────
if page == "Incident Brief":
    incident.render(settings)
elif page == "Country Health":
    health.render(settings)
elif page == "Anomaly Explorer":
    anomalies.render(settings)
elif page == "Blast Radius":
    blast.render(settings)
