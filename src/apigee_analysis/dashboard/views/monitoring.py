"""Platform Monitoring — historical trends, reliability scores, and partner insights."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy

_COUNTRY_NAMES = {
    "GHA": "Ghana",        "NGA": "Nigeria",       "ZAF": "South Africa",
    "UGA": "Uganda",       "CMR": "Cameroon",       "ZMB": "Zambia",
    "CIV": "Côte d'Ivoire","BEN": "Benin",          "LBR": "Liberia",
    "RWA": "Rwanda",       "SWZ": "Eswatini",       "GIN": "Guinea",
    "SDN": "Sudan",        "MOZ": "Mozambique",     "COD": "DR Congo",
}
SLA_TARGET = 99.5


# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 — SLA Trajectory
# ─────────────────────────────────────────────────────────────────────────────

def _sla_trajectory(settings: Settings) -> None:
    st.subheader("SLA Trajectory — Daily Availability per OpCo")
    st.caption("Showing last 30 days · Grey dashed line = 99.5% SLA target")

    with st.spinner("Querying 30 days of traffic data..."):
        df = queries.get_sla_trajectory(settings, days=30)

    if df.empty:
        st.info("No data available.")
        return

    df["name"] = df["country"].map(_COUNTRY_NAMES).fillna(df["country"])

    fig = px.line(
        df, x="date", y="availability_pct", color="name",
        labels={"date": "Date", "availability_pct": "Availability (%)", "name": "Country"},
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.add_hline(y=SLA_TARGET, line_dash="dash", line_color="#94A3B8",
                  annotation_text=f"SLA {SLA_TARGET}%", annotation_font_size=11)
    fig.update_layout(
        height=440, hovermode="x unified",
        yaxis=dict(range=[max(0, df["availability_pct"].min() - 2), 100.5],
                   ticksuffix="%", gridcolor="#E2E8F0"),
        xaxis=dict(gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=40, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Summary table — current vs previous period
    latest   = df[df["date"] == df["date"].max()]
    previous = df[df["date"] <= df["date"].max() - timedelta(days=7)]
    prev_avg = previous.groupby("country")["availability_pct"].mean()

    rows = []
    for _, row in latest.sort_values("availability_pct").iterrows():
        prev = prev_avg.get(row["country"], float("nan"))
        trend = row["availability_pct"] - prev if not np.isnan(prev) else float("nan")
        rows.append({
            "Country":        row["name"],
            "Today":          f"{row['availability_pct']:.2f}%",
            "7-day avg":      f"{prev:.2f}%" if not np.isnan(prev) else "—",
            "Trend":          (f"▲ +{trend:.2f}pp" if trend > 0.01
                               else f"▼ {trend:.2f}pp" if trend < -0.01
                               else "→ Stable"),
            "vs SLA":         "✓" if row["availability_pct"] >= SLA_TARGET else "✗",
        })

    summary = pd.DataFrame(rows)
    st.dataframe(summary, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 — Reliability Scores
# ─────────────────────────────────────────────────────────────────────────────

def _reliability_scores(settings: Settings) -> None:
    st.subheader("Platform Reliability Score by OpCo")
    st.caption(
        "Composite 0–100 score · Availability 60% · Incident frequency 20% · "
        "SLA headroom 20% · Based on last 30 days"
    )

    with st.spinner("Computing scores..."):
        avail_df    = queries.get_availability_scorecard(settings, days=30)
        incident_df = queries.get_chronic_proxies(settings, days=30)

    if avail_df.empty:
        st.info("No availability data.")
        return

    # Incidents per country — match proxy names against known country name fragments.
    # edgemicro proxies embed the full country name (e.g. "nigeria", "ghana", "rwanda").
    _NAME_TO_CODE = {name.lower(): code for code, name in _COUNTRY_NAMES.items()}
    # Also add common abbreviations found in proxy names
    _EXTRA = {"za": "ZAF", "civ": "CIV", "ssd": "SSD", "cog": "COG", "gnb": "GNB"}

    incident_by_country: dict[str, int] = {}
    if not incident_df.empty:
        for _, row in incident_df.iterrows():
            proxy = row.get("proxy", "").lower()
            matched = None
            for fragment, code in _NAME_TO_CODE.items():
                if fragment in proxy:
                    matched = code
                    break
            if not matched:
                for frag, code in _EXTRA.items():
                    if f"_{frag}_" in proxy:
                        matched = code
                        break
            if matched:
                incident_by_country[matched] = (
                    incident_by_country.get(matched, 0) + int(row.get("incident_hours", 1))
                )

    max_incidents = max(incident_by_country.values(), default=1)
    scores = []

    for _, row in avail_df.iterrows():
        # availability is already a percentage (0–100), NOT a fraction.
        avail_pct   = float(row["availability"])
        avail_score = min(100.0, avail_pct)                           # direct — no ×100
        inc_count   = incident_by_country.get(row["country"], 0)
        inc_score   = max(0.0, 100 - (inc_count / max(max_incidents, 1)) * 100)
        # headroom: how far above SLA are we? 100 = right at 100%, 0 = at or below SLA
        headroom    = max(0.0, (avail_pct - SLA_TARGET) / (100 - SLA_TARGET) * 100)

        composite   = avail_score * 0.6 + inc_score * 0.2 + headroom * 0.2
        composite   = round(min(100, max(0, composite)), 1)

        scores.append({
            "country":   row["country"],
            "name":      row["name"],
            "score":     composite,
            "avail_pct": avail_pct,   # already a percentage
            "incidents": inc_count,
        })

    score_df = pd.DataFrame(scores).sort_values("score", ascending=False)

    # Horizontal bar chart
    colors = ["#22C55E" if s >= 90 else "#F59E0B" if s >= 75 else "#EF4444"
              for s in score_df["score"]]

    fig = go.Figure(go.Bar(
        x=score_df["score"], y=score_df["name"],
        orientation="h",
        marker_color=colors,
        text=[f"{s:.0f}" for s in score_df["score"]],
        textposition="inside",
        textfont=dict(color="white", size=13, family="monospace"),
        hovertemplate="<b>%{y}</b><br>Score: %{x:.1f}<extra></extra>",
    ))
    fig.add_vline(x=90, line_dash="dash", line_color="#22C55E", line_width=1,
                  annotation_text="Good", annotation_font_size=10)
    fig.add_vline(x=75, line_dash="dash", line_color="#F59E0B", line_width=1,
                  annotation_text="Fair", annotation_font_size=10)
    fig.update_layout(
        height=420, xaxis=dict(range=[0, 105], title="Reliability Score"),
        yaxis=dict(title=""), plot_bgcolor="#FAFAFA",
        paper_bgcolor="rgba(0,0,0,0)", margin=dict(l=0, r=0, t=10, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 4 — Partner Experience
# ─────────────────────────────────────────────────────────────────────────────

def _partner_experience(settings: Settings) -> None:
    st.subheader("Partner Application Experience — Last 30 Days")
    st.caption("Error rate experienced by each developer application across all APIs. Sorted worst-first.")

    with st.spinner("Querying partner traffic data..."):
        df = queries.get_partner_experience(settings, days=30, top_n=25)

    if df.empty:
        st.info("No partner data available.")
        return

    c_left, c_right = st.columns(2)

    with c_left:
        st.markdown("**Worst partner experience (highest error rate)**")
        worst = df.sort_values("error_rate_pct", ascending=False).head(15)
        fig = px.bar(
            worst, x="error_rate_pct", y="app",
            orientation="h",
            color="error_rate_pct",
            color_continuous_scale=["#FEF9C3", "#DC2626"],
            labels={"error_rate_pct": "Error Rate %", "app": "Application"},
            text=worst["error_rate_pct"].apply(lambda x: f"{x:.1f}%"),
        )
        fig.update_layout(
            height=440, coloraxis_showscale=False,
            yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
            plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    with c_right:
        st.markdown("**Highest volume partners with elevated errors**")
        # Scatter: volume vs error rate — ideal quadrant is low-right (high volume, low errors)
        elevated = df[df["error_rate_pct"] > 1].copy()
        if elevated.empty:
            st.success("All high-volume partners showing < 1% error rate.")
        else:
            fig = px.scatter(
                elevated,
                x="total_calls", y="error_rate_pct",
                size="total_calls", color="error_rate_pct",
                hover_name="app",
                color_continuous_scale=["#86EFAC", "#DC2626"],
                labels={"total_calls": "Total API Calls (30d)",
                        "error_rate_pct": "Error Rate %", "app": "App"},
                size_max=40,
            )
            fig.update_layout(
                height=440, coloraxis_showscale=False,
                plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=0, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)

    # Full table
    st.markdown("**Full partner table**")
    display = df.copy()
    display["error_rate_pct"] = display["error_rate_pct"].apply(lambda x: f"{x:.2f}%")
    display["total_calls"]    = display["total_calls"].apply(lambda x: f"{int(x):,}")
    display["error_calls"]    = display["error_calls"].apply(lambda x: f"{int(x):,}")
    display.columns           = ["Application", "Total Calls", "Failed Calls", "Error Rate"]
    st.dataframe(display, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Tab 5 — Traffic Forecast
# ─────────────────────────────────────────────────────────────────────────────

def _traffic_forecast(settings: Settings) -> None:
    st.subheader("API Traffic Trends & 14-Day Forecast")
    st.caption("Historical daily call volumes per OpCo with a linear growth projection.")

    with st.spinner("Loading traffic data..."):
        df = queries.get_traffic_trend(settings, days=30)

    if df.empty:
        st.info("No traffic data available.")
        return

    df["name"] = df["country"].map(_COUNTRY_NAMES).fillna(df["country"])

    fig = go.Figure()
    colours = px.colors.qualitative.Set2
    forecast_days = 14

    for i, (country, grp) in enumerate(df.groupby("country")):
        grp  = grp.sort_values("date").reset_index(drop=True)
        name = _COUNTRY_NAMES.get(country, country)
        col  = colours[i % len(colours)]

        # Historical
        fig.add_trace(go.Scatter(
            x=grp["date"], y=grp["total_calls"],
            mode="lines", name=name,
            line=dict(color=col, width=2),
            hovertemplate=f"<b>{name}</b><br>%{{x}}<br>%{{y:,}} calls<extra></extra>",
        ))

        # Linear forecast
        if len(grp) >= 5:
            x_num = np.arange(len(grp))
            slope, intercept = np.polyfit(x_num, grp["total_calls"].values, 1)
            proj_dates = [grp["date"].iloc[-1] + timedelta(days=d) for d in range(1, forecast_days + 1)]
            proj_vals  = [max(0, slope * (len(grp) + d - 1) + intercept) for d in range(1, forecast_days + 1)]

            fig.add_trace(go.Scatter(
                x=[grp["date"].iloc[-1]] + proj_dates,
                y=[grp["total_calls"].iloc[-1]] + proj_vals,
                mode="lines", line=dict(color=col, width=1.5, dash="dot"),
                showlegend=False,
                hovertemplate=f"<b>{name} (forecast)</b><br>%{{x}}<br>%{{y:,.0f}} calls<extra></extra>",
            ))

    fig.add_vline(x=str(df["date"].max()), line_dash="dash",
                  line_color="#CBD5E1", line_width=1,
                  annotation_text="Today", annotation_font_size=10)
    fig.update_layout(
        height=460, hovermode="x unified",
        xaxis=dict(title="Date", gridcolor="#E2E8F0"),
        yaxis=dict(title="Daily API Calls", gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=40, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Top growing vs declining OpCos
    growth = []
    for country, grp in df.groupby("country"):
        grp = grp.sort_values("date")
        if len(grp) >= 7:
            recent  = grp.tail(7)["total_calls"].mean()
            earlier = grp.head(7)["total_calls"].mean()
            pct     = ((recent - earlier) / earlier * 100) if earlier > 0 else 0
            growth.append({"Country": _COUNTRY_NAMES.get(country, country),
                            "Growth": pct, "Avg Daily Calls (recent)": int(recent)})

    if growth:
        g_df = pd.DataFrame(growth).sort_values("Growth", ascending=False)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Fastest growing (first 7d vs last 7d)**")
            top = g_df.head(5)
            for _, r in top.iterrows():
                st.markdown(f"▲ **{r['Country']}** +{r['Growth']:.1f}% · {r['Avg Daily Calls (recent)']:,} calls/day")
        with c2:
            st.markdown("**Declining traffic**")
            bot = g_df[g_df["Growth"] < 0].tail(5)
            if bot.empty:
                st.success("All OpCos showing positive or flat traffic growth.")
            else:
                for _, r in bot.iterrows():
                    st.markdown(f"▼ **{r['Country']}** {r['Growth']:.1f}% · {r['Avg Daily Calls (recent)']:,} calls/day")


