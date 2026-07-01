"""Monitoring — AI-generated incident brief, actionable response, and cascade prediction.

Consolidates what was previously three separate pages (Monitoring, Incident Response,
and the raw Signal Explorer) into one, removing duplicate predictive-risk views and
the lowest-value raw Z-score tab.
"""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard.views import blast, incident, incident_response, predictions


def render(settings: Settings) -> None:
    # Auto-resolve full-page takeover — checked once here, shared by the
    # "Respond & Resolve" tab's action buttons.
    incident_response.init_session_state()
    if st.session_state.ar_proxy:
        incident_response._auto_resolve_page(settings)
        return

    st.header("Monitoring")

    tabs = st.tabs([
        "📋  Incident Brief",
        "🚨  Respond & Resolve",
        "⚡  Predictive Cascade",
    ])

    with tabs[0]:
        # AI-generated incident summary, active anomalies, predicted error rates,
        # complex pattern (multivariate) alerts.
        incident.render(settings)

    with tabs[1]:
        # Prioritised, actionable incident cards — effect / root cause / resolution
        # steps / auto-resolve — plus the business-impact visualization below.
        incident_response.render(settings, embedded=True)
        st.divider()
        blast.render(settings)

    with tabs[2]:
        # Behavioral cross-correlation cascade risk, with drill-down history charts.
        predictions.render(settings)
