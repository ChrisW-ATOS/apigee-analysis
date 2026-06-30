"""Incident Brief view — latest Claude summary + active anomaly table."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy, friendly_type

_NO_PREDICTION_MSG = (
    "Predictions are generated hourly by the detection pipeline. "
    "Run a backfill or wait for the next scheduled run."
)

_SEVERITY_COLORS = {
    "high":    "#B85450",
    "medium":  "#D97706",
    "low":     "#16A34A",
    "unknown": "#64748B",
}


def _brief_card(brief: dict) -> None:
    severity = brief.get("severity", "unknown").lower()
    color    = _SEVERITY_COLORS.get(severity, "#64748B")
    ts       = brief.get("timestamp")
    ts_str   = ts.strftime("%Y-%m-%d %H:%M UTC") if ts else "—"

    st.html(f"""
<div style="
    border-left: 6px solid {color};
    background: #FFFFFF;
    padding: 20px 24px;
    border-radius: 8px;
    margin-bottom: 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08);
">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
        <span style="font-size:11px;color:#94A3B8;font-weight:600;letter-spacing:0.07em;text-transform:uppercase;">
            Incident Brief · {ts_str}
        </span>
        <span style="
            background:{color};color:#FFFFFF;
            padding:3px 12px;border-radius:12px;
            font-size:11px;font-weight:700;letter-spacing:0.07em;text-transform:uppercase;
        ">{severity}</span>
    </div>

    <p style="font-size:15px;color:#1E293B;margin:0 0 18px 0;line-height:1.65;">
        {brief.get('summary','')}
    </p>

    <div style="background:#F1F5F9;border-radius:6px;padding:12px 16px;margin-bottom:12px;">
        <div style="font-size:10px;font-weight:700;color:#64748B;letter-spacing:0.07em;
                    text-transform:uppercase;margin-bottom:4px;">Root Cause</div>
        <p style="font-size:13px;color:#334155;margin:0;line-height:1.5;">
            {brief.get('root_cause','')}
        </p>
    </div>

    <div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:6px;
                padding:12px 16px;margin-bottom:14px;">
        <div style="font-size:10px;font-weight:700;color:#92400E;letter-spacing:0.07em;
                    text-transform:uppercase;margin-bottom:4px;">Recommended Action</div>
        <p style="font-size:13px;color:#78350F;margin:0;line-height:1.5;">
            {brief.get('recommended_action','')}
        </p>
    </div>

    <div style="display:flex;gap:28px;">
        <span style="font-size:12px;color:#64748B;">
            <b style="font-size:18px;color:#1E293B;">{brief.get('anomaly_count',0)}</b>
            &nbsp;anomalies
        </span>
        <span style="font-size:12px;color:#64748B;">
            <b style="font-size:18px;color:#1E293B;">{brief.get('affected_apps',0)}</b>
            &nbsp;apps affected
        </span>
    </div>
</div>
""")


def _anomaly_table(df: pd.DataFrame) -> None:
    # Exclude multivariate rows — shown separately below
    df = df[df["type"] != "Multivariate"].copy()
    if df.empty:
        return

    display = df.copy()
    display["Signal Strength"] = display["z_score"].apply(lambda x: f"{abs(x):.1f}×")
    display["Error Rate"] = display["error_rate"].apply(
        lambda x: f"{x:.1%}" if pd.notna(x) and x is not None else "—"
    )
    display["Incident Type"] = display.apply(
        lambda r: friendly_type(r["type"], r["error_class"]), axis=1
    )
    display["Ongoing"] = display["sustained"].apply(lambda x: "●" if x else "")
    display["Duration (hrs)"] = display["consecutive_hours"].apply(
        lambda x: str(int(x)) if x > 0 else "1"
    )
    display["API Service"] = display["proxy"].apply(friendly_proxy)

    st.dataframe(
        display[["API Service", "Incident Type", "Signal Strength", "Error Rate",
                 "Ongoing", "Duration (hrs)"]],
        use_container_width=True,
        hide_index=True,
    )


_COLOURS = ["#2563EB", "#DC2626", "#16A34A", "#D97706", "#9333EA"]


def _error_rate_chart(df: pd.DataFrame, pred_df: pd.DataFrame) -> None:
    """Historical error rates + AR(1) predictions from the most recent detection run.

    Predictions are written hourly by the detection pipeline. Only predictions
    whose plot_time (detection_time + hours_ahead) is still in the future are
    shown. If the last detection run was many hours ago, this chart will have
    no dotted projection — which is correct, not a bug.
    """
    st.subheader("Predicted Error Rates — Top 10 Endpoints")

    if df.empty:
        st.info("No error rate history available.")
        return

    has_preds = not pred_df.empty
    if has_preds:
        gen_at = pred_df["generated_at"].iloc[0] if "generated_at" in pred_df.columns else "?"
        st.caption(
            f"Solid: actual hourly error rate  ·  Diamond: AR(1) forecast (model run {gen_at})"
        )
    else:
        st.caption(
            "Solid: actual hourly error rate  ·  "
            "No future predictions available from the current detection run — "
            "projections will appear after the next scheduled analysis (HH:10)"
        )

    # Combine client + server into total error rate per proxy per hour
    total = (
        df.groupby(["proxy", "time"])
        .agg(error_rate=("error_rate", "sum"), is_anomaly=("is_anomaly", "any"))
        .reset_index()
    )
    total["error_rate"] = total["error_rate"].clip(0, 1)
    total = total.sort_values("time")

    # Index predictions by proxy for fast lookup in the per-proxy loop
    pred_map = pred_df.set_index("proxy") if has_preds else None

    fig = go.Figure()

    for i, proxy in enumerate(total["proxy"].unique()):
        grp    = total[total["proxy"] == proxy].sort_values("time").reset_index(drop=True)
        colour = _COLOURS[i % len(_COLOURS)]
        label  = friendly_proxy(proxy)[:40]

        anomaly_colours = ["#EF4444" if a else colour for a in grp["is_anomaly"]]
        anomaly_sizes   = [10 if a else 5 for a in grp["is_anomaly"]]

        # Historical line
        fig.add_trace(go.Scatter(
            x=grp["time"],
            y=grp["error_rate"] * 100,
            mode="lines+markers",
            name=label,
            line=dict(color=colour, width=2),
            marker=dict(color=anomaly_colours, size=anomaly_sizes,
                        line=dict(color="white", width=1)),
            hovertemplate=(
                f"<b>{label}</b><br>"
                "Time: %{x}<br>"
                "Error rate: %{y:.1f}%<extra></extra>"
            ),
        ))

        # Stored AR(1) predictions — one point per forecast step (t+1h … t+4h)
        if pred_map is not None and proxy in pred_map.index:
            p_rows = pred_map.loc[[proxy]].sort_values("hours_ahead")

            # Combine client + server into total predicted rate per step
            p_combined = (
                p_rows.groupby(["detection_time", "hours_ahead", "plot_time"])["predicted_rate"]
                .sum()
                .clip(0, 1)
                .reset_index()
                .sort_values("hours_ahead")
            )

            if not p_combined.empty:
                t_last   = grp["time"].iloc[-1]
                anchor_r = float(grp["error_rate"].iloc[-1]) * 100

                forecast_x = [t_last] + list(p_combined["plot_time"])
                forecast_y = [anchor_r] + [float(r) * 100 for r in p_combined["predicted_rate"]]

                hex_r = int(colour[1:3], 16)
                hex_g = int(colour[3:5], 16)
                hex_b = int(colour[5:7], 16)

                # Dotted forecast line through all steps
                fig.add_trace(go.Scatter(
                    x=forecast_x,
                    y=forecast_y,
                    mode="lines+markers",
                    line=dict(color=colour, width=2, dash="dot"),
                    marker=dict(
                        color=f"rgba({hex_r},{hex_g},{hex_b},0.85)",
                        size=[0] + [9] * len(p_combined),  # no marker at anchor
                        symbol="diamond",
                        line=dict(color="white", width=1.5),
                    ),
                    showlegend=False,
                    hovertemplate=(
                        f"<b>{label} — AR(1) forecast</b><br>"
                        "Predicted for: %{x}<br>"
                        "Predicted rate: %{y:.1f}%<extra></extra>"
                    ),
                ))

    fig.add_hline(
        y=10, line_dash="dash", line_color="#CBD5E1", line_width=1,
        annotation_text="10%", annotation_position="top left",
        annotation_font_size=10,
    )

    y_max = max(total["error_rate"].max() * 100 * 1.15, 15)
    fig.update_layout(
        xaxis_title="Time (UTC)",
        yaxis_title="Error Rate (%)",
        yaxis=dict(range=[0, y_max], gridcolor="#E2E8F0", ticksuffix="%"),
        xaxis=dict(gridcolor="#E2E8F0"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(size=11)),
        height=400,
        plot_bgcolor="#FAFAFA",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=40, b=0),
    )

    st.plotly_chart(fig, use_container_width=True)


def _multivariate_section(mv_df: pd.DataFrame) -> None:
    """Render the Isolation Forest anomaly section with radar charts."""
    st.subheader("Complex Pattern Alerts")
    st.caption(
        "APIs flagged because the *combination* of traffic, app errors, and service "
        "failures is unusual — patterns that standard monitoring misses"
    )

    if mv_df.empty:
        st.info("No complex pattern alerts in the last 25 hours.")
        return

    st.caption(f"{len(mv_df)} APIs flagged · anomaly confidence closer to −1 = stronger signal")

    # Summary table
    display = mv_df[["proxy", "score", "traffic_z", "client_z", "server_z",
                      "client_rate", "server_rate"]].copy()
    display["API Service"]        = display["proxy"].apply(friendly_proxy)
    display["Anomaly Confidence"] = display["score"].apply(lambda x: f"{x:.4f}")
    display["Traffic Signal"]     = display["traffic_z"].apply(lambda x: f"{abs(x):.1f}×")
    display["App Error Signal"]   = display["client_z"].apply(lambda x: f"{abs(x):.1f}×")
    display["Service Fail Signal"]= display["server_z"].apply(lambda x: f"{abs(x):.1f}×")
    display["App Error Rate"]     = display["client_rate"].apply(lambda x: f"{x:.1%}")
    display["Service Fail Rate"]  = display["server_rate"].apply(lambda x: f"{x:.1%}")
    st.dataframe(
        display[["API Service", "Anomaly Confidence", "Traffic Signal",
                 "App Error Signal", "Service Fail Signal",
                 "App Error Rate", "Service Fail Rate"]],
        use_container_width=True,
        hide_index=True,
    )

    # Radar charts for top 6 most anomalous
    top = mv_df.head(6)
    if top.empty:
        return

    st.markdown("**What triggered the alert — top signals**")
    cols = st.columns(min(3, len(top)))
    features    = ["traffic_z", "client_z", "server_z", "client_rate", "server_rate"]
    feat_labels = ["Traffic Z", "Client Z", "Server Z", "Client Rate", "Server Rate"]

    for idx, (_, row) in enumerate(top.iterrows()):
        col = cols[idx % 3]
        with col:
            # Keep rates as fractions (0–1) so they stay on the same order of
            # magnitude as z-scores. Dynamic axis range ensures nothing clips.
            values = [
                row["traffic_z"],
                row["client_z"],
                row["server_z"],
                row["client_rate"],
                row["server_rate"],
            ]

            # Axis must contain all points — pad by 20%, minimum ±3
            axis_max = max(max(abs(v) for v in values) * 1.2, 3)

            hover = [
                f"Traffic Z: {row['traffic_z']:+.2f}",
                f"Client Z: {row['client_z']:+.2f}",
                f"Server Z: {row['server_z']:+.2f}",
                f"Client Rate: {row['client_rate']:.1%}",
                f"Server Rate: {row['server_rate']:.1%}",
            ]

            # Close the polygon
            values_closed = values + [values[0]]
            labels_closed = feat_labels + [feat_labels[0]]
            hover_closed  = hover + [hover[0]]

            fig = go.Figure(go.Scatterpolar(
                r=values_closed,
                theta=labels_closed,
                fill="toself",
                fillcolor="rgba(184, 84, 80, 0.15)",
                line=dict(color="#B85450", width=2),
                name=row["proxy"],
                text=hover_closed,
                hoverinfo="text",
            ))
            fig.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[-axis_max, axis_max],
                        tickfont=dict(size=9),
                    ),
                    angularaxis=dict(tickfont=dict(size=10)),
                ),
                showlegend=False,
                margin=dict(l=10, r=10, t=30, b=10),
                height=240,
                title=dict(
                    text=friendly_proxy(row["proxy"])[:30],
                    font=dict(size=10),
                    x=0.5,
                ),
            )
            st.plotly_chart(fig, use_container_width=True)


def render(settings: Settings) -> None:
    st.header("Incident Brief")

    with st.spinner("Loading..."):
        brief          = queries.get_latest_incident_brief(settings)
        anomalies_df   = queries.get_active_anomalies(settings)
        predicted_df   = queries.get_predicted_anomalies(settings)
        mv_df          = queries.get_multivariate_anomalies(settings)
        error_trend_df = queries.get_error_rate_trend(settings, top_n=10)
        pred_df        = queries.get_error_rate_predictions(settings)

    # Predictive alert banner
    if not predicted_df.empty:
        n      = len(predicted_df)
        sample = ", ".join(friendly_proxy(p) for p in predicted_df["proxy"].head(3))
        suffix = f" +{n - 3} more" if n > 3 else ""
        st.warning(
            f"**Early Warning — {n} {'API' if n == 1 else 'APIs'} projected to breach "
            f"alert threshold within 2 hours:** {sample}{suffix}",
            icon="⚠️",
        )

    # Incident brief card
    if brief:
        _brief_card(brief)
    else:
        st.success("No incident briefs generated in the last 25 hours — system appears healthy.")

    # Active incidents (traffic + error rate)
    st.subheader("Active Incidents")
    univariate_df = anomalies_df[anomalies_df["type"] != "Multivariate"] if not anomalies_df.empty else anomalies_df
    if univariate_df.empty:
        st.info("No active incidents in the last 25 hours.")
    else:
        n_sustained = int(univariate_df["sustained"].sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Incidents Detected", len(univariate_df))
        c2.metric("Ongoing Incidents",  n_sustained,
                  delta=f"{n_sustained} need attention" if n_sustained else None,
                  delta_color="inverse")
        c3.metric("APIs Affected",      univariate_df["proxy"].nunique())
        _anomaly_table(anomalies_df)

    st.divider()

    # Error rate trend + AR(1) predictions from InfluxDB
    _error_rate_chart(error_trend_df, pred_df)

    st.divider()

    # Multivariate section
    _multivariate_section(mv_df)
