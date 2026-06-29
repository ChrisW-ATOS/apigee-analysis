"""Executive Summary — single-screen platform status overview."""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy

_COUNTRY_NAMES: dict[str, str] = {
    "GHA": "Ghana",        "NGA": "Nigeria",       "ZAF": "South Africa",
    "UGA": "Uganda",       "CMR": "Cameroon",       "ZMB": "Zambia",
    "CIV": "Côte d'Ivoire","BEN": "Benin",          "LBR": "Liberia",
    "RWA": "Rwanda",       "SWZ": "Eswatini",       "GIN": "Guinea",
    "SDN": "Sudan",        "MOZ": "Mozambique",     "COD": "DR Congo",
}

_STATUS_COLOR = {
    "degraded": "#EF4444",
    "watch":    "#F59E0B",
    "healthy":  "#22C55E",
}
_STATUS_LABEL = {
    "degraded": "Degraded",
    "watch":    "Watch",
    "healthy":  "Healthy",
}


def _opco_status(is_anomaly: bool, z: float) -> str:
    if is_anomaly:
        return "degraded"
    if abs(z) > 1.5:
        return "watch"
    return "healthy"


def _opco_grid(country_df) -> None:
    """Render a colour-coded grid of OpCo status badges."""
    countries = country_df.to_dict("records")

    cards_html = ""
    for row in sorted(countries, key=lambda r: r["country"]):
        name   = _COUNTRY_NAMES.get(row["country"], row["country"])
        status = _opco_status(row["is_anomaly"], row["z_score"])
        color  = _STATUS_COLOR[status]
        label  = _STATUS_LABEL[status]
        er     = row.get("error_rate_pct", 0)

        cards_html += f"""
        <div style="
            display:inline-flex;flex-direction:column;align-items:center;
            background:#FFFFFF;border:2px solid {color};border-radius:10px;
            padding:14px 20px;margin:6px;min-width:120px;
            box-shadow:0 1px 3px rgba(0,0,0,0.06);
        ">
            <span style="font-size:22px;margin-bottom:4px;">
                {'🔴' if status=='degraded' else '🟡' if status=='watch' else '🟢'}
            </span>
            <span style="font-size:14px;font-weight:700;color:#1E293B;">{name}</span>
            <span style="font-size:11px;color:{color};font-weight:600;margin-top:2px;">{label}</span>
            <span style="font-size:11px;color:#94A3B8;margin-top:1px;">{er:.1f}% errors</span>
        </div>"""

    st.html(f"""
    <div style="display:flex;flex-wrap:wrap;gap:4px;margin:4px 0 8px 0;">
        {cards_html}
    </div>
    """)


def render(settings: Settings) -> None:
    st.header("Platform Overview")

    with st.spinner("Loading..."):
        country_df   = queries.get_country_health(settings)
        anomalies_df = queries.get_active_anomalies(settings)
        brief        = queries.get_latest_incident_brief(settings)
        proxy_list   = queries.get_proxy_list(settings)
        predicted_df = queries.get_predicted_anomalies(settings)

    # ── Headline KPIs ─────────────────────────────────────────────────────────
    univariate = (
        anomalies_df[anomalies_df["type"] != "Multivariate"]
        if not anomalies_df.empty else anomalies_df
    )
    n_incidents  = univariate["proxy"].nunique() if not univariate.empty else 0
    n_sustained  = int(univariate["sustained"].sum()) if not univariate.empty else 0
    n_apis       = len(proxy_list)
    n_predicted  = len(predicted_df)

    worst_country = "—"
    if not country_df.empty:
        worst = country_df.loc[country_df["z_score"].abs().idxmax()]
        worst_country = _COUNTRY_NAMES.get(worst["country"], worst["country"])
        if not worst["is_anomaly"] and abs(worst["z_score"]) <= 1.5:
            worst_country = "None — all healthy"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("APIs Monitored",   n_apis)
    c2.metric("Active Incidents", n_incidents,
              delta=f"{n_sustained} ongoing" if n_sustained else None,
              delta_color="inverse")
    c3.metric("Early Warnings",   n_predicted,
              delta="projected to worsen" if n_predicted else None,
              delta_color="inverse")
    c4.metric("Most Affected",    worst_country)

    st.divider()

    # ── OpCo status grid ──────────────────────────────────────────────────────
    st.subheader("Operating Company Status")
    if country_df.empty:
        st.info("No country health data available.")
    else:
        _opco_grid(country_df)

    st.divider()

    # ── Latest incident brief ─────────────────────────────────────────────────
    st.subheader("Latest Incident Brief")
    if not brief:
        st.success("No incidents detected in the last 25 hours — platform is healthy.")
        return

    severity  = brief.get("severity", "unknown").lower()
    sev_color = {"high": "#EF4444", "medium": "#F59E0B", "low": "#22C55E"}.get(severity, "#94A3B8")
    ts        = brief.get("timestamp")
    ts_str    = ts.strftime("%Y-%m-%d %H:%M UTC") if ts else "—"
    n_anom    = brief.get("anomaly_count", 0)
    n_apps    = brief.get("affected_apps", 0)

    st.html(f"""
<div style="
    border-left:6px solid {sev_color};background:#FFFFFF;
    padding:20px 24px;border-radius:8px;
    box-shadow:0 1px 4px rgba(0,0,0,0.08);
">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
        <span style="font-size:11px;color:#94A3B8;font-weight:600;letter-spacing:0.07em;text-transform:uppercase;">
            {ts_str}
        </span>
        <span style="background:{sev_color};color:#FFFFFF;padding:3px 12px;
                     border-radius:12px;font-size:11px;font-weight:700;letter-spacing:0.07em;text-transform:uppercase;">
            {severity}
        </span>
    </div>
    <p style="font-size:16px;color:#1E293B;margin:0 0 16px 0;line-height:1.65;">
        {brief.get('summary', '')}
    </p>
    <div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:6px;padding:12px 16px;margin-bottom:12px;">
        <div style="font-size:10px;font-weight:700;color:#92400E;letter-spacing:0.07em;text-transform:uppercase;margin-bottom:4px;">
            Recommended Action
        </div>
        <p style="font-size:13px;color:#78350F;margin:0;line-height:1.5;">
            {brief.get('recommended_action', '')}
        </p>
    </div>
    <div style="display:flex;gap:28px;">
        <span style="font-size:12px;color:#64748B;">
            <b style="font-size:18px;color:#1E293B;">{n_anom}</b>&nbsp;incidents
        </span>
        <span style="font-size:12px;color:#64748B;">
            <b style="font-size:18px;color:#1E293B;">{n_apps}</b>&nbsp;partners affected
        </span>
    </div>
</div>
""")

    # Top affected APIs (from active anomalies)
    if not univariate.empty:
        st.markdown(" ")
        st.caption("Top affected APIs")
        top = (univariate.sort_values("z_score", key=lambda s: s.abs(), ascending=False)
                          .drop_duplicates("proxy")
                          .head(5))
        for _, row in top.iterrows():
            name   = friendly_proxy(row["proxy"])
            t_type = row["type"]
            ec     = row.get("error_class", "")
            er     = row.get("error_rate")
            er_str = f" · {er:.1%} error rate" if er and er > 0 else ""
            sustained_str = " · **Ongoing**" if row.get("sustained") else ""
            st.markdown(f"- **{name}** — {t_type}{f' ({ec})' if ec else ''}{er_str}{sustained_str}")
