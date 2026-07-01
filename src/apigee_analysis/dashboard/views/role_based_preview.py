"""Role-Based Views — mockup of Microsoft Entra ID role-tailored dashboards.

PREVIEW / MOCKUP ONLY. This page demonstrates how the platform would present
different information to different Entra ID (Azure AD) roles once tenant
integration is wired up. Some data is pulled live from InfluxDB; ticket queues,
budget figures, on-call rosters, and similar operational detail are illustrative
placeholders standing in for systems (ServiceNow, PagerDuty, Teams) not yet
connected.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy

_NAVY   = "#1B2A4A"
_GOLD   = "#FFCB05"
_RED    = "#EF4444"
_AMBER  = "#F59E0B"
_GREEN  = "#22C55E"
_BLUE   = "#3B82F6"
_PURPLE = "#7C3AED"
_MUTED  = "#64748B"


def _mock_banner(role_name: str, entra_role: str) -> None:
    st.html(f"""
<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;
            padding:10px 16px;margin-bottom:16px;display:flex;
            align-items:center;justify-content:space-between;">
    <span style="font-size:12px;color:#92400E;">
        <b>Preview mockup</b> — demonstrates the {role_name} view once Microsoft Entra ID
        role claims are wired up. Some data below is illustrative.
    </span>
    <span style="background:{_NAVY};color:#FFFFFF;padding:3px 10px;border-radius:10px;
                 font-size:10px;font-weight:700;letter-spacing:0.05em;">
        ENTRA ROLE: {entra_role.upper()}
    </span>
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
# Managerial Overview
# ─────────────────────────────────────────────────────────────────────────────

def _managerial_tab(settings: Settings) -> None:
    _mock_banner("Managerial", "Executive")

    with st.spinner("Loading..."):
        country_df = queries.get_country_health(settings)
        anomalies  = queries.get_active_anomalies(settings)

    n_incidents = anomalies[anomalies["type"] != "Multivariate"]["proxy"].nunique() if not anomalies.empty else 0
    avg_avail   = 100 - country_df["error_rate_pct"].mean() if not country_df.empty else 99.6

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Platform Availability (QTD)", f"{avg_avail:.2f}%", delta="+0.3pp vs last quarter")
    c2.metric("Est. Downtime Cost Avoided",  "$184,000", delta="This quarter", delta_color="off")
    c3.metric("Autonomously Resolved",       "37 incidents", delta="No human involvement needed")
    c4.metric("Active Incidents Now",        n_incidents, delta_color="inverse")

    st.divider()

    col_l, col_r = st.columns([3, 2])

    with col_l:
        st.subheader("Incident Volume Trend")
        months = [(datetime.now(timezone.utc) - timedelta(days=30 * i)).strftime("%b") for i in range(5, -1, -1)]
        incident_counts = [61, 54, 48, 39, 28, 22]
        auto_resolved    = [12, 18, 21, 24, 29, 33]

        fig = go.Figure()
        fig.add_trace(go.Bar(x=months, y=incident_counts, name="Total incidents",
                              marker_color=_MUTED, opacity=0.5))
        fig.add_trace(go.Bar(x=months, y=auto_resolved, name="Auto-resolved by agents",
                              marker_color=_GREEN))
        fig.update_layout(
            barmode="overlay", height=300, plot_bgcolor="#FAFAFA", paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Illustrative trend — agent-driven auto-resolution rate has grown from 20% to 60% of total incidents over 6 months.")

    with col_r:
        st.subheader("Top Strategic Risks")
        st.markdown("""
1. **Nigeria KYC dependency cluster** — 5 APIs share a single backend auth
   service; a failure there cascades platform-wide in that market.
2. **Côte d'Ivoire chronic degradation** — sustained ~30% error rate; root
   cause likely infrastructure, not application — needs capital investment case.
3. **Partner integration drift** — 3 partner apps have not adopted the latest
   API contract version, creating avoidable 4xx load.
""")
        st.subheader("Investment ROI This Quarter")
        st.html(f"""
<div style="background:{_NAVY};border-radius:8px;padding:16px 20px;">
    <div style="color:{_GOLD};font-size:28px;font-weight:800;">$184K</div>
    <div style="color:#CBD5E1;font-size:12px;">
        Estimated cost of downtime avoided through predictive detection and
        autonomous remediation, vs. prior-quarter reactive-only baseline.
    </div>
</div>
""")

    st.divider()
    st.caption(
        "Managerial role (Entra ID group: `mtn-api-platform-exec`) sees quarter-level "
        "trends, financial framing, and strategic risk — not raw telemetry."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Monitoring / NOC
# ─────────────────────────────────────────────────────────────────────────────

def _monitoring_noc_tab(settings: Settings) -> None:
    _mock_banner("Monitoring / NOC", "Monitoring-NOC")

    with st.spinner("Loading..."):
        country_df = queries.get_country_health(settings)
        anomalies  = queries.get_active_anomalies(settings)

    uni = anomalies[anomalies["type"] != "Multivariate"] if not anomalies.empty else pd.DataFrame()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Systems Monitored",   len(country_df) if not country_df.empty else 15)
    c2.metric("Active Alerts",       len(uni))
    c3.metric("On-Call Engineer",    "S. Adeyemi")
    c4.metric("Next Rotation",       "Fri 08:00 UTC")

    st.divider()
    col_l, col_r = st.columns([2, 1])

    with col_l:
        st.subheader("Live Alert Queue")
        if uni.empty:
            st.success("No active alerts.")
        else:
            display = uni.sort_values("z_score", key=lambda s: s.abs(), ascending=False).head(8).copy()
            display["API"]      = display["proxy"].apply(friendly_proxy)
            display["Signal"]   = display["z_score"].apply(lambda x: f"{abs(x):.1f}σ")
            display["Sustained"] = display["sustained"].apply(lambda x: "🔴 Yes" if x else "🟡 New")
            st.dataframe(
                display[["API", "type", "Signal", "Sustained"]].rename(columns={"type": "Category"}),
                use_container_width=True, hide_index=True,
            )

    with col_r:
        st.subheader("Escalation Policy")
        st.html(f"""
<div style="background:#F0FDF4;border:1px solid #86EFAC;border-radius:8px;padding:12px 16px;margin-bottom:10px;">
    <b style="color:#166534;">✓ Tier 1</b><br>
    <span style="font-size:12px;color:#166534;">Auto-triage active — routing to on-call</span>
</div>
<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;padding:12px 16px;margin-bottom:10px;">
    <b style="color:#92400E;">Tier 2</b><br>
    <span style="font-size:12px;color:#92400E;">Escalates after 15 min unacknowledged</span>
</div>
<div style="background:#FEF2F2;border:1px solid #FCA5A5;border-radius:8px;padding:12px 16px;">
    <b style="color:#991B1B;">Tier 3</b><br>
    <span style="font-size:12px;color:#991B1B;">Pages engineering lead + posts to Teams #incidents</span>
</div>
""")

    st.divider()
    st.subheader("On-Call Roster (This Week)")
    roster = pd.DataFrame([
        {"Day": "Mon–Tue", "Primary": "S. Adeyemi", "Secondary": "K. Mokoena"},
        {"Day": "Wed–Thu", "Primary": "K. Mokoena",  "Secondary": "R. Osei"},
        {"Day": "Fri–Sun",  "Primary": "R. Osei",     "Secondary": "S. Adeyemi"},
    ])
    st.dataframe(roster, use_container_width=True, hide_index=True)
    st.caption(
        "Monitoring/NOC role (Entra ID group: `mtn-api-platform-noc`) sees live "
        "operational state, escalation policy, and on-call rotation — sourced from "
        "PagerDuty integration (not yet connected in this preview)."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Support
# ─────────────────────────────────────────────────────────────────────────────

def _support_tab(settings: Settings) -> None:
    _mock_banner("Customer Support", "Support")

    with st.spinner("Loading..."):
        blast = queries.get_blast_radius(settings, hours_back=25)

    c1, c2, c3 = st.columns(3)
    c1.metric("Customers Currently Affected", "4")
    c2.metric("Open Support Tickets",         "11", delta="+3 today", delta_color="inverse")
    c3.metric("Avg. Response Time",            "8 min")

    st.divider()
    st.subheader("Customers Currently Affected")

    top_apps = []
    if not blast.empty:
        top_apps = (
            blast[~blast["app"].isin(["(not set)", ""])]
            .groupby("app")["call_count"].sum()
            .sort_values(ascending=False)
            .head(4)
            .index.tolist()
        )
    if not top_apps:
        top_apps = ["tchokokash", "FCMB Integration", "timwe-prod", "Access Bank KYC"]

    tickets = pd.DataFrame([
        {"Customer": top_apps[0] if len(top_apps) > 0 else "tchokokash",
         "Issue": "KYC verification failing intermittently", "Status": "🔴 Investigating", "ETA": "30 min"},
        {"Customer": top_apps[1] if len(top_apps) > 1 else "FCMB Integration",
         "Issue": "Elevated 4xx on bill management API", "Status": "🟡 Fix staged", "ETA": "10 min"},
        {"Customer": top_apps[2] if len(top_apps) > 2 else "timwe-prod",
         "Issue": "Slow response on notification service", "Status": "🟢 Monitoring", "ETA": "Resolved, watching"},
        {"Customer": top_apps[3] if len(top_apps) > 3 else "Access Bank KYC",
         "Issue": "Consent validation timeouts", "Status": "🔴 Investigating", "ETA": "45 min"},
    ])
    st.dataframe(tickets, use_container_width=True, hide_index=True)

    st.divider()
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Known Issues Board")
        st.markdown("**🔴 Investigating**")
        st.markdown("- Nigeria KYC cluster — backend auth dependency")
        st.markdown("**🟡 Fix Staged**")
        st.markdown("- Bill management 4xx — credential rotation queued")
        st.markdown("**🟢 Resolved (last 24h)**")
        st.markdown("- Uganda service activation — config revert deployed 02:14 UTC")

    with col_r:
        st.subheader("Generate Customer Response")
        st.text_area(
            "Draft response",
            value=(
                "Hi team,\n\nWe've identified an intermittent issue affecting KYC "
                "verification calls and our engineering team is actively working on "
                "a resolution. Current ETA is approximately 30 minutes. We'll update "
                "you as soon as service is fully restored.\n\nApologies for the "
                "inconvenience.\n"
            ),
            height=160,
        )
        st.button("✉️  Send via Teams to account manager", disabled=True)
        st.caption("Mock — drafts a response using the AI incident brief, ready to route to Teams.")

    st.divider()
    st.caption(
        "Support role (Entra ID group: `mtn-api-platform-support`) sees customer-facing "
        "impact, not raw signal data — designed to answer 'who do I call and what do I tell them'."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Developer
# ─────────────────────────────────────────────────────────────────────────────

def _developer_tab(settings: Settings) -> None:
    _mock_banner("Developer", "Developer")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open PRs (agent-authored)", "3")
    c2.metric("Deploys Today",             "7")
    c3.metric("Test Coverage",             "84.2%", delta="+1.1pp")
    c4.metric("Build Agent Status",        "🟢 Active")

    st.divider()
    col_l, col_r = st.columns([3, 2])

    with col_l:
        st.subheader("Agent Pipeline Status")
        stages = [
            ("① Planning",   "🟢 Idle",     "Last run 09:14 UTC"),
            ("② Build",      "🟢 Active",   "PR #482 — credential rotation fix"),
            ("③ Review",     "🟡 Pending",  "Awaiting build agent output"),
            ("④ Testing",    "🟢 Idle",     "Last run passed — 84.2% coverage"),
            ("⑤ Validation", "🟢 Idle",     "SLA check passed 08:02 UTC"),
            ("⑥ Deployment", "🟢 Idle",     "Last deploy 07:58 UTC · commit a3f21c9"),
        ]
        for name, status, detail in stages:
            st.markdown(f"**{name}** — {status}  \n<span style='color:{_MUTED};font-size:12px;'>{detail}</span>",
                        unsafe_allow_html=True)

        st.subheader("Recent Deploys")
        deploys = pd.DataFrame([
            {"Time": "07:58 UTC", "Commit": "a3f21c9", "Author": "build-agent", "Result": "✅ Healthy"},
            {"Time": "06:12 UTC", "Commit": "f88e102", "Author": "fix-dev-agent", "Result": "✅ Healthy"},
            {"Time": "02:14 UTC", "Commit": "c710aa4", "Author": "fix-dev-agent", "Result": "✅ Healthy (auto-rollback tested)"},
        ])
        st.dataframe(deploys, use_container_width=True, hide_index=True)

    with col_r:
        st.subheader("Live Log Tail")
        st.code(
            "[09:14:02] planning-agent: no new tasks queued\n"
            "[09:12:41] build-agent: PR #482 opened (credential_rotation)\n"
            "[09:12:39] build-agent: tests generated (6 new cases)\n"
            "[08:02:15] validation-agent: SLA check PASSED\n"
            "[07:58:03] deploy-agent: canary 100% — commit a3f21c9\n"
            "[07:55:00] deploy-agent: canary 25% — health OK\n",
            language="log",
        )
        st.subheader("Quick Links")
        st.markdown("""
- 🔗 [Repository](#) `apigee-analysis`
- 📘 [Runbook: APIGEE-IR-001](#) — Credential Rotation
- 📘 [Runbook: APIGEE-IR-002](#) — Config Review
- 📊 [API Contract Registry](#)
""")

    st.divider()
    st.caption(
        "Developer role (Entra ID group: `mtn-api-platform-dev`) sees agent pipeline "
        "internals, deploy history, and logs — the only role with write-adjacent visibility."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Page render
# ─────────────────────────────────────────────────────────────────────────────

def render(settings: Settings, embedded: bool = False) -> None:
    if not embedded:
        st.html(f"""
<div style="background:{_NAVY};border-radius:12px;padding:20px 28px;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-bottom:6px;">
        Role-Based Views
    </div>
    <div style="font-size:13px;color:#94A3B8;line-height:1.6;">
        Preview of how the platform will present tailored views once integrated with
        Microsoft Entra ID (Azure AD). A user's group membership determines which of
        these views they land on when they sign in — no manual configuration required.
    </div>
</div>
""")

    tabs = st.tabs([
        "📊  Managerial Overview",
        "🖥️  Monitoring / NOC",
        "🎧  Support",
        "💻  Developer",
    ])

    with tabs[0]:
        _managerial_tab(settings)
    with tabs[1]:
        _monitoring_noc_tab(settings)
    with tabs[2]:
        _support_tab(settings)
    with tabs[3]:
        _developer_tab(settings)
