"""Failure Predictions — behavioral cross-correlation cascade risk."""
from __future__ import annotations

from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _risk_level(score: float, corr: float) -> tuple[str, str]:
    """(label, hex_color) based on combined score and correlation strength."""
    if score >= 0.4 and corr >= 0.60:
        return "HIGH",   "#EF4444"
    if score >= 0.20 and corr >= 0.40:
        return "MEDIUM", "#F59E0B"
    return "WATCH", "#64748B"


def _co_failure_chart(
    settings:    Settings,
    proxy_a:     str, ec_a: str,
    proxy_b:     str, ec_b: str,
    driver_name: str,
    risk_name:   str,
) -> None:
    """Dual-panel rate chart: driver (top, red) and at-risk API (bottom, amber).

    Uses actual hourly error rates — not binary anomaly flags — so the chart
    shows the correlated rises and falls that the model detected.
    """
    df = queries.get_co_failure_history(settings, proxy_a, ec_a, proxy_b, ec_b, days=7)
    if df.empty:
        st.caption("No history data available for this pair.")
        return

    now = datetime.now(timezone.utc)

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.10,
        subplot_titles=[
            f"Driver (currently rising): {driver_name[:50]} [{ec_a}]",
            f"At risk: {risk_name[:50]} [{ec_b}]",
        ],
    )

    # Top: driver proxy
    fig.add_trace(go.Scatter(
        x=df["hour"], y=df["a_rate"] * 100,
        mode="lines", name=driver_name[:30],
        line=dict(color="#EF4444", width=2),
        fill="tozeroy", fillcolor="rgba(239,68,68,0.10)",
        hovertemplate="Driver<br>%{x}<br>%{y:.1f}%<extra></extra>",
    ), row=1, col=1)
    anom_a = df[df["a_anomalous"]]
    if not anom_a.empty:
        fig.add_trace(go.Scatter(
            x=anom_a["hour"], y=anom_a["a_rate"] * 100, mode="markers",
            marker=dict(color="#EF4444", size=9, symbol="circle",
                        line=dict(color="white", width=1.5)),
            showlegend=False,
            hovertemplate="⚠ Anomalous %{y:.1f}%<extra></extra>",
        ), row=1, col=1)

    # Bottom: at-risk proxy
    fig.add_trace(go.Scatter(
        x=df["hour"], y=df["b_rate"] * 100,
        mode="lines", name=risk_name[:30],
        line=dict(color="#F59E0B", width=2),
        fill="tozeroy", fillcolor="rgba(245,158,11,0.10)",
        hovertemplate="At risk<br>%{x}<br>%{y:.1f}%<extra></extra>",
    ), row=2, col=1)
    anom_b = df[df["b_anomalous"]]
    if not anom_b.empty:
        fig.add_trace(go.Scatter(
            x=anom_b["hour"], y=anom_b["b_rate"] * 100, mode="markers",
            marker=dict(color="#F59E0B", size=9, symbol="circle",
                        line=dict(color="white", width=1.5)),
            showlegend=False,
            hovertemplate="⚠ Anomalous %{y:.1f}%<extra></extra>",
        ), row=2, col=1)

    fig.add_vline(x=str(now), line_dash="dot", line_color="#94A3B8", line_width=1,
                  annotation_text="Now", annotation_font_size=10,
                  annotation_position="top left")

    fig.update_layout(
        height=360, showlegend=False, hovermode="x unified",
        plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=40, b=0),
    )
    fig.update_yaxes(ticksuffix="%", gridcolor="#E2E8F0", range=[0, 105])
    fig.update_xaxes(gridcolor="#E2E8F0", row=2, col=1)
    st.plotly_chart(fig, use_container_width=True)

    # Count visible co-movement: periods where both were simultaneously elevated
    if not df.empty:
        both_elevated = ((df["a_rate"] > 0.05) & (df["b_rate"] > 0.05)).sum()
        if both_elevated:
            st.caption(
                f"↑ Both APIs showed elevated error rates simultaneously in "
                f"{both_elevated} of the last {len(df)} hours — "
                f"consistent with the {df['a_rate'].corr(df['b_rate']):.2f} "
                f"rate correlation detected in the model."
            )


# ─────────────────────────────────────────────────────────────────────────────
# Page render
# ─────────────────────────────────────────────────────────────────────────────

def render(settings: Settings) -> None:
    st.header("Failure Predictions")
    st.caption(
        "Predictions are based on behavioral cross-correlation of error rate changes — "
        "not threshold breaches. When a driver API's rate rises, APIs that have "
        "historically risen in parallel are flagged as at risk."
    )

    with st.spinner("Computing behavioral correlations..."):
        df = queries.get_cascade_predictions(settings)

    if df.empty:
        st.info(
            "No cascade predictions available. This occurs when no APIs are currently "
            "showing significant rate changes, or when insufficient behavioral correlation "
            "history exists (requires ≥10 non-zero hours per proxy)."
        )
        return

    history_days = int(df["history_days"].iloc[0])
    n_high   = int(((df["score"] >= 0.4) & (df["correlation"] >= 0.60)).sum())
    n_medium = int(((df["score"] >= 0.20) & (df["correlation"] >= 0.40) &
                    ~((df["score"] >= 0.4) & (df["correlation"] >= 0.60))).sum())

    st.markdown(
        f"**{len(df)} APIs at elevated risk** — "
        f"{'**' + str(n_high) + ' HIGH**, ' if n_high else ''}"
        f"{n_medium} MEDIUM · "
        f"Model trained on {history_days} days of hourly rate data"
    )

    st.html(f"""
<div style="background:#F0F9FF;border:1px solid #BAE6FD;border-radius:8px;
            padding:12px 16px;margin:8px 0 16px 0;">
    <span style="font-size:12px;color:#0369A1;">
        <b>How to read this:</b> Each prediction shows the currently-failing API whose
        error rate behaviour is historically correlated with the at-risk API. The
        correlation score is computed on <i>first differences</i> (hourly rate changes),
        not absolute levels — so two APIs permanently at 100% are correctly identified
        as uncorrelated. The driver's recent change magnitude (pp in last 2h) is
        multiplied by the correlation to produce the overall risk score.
    </span>
</div>
""")

    top = df.head(10)
    for _, row in top.iterrows():
        score   = float(row["score"])
        corr    = float(row["correlation"])
        lag     = int(row["driver_lag"])
        change  = float(row["driver_change_pct"])
        label, color = _risk_level(score, corr)

        name       = friendly_proxy(row["proxy"])
        ec         = row["error_class"]
        driver     = friendly_proxy(row["driver_proxy"])
        driver_ec  = row["driver_ec"]
        ec_str     = "App Errors (4xx)" if ec == "client" else "Service Failures (5xx)"
        drv_ec_str = "4xx" if driver_ec == "client" else "5xx"
        lag_str    = "simultaneously" if lag == 0 else f"within {lag} hour{'s' if lag != 1 else ''}"
        n_drivers  = int(row["n_drivers"])
        multi_note = f" (+{n_drivers - 1} other active signals)" if n_drivers > 1 else ""

        st.html(f"""
<div style="background:#FFFFFF;border-left:5px solid {color};border-radius:8px;
            padding:16px 20px;margin-bottom:4px;
            box-shadow:0 1px 3px rgba(0,0,0,0.07);">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;">
        <div>
            <span style="font-size:15px;font-weight:700;color:#1E293B;">{name}</span>
            <span style="font-size:12px;color:#94A3B8;margin-left:8px;">{ec_str}</span>
        </div>
        <div style="text-align:right;min-width:90px;">
            <span style="background:{color};color:#FFFFFF;padding:3px 10px;
                         border-radius:12px;font-size:11px;font-weight:700;">{label}</span>
            <div style="font-size:11px;color:#64748B;margin-top:4px;">
                corr&nbsp;<b style="color:#1E293B;">{corr:.2f}</b>
            </div>
        </div>
    </div>
    <div style="font-size:13px;color:#374151;margin-bottom:5px;">
        <b>Driver:</b> {driver} ({drv_ec_str}) rose
        <b style="color:{color};">{change:+.1f}pp</b> in the last 2 hours{multi_note}
    </div>
    <div style="font-size:12px;color:#64748B;">
        Historically moves {lag_str} with this change pattern
        &nbsp;·&nbsp; Risk score: {score:.3f}
    </div>
</div>
""")

        with st.expander(
            f"View 7-day rate history — {name} vs {driver}", expanded=False
        ):
            _co_failure_chart(
                settings,
                proxy_a=row["driver_proxy"], ec_a=row["driver_ec"],
                proxy_b=row["proxy"],        ec_b=row["error_class"],
                driver_name=driver,
                risk_name=name,
            )

    if len(df) > 10:
        with st.expander(f"Show {len(df) - 10} additional lower-risk predictions"):
            for _, row in df.iloc[10:].iterrows():
                corr = float(row["correlation"])
                name = friendly_proxy(row["proxy"])
                drv  = friendly_proxy(row["driver_proxy"])
                st.markdown(
                    f"- **{name}** [{row['error_class']}] — "
                    f"corr {corr:.2f} with {drv} "
                    f"(score {float(row['score']):.3f})"
                )

    st.divider()
    st.caption(
        f"Cross-correlation computed on first differences of hourly error rates "
        f"over {history_days} days × all monitored proxies. "
        f"Requires ≥10 non-zero hours per proxy and ≥0.35 correlation at any lag 0–4h. "
        f"Score = |current rate change| × correlation strength."
    )
