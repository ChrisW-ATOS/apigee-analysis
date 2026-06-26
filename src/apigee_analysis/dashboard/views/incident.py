"""Incident Brief view — latest Claude summary + active anomaly table."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries

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
    display["Z-Score"] = display["z_score"].apply(lambda x: f"{x:+.2f}")
    display["Error Rate"] = display["error_rate"].apply(
        lambda x: f"{x:.1%}" if pd.notna(x) and x is not None else "—"
    )
    display["Type"] = display.apply(
        lambda r: r["type"] + (f" ({r['error_class']})" if r["error_class"] else ""),
        axis=1,
    )
    display["Sustained"] = display["sustained"].apply(lambda x: "✓" if x else "")
    display["Hours"] = display["consecutive_hours"].apply(lambda x: str(int(x)) if x > 0 else "1")

    st.dataframe(
        display[["proxy", "Type", "Z-Score", "Error Rate", "Sustained", "Hours"]].rename(columns={
            "proxy": "API Proxy",
            "Hours": "Consecutive Hours",
        }),
        use_container_width=True,
        hide_index=True,
    )


def _multivariate_section(mv_df: pd.DataFrame) -> None:
    """Render the Isolation Forest anomaly section with radar charts."""
    st.subheader("Multivariate Anomalies")
    st.caption(
        "Proxies flagged by Isolation Forest — unusual *combinations* of metrics "
        "that univariate Z-scores miss"
    )

    if mv_df.empty:
        st.info("No multivariate anomalies in the last 4 hours.")
        return

    st.caption(f"{len(mv_df)} proxies flagged · score closer to −1 = more anomalous")

    # Summary table
    display = mv_df[["proxy", "score", "traffic_z", "client_z", "server_z",
                      "client_rate", "server_rate"]].copy()
    display["score"]       = display["score"].apply(lambda x: f"{x:.4f}")
    display["traffic_z"]   = display["traffic_z"].apply(lambda x: f"{x:+.2f}")
    display["client_z"]    = display["client_z"].apply(lambda x: f"{x:+.2f}")
    display["server_z"]    = display["server_z"].apply(lambda x: f"{x:+.2f}")
    display["client_rate"] = display["client_rate"].apply(lambda x: f"{x:.1%}")
    display["server_rate"] = display["server_rate"].apply(lambda x: f"{x:.1%}")
    display.columns = [
        "API Proxy", "IF Score", "Traffic Z", "Client Err Z",
        "Server Err Z", "Client Rate", "Server Rate",
    ]
    st.dataframe(display, use_container_width=True, hide_index=True)

    # Radar charts for top 6 most anomalous
    top = mv_df.head(6)
    if top.empty:
        return

    st.markdown("**Feature breakdown — top anomalies**")
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
                    text=row["proxy"].split("_")[-1][:24],
                    font=dict(size=10),
                    x=0.5,
                ),
            )
            st.plotly_chart(fig, use_container_width=True)


def render(settings: Settings) -> None:
    st.header("Incident Brief")

    with st.spinner("Loading..."):
        brief        = queries.get_latest_incident_brief(settings)
        anomalies_df = queries.get_active_anomalies(settings)
        predicted_df = queries.get_predicted_anomalies(settings)
        mv_df        = queries.get_multivariate_anomalies(settings)

    # Predictive alert banner
    if not predicted_df.empty:
        n      = len(predicted_df)
        sample = ", ".join(predicted_df["proxy"].head(3).tolist())
        suffix = f" +{n - 3} more" if n > 3 else ""
        st.warning(
            f"**Predictive Alert — {n} {'proxy' if n == 1 else 'proxies'} projected to breach "
            f"threshold within 2 hours:** {sample}{suffix}",
            icon="⚠️",
        )

    # Incident brief card
    if brief:
        _brief_card(brief)
    else:
        st.success("No incident briefs generated in the last 25 hours — system appears healthy.")

    # Active anomalies (traffic + error rate)
    st.subheader("Active Anomalies")
    univariate_df = anomalies_df[anomalies_df["type"] != "Multivariate"] if not anomalies_df.empty else anomalies_df
    if univariate_df.empty:
        st.info("No active anomalies in the last 4 hours.")
    else:
        n_sustained = int(univariate_df["sustained"].sum())
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Anomalies",  len(univariate_df))
        c2.metric("Sustained",        n_sustained,
                  delta=f"{n_sustained} need attention" if n_sustained else None,
                  delta_color="inverse")
        c3.metric("Unique Proxies",   univariate_df["proxy"].nunique())
        _anomaly_table(anomalies_df)

    st.divider()

    # Multivariate section
    _multivariate_section(mv_df)
