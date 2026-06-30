"""Monitoring — four-tab operational view: incidents, predictions, signals, history."""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard.views import anomalies, blast, incident, predictions
from apigee_analysis.dashboard.views.monitoring import (
    _chronic_problems,
    _partner_experience,
)


def render(settings: Settings) -> None:
    st.header("Monitoring")

    tabs = st.tabs([
        "🔴  Incidents",
        "⚡  Predictions",
        "🔍  Signals & Impact",
        "📊  History",
    ])

    with tabs[0]:
        # Active anomalies, Claude brief, complex pattern alerts
        incident.render(settings)

    with tabs[1]:
        # Time-to-failure countdown + predicted error rate chart
        predictions.render(settings)

    with tabs[2]:
        # Z-score explorer + blast radius drill-down
        st.subheader("Signal Explorer")
        anomalies.render(settings)
        st.divider()
        blast.render(settings)

    with tabs[3]:
        # 30-day chronic problems + partner experience
        _chronic_problems(settings)
        st.divider()
        _partner_experience(settings)
