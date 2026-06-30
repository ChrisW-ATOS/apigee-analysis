"""Failure Predictions — co-failure cascade risk based on historical patterns."""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy


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
