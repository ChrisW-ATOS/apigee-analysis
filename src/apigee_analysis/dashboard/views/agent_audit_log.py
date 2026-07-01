"""Agent Decision Audit Log — searchable history of every autonomous agent decision.

PREVIEW / MOCKUP ONLY. Demonstrates the governance/trust layer for autonomous
action — every decision an agent makes, its confidence, and its outcome, in one
searchable log. No live agent execution history is connected yet.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from apigee_analysis.config import Settings

_NAVY   = "#1B2A4A"
_RED    = "#EF4444"
_AMBER  = "#F59E0B"
_GREEN  = "#22C55E"
_PURPLE = "#7C3AED"
_MUTED  = "#64748B"

_now = lambda h=0, m=0: (datetime.now(timezone.utc) - timedelta(hours=h, minutes=m)).strftime("%Y-%m-%d %H:%M UTC")

_DECISIONS = [
    {"time": _now(0, 12),  "agent": "Auto-Deploy",   "decision": "Auto-deployed config revert",
     "target": "Uganda · Service Activation", "confidence": 0.94, "outcome": "✅ Success — error rate to baseline in 4 min", "issue": "FEAT-138"},
    {"time": _now(1, 40),  "agent": "Fix Dev",       "decision": "Staged fix — escalated (blast radius > threshold)",
     "target": "Nigeria · Customer Bill Management", "confidence": 0.82, "outcome": "🟡 Awaiting human approval", "issue": "FEAT-146"},
    {"time": _now(3, 5),   "agent": "Predictive",    "decision": "Flagged cascade risk",
     "target": "Ghana · Products (driven by Nigeria · NIMC)", "confidence": 0.68, "outcome": "🔵 Monitoring — no action taken", "issue": "—"},
    {"time": _now(5, 22),  "agent": "Auto-Deploy",   "decision": "Auto-deployed credential rotation",
     "target": "Rwanda · Resourceconfig", "confidence": 0.91, "outcome": "✅ Success — 5xx rate to baseline in 6 min", "issue": "FEAT-130"},
    {"time": _now(8, 2),   "agent": "Review",        "decision": "Blocked PR — medium severity finding",
     "target": "FEAT-141 rate-limit auto-tune", "confidence": 0.97, "outcome": "🔴 Blocked — awaiting fix", "issue": "FEAT-141"},
    {"time": _now(11, 15), "agent": "Auto-Deploy",   "decision": "Rolled back deployment automatically",
     "target": "TMF621_TroubleTicket_prod", "confidence": 0.88, "outcome": "🟠 Rolled back — error rate rose post-deploy", "issue": "FEAT-118"},
    {"time": _now(14, 30), "agent": "Fix Dev",       "decision": "Auto-deployed credential rotation",
     "target": "South Africa · OAuth Token", "confidence": 0.96, "outcome": "✅ Success — 4xx rate to baseline in 3 min", "issue": "FEAT-112"},
    {"time": _now(18, 0),  "agent": "Predictive",    "decision": "Flagged cascade risk — escalated (high confidence + high blast radius)",
     "target": "Nigeria · KYC cluster (5 proxies)", "confidence": 0.87, "outcome": "🟡 Human notified via Teams", "issue": "—"},
    {"time": _now(22, 45), "agent": "Testing",       "decision": "Quarantined flaky test",
     "target": "test_stl_forecast_short_series", "confidence": 0.99, "outcome": "✅ Removed from deploy gate", "issue": "—"},
    {"time": _now(26, 10), "agent": "Auto-Deploy",   "decision": "Auto-deployed config revert",
     "target": "edgemicro_ghana_prod_datatransfer", "confidence": 0.90, "outcome": "✅ Success — stable for 24h since", "issue": "FEAT-103"},
]

_AGENT_COLOR = {
    "Planning": "#3B82F6", "Build": "#22C55E", "Review": "#F59E0B",
    "Testing": "#EC4899", "Validation": "#06B6D4", "Deployment": "#EF4444",
    "Predictive": _PURPLE, "Fix Dev": "#22D3EE", "Auto-Deploy": "#4ADE80",
}


def _mock_banner() -> None:
    st.html("""
<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;
            padding:10px 16px;margin-bottom:20px;">
    <span style="font-size:12px;color:#92400E;">
        <b>Preview mockup</b> — no live agent execution history is connected yet.
        This log demonstrates the governance and audit trail every autonomous
        action would produce: what was decided, at what confidence, and what happened.
    </span>
</div>
""")


def _kpi_row(df: pd.DataFrame) -> None:
    total       = len(df)
    auto_pct    = (df["decision"].str.contains("Auto-deployed").sum() / total * 100) if total else 0
    escalated   = df["outcome"].str.contains("Awaiting human|notified").sum()
    avg_conf    = df["confidence"].mean()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Decisions (7 days)",       total)
    c2.metric("Auto-Resolved",            f"{auto_pct:.0f}%")
    c3.metric("Escalated to Human",       int(escalated))
    c4.metric("Avg. Confidence Score",    f"{avg_conf:.2f}")


def _confidence_trend(df: pd.DataFrame) -> None:
    st.subheader("Confidence Score Distribution")
    fig = go.Figure(go.Histogram(
        x=df["confidence"], nbinsx=10, marker_color=_PURPLE, opacity=0.75,
    ))
    fig.add_vline(x=0.85, line_dash="dash", line_color=_RED,
                  annotation_text="Auto-deploy threshold (0.85)", annotation_font_size=10)
    fig.update_layout(
        height=260, plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
        xaxis=dict(title="Confidence score", range=[0.5, 1.0]),
        yaxis=dict(title="Decisions"),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Decisions above the dashed line are eligible for autonomous action without human sign-off.")


def _filters(df: pd.DataFrame) -> pd.DataFrame:
    c1, c2, c3 = st.columns(3)
    with c1:
        agents = st.multiselect("Agent", sorted(df["agent"].unique()), default=[])
    with c2:
        min_conf = st.slider("Minimum confidence", 0.0, 1.0, 0.0, 0.05)
    with c3:
        search = st.text_input("Search target / issue", "")

    filtered = df.copy()
    if agents:
        filtered = filtered[filtered["agent"].isin(agents)]
    filtered = filtered[filtered["confidence"] >= min_conf]
    if search:
        mask = (
            filtered["target"].str.contains(search, case=False, na=False) |
            filtered["issue"].str.contains(search, case=False, na=False)
        )
        filtered = filtered[mask]
    return filtered


def _decision_log(df: pd.DataFrame) -> None:
    st.subheader("Decision Log")
    if df.empty:
        st.info("No decisions match the current filters.")
        return

    for _, row in df.iterrows():
        color = _AGENT_COLOR.get(row["agent"], _MUTED)
        st.html(f"""
<div style="background:#FFFFFF;border-left:4px solid {color};border-radius:6px;
            padding:12px 16px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,0.06);">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
            <span style="background:{color};color:#FFFFFF;padding:2px 8px;border-radius:8px;
                         font-size:10px;font-weight:700;margin-right:8px;">{row['agent']}</span>
            <span style="font-size:12px;font-weight:600;color:#1E293B;">{row['decision']}</span>
        </div>
        <span style="font-size:10px;color:{_MUTED};">{row['time']}</span>
    </div>
    <div style="font-size:11px;color:#374151;margin-top:6px;">
        <b>Target:</b> {row['target']} &nbsp;·&nbsp; <b>Confidence:</b> {row['confidence']:.2f}
        &nbsp;·&nbsp; <b>Issue:</b> {row['issue']}
    </div>
    <div style="font-size:11px;color:#374151;margin-top:4px;">{row['outcome']}</div>
</div>
""")


def render(settings: Settings) -> None:
    st.html(f"""
<div style="background:{_NAVY};border-radius:12px;padding:20px 28px;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-bottom:6px;">
        Agent Decision Audit Log
    </div>
    <div style="font-size:13px;color:#94A3B8;line-height:1.6;">
        Every autonomous decision made by the agent pipeline — what was decided,
        at what confidence, and what happened. The governance record behind
        every auto-resolved incident.
    </div>
</div>
""")

    _mock_banner()
    df = pd.DataFrame(_DECISIONS)
    _kpi_row(df)
    st.divider()
    _confidence_trend(df)
    st.divider()
    filtered = _filters(df)
    _decision_log(filtered)
