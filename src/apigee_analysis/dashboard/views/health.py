"""Country Health view — Africa choropleth + OpCo summary panel."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries

# Full names for hover labels
_COUNTRY_NAMES: dict[str, str] = {
    "GHA": "Ghana",     "NGA": "Nigeria",        "ZAF": "South Africa",
    "UGA": "Uganda",    "CMR": "Cameroon",        "ZMB": "Zambia",
    "CIV": "Côte d'Ivoire", "BEN": "Benin",       "LBR": "Liberia",
    "RWA": "Rwanda",    "SWZ": "Eswatini",        "GIN": "Guinea",
    "SDN": "Sudan",     "MOZ": "Mozambique",      "COD": "DR Congo",
}


def render(settings: Settings) -> None:
    st.header("Country Health")
    st.caption("Rolled-up API error rate per Operating Company — Z-score vs 7-day baseline")

    with st.spinner("Loading..."):
        df = queries.get_country_health(settings)

    if df.empty:
        st.info("No country health data in the last 4 hours.")
        return

    df["name"] = df["country"].map(_COUNTRY_NAMES).fillna(df["country"])

    col_map, col_list = st.columns([3, 1])

    with col_map:
        fig = px.choropleth(
            df,
            locations="country",
            locationmode="ISO-3",
            color="z_score",
            scope="africa",
            color_continuous_scale=[
                [0.0,  "#16A34A"],   # green  — healthy
                [0.375, "#86EFAC"],  # light green
                [0.5,  "#F9FAFB"],   # neutral
                [0.625, "#FCA5A5"],  # light red
                [1.0,  "#B91C1C"],   # red — degraded
            ],
            range_color=[-4, 4],
            color_continuous_midpoint=0,
            hover_name="name",
            hover_data={
                "country":        False,
                "z_score":        ":.2f",
                "error_rate_pct": ":.1f",
                "total_calls":    ":,",
            },
            labels={
                "z_score":        "Health Z-Score",
                "error_rate_pct": "Error Rate %",
                "total_calls":    "Total Calls",
            },
        )
        fig.update_layout(
            margin=dict(r=0, t=0, l=0, b=0),
            height=520,
            geo=dict(
                bgcolor="rgba(0,0,0,0)",
                showframe=False,
                showcoastlines=True,
                coastlinecolor="#CBD5E1",
                showland=True,
                landcolor="#F8FAFC",
                showocean=True,
                oceancolor="#EFF6FF",
                showcountries=True,
                countrycolor="#E2E8F0",
            ),
            coloraxis_colorbar=dict(
                title="Z-Score",
                tickvals=[-3, -1.5, 0, 1.5, 3],
                ticktext=["−3 Degraded", "−1.5", "Normal", "+1.5", "+3 Elevated"],
                len=0.7,
            ),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_list:
        st.subheader("OpCo Status")
        ranked = df.sort_values("z_score", key=lambda s: s.abs(), ascending=False)
        for _, row in ranked.iterrows():
            z          = row["z_score"]
            er         = row["error_rate_pct"]
            name       = row["name"]
            is_anomaly = row["is_anomaly"]

            if is_anomaly:
                icon = "🔴"
            elif abs(z) > 1.5:
                icon = "🟡"
            else:
                icon = "🟢"

            st.markdown(f"{icon} **{name}**")
            st.caption(f"Z `{z:+.2f}` · error `{er:.1f}%`")
            st.write("")   # spacing

    # Summary metrics
    st.divider()
    anomalous = df[df["is_anomaly"]]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("OpCos Monitored",  len(df))
    c2.metric("Anomalous OpCos",  len(anomalous),
              delta=f"{len(anomalous)} degraded" if len(anomalous) else None,
              delta_color="inverse")
    c3.metric("Worst Z-Score",
              f"{df['z_score'].abs().max():.2f}",
              delta=df.loc[df['z_score'].abs().idxmax(), 'name'])
    c4.metric("Avg Error Rate",
              f"{df['error_rate_pct'].mean():.1f}%")
