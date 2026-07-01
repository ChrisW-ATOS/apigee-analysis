"""Agentic SDLC — how the agent pipeline builds, validates, and learns from fixes.

Consolidates Feature Pipeline, Runbook Library, and Agent Decision Audit Log into
one page: what's being built right now, the growing library of fixes agents can
apply autonomously, and the governance trail behind every autonomous decision.
"""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard.views import agent_audit_log, feature_pipeline, runbook_library

_NAVY = "#1B2A4A"


def render(settings: Settings) -> None:
    st.html(f"""
<div style="background:{_NAVY};border-radius:12px;padding:20px 28px;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-bottom:6px;">
        Agentic SDLC
    </div>
    <div style="font-size:13px;color:#94A3B8;line-height:1.6;">
        How the agent pipeline plans, builds, and validates changes — the growing
        library of fixes it can apply autonomously — and the governance trail
        behind every decision it makes without a human in the loop.
    </div>
</div>
""")

    tabs = st.tabs([
        "🔧  Pipeline & Environments",
        "📚  Runbook Library",
        "🗂️  Decision Log",
    ])

    with tabs[0]:
        feature_pipeline.render(settings, embedded=True)

    with tabs[1]:
        runbook_library.render(settings, embedded=True)

    with tabs[2]:
        agent_audit_log.render(settings, embedded=True)
