"""Availability Scorecard — per-OpCo SLA compliance over the last 30 days."""
from __future__ import annotations

import math

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries

SLA_TARGET = 99.5   # percent — change here to update across the whole view


def _bar(pct: float) -> str:
    """HTML availability bar — green above SLA, red below."""
    clamped = max(0.0, min(100.0, pct))
    color   = "#22C55E" if pct >= SLA_TARGET else "#EF4444"
    # SLA marker position
    sla_pos = SLA_TARGET
    return f"""
<div style="position:relative;height:10px;background:#E2E8F0;border-radius:5px;width:100%;margin:4px 0;">
    <div style="height:10px;width:{clamped:.1f}%;background:{color};
                border-radius:5px;transition:width 0.3s;"></div>
    <div style="position:absolute;top:-3px;left:{sla_pos:.1f}%;
                width:2px;height:16px;background:#64748B;border-radius:1px;"
         title="SLA {SLA_TARGET}%"></div>
</div>"""


def _trend_str(pp: float) -> str:
    if math.isnan(pp):
        return "<span style='color:#94A3B8;font-size:12px;'>—</span>"
    color  = "#22C55E" if pp >= 0 else "#EF4444"
    arrow  = "▲" if pp > 0.01 else ("▼" if pp < -0.01 else "→")
    return (f"<span style='color:{color};font-size:12px;font-weight:600;'>"
            f"{arrow} {abs(pp):.2f}pp</span>")


def render(settings: Settings) -> None:
    st.header("Availability Scorecard")
    st.caption(f"API availability per Operating Company · SLA target: {SLA_TARGET}%")

    with st.spinner("Loading — querying 30 days of traffic data..."):
        df = queries.get_availability_scorecard(settings, days=30)

    if df.empty:
        st.info("No availability data found. Check that the Apigee fetch pipeline is running.")
        return

    # ── Headline metrics ──────────────────────────────────────────────────────
    total_calls     = int(df["total_calls"].sum())
    total_errors    = int(df["error_calls"].sum())
    platform_avail  = (1 - total_errors / total_calls) * 100 if total_calls else 0
    below_sla       = df[~df["sla_met"]]
    above_sla       = df[df["sla_met"]]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Platform Availability", f"{platform_avail:.2f}%",
              delta="Above SLA" if platform_avail >= SLA_TARGET else "Below SLA",
              delta_color="normal" if platform_avail >= SLA_TARGET else "inverse")
    c2.metric("SLA Target",            f"{SLA_TARGET}%")
    c3.metric("OpCos Above SLA",       len(above_sla))
    c4.metric("OpCos Below SLA",       len(below_sla),
              delta=f"{len(below_sla)} need attention" if len(below_sla) else None,
              delta_color="inverse")

    st.divider()

    # ── Per-OpCo scorecard table ──────────────────────────────────────────────
    has_trend = df["trend_pp"].notna().any()

    rows_html = ""
    for _, row in df.sort_values("availability").iterrows():
        avail      = row["availability"]
        er         = row["error_rate_pct"]
        sla_ok     = row["sla_met"]
        sla_icon   = "✓" if sla_ok else "✗"
        sla_color  = "#16A34A" if sla_ok else "#DC2626"
        sla_label  = "Above SLA" if sla_ok else "Below SLA"
        trend_html = _trend_str(row["trend_pp"]) if has_trend else ""
        avail_color = "#22C55E" if sla_ok else "#DC2626"

        rows_html += f"""
        <tr style="border-bottom:1px solid #F1F5F9;">
            <td style="padding:12px 8px;font-weight:600;color:#1E293B;width:180px;">
                {row['name']}
            </td>
            <td style="padding:12px 8px;width:260px;">
                {_bar(avail)}
            </td>
            <td style="padding:12px 8px;font-size:15px;font-weight:700;
                       color:{avail_color};width:80px;text-align:right;">
                {avail:.2f}%
            </td>
            <td style="padding:12px 8px;width:100px;text-align:center;">
                {trend_html}
            </td>
            <td style="padding:12px 8px;width:40px;text-align:center;
                       font-size:15px;color:{sla_color};font-weight:700;"
                title="{sla_label}">
                {sla_icon}
            </td>
            <td style="padding:12px 8px;color:#64748B;font-size:12px;width:120px;text-align:right;">
                {er:.2f}% errors
            </td>
            <td style="padding:12px 8px;color:#94A3B8;font-size:12px;width:120px;text-align:right;">
                {row['total_calls']:,} calls
            </td>
        </tr>"""

    trend_header = "<th style='padding:10px 8px;text-align:center;'>Trend</th>" if has_trend else ""

    st.html(f"""
<table style="width:100%;border-collapse:collapse;background:#FFFFFF;
              border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
    <thead>
        <tr style="background:#F8FAFC;border-bottom:2px solid #E2E8F0;">
            <th style="padding:10px 8px;text-align:left;font-size:11px;letter-spacing:0.07em;
                       text-transform:uppercase;color:#64748B;">Country</th>
            <th style="padding:10px 8px;text-align:left;font-size:11px;letter-spacing:0.07em;
                       text-transform:uppercase;color:#64748B;">Availability</th>
            <th style="padding:10px 8px;text-align:right;font-size:11px;letter-spacing:0.07em;
                       text-transform:uppercase;color:#64748B;">%</th>
            {trend_header}
            <th style="padding:10px 8px;text-align:center;font-size:11px;letter-spacing:0.07em;
                       text-transform:uppercase;color:#64748B;">SLA</th>
            <th style="padding:10px 8px;text-align:right;font-size:11px;letter-spacing:0.07em;
                       text-transform:uppercase;color:#64748B;">Error Rate</th>
            <th style="padding:10px 8px;text-align:right;font-size:11px;letter-spacing:0.07em;
                       text-transform:uppercase;color:#64748B;">Volume</th>
        </tr>
    </thead>
    <tbody>
        {rows_html}
    </tbody>
</table>
<p style="margin-top:8px;font-size:11px;color:#94A3B8;">
    SLA target: {SLA_TARGET}% &nbsp;·&nbsp;
    Grey marker on bar indicates SLA threshold &nbsp;·&nbsp;
    {'Trend vs previous 30-day period' if has_trend else 'Trend unavailable — insufficient history for prior period comparison'}
</p>
""")
