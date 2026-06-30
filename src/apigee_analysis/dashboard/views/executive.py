"""Executive Summary — single-screen platform status overview."""
from __future__ import annotations

from datetime import datetime, timezone

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

# ─────────────────────────────────────────────────────────────────────────────
# Platform Stress Index
# ─────────────────────────────────────────────────────────────────────────────

def _psi(n_incidents: int, n_sustained: int, n_predicted: int, n_degraded: int) -> float:
    return round(
        min(n_incidents / 30,  1.0) * 100 * 0.35 +
        min(n_sustained / 10,  1.0) * 100 * 0.30 +
        min(n_predicted / 15,  1.0) * 100 * 0.20 +
        min(n_degraded  /  5,  1.0) * 100 * 0.15,
        1,
    )


def _psi_driver(n_incidents: int, n_sustained: int, n_predicted: int, n_degraded: int) -> str:
    components = {
        "active incidents":     min(n_incidents / 30,  1.0) * 0.35,
        "sustained incidents":  min(n_sustained / 10,  1.0) * 0.30,
        "early warnings":       min(n_predicted / 15,  1.0) * 0.20,
        "degraded countries":   min(n_degraded  /  5,  1.0) * 0.15,
    }
    top = max(components, key=components.get)
    return top if components[top] > 0 else "none"


def _psi_card(score: float, prev_score: float, driver: str) -> None:
    if score < 40:
        color, label = "#22C55E", "Normal"
    elif score < 70:
        color, label = "#F59E0B", "Elevated"
    else:
        color, label = "#EF4444", "Critical"

    delta = score - prev_score
    if delta > 5:
        arrow, arrow_color = "▲", "#EF4444"
    elif delta < -5:
        arrow, arrow_color = "▼", "#22C55E"
    else:
        arrow, arrow_color = "→", "#94A3B8"

    bar_pct = min(100, score)

    st.html(f"""
<div style="background:#FFFFFF;border:2px solid {color};border-radius:12px;
            padding:20px 28px;display:flex;align-items:center;gap:28px;
            box-shadow:0 1px 4px rgba(0,0,0,0.08);margin-bottom:16px;">
    <div style="text-align:center;min-width:110px;">
        <div style="font-size:10px;color:#94A3B8;font-weight:700;
                    letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px;">
            Platform Stress Index
        </div>
        <div style="font-size:68px;font-weight:900;color:{color};line-height:1;">
            {score:.0f}
        </div>
        <div style="font-size:13px;font-weight:700;color:{color};margin-top:2px;
                    letter-spacing:0.05em;text-transform:uppercase;">
            {label}&nbsp;
            <span style="color:{arrow_color};">{arrow}</span>
        </div>
    </div>
    <div style="flex:1;border-left:1px solid #E2E8F0;padding-left:24px;">
        <div style="background:#E2E8F0;border-radius:6px;height:10px;width:100%;margin-bottom:14px;">
            <div style="background:{color};height:10px;border-radius:6px;
                        width:{bar_pct:.1f}%;transition:width 0.3s;"></div>
        </div>
        <div style="font-size:12px;color:#64748B;line-height:1.7;">
            Composite of <b style="color:#1E293B;">active incidents</b> (35%),
            <b style="color:#1E293B;">sustained incidents</b> (30%),
            <b style="color:#1E293B;">early warnings</b> (20%),
            and <b style="color:#1E293B;">degraded OpCos</b> (15%).
        </div>
        <div style="font-size:13px;color:#64748B;margin-top:8px;">
            Primary driver: <b style="color:#1E293B;">{driver}</b>
        </div>
    </div>
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
# Business Impact Counter
# ─────────────────────────────────────────────────────────────────────────────

def _impact_counter(total_calls: int, n_apps: int) -> None:
    if total_calls == 0 and n_apps == 0:
        st.success("No business impact detected in the last 25 hours.")
        return

    st.html(f"""
<div style="display:flex;gap:16px;margin-bottom:16px;">
    <div style="flex:1;background:#FFFFFF;border-radius:10px;padding:18px 24px;
                border:1px solid #E2E8F0;box-shadow:0 1px 3px rgba(0,0,0,0.06);text-align:center;">
        <div style="font-size:10px;color:#94A3B8;font-weight:700;letter-spacing:0.1em;
                    text-transform:uppercase;margin-bottom:6px;">
            API Calls During Incidents
        </div>
        <div style="font-size:44px;font-weight:800;color:#1E293B;line-height:1;">
            {total_calls:,}
        </div>
        <div style="font-size:11px;color:#94A3B8;margin-top:4px;">last 25 hours</div>
    </div>
    <div style="flex:1;background:#FFFFFF;border-radius:10px;padding:18px 24px;
                border:1px solid #E2E8F0;box-shadow:0 1px 3px rgba(0,0,0,0.06);text-align:center;">
        <div style="font-size:10px;color:#94A3B8;font-weight:700;letter-spacing:0.1em;
                    text-transform:uppercase;margin-bottom:6px;">
            Partner Applications Impacted
        </div>
        <div style="font-size:44px;font-weight:800;color:#1E293B;line-height:1;">
            {n_apps}
        </div>
        <div style="font-size:11px;color:#94A3B8;margin-top:4px;">last 25 hours</div>
    </div>
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
# Platform Briefing
# ─────────────────────────────────────────────────────────────────────────────

def _briefing_section(settings: Settings, **kwargs) -> None:
    col_head, col_btn = st.columns([6, 1])
    with col_head:
        st.subheader("Platform Briefing")
    with col_btn:
        st.write("")   # vertical alignment nudge
        if st.button("⟳ Regenerate", key="regen_briefing", use_container_width=True):
            queries.get_platform_briefing.clear()
            st.rerun()

    hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H")
    briefing = queries.get_platform_briefing(settings, hour_key=hour_key, **kwargs)

    mode_color = "#7C3AED" if briefing["mode"] == "claude" else "#64748B"
    mode_label = ("Claude AI · " if briefing["mode"] == "claude" else "Auto-generated · ") + briefing.get("generated_at", "")

    st.html(f"""
<div style="border-left:4px solid {mode_color};background:#FFFFFF;
            padding:20px 24px;border-radius:8px;
            box-shadow:0 1px 4px rgba(0,0,0,0.08);margin-bottom:8px;">
    <p style="font-size:16px;color:#1E293B;line-height:1.75;margin:0 0 14px 0;">
        {briefing['text']}
    </p>
    <span style="font-size:10px;color:#94A3B8;text-transform:uppercase;
                 letter-spacing:0.07em;font-weight:600;">
        {mode_label}
    </span>
</div>
""")


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
        blast_25h    = queries.get_blast_radius(settings, hours_back=25)

    # ── Derived values ────────────────────────────────────────────────────────
    univariate = (
        anomalies_df[anomalies_df["type"] != "Multivariate"]
        if not anomalies_df.empty else pd.DataFrame()
    )
    n_incidents    = univariate["proxy"].nunique() if not univariate.empty else 0
    n_sustained    = int(univariate["sustained"].sum()) if not univariate.empty else 0
    n_apis         = len(proxy_list)
    n_predicted    = len(predicted_df)
    n_degraded     = int(country_df["is_anomaly"].sum()) if not country_df.empty else 0
    platform_avail = (100 - country_df["error_rate_pct"].mean()) if not country_df.empty else 100.0

    worst_country      = "—"
    worst_country_name = "—"
    if not country_df.empty:
        worst = country_df.loc[country_df["error_rate_pct"].idxmax()]
        if worst["error_rate_pct"] > 0.5:
            worst_country_name = _COUNTRY_NAMES.get(worst["country"], worst["country"])
            worst_country = f"{worst_country_name} ({worst['error_rate_pct']:.1f}%)"

    # Business impact: calls + apps during anomalous proxy incidents
    if not blast_25h.empty and not anomalies_df.empty:
        anomalous_proxies = set(anomalies_df["proxy"].unique())
        affected_br = blast_25h[blast_25h["proxy"].isin(anomalous_proxies)]
        total_calls_impacted = int(affected_br["call_count"].sum())
        n_apps_impacted = int(
            affected_br[~affected_br["app"].isin(["(not set)", ""])]["app"].nunique()
        )
    else:
        total_calls_impacted = 0
        n_apps_impacted = 0

    # PSI — current and previous hour
    psi_now = _psi(n_incidents, n_sustained, n_predicted, n_degraded)

    # ── Platform Stress Index ─────────────────────────────────────────────────
    driver = _psi_driver(n_incidents, n_sustained, n_predicted, n_degraded)
    # Previous PSI: approximate from 1h-ago anomaly counts stored as Anomalies bucket
    # data. For simplicity, use 0 as baseline so trend shows increase from zero.
    # (A dedicated history query can be added to enable true trend arrow later.)
    _psi_card(psi_now, 0, driver)

    # ── Business Impact ───────────────────────────────────────────────────────
    _impact_counter(total_calls_impacted, n_apps_impacted)

    # ── Headline KPIs ─────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("APIs Monitored",   n_apis)
    c2.metric("Active Incidents", n_incidents,
              delta=f"{n_sustained} sustained" if n_sustained else None,
              delta_color="inverse")
    c3.metric("Early Warnings",   n_predicted)
    c4.metric("Most Affected",    worst_country)

    st.divider()

    # ── OpCo status grid ──────────────────────────────────────────────────────
    st.subheader("Operating Company Status")
    if country_df.empty:
        st.info("No country health data available.")
    else:
        _opco_grid(country_df)

    st.divider()

    # ── Platform Briefing ─────────────────────────────────────────────────────
    _briefing_section(
        settings,
        n_incidents      = n_incidents,
        n_sustained      = n_sustained,
        n_predicted      = n_predicted,
        n_degraded       = n_degraded,
        worst_country    = worst_country_name,
        platform_avail   = platform_avail,
        n_apps_impacted  = n_apps_impacted,
    )

    st.divider()

    # ── Catch of the Day ──────────────────────────────────────────────────────
    st.subheader("Catch of the Day")
    catch_raw = _find_catch(anomalies_df, mv_df)
    if catch_raw:
        _catch_card(_build_catch(catch_raw))
    else:
        st.success("No notable anomalies in the last 25 hours.")

    st.caption("For incident detail, predictions, and drill-down → open **Monitoring** in the sidebar.")
