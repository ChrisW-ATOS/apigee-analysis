"""Country Health view — Africa choropleth + OpCo summary panel."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries

_COUNTRY_NAMES: dict[str, str] = {
    "GHA": "Ghana",     "NGA": "Nigeria",        "ZAF": "South Africa",
    "UGA": "Uganda",    "CMR": "Cameroon",        "ZMB": "Zambia",
    "CIV": "Côte d'Ivoire", "BEN": "Benin",       "LBR": "Liberia",
    "RWA": "Rwanda",    "SWZ": "Eswatini",        "GIN": "Guinea",
    "SDN": "Sudan",     "MOZ": "Mozambique",      "COD": "DR Congo",
}

# Use absolute error rate thresholds — z_score only detects deviation from a
# country's own baseline, so a historically-bad country always looks "normal".
_DEGRADED_THRESHOLD = 10.0
_WATCH_THRESHOLD    =  3.0


def _status(error_rate_pct: float) -> tuple[str, str]:
    """(icon, label) based on absolute error rate."""
    if error_rate_pct > _DEGRADED_THRESHOLD:
        return "🔴", "Degraded"
    if error_rate_pct > _WATCH_THRESHOLD:
        return "🟡", "Watch"
    return "🟢", "Healthy"


def render(settings: Settings) -> None:
    st.header("Country Health")
    st.caption(
        "API error rate per Operating Company — coloured by absolute error rate. "
        "A country historically at high error rates is still degraded."
    )

    with st.spinner("Loading..."):
        df = queries.get_country_health(settings)

    if df.empty:
        st.info("No country health data available.")
        return

    df["name"] = df["country"].map(_COUNTRY_NAMES).fillna(df["country"])

    col_map, col_list = st.columns([3, 1])

    with col_map:
        # Colour by absolute error rate — not z_score.
        # Max of the scale set to 35% so CIV at 30% shows clearly red.
        max_rate = max(df["error_rate_pct"].max() * 1.1, 15.0)
        fig = px.choropleth(
            df,
            locations="country",
            locationmode="ISO-3",
            color="error_rate_pct",
            scope="africa",
            color_continuous_scale=[
                [0.0,  "#16A34A"],
                [_WATCH_THRESHOLD / max_rate, "#86EFAC"],
                [_DEGRADED_THRESHOLD / max_rate, "#FCA5A5"],
                [1.0,  "#B91C1C"],
            ],
            range_color=[0, max_rate],
            hover_name="name",
            hover_data={
                "country":        False,
                "error_rate_pct": ":.1f",
                "total_calls":    ":,",
                "z_score":        ":.2f",
            },
            labels={
                "error_rate_pct": "Error Rate %",
                "total_calls":    "Total Requests",
                "z_score":        "vs Baseline (σ)",
            },
        )
        fig.update_layout(
            margin=dict(r=0, t=0, l=0, b=0),
            height=520,
            geo=dict(
                bgcolor="rgba(0,0,0,0)",
                showframe=False,
                showcoastlines=True,  coastlinecolor="#CBD5E1",
                showland=True,        landcolor="#F8FAFC",
                showocean=True,       oceancolor="#EFF6FF",
                showcountries=True,   countrycolor="#E2E8F0",
            ),
            coloraxis_colorbar=dict(
                title="Error Rate %",
                tickvals=[0, _WATCH_THRESHOLD, _DEGRADED_THRESHOLD,
                          round(max_rate / 2), round(max_rate)],
                ticktext=["0%", f"{_WATCH_THRESHOLD:.0f}% Watch",
                          f"{_DEGRADED_THRESHOLD:.0f}% Degraded",
                          f"{max_rate/2:.0f}%", f"{max_rate:.0f}%"],
                len=0.7,
            ),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_list:
        st.subheader("OpCo Status")
        ranked = df.sort_values("error_rate_pct", ascending=False)
        for _, row in ranked.iterrows():
            er   = row["error_rate_pct"]
            name = row["name"]
            icon, status_label = _status(er)
            st.markdown(f"{icon} **{name}**")
            st.caption(f"{status_label} · Error rate: `{er:.1f}%`")
            st.write("")

    st.divider()
    # Use absolute error rate for "degraded" count
    degraded  = df[df["error_rate_pct"] > _DEGRADED_THRESHOLD]
    watch     = df[(df["error_rate_pct"] > _WATCH_THRESHOLD) &
                   (df["error_rate_pct"] <= _DEGRADED_THRESHOLD)]
    worst     = df.loc[df["error_rate_pct"].idxmax()]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Countries Monitored", len(df))
    c2.metric("Degraded (>10%)",     len(degraded),
              delta=f"{len(degraded)} need attention" if len(degraded) else None,
              delta_color="inverse")
    c3.metric("Highest Error Rate",
              f"{worst['error_rate_pct']:.1f}%",
              delta=worst["name"])
    c4.metric("Platform Error Rate",
              f"{df['error_rate_pct'].mean():.1f}%")
