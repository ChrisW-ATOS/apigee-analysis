"""OpCo Analytics — country health, availability, and traffic trends."""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard.views import health, scorecard
from apigee_analysis.dashboard.views.monitoring import (
    _reliability_scores,
    _sla_trajectory,
    _traffic_forecast,
)


def render(settings: Settings) -> None:
    st.header("OpCo Analytics")

    tabs = st.tabs([
        "🌍  Country Health",
        "📋  Availability",
        "📈  Trends",
    ])

    with tabs[0]:
        # Africa choropleth + OpCo status list + metrics
        health.render(settings)

    with tabs[1]:
        # SLA trajectory chart + per-OpCo scorecard table
        _sla_trajectory(settings)
        st.divider()
        scorecard.render(settings)

    with tabs[2]:
        # Traffic growth + 14-day forecast + reliability scores
        _traffic_forecast(settings)
        st.divider()
        _reliability_scores(settings)
