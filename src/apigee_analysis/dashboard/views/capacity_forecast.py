"""Capacity & Cost Forecasting — infrastructure spend projection tied to traffic growth.

Traffic data is REAL (from get_traffic_trend, same source as OpCo Analytics).
Cost figures, capacity ceilings, and scaling recommendations are illustrative —
no live billing or infrastructure-capacity API is connected yet.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries

_NAVY  = "#1B2A4A"
_RED   = "#EF4444"
_AMBER = "#F59E0B"
_GREEN = "#22C55E"
_BLUE  = "#3B82F6"
_MUTED = "#64748B"

_COUNTRY_NAMES = {
    "GHA": "Ghana",        "NGA": "Nigeria",       "ZAF": "South Africa",
    "UGA": "Uganda",       "CMR": "Cameroon",       "ZMB": "Zambia",
    "CIV": "Côte d'Ivoire","BEN": "Benin",          "LBR": "Liberia",
    "RWA": "Rwanda",       "SWZ": "Eswatini",       "GIN": "Guinea",
    "SDN": "Sudan",        "MOZ": "Mozambique",     "COD": "DR Congo",
}

# Illustrative cost model: $ per million API calls, and per-OpCo capacity ceiling
_COST_PER_MILLION_CALLS = 4.20
_CAPACITY_CEILING_DAILY = {   # calls/day before scaling is required — mock
    "NGA": 12_000_000, "GHA": 3_500_000, "ZAF": 2_000_000, "UGA": 1_800_000,
    "CIV": 1_200_000, "CMR": 1_000_000, "ZMB": 700_000, "RWA": 500_000,
    "BEN": 400_000, "SWZ": 300_000, "GIN": 250_000, "SDN": 200_000,
    "MOZ": 200_000, "COD": 150_000,
}


def _mock_banner() -> None:
    st.html("""
<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;
            padding:10px 16px;margin-bottom:20px;">
    <span style="font-size:12px;color:#92400E;">
        <b>Traffic volumes below are real</b> (same InfluxDB source as OpCo Analytics).
        Cost-per-call, capacity ceilings, and dollar figures are illustrative — no live
        billing or infrastructure-capacity API is connected yet.
    </span>
</div>
""")


def _kpi_row(df: pd.DataFrame) -> tuple[float, float]:
    if df.empty:
        st.info("No traffic data available.")
        return 0.0, 0.0

    total_calls_30d = df["total_calls"].sum()
    monthly_cost    = total_calls_30d / 1_000_000 * _COST_PER_MILLION_CALLS

    recent  = df.groupby("date")["total_calls"].sum().sort_index()
    if len(recent) >= 14:
        first_half  = recent.iloc[:7].mean()
        second_half = recent.iloc[-7:].mean()
        growth_pct  = ((second_half - first_half) / first_half * 100) if first_half > 0 else 0
    else:
        growth_pct = 0.0

    projected_cost = monthly_cost * (1 + growth_pct / 100)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current Monthly Spend (est.)", f"${monthly_cost:,.0f}")
    c2.metric("Projected Next Month",         f"${projected_cost:,.0f}", delta=f"{growth_pct:+.1f}% traffic growth")
    c3.metric("Cost per Million Calls",       f"${_COST_PER_MILLION_CALLS:.2f}")
    c4.metric("Total Calls (30d)",            f"{total_calls_30d/1e6:.1f}M")

    return monthly_cost, growth_pct


def _cost_trend_chart(df: pd.DataFrame, growth_pct: float) -> None:
    st.subheader("Daily Spend Trend & 14-Day Forecast")

    daily = df.groupby("date")["total_calls"].sum().sort_index().reset_index()
    daily["cost"] = daily["total_calls"] / 1_000_000 * _COST_PER_MILLION_CALLS

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily["date"], y=daily["cost"], mode="lines", name="Daily spend (actual)",
        line=dict(color=_BLUE, width=2), fill="tozeroy", fillcolor="rgba(59,130,246,0.08)",
    ))

    if len(daily) >= 5:
        x_num = np.arange(len(daily))
        slope, intercept = np.polyfit(x_num, daily["cost"].values, 1)
        forecast_days = 14
        proj_dates = [daily["date"].iloc[-1] + timedelta(days=d) for d in range(1, forecast_days + 1)]
        proj_vals  = [max(0, slope * (len(daily) + d - 1) + intercept) for d in range(1, forecast_days + 1)]
        fig.add_trace(go.Scatter(
            x=[daily["date"].iloc[-1]] + proj_dates,
            y=[daily["cost"].iloc[-1]] + proj_vals,
            mode="lines", name="Forecast", line=dict(color=_AMBER, width=2, dash="dot"),
        ))

    fig.update_layout(
        height=320, plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=10, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        yaxis=dict(title="Estimated daily spend ($)"),
        xaxis=dict(title="Date"),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Traffic volumes are real; the $ figure applies an illustrative "
               f"${_COST_PER_MILLION_CALLS:.2f}/million-calls rate. Forecast uses simple linear extrapolation.")


def _capacity_table(df: pd.DataFrame) -> None:
    st.subheader("Capacity Headroom by OpCo")
    st.caption("Illustrative capacity ceilings — flags which OpCos are approaching a scaling decision point.")

    if df.empty:
        st.info("No traffic data available.")
        return

    latest_by_country = (
        df.sort_values("date")
        .groupby("country")
        .tail(7)
        .groupby("country")["total_calls"]
        .mean()
        .reset_index()
    )

    rows = []
    for _, row in latest_by_country.iterrows():
        code    = row["country"]
        avg_day = row["total_calls"]
        ceiling = _CAPACITY_CEILING_DAILY.get(code, 500_000)
        headroom_pct = max(0, (1 - avg_day / ceiling) * 100)

        if headroom_pct < 15:
            days_to_limit = "< 30 days"
            action = "🔴 Scale now"
        elif headroom_pct < 35:
            days_to_limit = "~60–90 days"
            action = "🟡 Plan scaling"
        else:
            days_to_limit = "> 120 days"
            action = "🟢 Healthy"

        rows.append({
            "OpCo": _COUNTRY_NAMES.get(code, code),
            "Avg Daily Calls": f"{avg_day:,.0f}",
            "Capacity Ceiling": f"{ceiling:,.0f}",
            "Headroom": f"{headroom_pct:.0f}%",
            "Est. Time to Limit": days_to_limit,
            "Recommendation": action,
        })

    result = pd.DataFrame(rows).sort_values(
        "Headroom", key=lambda s: s.str.rstrip("%").astype(float)
    )
    st.dataframe(result, use_container_width=True, hide_index=True)


def _cost_by_opco(df: pd.DataFrame) -> None:
    st.subheader("Cost Distribution by OpCo (30 days)")
    if df.empty:
        return
    by_country = df.groupby("country")["total_calls"].sum().reset_index()
    by_country["name"] = by_country["country"].map(_COUNTRY_NAMES).fillna(by_country["country"])
    by_country["cost"] = by_country["total_calls"] / 1_000_000 * _COST_PER_MILLION_CALLS

    fig = px.pie(
        by_country, values="cost", names="name", hole=0.45,
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(
        height=380, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


def render(settings: Settings) -> None:
    st.html(f"""
<div style="background:{_NAVY};border-radius:12px;padding:20px 28px;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-bottom:6px;">
        Capacity &amp; Cost Forecasting
    </div>
    <div style="font-size:13px;color:#94A3B8;line-height:1.6;">
        Infrastructure spend projected from real traffic growth — flagging which
        Operating Companies are approaching a scaling decision before they hit it.
    </div>
</div>
""")

    _mock_banner()

    with st.spinner("Loading traffic data..."):
        df = queries.get_traffic_trend(settings, days=30)

    monthly_cost, growth_pct = _kpi_row(df)
    st.divider()
    _cost_trend_chart(df, growth_pct)
    st.divider()

    col_l, col_r = st.columns([3, 2])
    with col_l:
        _capacity_table(df)
    with col_r:
        _cost_by_opco(df)
