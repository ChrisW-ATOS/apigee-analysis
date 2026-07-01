"""Quality & Testing — coverage trends, flaky tests, and security findings backlog.

PREVIEW / MOCKUP ONLY. Demonstrates the quality signal the Review and Testing
agents would surface once connected to a live CI system. No live CI/CD or SAST
tooling is connected yet — all figures below are illustrative.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from apigee_analysis.config import Settings

_NAVY  = "#1B2A4A"
_RED   = "#EF4444"
_AMBER = "#F59E0B"
_GREEN = "#22C55E"
_BLUE  = "#3B82F6"
_MUTED = "#64748B"

_WEEKS       = ["W-6", "W-5", "W-4", "W-3", "W-2", "W-1", "Now"]
_COVERAGE    = [78.1, 79.4, 80.2, 81.5, 82.8, 83.6, 84.2]
_FLAKY_COUNT = [14, 12, 11, 9, 7, 6, 5]

_FLAKY_TESTS = [
    {"Test": "test_predicted_anomaly_timing", "Module": "detect.py", "Flake Rate": "18%", "Last Seen": "2h ago",  "Status": "🟡 Active"},
    {"Test": "test_blast_radius_multi_country", "Module": "detect.py", "Flake Rate": "12%", "Last Seen": "6h ago",  "Status": "🟡 Active"},
    {"Test": "test_stl_forecast_short_series",  "Module": "baseline.py", "Flake Rate": "9%",  "Last Seen": "1d ago",  "Status": "🟠 Quarantined"},
    {"Test": "test_cascade_prob_edge_case",     "Module": "correlation.py", "Flake Rate": "7%",  "Last Seen": "1d ago",  "Status": "🟡 Active"},
    {"Test": "test_influx_write_retry",         "Module": "load.py", "Flake Rate": "4%",  "Last Seen": "3d ago",  "Status": "🟢 Monitoring"},
]

_SECURITY_FINDINGS = [
    {"Severity": "🟡 Medium", "Component": "rate-limit-auto-tune (FEAT-141)", "Finding": "Missing input validation on threshold param", "Age": "2 days", "Status": "Fix in review"},
    {"Severity": "🟢 Low",    "Component": "opco_fetch.py", "Finding": "Verbose error message may leak internal hostnames", "Age": "9 days", "Status": "Backlog"},
    {"Severity": "🟢 Low",    "Component": "dashboard/queries.py", "Finding": "Flux query string built via f-string (no user input path)", "Age": "14 days", "Status": "Accepted risk"},
]


def _mock_banner() -> None:
    st.html("""
<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;
            padding:10px 16px;margin-bottom:20px;">
    <span style="font-size:12px;color:#92400E;">
        <b>Preview mockup</b> — no live CI/CD or SAST tooling is connected yet.
        Coverage trends, flaky test tracking, and the security backlog below are
        illustrative of what the Review and Testing agents would surface.
    </span>
</div>
""")


def _kpi_row() -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Test Coverage",        f"{_COVERAGE[-1]:.1f}%", delta=f"+{_COVERAGE[-1]-_COVERAGE[-2]:.1f}pp this week")
    c2.metric("Flaky Tests",          _FLAKY_COUNT[-1], delta=f"{_FLAKY_COUNT[-1]-_FLAKY_COUNT[-2]:+d} this week", delta_color="inverse")
    c3.metric("Open Security Findings", len(_SECURITY_FINDINGS), delta_color="off")
    c4.metric("Tests Run Today",      "1,842", delta="12 suites")


def _coverage_trend() -> None:
    st.subheader("Coverage & Flaky Test Trend")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=_WEEKS, y=_COVERAGE, name="Coverage %", mode="lines+markers",
        line=dict(color=_GREEN, width=3), yaxis="y1",
    ))
    fig.add_trace(go.Bar(
        x=_WEEKS, y=_FLAKY_COUNT, name="Flaky tests", marker_color=_AMBER, opacity=0.5, yaxis="y2",
    ))
    fig.update_layout(
        height=320, plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis=dict(title="Coverage %", range=[70, 90]),
        yaxis2=dict(title="Flaky tests", overlaying="y", side="right", range=[0, 20]),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Testing Agent (④) drives both trends — generating edge-case tests raises coverage, "
               "while flagged-flaky tests are automatically quarantined pending root-cause fix.")


def _flaky_tests_table() -> None:
    st.subheader("Flaky Test Tracker")
    df = pd.DataFrame(_FLAKY_TESTS)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("Tests exceeding a 15% flake rate over 20 runs are auto-quarantined by the Testing Agent "
               "and excluded from deployment gates until stabilised.")


def _security_backlog() -> None:
    st.subheader("Security Findings Backlog")
    df = pd.DataFrame(_SECURITY_FINDINGS)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("Sourced from the Review Agent's (③) static analysis pass on every PR. "
               "Medium+ severity findings block auto-deploy regardless of confidence score.")


def render(settings: Settings) -> None:
    st.html(f"""
<div style="background:{_NAVY};border-radius:12px;padding:20px 28px;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-bottom:6px;">
        Quality &amp; Testing
    </div>
    <div style="font-size:13px;color:#94A3B8;line-height:1.6;">
        Coverage trends, flaky test tracking, and the security findings backlog —
        the quality signal produced by the Review and Testing agents on every change.
    </div>
</div>
""")

    _mock_banner()
    _kpi_row()
    st.divider()
    _coverage_trend()
    st.divider()
    col_l, col_r = st.columns(2)
    with col_l:
        _flaky_tests_table()
    with col_r:
        _security_backlog()
