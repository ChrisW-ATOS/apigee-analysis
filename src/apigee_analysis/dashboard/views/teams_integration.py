"""Microsoft Teams Integration — mockup of agent status + conversational query interface.

PREVIEW / MOCKUP ONLY. Demonstrates how the agent pipeline would expose its status
and answer questions directly inside Microsoft Teams once the bot/webhook integration
is built. No live Teams connection exists yet — all content below is illustrative.
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries

_TEAMS_PURPLE = "#6264A7"
_TEAMS_DARK   = "#464775"
_GREEN        = "#22C55E"
_AMBER        = "#F59E0B"
_RED          = "#EF4444"
_MUTED        = "#64748B"


_AGENTS = [
    {"name": "Live Monitoring Agent",     "icon": "🔍", "status": "active", "detail": "Scanning 303 APIs · next scan 4 min"},
    {"name": "Predictive Intelligence",   "icon": "🔮", "status": "active", "detail": "2 cascade risks flagged this hour"},
    {"name": "Proactive Fix Development", "icon": "🛠️", "status": "idle",   "detail": "No fix briefs pending"},
    {"name": "Auto-Deploy / Self-Heal",   "icon": "🚀", "status": "active", "detail": "Fix PR #482 staged, awaiting confidence gate"},
]

_STATUS_COLOR = {"active": _GREEN, "idle": _MUTED, "escalated": _RED}
_STATUS_LABEL = {"active": "ACTIVE", "idle": "IDLE", "escalated": "ESCALATED"}


def _agent_status_row() -> None:
    st.subheader("Agent Status")
    st.caption("Live status of the monitoring → prediction → fix → deploy agent chain, as it would appear queried from Teams.")

    cols = st.columns(4)
    for col, agent in zip(cols, _AGENTS):
        color = _STATUS_COLOR[agent["status"]]
        label = _STATUS_LABEL[agent["status"]]
        with col:
            st.html(f"""
<div style="background:#FFFFFF;border:2px solid {color};border-radius:10px;
            padding:16px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,0.06);
            min-height:150px;">
    <div style="font-size:28px;margin-bottom:6px;">{agent['icon']}</div>
    <div style="font-size:12px;font-weight:700;color:#1E293B;margin-bottom:6px;">
        {agent['name']}
    </div>
    <span style="background:{color};color:#FFFFFF;padding:2px 10px;border-radius:10px;
                 font-size:9px;font-weight:700;letter-spacing:0.05em;">
        {label}
    </span>
    <div style="font-size:10px;color:{_MUTED};margin-top:8px;">
        {agent['detail']}
    </div>
</div>
""")


def _teams_channel_preview() -> None:
    st.subheader("Teams Channel Preview — #api-platform-incidents")
    st.caption("What agent-originated notifications look like when posted into a connected Teams channel.")

    now = datetime.now(timezone.utc).strftime("%H:%M")

    st.html(f"""
<div style="background:#F5F5F9;border-radius:8px;padding:16px;font-family:'Segoe UI',sans-serif;">

    <div style="background:#FFFFFF;border-left:4px solid {_RED};border-radius:6px;
                padding:14px 16px;margin-bottom:10px;box-shadow:0 1px 2px rgba(0,0,0,0.08);">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <div style="width:28px;height:28px;border-radius:50%;background:{_TEAMS_PURPLE};
                        color:#FFFFFF;display:flex;align-items:center;justify-content:center;
                        font-size:13px;font-weight:700;">AI</div>
            <b style="font-size:13px;color:#242424;">API Platform Bot</b>
            <span style="font-size:11px;color:#616161;">{now}</span>
        </div>
        <div style="font-size:13px;color:#242424;line-height:1.5;">
            🔴 <b>New incident detected</b> — Nigeria · NIMC showing 100% server errors,
            sustained 3 hours. Blast radius: 4 partner apps, ~29K calls affected.
            <br><i>Root cause hypothesis: shared auth dependency with USSD Transaction History.</i>
        </div>
        <div style="margin-top:8px;">
            <span style="background:{_TEAMS_PURPLE};color:#FFFFFF;font-size:11px;
                         padding:4px 10px;border-radius:4px;margin-right:6px;">View in Dashboard</span>
            <span style="background:#E1E1E1;color:#242424;font-size:11px;
                         padding:4px 10px;border-radius:4px;">Acknowledge</span>
        </div>
    </div>

    <div style="background:#FFFFFF;border-left:4px solid {_GREEN};border-radius:6px;
                padding:14px 16px;margin-bottom:10px;box-shadow:0 1px 2px rgba(0,0,0,0.08);">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <div style="width:28px;height:28px;border-radius:50%;background:{_TEAMS_PURPLE};
                        color:#FFFFFF;display:flex;align-items:center;justify-content:center;
                        font-size:13px;font-weight:700;">AI</div>
            <b style="font-size:13px;color:#242424;">API Platform Bot</b>
            <span style="font-size:11px;color:#616161;">08:14</span>
        </div>
        <div style="font-size:13px;color:#242424;line-height:1.5;">
            ✅ <b>Auto-resolved</b> — Uganda Service Activation config drift reverted
            automatically. Error rate returned to baseline (0.3%) within 4 minutes.
            No human action required.
        </div>
    </div>

    <div style="background:#FFFFFF;border-left:4px solid {_AMBER};border-radius:6px;
                padding:14px 16px;box-shadow:0 1px 2px rgba(0,0,0,0.08);">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <div style="width:28px;height:28px;border-radius:50%;background:{_TEAMS_PURPLE};
                        color:#FFFFFF;display:flex;align-items:center;justify-content:center;
                        font-size:13px;font-weight:700;">AI</div>
            <b style="font-size:13px;color:#242424;">API Platform Bot</b>
            <span style="font-size:11px;color:#616161;">06:12</span>
        </div>
        <div style="font-size:13px;color:#242424;line-height:1.5;">
            🟡 <b>Fix staged, awaiting approval</b> — Credential rotation ready for
            Nigeria · Customer Bill Management (71% client error rate). Confidence: 0.82.
            Blast radius exceeds auto-deploy threshold — human sign-off required.
        </div>
        <div style="margin-top:8px;">
            <span style="background:{_GREEN};color:#FFFFFF;font-size:11px;
                         padding:4px 10px;border-radius:4px;margin-right:6px;">Approve &amp; Deploy</span>
            <span style="background:#E1E1E1;color:#242424;font-size:11px;
                         padding:4px 10px;border-radius:4px;">Review Fix</span>
        </div>
    </div>

</div>
""")


def _ask_the_platform() -> None:
    st.subheader("Ask the Platform")
    st.caption("Conversational query interface — the same bot users would @mention in Teams.")

    examples = [
        ("Which APIs are at risk right now?",
         "3 APIs are currently flagged as at-risk: Nigeria · NIMC (84% cascade probability, "
         "driven by USSD Transaction History), Ghana · Products, and Rwanda · Resourceconfig. "
         "Full detail is on the API Intelligence page."),
        ("What's our platform availability this month?",
         "96.8% platform-wide, against a 99.5% SLA target. Côte d'Ivoire is the primary "
         "drag at 75.6% availability — driven by a sustained infrastructure-level issue, "
         "not application code."),
        ("Has anything been auto-resolved today?",
         "Yes — 1 incident. Uganda Service Activation config drift was detected at 08:10 "
         "UTC and reverted automatically by 08:14 UTC. Error rate returned to baseline "
         "within 4 minutes, no human involvement required."),
    ]

    for q, a in examples:
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            st.write(a)

    st.chat_input("Ask about platform health, incidents, or agent status... (mock — not connected)", disabled=True)
    st.caption("Mock interface — in production this maps to a Teams bot command backed by the same Claude API used for incident briefs.")


def _connection_status() -> None:
    st.subheader("Connection Status")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.html(f"""
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;padding:14px;">
    <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;letter-spacing:0.05em;">Tenant</div>
    <div style="font-size:14px;font-weight:700;color:#1E293B;margin-top:4px;">mtn.onmicrosoft.com</div>
    <span style="color:{_GREEN};font-size:12px;">● Connected</span>
</div>
""")
    with c2:
        st.html(f"""
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;padding:14px;">
    <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;letter-spacing:0.05em;">Channel</div>
    <div style="font-size:14px;font-weight:700;color:#1E293B;margin-top:4px;">#api-platform-incidents</div>
    <span style="color:{_GREEN};font-size:12px;">● Webhook active</span>
</div>
""")
    with c3:
        st.html(f"""
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;padding:14px;">
    <div style="font-size:11px;color:{_MUTED};text-transform:uppercase;letter-spacing:0.05em;">Bot Identity</div>
    <div style="font-size:14px;font-weight:700;color:#1E293B;margin-top:4px;">API Platform Bot</div>
    <span style="color:{_AMBER};font-size:12px;">● Not yet registered (preview)</span>
</div>
""")


def render(settings: Settings) -> None:
    st.html(f"""
<div style="background:{_TEAMS_DARK};border-radius:12px;padding:20px 28px;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-bottom:6px;">
        💬 Microsoft Teams Integration
    </div>
    <div style="font-size:13px;color:#C7C7DE;line-height:1.6;">
        Preview of how the agent pipeline communicates status and answers questions
        directly inside Microsoft Teams — incident notifications, one-click approvals,
        and a conversational interface backed by the same AI used for incident briefs.
    </div>
</div>
""")

    st.html(f"""
<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;
            padding:10px 16px;margin-bottom:20px;">
    <span style="font-size:12px;color:#92400E;">
        <b>Preview mockup</b> — no live Teams connection exists yet. This page demonstrates
        the intended interaction model for the bot integration.
    </span>
</div>
""")

    _agent_status_row()
    st.divider()
    _teams_channel_preview()
    st.divider()
    _ask_the_platform()
    st.divider()
    _connection_status()
