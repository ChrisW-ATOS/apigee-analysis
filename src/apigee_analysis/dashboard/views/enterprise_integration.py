"""Enterprise Integration — how this fits into the existing Microsoft tenant.

Consolidates Role-Based Views and Teams Integration into one page: role-tailored
dashboards on sign-in via Entra ID, and agent status/notifications surfaced
directly in Microsoft Teams.
"""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard.views import role_based_preview, teams_integration

_NAVY = "#1B2A4A"


def render(settings: Settings) -> None:
    st.html(f"""
<div style="background:{_NAVY};border-radius:12px;padding:20px 28px;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-bottom:6px;">
        Enterprise Integration
    </div>
    <div style="font-size:13px;color:#94A3B8;line-height:1.6;">
        How the platform fits into the existing Microsoft tenant — role-tailored
        views on sign-in via Entra ID, and agent status surfaced directly in Teams.
    </div>
</div>
""")

    tabs = st.tabs([
        "🔐  Role-Based Views",
        "💬  Teams Integration",
    ])

    with tabs[0]:
        role_based_preview.render(settings, embedded=True)

    with tabs[1]:
        teams_integration.render(settings, embedded=True)
