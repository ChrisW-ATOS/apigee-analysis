"""Failure Predictions — co-failure cascade risk based on historical patterns."""
from __future__ import annotations

from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy


def _co_failure_chart(
    settings: Settings,
    proxy_a: str, ec_a: str,
    proxy_b: str, ec_b: str,
    driver_name: str,
    risk_name: str,
) -> None:
    """Dual-panel chart: driver API (top) and at-risk API (bottom), shared time axis.

    Red fills when the driver is anomalous; amber when the at-risk API is anomalous.
    The temporal co-occurrence pattern is immediately visible.
    """
    df = queries.get_co_failure_history(settings, proxy_a, ec_a, proxy_b, ec_b, days=7)
    if df.empty:
        st.caption("No history data available for this pair.")
        return

    now = datetime.now(timezone.utc)

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=[
            f"Driver (currently failing): {driver_name[:50]} [{ec_a}]",
            f"At risk: {risk_name[:50]} [{ec_b}]",
        ],
    )

    # ── Top panel: driver proxy ───────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df["hour"], y=df["a_rate"] * 100,
        mode="lines",
        line=dict(color="#EF4444", width=1.5),
        fill="tozeroy",
        fillcolor="rgba(239,68,68,0.08)",
        name=driver_name[:30],
        hovertemplate="Driver<br>%{x}<br>Error rate: %{y:.1f}%<extra></extra>",
    ), row=1, col=1)

    # Anomaly markers on driver
    anom_a = df[df["a_anomalous"]]
    if not anom_a.empty:
        fig.add_trace(go.Scatter(
            x=anom_a["hour"], y=anom_a["a_rate"] * 100,
            mode="markers",
            marker=dict(color="#EF4444", size=8, symbol="circle",
                        line=dict(color="white", width=1.5)),
            showlegend=False,
            hovertemplate="⚠ Anomalous<br>%{x}<br>%{y:.1f}%<extra></extra>",
        ), row=1, col=1)

    # ── Bottom panel: at-risk proxy ───────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df["hour"], y=df["b_rate"] * 100,
        mode="lines",
        line=dict(color="#F59E0B", width=1.5),
        fill="tozeroy",
        fillcolor="rgba(245,158,11,0.08)",
        name=risk_name[:30],
        hovertemplate="At risk<br>%{x}<br>Error rate: %{y:.1f}%<extra></extra>",
    ), row=2, col=1)

    anom_b = df[df["b_anomalous"]]
    if not anom_b.empty:
        fig.add_trace(go.Scatter(
            x=anom_b["hour"], y=anom_b["b_rate"] * 100,
            mode="markers",
            marker=dict(color="#F59E0B", size=8, symbol="circle",
                        line=dict(color="white", width=1.5)),
            showlegend=False,
            hovertemplate="⚠ Anomalous<br>%{x}<br>%{y:.1f}%<extra></extra>",
        ), row=2, col=1)

    # "Now" line
    fig.add_vline(
        x=str(now), line_dash="dot", line_color="#94A3B8", line_width=1,
        annotation_text="Now", annotation_font_size=10,
        annotation_position="top left",
    )

    fig.update_layout(
        height=360,
        showlegend=False,
        hovermode="x unified",
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=40, b=0),
    )
    fig.update_yaxes(ticksuffix="%", gridcolor="#E2E8F0", range=[0, 105])
    fig.update_xaxes(gridcolor="#E2E8F0", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True)

    # Annotate co-failure occurrences visible in the chart
    if not anom_a.empty and not anom_b.empty:
        from datetime import timedelta
        co_count = 0
        for ta in anom_a["hour"]:
            for lag in range(1, 5):
                if (ta + timedelta(hours=lag)) in set(anom_b["hour"]):
                    co_count += 1
                    break
        if co_count:
            st.caption(
                f"↑ {co_count} co-failure instance{'s' if co_count != 1 else ''} "
                f"visible in this 7-day window — driver anomaly followed by at-risk "
                f"anomaly within 4 hours."
            )


def _risk_color(prob: float) -> str:
    if prob >= 0.75: return "#EF4444"
    if prob >= 0.55: return "#F59E0B"
    return "#64748B"


def _risk_label(prob: float) -> str:
    if prob >= 0.75: return "HIGH"
    if prob >= 0.55: return "MEDIUM"
    return "WATCH"


def _confidence_note(count_a: int, count_ab: int, history_days: int) -> str:
    return (
        f"Based on {count_ab} co-failures out of {count_a} "
        f"observed failures in the last {history_days} days"
    )


def render(settings: Settings) -> None:
    st.header("Failure Predictions")
    st.caption(
        "These predictions are not trend extrapolations. They are conditional "
        "probabilities derived from observed co-failure patterns: given what is "
        "currently failing, what has historically followed?"
    )

    with st.spinner("Building co-failure model from historical data..."):
        df = queries.get_cascade_predictions(settings)

    if df.empty:
        st.info(
            "No cascade predictions available. This can occur when no APIs are "
            "currently anomalous, or when insufficient co-failure history exists "
            "to compute reliable probabilities."
        )
        return

    history_days = int(df["history_days"].iloc[0]) if "history_days" in df.columns else "?"
    n_high   = int((df["best_single_prob"] >= 0.75).sum())
    n_medium = int(((df["best_single_prob"] >= 0.55) & (df["best_single_prob"] < 0.75)).sum())

    st.markdown(
        f"**{len(df)} APIs at elevated risk** — "
        f"{'**' + str(n_high) + ' HIGH,** ' if n_high else ''}"
        f"{n_medium} MEDIUM · "
        f"Model trained on {history_days} days of co-failure history"
    )

    st.html(f"""
<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;
            padding:12px 16px;margin:8px 0 16px 0;">
    <span style="font-size:12px;color:#92400E;">
        <b>How to read this:</b> Each prediction names the currently-failing API that
        historically drives the cascade. The percentage is the Laplace-smoothed
        conditional probability — i.e. how often the predicted API failed when the
        driver was failing, across the last {history_days} days. It is not a time-series
        forecast. It uses the structure of past failures, not the current trend.
    </span>
</div>
""")

    # Show top 10, grouped by risk band
    top = df.head(10)
    for _, row in top.iterrows():
        prob       = float(row["best_single_prob"])
        color      = _risk_color(prob)
        label      = _risk_label(prob)
        name       = friendly_proxy(row["proxy"])
        ec         = row["error_class"]
        driver     = friendly_proxy(row["driver_proxy"])
        driver_ec  = row["driver_ec"]
        raw_pct    = float(row["driver_prob"]) * 100
        count_ab   = int(row["driver_count_ab"])
        count_a    = int(row["driver_count_a"])
        lag        = int(row["best_lag"])
        n_drivers  = int(row["n_drivers"])
        ec_str     = "App Errors (4xx)" if ec == "client" else "Service Failures (5xx)"
        drv_ec_str = "4xx" if driver_ec == "client" else "5xx"

        multi_note = f" (+{n_drivers - 1} other active signals)" if n_drivers > 1 else ""
        confidence = _confidence_note(count_a, count_ab, history_days)

        st.html(f"""
<div style="background:#FFFFFF;border-left:5px solid {color};border-radius:8px;
            padding:16px 20px;margin-bottom:10px;
            box-shadow:0 1px 3px rgba(0,0,0,0.07);">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
        <div>
            <span style="font-size:15px;font-weight:700;color:#1E293B;">{name}</span>
            <span style="font-size:12px;color:#94A3B8;margin-left:8px;">{ec_str}</span>
        </div>
        <div style="text-align:right;">
            <span style="background:{color};color:#FFFFFF;padding:3px 10px;
                         border-radius:12px;font-size:11px;font-weight:700;
                         letter-spacing:0.06em;">{label}</span>
            <span style="display:block;font-size:22px;font-weight:800;
                         color:{color};margin-top:2px;">{prob*100:.0f}%</span>
        </div>
    </div>
    <div style="font-size:13px;color:#374151;margin-bottom:6px;">
        <b>Driven by:</b> {driver} ({drv_ec_str}) is currently failing{multi_note}
    </div>
    <div style="font-size:12px;color:#64748B;">
        {confidence} — typically follows within <b>{lag} hour{'s' if lag != 1 else ''}</b>
        &nbsp;·&nbsp; {raw_pct:.0f}% raw co-failure rate
    </div>
</div>
""")

        with st.expander(f"View 7-day failure history — {name} vs {driver}", expanded=False):
            _co_failure_chart(
                settings,
                proxy_a=row["driver_proxy"], ec_a=row["driver_ec"],
                proxy_b=row["proxy"],        ec_b=row["error_class"],
                driver_name=driver,
                risk_name=name,
            )

    if len(df) > 10:
        with st.expander(f"Show remaining {len(df) - 10} lower-confidence predictions"):
            for _, row in df.iloc[10:].iterrows():
                prob  = float(row["best_single_prob"])
                name  = friendly_proxy(row["proxy"])
                drv   = friendly_proxy(row["driver_proxy"])
                n, t  = int(row["driver_count_ab"]), int(row["driver_count_a"])
                st.markdown(
                    f"- **{name}** [{row['error_class']}] — {prob*100:.0f}% "
                    f"(driver: {drv}, {n}/{t} occurrences)"
                )

    st.divider()
    st.caption(
        f"Predictions use {history_days} days of observed anomaly co-occurrence data. "
        f"Probabilities are Laplace-smoothed to account for limited history. "
        f"Pairs require ≥5 driver observations and ≥3 co-failures to be included. "
        f"This model captures structural API dependencies, not time-series trends."
    )
