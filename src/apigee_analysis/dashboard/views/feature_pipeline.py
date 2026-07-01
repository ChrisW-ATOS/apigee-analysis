"""Feature Pipeline — stories moving through the agent SDLC + environment status.

PREVIEW / MOCKUP ONLY. Demonstrates how in-flight feature work would be tracked
across the Planning → Build → Review → Testing → Validation → Deployment agent
chain, and where each change is currently being proven safe (dev, staging, canary,
shadow, production). No live CI/CD or ticketing system is connected yet.
"""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import Settings

_NAVY   = "#1B2A4A"
_GOLD   = "#FFCB05"
_RED    = "#EF4444"
_AMBER  = "#F59E0B"
_GREEN  = "#22C55E"
_BLUE   = "#3B82F6"
_PURPLE = "#7C3AED"
_TEAL   = "#0E7490"
_MUTED  = "#64748B"

_STAGE_COLOR = {
    "Planning":    _BLUE,
    "Build":       _GREEN,
    "Review":      _AMBER,
    "Testing":     "#EC4899",
    "Validation":  _TEAL,
    "Deployment":  _RED,
    "Done":        _MUTED,
}
_STAGE_ICON = {
    "Planning": "①", "Build": "②", "Review": "③",
    "Testing": "④", "Validation": "⑤", "Deployment": "⑥", "Done": "✓",
}

_STAGES = ["Planning", "Build", "Review", "Testing", "Validation", "Deployment", "Done"]

_STORIES = [
    {"id": "FEAT-151", "title": "Add partner-facing SLA dashboard export (PDF)",
     "stage": "Planning", "detail": "Risk register drafted · complexity: medium", "blocker": None},
    {"id": "FEAT-149", "title": "Support multi-region failover for KYC proxies",
     "stage": "Planning", "detail": "Architecture notes in progress", "blocker": "Awaiting infra capacity sign-off"},

    {"id": "FEAT-146", "title": "Credential rotation for Nigeria Bill Management",
     "stage": "Build", "detail": "PR #482 open · 6 tests generated", "blocker": None},
    {"id": "FEAT-144", "title": "Extend cascade model to include traffic-volume correlation",
     "stage": "Build", "detail": "Implementation 70% complete", "blocker": None},

    {"id": "FEAT-141", "title": "Rate-limit auto-tune for high-traffic partner apps",
     "stage": "Review", "detail": "2 findings — 1 medium severity (input validation)", "blocker": "Awaiting review agent re-scan"},

    {"id": "FEAT-138", "title": "Config-drift auto-revert for Uganda Service Activation",
     "stage": "Testing", "detail": "84.2% coverage · edge cases generated: 9", "blocker": None},

    {"id": "FEAT-135", "title": "Predictive SLA-breach early warning (30-day)",
     "stage": "Validation", "detail": "Load test passed · chaos injection pending", "blocker": None},

    {"id": "FEAT-130", "title": "Isolation Forest retraining cadence → 6-hourly",
     "stage": "Deployment", "detail": "Canary 25% · health checks nominal", "blocker": None},

    {"id": "FEAT-127", "title": "STL seasonality window auto-adjust per proxy",
     "stage": "Done", "detail": "Deployed 07:58 UTC · commit a3f21c9", "blocker": None},
    {"id": "FEAT-121", "title": "Blast radius: include indirect (2-hop) dependencies",
     "stage": "Done", "detail": "Deployed 3 days ago · stable", "blocker": None},
]

_ENVIRONMENTS = [
    {"name": "Development", "icon": "🧪", "status": "healthy",
     "version": "main @ f88e102", "traffic": "0% (synthetic only)",
     "focus": "FEAT-144 cascade model extension — unit tests running"},
    {"name": "Staging", "icon": "🏗️", "status": "healthy",
     "version": "release/1.42 @ c710aa4", "traffic": "0% (synthetic + replay)",
     "focus": "FEAT-138 config-drift auto-revert — integration suite"},
    {"name": "Canary", "icon": "🐤", "status": "testing",
     "version": "release/1.41 @ a3f21c9", "traffic": "25% of production",
     "focus": "FEAT-130 retraining cadence change — health checks nominal"},
    {"name": "Shadow (Live Stress Test)", "icon": "⚡", "status": "healthy",
     "version": "mirrors production", "traffic": "100% replayed (read-only)",
     "focus": "Continuous production-traffic replay — probing capacity limits ahead of real load"},
    {"name": "Production", "icon": "🌐", "status": "healthy",
     "version": "release/1.40 @ 9b2e771", "traffic": "100% live",
     "focus": "Stable · last deploy 07:58 UTC"},
]
_ENV_STATUS_COLOR = {"healthy": _GREEN, "testing": _AMBER, "degraded": _RED}


def _mock_banner() -> None:
    st.html("""
<div style="background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;
            padding:10px 16px;margin-bottom:20px;">
    <span style="font-size:12px;color:#92400E;">
        <b>Preview mockup</b> — no live ticketing or CI/CD system is connected yet.
        Story cards and environment state below are illustrative, demonstrating how
        in-flight work would be tracked across the agent pipeline once integrated with
        the build/deploy tooling.
    </span>
</div>
""")


def _kpi_row() -> None:
    n_by_stage = {s: sum(1 for st_ in _STORIES if st_["stage"] == s) for s in _STAGES}
    in_flight  = sum(v for k, v in n_by_stage.items() if k != "Done")
    blocked    = sum(1 for s in _STORIES if s["blocker"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stories In Flight",     in_flight)
    c2.metric("Blocked",               blocked, delta_color="inverse")
    c3.metric("Avg. Cycle Time",       "3.2 days", delta="-0.6d vs last month")
    c4.metric("Deploy Frequency",      "7 / day")


def _story_card(story: dict) -> None:
    stage  = story["stage"]
    color  = _STAGE_COLOR[stage]
    icon   = _STAGE_ICON[stage]
    blocker_html = (
        f"""<div style="margin-top:8px;font-size:11px;color:#991B1B;background:#FEF2F2;
                        border-radius:4px;padding:4px 8px;">⚠ {story['blocker']}</div>"""
        if story["blocker"] else ""
    )
    st.html(f"""
<div style="background:#FFFFFF;border-left:4px solid {color};border-radius:6px;
            padding:12px 14px;margin-bottom:10px;box-shadow:0 1px 2px rgba(0,0,0,0.06);">
    <div style="font-size:10px;color:{_MUTED};font-weight:700;letter-spacing:0.04em;">
        {icon} {story['id']}
    </div>
    <div style="font-size:12px;color:#1E293B;font-weight:600;margin:4px 0 6px 0;line-height:1.4;">
        {story['title']}
    </div>
    <div style="font-size:10px;color:{_MUTED};">
        {story['detail']}
    </div>
    {blocker_html}
</div>
""")


def _kanban_board() -> None:
    st.subheader("Pipeline Board")
    st.caption("Stories tracked as they move through the same agent chain that builds and ships every change.")

    cols = st.columns(len(_STAGES))
    for col, stage in zip(cols, _STAGES):
        with col:
            color = _STAGE_COLOR[stage]
            count = sum(1 for s in _STORIES if s["stage"] == stage)
            st.html(f"""
<div style="background:{color};color:#FFFFFF;border-radius:6px 6px 0 0;
            padding:8px 10px;text-align:center;font-size:11px;font-weight:700;
            letter-spacing:0.04em;">
    {_STAGE_ICON[stage]} {stage.upper()} ({count})
</div>
""")
            for story in _STORIES:
                if story["stage"] == stage:
                    _story_card(story)


def _quality_gates() -> None:
    st.subheader("Active Quality Gates — PR #482 (FEAT-146)")
    st.caption("The furthest-along in-flight change, showing every gate it must clear before deployment.")

    gates = [
        ("Static analysis (SAST)", "pass", "0 critical, 0 high findings"),
        ("Unit + integration tests", "pass", "84.2% coverage, 142/142 passing"),
        ("Security review", "pass", "No credential/secret exposure detected"),
        ("SLA compliance simulation", "pending", "Validation agent queued — ETA 4 min"),
        ("Chaos / failure injection", "pending", "Awaiting SLA simulation result"),
        ("Confidence threshold (auto-deploy)", "pending", "Requires ≥0.85 — currently 0.82"),
    ]
    cols = st.columns(3)
    for i, (name, status, detail) in enumerate(gates):
        color = _GREEN if status == "pass" else _AMBER
        icon  = "✓" if status == "pass" else "⏳"
        with cols[i % 3]:
            st.html(f"""
<div style="background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;
            padding:12px 14px;margin-bottom:10px;">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
        <span style="font-size:12px;font-weight:700;color:#1E293B;">{name}</span>
        <span style="color:{color};font-size:14px;">{icon}</span>
    </div>
    <div style="font-size:10px;color:{_MUTED};">{detail}</div>
</div>
""")


def _environment_grid() -> None:
    st.subheader("Environment Status")
    st.caption("Where each change is currently being proven safe before reaching production.")

    cols = st.columns(len(_ENVIRONMENTS))
    for col, env in zip(cols, _ENVIRONMENTS):
        color = _ENV_STATUS_COLOR[env["status"]]
        with col:
            st.html(f"""
<div style="background:#FFFFFF;border:2px solid {color};border-radius:10px;
            padding:14px;min-height:190px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
    <div style="font-size:24px;margin-bottom:4px;">{env['icon']}</div>
    <div style="font-size:12px;font-weight:700;color:#1E293B;margin-bottom:6px;">
        {env['name']}
    </div>
    <span style="background:{color};color:#FFFFFF;padding:2px 8px;border-radius:8px;
                 font-size:9px;font-weight:700;letter-spacing:0.04em;">
        {env['status'].upper()}
    </span>
    <div style="font-size:10px;color:{_MUTED};margin-top:8px;">
        <b>Version:</b> {env['version']}<br>
        <b>Traffic:</b> {env['traffic']}
    </div>
    <div style="font-size:10px;color:#374151;margin-top:8px;border-top:1px solid #F1F5F9;
                padding-top:6px;">
        {env['focus']}
    </div>
</div>
""")

    st.html(f"""
<div style="background:#FFF7ED;border:1px solid #FDBA74;border-radius:8px;
            padding:12px 16px;margin-top:14px;">
    <span style="font-size:12px;color:#9A3412;">
        <b>⚡ Shadow environment</b> continuously replays real production traffic patterns
        against a mirror of the live system — the same mechanism the Live Monitoring Agent
        uses to identify APIs approaching capacity limits before real traffic gets there,
        feeding directly into the Proactive Fix Development Agent.
    </span>
</div>
""")


def render(settings: Settings, embedded: bool = False) -> None:
    if not embedded:
        st.html(f"""
<div style="background:{_NAVY};border-radius:12px;padding:20px 28px;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:800;color:#FFFFFF;margin-bottom:6px;">
        Feature Pipeline
    </div>
    <div style="font-size:13px;color:#94A3B8;line-height:1.6;">
        In-flight feature and fix work as it moves through the agent SDLC — and where
        each change is currently being validated before it reaches production.
    </div>
</div>
""")

    _mock_banner()
    _kpi_row()
    st.divider()
    _kanban_board()
    st.divider()
    _quality_gates()
    st.divider()
    _environment_grid()
