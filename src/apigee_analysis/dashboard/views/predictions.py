"""Failure Predictions — time-to-failure estimates with on-demand explanations."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy

_HOURS_COLOR = {1: "#EF4444", 2: "#F59E0B", 3: "#D97706", 4: "#64748B"}
_HOURS_LABEL = {1: "CRITICAL",  2: "HIGH",     3: "MEDIUM",   4: "LOW"}


def _ttf_card(row: dict, idx: int) -> None:
    """Render a single time-to-failure card and an optional explanation below it."""
    proxy    = row["proxy"]
    ec       = row["error_class"]
    h        = row["hours_until_breach"]
    fz       = abs(row["forecast_z"])
    rate_pct = row["predicted_rate_pct"]
    conf     = row["confidence_pct"]
    current  = row.get("is_currently_anomalous", False)

    label    = friendly_proxy(proxy)
    color    = _HOURS_COLOR.get(h, "#94A3B8")
    urgency  = _HOURS_LABEL.get(h, "WATCH")
    ec_str   = "App Errors (4xx)" if ec == "client" else "Service Failures (5xx)" if ec == "server" else "Errors"
    status   = "⚠ Already failing" if current else "● Predicted"

    # Fill bar: how close to breach (1h = nearly full, 4h = quarter)
    bar_fill = max(10, 100 - (h - 1) * 22)

    st.html(f"""
<div style="background:#FFFFFF;border:2px solid {color};border-radius:12px;
            padding:20px 24px;margin-bottom:4px;
            box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
        <div>
            <span style="font-size:16px;font-weight:700;color:#1E293B;">{label}</span>
            <span style="font-size:12px;color:#94A3B8;margin-left:10px;">{ec_str}</span>
        </div>
        <span style="background:{color};color:#FFFFFF;padding:4px 12px;border-radius:20px;
                     font-size:11px;font-weight:700;letter-spacing:0.07em;">{urgency}</span>
    </div>
    <div style="display:flex;align-items:center;gap:24px;">
        <div style="text-align:center;min-width:80px;">
            <div style="font-size:10px;color:#94A3B8;text-transform:uppercase;
                        letter-spacing:0.07em;margin-bottom:2px;">Fails in</div>
            <div style="font-size:48px;font-weight:900;color:{color};line-height:1;">{h}</div>
            <div style="font-size:12px;color:{color};font-weight:600;">
                {'hour' if h == 1 else 'hours'}
            </div>
        </div>
        <div style="flex:1;">
            <div style="display:flex;justify-content:space-between;
                        font-size:11px;color:#64748B;margin-bottom:4px;">
                <span>Now — {rate_pct:.1f}% error rate predicted</span>
                <span>Alert threshold</span>
            </div>
            <div style="background:#F1F5F9;border-radius:6px;height:14px;position:relative;">
                <div style="background:{color};height:14px;border-radius:6px;
                            width:{bar_fill:.0f}%;"></div>
                <div style="position:absolute;right:0;top:-3px;width:2px;height:20px;
                            background:#1E293B;border-radius:1px;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;
                        font-size:10px;color:#94A3B8;margin-top:4px;">
                <span>{status}</span>
                <span>Confidence: {conf:.0f}%</span>
            </div>
        </div>
    </div>
</div>
""")

    # Explain button + explanation panel
    explain_key = f"explain_{idx}"
    col_l, col_r = st.columns([4, 1])
    with col_r:
        if st.button("Explain cause & effect", key=f"btn_{idx}", use_container_width=True):
            if st.session_state.get("active_explain") == explain_key:
                st.session_state.pop("active_explain", None)
            else:
                st.session_state["active_explain"] = explain_key

    if st.session_state.get("active_explain") == explain_key:
        with st.spinner(f"Generating explanation for {label}..."):
            hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
            ctx      = queries.get_proxy_context(settings_ref[0], proxy)
            expl     = queries.get_proxy_explanation(
                settings_ref[0],
                proxy      = proxy,
                hour_key   = hour_key,
                error_class             = ec,
                hours_until_breach      = h,
                current_error_rate      = ctx.get("current_error_rate") or 0.0,
                forecast_rate_pct       = rate_pct,
                total_calls_at_risk     = ctx.get("total_calls_at_risk", 0),
                n_apps                  = len(ctx.get("blast_apps", [])),
                incident_hours_30d      = ctx.get("incident_hours_30d", 0),
            )

        mode_color = "#7C3AED" if expl["mode"] == "claude" else "#64748B"
        mode_badge = "Claude AI" if expl["mode"] == "claude" else "Auto-generated"

        import re
        raw_text = expl["text"]
        # Convert **bold** to HTML <b>
        html_text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", raw_text)
        # Convert newlines to <br>
        html_text = html_text.replace("\n\n", "</p><p style='margin:10px 0 0 0;'>")
        html_text = html_text.replace("\n", "<br>")

        st.html(f"""
<div style="border-left:4px solid {mode_color};background:#F8FAFC;
            padding:18px 22px;border-radius:8px;margin:4px 0 16px 0;">
    <div style="font-size:10px;color:{mode_color};font-weight:700;
                text-transform:uppercase;letter-spacing:0.07em;margin-bottom:12px;">
        {mode_badge} · {expl.get('generated_at', '')}
    </div>
    <p style="font-size:14px;color:#1E293B;line-height:1.8;margin:0;">
        {html_text}
    </p>
</div>
""")

        # Blast radius mini-table if available
        blast = ctx.get("blast_apps", [])
        if blast:
            st.caption("Partner applications at risk if this API fails:")
            import pandas as pd
            br_df = pd.DataFrame(blast[:6])
            br_df["calls"] = br_df["calls"].apply(lambda x: f"{int(x):,}")
            br_df.columns = ["Application", "Country", "Calls (25h)"]
            st.dataframe(br_df, use_container_width=True, hide_index=True)

        st.write("")


# Module-level settings holder so _ttf_card can access it without threading it
# through every call signature. Set once in render().
settings_ref: list = []


def render(settings: Settings) -> None:
    settings_ref.clear()
    settings_ref.append(settings)

    if "active_explain" not in st.session_state:
        st.session_state["active_explain"] = None

    st.header("Failure Predictions")
    st.caption(
        "APIs currently trending toward the alert threshold — ranked by urgency. "
        "Predictions are generated hourly by the AR(1) model fitted on STL residuals."
    )

    with st.spinner("Loading predictions..."):
        df = queries.get_time_to_failure(settings)

    if df.empty:
        st.success(
            "No APIs are currently predicted to breach the alert threshold in the next 4 hours. "
            "The platform is stable."
        )
        return

    # Summary line
    n_critical  = int((df["hours_until_breach"] == 1).sum())
    n_high      = int((df["hours_until_breach"] == 2).sum())
    n_total     = len(df)
    already_bad = int(df["is_currently_anomalous"].sum())

    summary_parts = []
    if n_critical:  summary_parts.append(f"**{n_critical} critical** (≤1h)")
    if n_high:      summary_parts.append(f"**{n_high} high** (≤2h)")
    if already_bad: summary_parts.append(f"**{already_bad} already failing**")

    st.markdown(
        f"**{n_total} API{'s' if n_total != 1 else ''} flagged** — "
        + (", ".join(summary_parts) if summary_parts else "see details below")
    )
    st.divider()

    for idx, (_, row) in enumerate(df.iterrows()):
        _ttf_card(row.to_dict(), idx)
