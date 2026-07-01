"""OpCo Analytics — country health, availability, growth, and partner impact."""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard.views import capacity_forecast, health, scorecard
from apigee_analysis.dashboard.views.monitoring import (
    _partner_experience,
    _reliability_scores,
    _sla_trajectory,
    _traffic_forecast,
)


def render(settings: Settings) -> None:
    st.header("OpCo Analytics")

    tabs = st.tabs([
        "🌍  Country Health",
        "📋  Availability",
        "📈  Trends & Capacity",
        "🤝  Partner Experience",
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
        # Traffic growth + 14-day forecast + reliability scores + capacity headroom
        _traffic_forecast(settings)
        st.divider()
        _reliability_scores(settings)
        st.divider()
        capacity_forecast.render(settings, embedded=True)

    with tabs[3]:
        # Which partner apps are experiencing the worst API quality
        _partner_experience(settings)
