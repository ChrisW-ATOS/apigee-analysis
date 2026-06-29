"""Executive Summary — single-screen platform status overview."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy, friendly_type

_COUNTRY_NAMES: dict[str, str] = {
    "GHA": "Ghana",        "NGA": "Nigeria",       "ZAF": "South Africa",
    "UGA": "Uganda",       "CMR": "Cameroon",       "ZMB": "Zambia",
    "CIV": "Côte d'Ivoire","BEN": "Benin",          "LBR": "Liberia",
    "RWA": "Rwanda",       "SWZ": "Eswatini",       "GIN": "Guinea",
    "SDN": "Sudan",        "MOZ": "Mozambique",     "COD": "DR Congo",
}

_STATUS_COLOR = {"degraded": "#EF4444", "watch": "#F59E0B", "healthy": "#22C55E"}
_STATUS_LABEL = {"degraded": "Degraded", "watch": "Watch",   "healthy": "Healthy"}


def _opco_status(is_anomaly: bool, z: float) -> str:
    if is_anomaly:       return "degraded"
    if abs(z) > 1.5:     return "watch"
    return "healthy"


def _opco_grid(country_df) -> None:
    cards_html = ""
    for row in sorted(country_df.to_dict("records"), key=lambda r: r["country"]):
        name   = _COUNTRY_NAMES.get(row["country"], row["country"])
        status = _opco_status(row["is_anomaly"], row["z_score"])
        color  = _STATUS_COLOR[status]
        label  = _STATUS_LABEL[status]
        er     = row.get("error_rate_pct", 0)
        icon   = "🔴" if status == "degraded" else ("🟡" if status == "watch" else "🟢")

        cards_html += f"""
        <div style="display:inline-flex;flex-direction:column;align-items:center;
            background:#FFFFFF;border:2px solid {color};border-radius:10px;
            padding:14px 20px;margin:6px;min-width:120px;
            box-shadow:0 1px 3px rgba(0,0,0,0.06);">
            <span style="font-size:22px;margin-bottom:4px;">{icon}</span>
            <span style="font-size:14px;font-weight:700;color:#1E293B;">{name}</span>
            <span style="font-size:11px;color:{color};font-weight:600;margin-top:2px;">{label}</span>
            <span style="font-size:11px;color:#94A3B8;margin-top:1px;">{er:.1f}% errors</span>
        </div>"""

    st.html(f'<div style="display:flex;flex-wrap:wrap;gap:4px;margin:4px 0 8px 0;">{cards_html}</div>')


# ─────────────────────────────────────────────────────────────────────────────
# Catch of the Day
# ─────────────────────────────────────────────────────────────────────────────

def _find_catch(anomalies_df: pd.DataFrame, mv_df: pd.DataFrame) -> dict | None:
    """Apply the priority logic and return a catch descriptor dict, or None."""
    univariate = (
        anomalies_df[anomalies_df["type"] != "Multivariate"].copy()
        if not anomalies_df.empty else pd.DataFrame()
    )
    std_proxies = set(univariate["proxy"].unique()) if not univariate.empty else set()

    # Priority 1: flagged by Isolation Forest but NOT by Z-score — most novel
    if not mv_df.empty:
        exclusive = mv_df[~mv_df["proxy"].isin(std_proxies)]
        if not exclusive.empty:
            best = exclusive.loc[exclusive["score"].idxmin()]
            return {"category": "pattern_only", "row": best}

    # Priority 2: most sustained (longest consecutive anomalous run)
    if not univariate.empty:
        sustained = univariate[univariate["sustained"] == True]
        if not sustained.empty:
            best = sustained.loc[sustained["consecutive_hours"].idxmax()]
            return {"category": "sustained", "row": best}

        # Priority 3: highest absolute Z-score
        best = univariate.loc[univariate["z_score"].abs().idxmax()]
        return {"category": "peak", "row": best}

    # Priority 4: any multivariate anomaly (no standard anomalies exist)
    if not mv_df.empty:
        best = mv_df.loc[mv_df["score"].idxmin()]
        return {"category": "pattern", "row": best}

    return None


def _build_catch(catch: dict) -> dict:
    """Turn a catch descriptor into display-ready strings."""
    category = catch["category"]
    row      = catch["row"]
    name     = friendly_proxy(row["proxy"])

    if category == "pattern_only":
        color = "#7C3AED"
        badge = "Pattern Anomaly — Standard Monitoring Missed This"
        # Describe which feature combination triggered it
        parts = []
        if abs(row.get("traffic_z", 0)) > 1.5:
            direction = "spike" if row["traffic_z"] > 0 else "drop"
            parts.append(f"traffic {direction}")
        if abs(row.get("client_z", 0)) > 1.5:
            parts.append(f"app error surge ({row['client_rate']:.0%})")
        if abs(row.get("server_z", 0)) > 1.5:
            parts.append(f"service failure spike ({row['server_rate']:.0%})")
        combo   = " alongside ".join(parts) if parts else "unusual metric combination"
        headline = f"{name} was flagged by pattern analysis but not by standard monitoring."
        detail   = (f"The AI detected {combo} simultaneously — "
                    f"a combination invisible to univariate Z-score analysis.")

    elif category == "sustained":
        color    = "#DC2626"
        badge    = "Sustained Incident"
        hours    = int(row.get("consecutive_hours", 2))
        t_label  = friendly_type(row["type"], row.get("error_class", ""))
        er       = row.get("error_rate")
        rate_str = f" at {er:.1%} error rate" if er and er > 0 else ""
        headline = (f"{name} has been showing {t_label.lower()}{rate_str} "
                    f"for {hours} consecutive hours.")
        detail   = "This is a persistent incident — not a transient spike that self-resolved."

    elif category == "peak":
        color    = "#D97706"
        badge    = "Peak Signal"
        z        = abs(row.get("z_score", 0))
        t_label  = friendly_type(row["type"], row.get("error_class", ""))
        er       = row.get("error_rate")
        rate_str = f" — current error rate {er:.1%}" if er and er > 0 else ""
        headline = f"{name} is showing a signal {z:.1f}× above its normal level."
        detail   = f"{t_label}{rate_str}."

    else:  # "pattern"
        color    = "#7C3AED"
        badge    = "Pattern Anomaly"
        headline = f"{name} flagged by cross-metric pattern analysis."
        detail   = f"Anomaly confidence: {row.get('score', 0):.4f} (closer to −1 = stronger signal)."

    return {"color": color, "badge": badge, "headline": headline,
            "detail": detail, "proxy": name}


def _catch_card(catch: dict) -> None:
    color   = catch["color"]
    badge   = catch["badge"]
    headline = catch["headline"]
    detail   = catch["detail"]

    st.html(f"""
<div style="border-left:6px solid {color};background:#FFFFFF;
            padding:20px 24px;border-radius:8px;
            box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="display:flex;justify-content:space-between;
                align-items:center;margin-bottom:14px;">
        <span style="font-size:11px;color:#94A3B8;font-weight:600;
                     letter-spacing:0.07em;text-transform:uppercase;">
            Catch of the Day · Last 25 hours
        </span>
        <span style="background:{color};color:#FFFFFF;padding:3px 12px;
                     border-radius:12px;font-size:11px;font-weight:700;
                     letter-spacing:0.05em;text-transform:uppercase;">
            {badge}
        </span>
    </div>
    <p style="font-size:16px;color:#1E293B;margin:0 0 10px 0;
              font-weight:600;line-height:1.5;">
        {headline}
    </p>
    <p style="font-size:13px;color:#64748B;margin:0;line-height:1.5;">
        {detail}
    </p>
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
# Page render
# ─────────────────────────────────────────────────────────────────────────────

def render(settings: Settings) -> None:
    st.header("Platform Overview")

    with st.spinner("Loading..."):
        country_df   = queries.get_country_health(settings)
        anomalies_df = queries.get_active_anomalies(settings)
        brief        = queries.get_latest_incident_brief(settings)
        proxy_list   = queries.get_proxy_list(settings)
        predicted_df = queries.get_predicted_anomalies(settings)
        mv_df        = queries.get_multivariate_anomalies(settings)

    # ── Headline KPIs ─────────────────────────────────────────────────────────
    univariate = (
        anomalies_df[anomalies_df["type"] != "Multivariate"]
        if not anomalies_df.empty else pd.DataFrame()
    )
    n_incidents = univariate["proxy"].nunique() if not univariate.empty else 0
    n_sustained = int(univariate["sustained"].sum()) if not univariate.empty else 0
    n_apis      = len(proxy_list)
    n_predicted = len(predicted_df)

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

    # ── Catch of the Day ──────────────────────────────────────────────────────
    st.subheader("Catch of the Day")
    catch_raw = _find_catch(anomalies_df, mv_df)
    if catch_raw:
        _catch_card(_build_catch(catch_raw))
    else:
        st.success("No notable anomalies in the last 25 hours.")

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
<div style="border-left:6px solid {sev_color};background:#FFFFFF;
            padding:20px 24px;border-radius:8px;
            box-shadow:0 1px 4px rgba(0,0,0,0.08);">
    <div style="display:flex;justify-content:space-between;
                align-items:center;margin-bottom:14px;">
        <span style="font-size:11px;color:#94A3B8;font-weight:600;
                     letter-spacing:0.07em;text-transform:uppercase;">
            {ts_str}
        </span>
        <span style="background:{sev_color};color:#FFFFFF;padding:3px 12px;
                     border-radius:12px;font-size:11px;font-weight:700;
                     letter-spacing:0.07em;text-transform:uppercase;">
            {severity}
        </span>
    </div>
    <p style="font-size:16px;color:#1E293B;margin:0 0 16px 0;line-height:1.65;">
        {brief.get('summary', '')}
    </p>
    <div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:6px;
                padding:12px 16px;margin-bottom:12px;">
        <div style="font-size:10px;font-weight:700;color:#92400E;letter-spacing:0.07em;
                    text-transform:uppercase;margin-bottom:4px;">Recommended Action</div>
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

    if not univariate.empty:
        st.markdown(" ")
        st.caption("Top affected APIs")
        top = (univariate.sort_values("z_score", key=lambda s: s.abs(), ascending=False)
                          .drop_duplicates("proxy").head(5))
        for _, row in top.iterrows():
            name      = friendly_proxy(row["proxy"])
            t_label   = friendly_type(row["type"], row.get("error_class", ""))
            er        = row.get("error_rate")
            er_str    = f" · {er:.1%} error rate" if er and er > 0 else ""
            sust_str  = " · **Ongoing**" if row.get("sustained") else ""
            st.markdown(f"- **{name}** — {t_label}{er_str}{sust_str}")
