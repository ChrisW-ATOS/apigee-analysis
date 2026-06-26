"""Blast Radius view — affected apps and countries per incident window."""
from __future__ import annotations

import plotly.express as px
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries


def render(settings: Settings) -> None:
    st.header("Blast Radius")
    st.caption("Which developer apps and countries are affected by active incidents")

    # ── Filters ───────────────────────────────────────────────────────────────
    c1, c2 = st.columns([1, 2])
    with c1:
        hours_back = st.selectbox(
            "Incident window",
            [2, 4, 6, 12, 24],
            index=1,
            format_func=lambda x: f"Last {x}h",
        )

    with st.spinner("Loading..."):
        df = queries.get_blast_radius(settings, hours_back=hours_back)

    if df.empty:
        st.info(f"No blast radius data in the last {hours_back} hours.")
        return

    proxy_options = sorted(df["proxy"].unique())
    with c2:
        selected_proxy = st.selectbox("Filter by proxy", ["(all anomalous proxies)"] + proxy_options)

    if selected_proxy != "(all anomalous proxies)":
        df = df[df["proxy"] == selected_proxy]

    # ── Headline metrics ──────────────────────────────────────────────────────
    total_calls    = int(df["call_count"].sum())
    unique_apps    = df["app"].nunique()
    unique_proxies = df["proxy"].nunique()
    unique_countries = df["country"].nunique()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Anomalous Proxies",   unique_proxies)
    c2.metric("Affected Apps",       unique_apps)
    c3.metric("Affected Countries",  unique_countries)
    c4.metric("Total Calls at Risk", f"{total_calls:,}")

    st.divider()

    # ── Charts ────────────────────────────────────────────────────────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Top Affected Applications")
        by_app = (
            df.groupby("app")["call_count"]
            .sum()
            .sort_values(ascending=False)
            .head(15)
            .reset_index()
        )
        by_app.columns = ["Application", "Calls"]

        fig = px.bar(
            by_app,
            x="Calls",
            y="Application",
            orientation="h",
            color="Calls",
            color_continuous_scale=["#DBEAFE", "#1D4ED8"],
        )
        fig.update_layout(
            showlegend=False,
            coloraxis_showscale=False,
            yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
            xaxis=dict(title="API Calls"),
            margin=dict(l=0, r=0, t=0, b=0),
            height=420,
            plot_bgcolor="#FAFAFA",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("Geographic Spread")
        by_country = (
            df.groupby("country")["call_count"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
        )
        by_country.columns = ["Country", "Calls"]

        fig = px.choropleth(
            by_country,
            locations="Country",
            locationmode="ISO-3",
            color="Calls",
            scope="africa",
            color_continuous_scale=["#FEF9C3", "#B45309"],
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=0, b=0),
            height=420,
            geo=dict(
                bgcolor="rgba(0,0,0,0)",
                showframe=False,
                showcoastlines=True,
                coastlinecolor="#CBD5E1",
                showland=True,
                landcolor="#F8FAFC",
                showcountries=True,
                countrycolor="#E2E8F0",
            ),
            coloraxis_colorbar=dict(title="Calls", len=0.6),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Detail table ──────────────────────────────────────────────────────────
    st.subheader("Full Detail")
    detail = (
        df.groupby(["proxy", "app", "country"])["call_count"]
        .sum()
        .sort_values(ascending=False)
        .reset_index()
    )
    detail.columns = ["Proxy", "Application", "Country", "Calls"]
    detail["Calls"] = detail["Calls"].apply(lambda x: f"{int(x):,}")
    st.dataframe(detail, use_container_width=True, hide_index=True)
