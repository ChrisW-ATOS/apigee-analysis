"""Anomaly Explorer view — time-series Z-score chart with proxy/range filters."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries


def render(settings: Settings) -> None:
    st.header("Anomaly Explorer")
    st.caption("Z-score over time per proxy — red markers indicate anomaly threshold breaches")

    # ── Filters ──────────────────────────────────────────────────────────────
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        hours = st.selectbox(
            "Time range",
            [6, 12, 24, 48],
            index=2,
            format_func=lambda x: f"Last {x}h",
        )
    with c2:
        measure = st.selectbox(
            "Measurement",
            ["traffic_anomaly", "error_rate_anomaly"],
            format_func=lambda x: x.replace("_", " ").title(),
        )
    with c3:
        with st.spinner("Loading proxies..."):
            proxy_list = queries.get_proxy_list(settings)
        proxy_filter = st.selectbox("Filter by proxy", ["(all proxies)"] + proxy_list)

    proxy = None if proxy_filter == "(all proxies)" else proxy_filter

    with st.spinner("Loading data..."):
        df = queries.get_anomaly_trend(settings, hours=hours, measurement=measure, proxy=proxy)

    if df.empty:
        st.info("No data for the selected filters.")
        return

    # Limit to top 15 proxies by max |Z| to keep the chart readable
    if proxy is None:
        top_proxies = (
            df.groupby("proxy")["z_score"]
            .apply(lambda s: s.abs().max())
            .nlargest(15)
            .index.tolist()
        )
        df = df[df["proxy"].isin(top_proxies)]

    # ── Chart ─────────────────────────────────────────────────────────────────
    fig = go.Figure()

    colour_cycle = [
        "#2563EB", "#DC2626", "#16A34A", "#D97706", "#9333EA",
        "#0891B2", "#BE185D", "#059669", "#B45309", "#1D4ED8",
        "#7C3AED", "#047857", "#B91C1C", "#0369A1", "#6D28D9",
    ]

    for i, (proxy_name, grp) in enumerate(df.groupby("proxy")):
        grp   = grp.sort_values("time")
        color = colour_cycle[i % len(colour_cycle)]

        # Main line
        fig.add_trace(go.Scatter(
            x=grp["time"],
            y=grp["z_score"],
            mode="lines",
            name=proxy_name,
            line=dict(width=1.5, color=color),
            hovertemplate=(
                f"<b>{proxy_name}</b><br>"
                "Time: %{x}<br>"
                "Z-Score: %{y:.2f}<extra></extra>"
            ),
        ))

        # Anomaly markers
        bad = grp[grp["is_anomaly"]]
        if not bad.empty:
            fig.add_trace(go.Scatter(
                x=bad["time"],
                y=bad["z_score"],
                mode="markers",
                marker=dict(color="red", size=9, symbol="circle",
                            line=dict(color="white", width=1.5)),
                name=f"{proxy_name} ⚠",
                showlegend=False,
                hovertemplate=(
                    f"<b>ANOMALY — {proxy_name}</b><br>"
                    "Time: %{x}<br>"
                    "Z-Score: %{y:.2f}<extra></extra>"
                ),
            ))

    # Threshold bands
    fig.add_hline(y=3.0,  line_dash="dash", line_color="red",  line_width=1,
                  annotation_text="±3σ anomaly threshold", annotation_position="top right")
    fig.add_hline(y=-3.0, line_dash="dash", line_color="red",  line_width=1)
    fig.add_hrect(y0=-3.0, y1=3.0, fillcolor="#16A34A", opacity=0.04, line_width=0)

    measure_label = measure.replace("_", " ").title()
    fig.update_layout(
        title=dict(text=f"{measure_label} · Last {hours}h", font=dict(size=14)),
        xaxis_title="Time",
        yaxis_title="Z-Score (σ)",
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=10),
        ),
        height=460,
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(gridcolor="#E2E8F0"),
        yaxis=dict(gridcolor="#E2E8F0", zeroline=True, zerolinecolor="#CBD5E1"),
        margin=dict(l=0, r=0, t=40, b=0),
    )

    st.plotly_chart(fig, use_container_width=True)

    # ── Anomalous points table ────────────────────────────────────────────────
    st.subheader("Anomalous Points in Window")
    bad_df = df[df["is_anomaly"]].sort_values("z_score", key=lambda s: s.abs(), ascending=False)

    if bad_df.empty:
        st.success("No anomalies detected in this time range.")
    else:
        st.caption(f"{len(bad_df)} anomalous data points across {bad_df['proxy'].nunique()} proxies")
        display = bad_df[["time", "proxy", "z_score", "sustained"]].copy()
        display["time"]      = display["time"].dt.strftime("%Y-%m-%d %H:%M UTC")
        display["z_score"]   = display["z_score"].apply(lambda x: f"{x:+.2f}")
        display["sustained"] = display["sustained"].apply(lambda x: "Yes" if x else "No")
        display.columns      = ["Time", "Proxy", "Z-Score", "Sustained"]
        st.dataframe(display, use_container_width=True, hide_index=True)
