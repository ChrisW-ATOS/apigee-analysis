"""Runbook Library — catalog of known fix patterns agents can auto-apply.

PREVIEW / MOCKUP ONLY. Shows the growing library of validated fix patterns
and their historical success rate — evidence the system gets more capable
over time. No live runbook execution history is connected yet.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from apigee_analysis.config import Settings

_NAVY   = "#1B2A4A"
_RED    = "#EF4444"
_AMBER  = "#F59E0B"
_GREEN  = "#22C55E"
_PURPLE = "#7C3AED"
_TEAL   = "#0E7490"
_MUTED  = "#64748B"

_RUNBOOKS = [
    {"id": "APIGEE-IR-001", "name": "Credential Rotation", "category": "Auth",
     "trigger": "Client 4xx > 70%, sustained ≥1h", "applied": 41, "success_rate": 0.95,
     "avg_resolution": "6 min", "confidence_req": 0.85,
     "steps": ["Identify suspect credentials issued before incident onset",
               "Generate replacement credentials with matching scope",
               "Stage new credentials in secrets vault",
               "Rolling restart with health checks",
               "Validate error rate returns to baseline"]},
    {"id": "APIGEE-IR-002", "name": "Configuration Revert", "category": "Config",
     "trigger": "Client 4xx > 30%, sustained ≥2h, config drift detected", "applied": 23, "success_rate": 0.87,
     "avg_resolution": "9 min", "confidence_req": 0.85,
     "steps": ["Diff current config against last-known-good snapshot",
               "Classify drift (rate limit, timeout, auth policy, target URL)",
               "Revert to last-known-good configuration",
               "Notify partner teams if contract-affecting fields changed",
               "Validate error rate returns to baseline"]},
    {"id": "APIGEE-IR-003", "name": "Rate Limit Auto-Tune", "category": "Capacity",
     "trigger": "Traffic z-score > 3σ with <5% error rate (legitimate growth)", "applied": 12, "success_rate": 1.00,
     "avg_resolution": "3 min", "confidence_req": 0.80,
     "steps": ["Confirm traffic increase is not anomalous (error rate stable)",
               "Calculate new rate limit ceiling with 20% headroom",
               "Apply updated limit via API management config",
               "Monitor for 15 min to confirm no downstream impact"]},
    {"id": "APIGEE-IR-004", "name": "Backend Health Restart", "category": "Infrastructure",
     "trigger": "Server 5xx > 90%, no recent deploy correlation", "applied": 8, "success_rate": 0.63,
     "avg_resolution": "14 min", "confidence_req": 0.90,
     "steps": ["Check backend service health endpoint",
               "Attempt graceful service restart",
               "Verify downstream dependency connectivity",
               "Escalate to human if restart does not resolve within 10 min"]},
    {"id": "APIGEE-IR-005", "name": "Cascade Isolation", "category": "Dependency",
     "trigger": "Predictive agent flags high-confidence cascade risk ≥0.75", "applied": 6, "success_rate": 0.83,
     "avg_resolution": "N/A (preventive)", "confidence_req": 0.90,
     "steps": ["Identify shared dependency between driver and at-risk API",
               "Apply circuit breaker on the at-risk API's call to shared dependency",
               "Notify owning team of pre-emptive isolation",
               "Remove isolation once driver API recovers"]},
]

_CATEGORY_COLOR = {"Auth": _PURPLE, "Config": "#3B82F6", "Capacity": _GREEN,
                    "Infrastructure": _RED, "Dependency": _TEAL}


def _mock_banner() -> None:
    st.html("""
<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;
            padding:10px 16px;margin-bottom:20px;">
    <span style="font-size:12px;color:#92400E;">
        <b>Preview mockup</b> — no live runbook execution history is connected yet.
        Application counts and success rates below are illustrative of how the
        catalog would grow and self-report accuracy over time.
    </span>
</div>
""")


def _kpi_row(df: pd.DataFrame) -> None:
    total_applied = df["applied"].sum()
    weighted_success = (df["success_rate"] * df["applied"]).sum() / total_applied if total_applied else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Runbooks in Catalog",   len(df))
    c2.metric("Total Applications",    int(total_applied))
    c3.metric("Weighted Success Rate", f"{weighted_success:.0%}")
    c4.metric("Newest Pattern",        "APIGEE-IR-005", delta="Added 4 days ago")


def _success_chart(df: pd.DataFrame) -> None:
    st.subheader("Success Rate by Pattern")
    fig = go.Figure(go.Bar(
        x=df["success_rate"] * 100,
        y=df["name"],
        orientation="h",
        marker_color=[_CATEGORY_COLOR.get(c, _MUTED) for c in df["category"]],
        text=[f"{r:.0%} ({n} runs)" for r, n in zip(df["success_rate"], df["applied"])],
        textposition="auto",
    ))
    fig.update_layout(
        height=280, plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis=dict(title="Success rate %", range=[0, 105]),
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Success rate is tracked per-pattern and feeds back into the confidence score the "
               "Auto-Deploy Agent requires before applying that pattern autonomously.")


def _runbook_cards(df: pd.DataFrame) -> None:
    st.subheader("Runbook Catalog")
    for _, rb in df.iterrows():
        color = _CATEGORY_COLOR.get(rb["category"], _MUTED)
        with st.expander(f"{rb['id']} — {rb['name']}  ·  {rb['category']}  ·  {rb['success_rate']:.0%} success ({rb['applied']} runs)"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Applied",           rb["applied"])
            c2.metric("Success Rate",      f"{rb['success_rate']:.0%}")
            c3.metric("Avg. Resolution",   rb["avg_resolution"])
            c4.metric("Confidence Req.",   f"{rb['confidence_req']:.2f}")

            st.markdown(f"**Trigger condition:** {rb['trigger']}")
            st.markdown("**Steps:**")
            for i, step in enumerate(rb["steps"], 1):
                st.markdown(f"{i}. {step}")

            st.html(f"""
<div style="background:#F8FAFC;border-left:3px solid {color};border-radius:4px;
            padding:8px 12px;margin-top:8px;">
    <span style="font-size:11px;color:{_MUTED};">
        Category: <b style="color:{color};">{rb['category']}</b> — this pattern is
        auto-applied only when detection confidence exceeds {rb['confidence_req']:.2f}.
    </span>
</div>
""")


def render(settings: Settings) -> None:
    st.html(f"""
<div style="background:{_NAVY};border-radius:12px;padding:20px 28px;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-bottom:6px;">
        Runbook Library
    </div>
    <div style="font-size:13px;color:#94A3B8;line-height:1.6;">
        The catalog of validated fix patterns the Proactive Fix Development Agent
        can apply autonomously — and how reliably each one has worked historically.
    </div>
</div>
""")

    _mock_banner()
    df = pd.DataFrame(_RUNBOOKS)
    _kpi_row(df)
    st.divider()
    _success_chart(df)
    st.divider()
    _runbook_cards(df)
