"""Incident Response — developer-focused triage, explanation, and resolution."""
from __future__ import annotations

import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy

# ─────────────────────────────────────────────────────────────────────────────
# Template intelligence — effect, hypothesis, fix, auto-resolve classification
# ─────────────────────────────────────────────────────────────────────────────

def _effect(name, ec, error_rate, total_calls, n_apps, n_countries, hours):
    ec_str   = "app errors (4xx)" if ec == "client" else "service failures (5xx)"
    duration = f"over the last {hours} hour{'s' if hours != 1 else ''}" if hours > 1 else "in the last hour"
    impact   = f"{int(total_calls):,} API calls" if total_calls > 0 else "an unknown number of calls"
    partners = f"{n_apps} partner application{'s' if n_apps != 1 else ''}" if n_apps > 0 else "partner applications"
    spread   = f" across {n_countries} countr{'ies' if n_countries != 1 else 'y'}" if n_countries > 1 else ""
    rate_str = f" at a {error_rate:.0%} failure rate" if error_rate > 0 else ""
    return (
        f"**{name}** is generating {ec_str}{rate_str}. "
        f"{impact} have failed {duration}, affecting {partners}{spread}."
    )


def _hypothesis(ec, error_rate, hours, proxy_name):
    if ec == "server":
        if error_rate > 0.9:
            return (
                "Near-total server-side failure suggests a complete backend outage — "
                "infrastructure crash, network partition, or unresponsive dependency service. "
                "Not a client or configuration issue."
            )
        elif hours > 3:
            return (
                "Sustained 5xx errors over multiple hours point to resource exhaustion, "
                "a memory leak, or a degraded downstream dependency (database, cache, or "
                "upstream API). Gradual degradation rather than sudden failure."
            )
        return (
            "Backend service failure — likely caused by a recent deployment, "
            "a dependency timeout, or a transient infrastructure event. "
            "Check service health dashboards and recent release activity."
        )
    else:  # client
        if error_rate > 0.8:
            return (
                "Near-total request rejection on 4xx suggests expired or revoked credentials, "
                "an API key rotation that wasn't propagated, or a breaking change to the "
                "authentication contract. Client code is making structurally invalid requests."
            )
        elif hours > 3:
            return (
                "Persistent 4xx errors indicate a configuration drift — credentials may have "
                "partially expired, rate limits may have changed, or an API contract update "
                "was not reflected in the calling application."
            )
        return (
            "Client-side request failures — check authentication tokens, API keys, "
            "and whether recent changes to the API contract or calling application "
            "are compatible with the current endpoint specification."
        )


def _steps(ec, error_rate, hours):
    if ec == "server":
        return [
            "Check the backend service health dashboard for the affected proxy",
            "Review deployment history for the last 4 hours — roll back if a recent change is suspected",
            "Inspect service logs for stack traces, timeouts, or OOM errors",
            "Verify connectivity to downstream dependencies (database, cache, upstream APIs)",
            "Monitor error rate after each action — confirm recovery before closing",
        ]
    else:
        if error_rate > 0.7:
            return [
                "Verify API credentials and authentication tokens for the affected proxy",
                "Check whether credentials were rotated or revoked recently",
                "Confirm the calling application is using the current token/key format",
                "If credential expiry is confirmed, rotate and re-deploy credentials",
                "Monitor error rate — 4xx should drop immediately on credential fix",
            ]
        return [
            "Review rate limit configuration — check if limits were recently reduced",
            "Inspect calling application for recent changes to request format or headers",
            "Verify the API contract version — check for breaking changes in the endpoint spec",
            "Review error response bodies for specific rejection reasons (401, 403, 429, etc.)",
            "Coordinate with the partner development team if the issue persists",
        ]


def _auto_resolve_type(ec, error_rate, hours):
    """Returns the auto-resolve category or None if not a routine fix."""
    if ec == "client" and error_rate > 0.70 and hours >= 1:
        return "credential_rotation"
    if ec == "client" and error_rate > 0.30 and hours >= 2:
        return "config_review"
    return None


_AUTO_RESOLVE_LABELS = {
    "credential_rotation": ("🔑 Credential Rotation", "#7C3AED"),
    "config_review":       ("⚙️  Config Review",       "#2563EB"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Resolve — architecture flow + pseudo-code + mock dispatch
# ─────────────────────────────────────────────────────────────────────────────

_ARCH_FLOW = """
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         AI AGENT EXECUTION ARCHITECTURE                         │
└─────────────────────────────────────────────────────────────────────────────────┘

  ┌────────────────┐     ┌───────────────────┐     ┌──────────────────────────┐
  │  Incident      │────▶│  Agent Planner     │────▶│  Execution Engine        │
  │  Context       │     │  (Claude AI)       │     │                          │
  │                │     │                   │     │  ① Identify              │
  │  · Proxy ID    │     │  · Analyses error  │     │  ② Generate credentials  │
  │  · Error class │     │    class & rate    │     │  ③ Stage update          │
  │  · Blast radius│     │  · Selects runbook │     │  ④ Deploy (rolling)      │
  │  · Duration    │     │  · Generates plan  │     │  ⑤ Validate              │
  └────────────────┘     └───────────────────┘     └──────────┬───────────────┘
                                                               │
                         ┌─────────────────────────────────────▼───────────────┐
                         │                  Integration Layer                   │
                         │                                                      │
                         │  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  │
                         │  │  API Manager  │  │  Secrets     │  │  Monitor │  │
                         │  │  (Apigee)     │  │  (Vault)     │  │  (Influx)│  │
                         │  └──────────────┘  └──────────────┘  └──────────┘  │
                         └──────────────────────────────────────────────────────┘
                                               │
                         ┌─────────────────────▼────────────────────────────────┐
                         │              Outcome & Notification                   │
                         │                                                       │
                         │  · Error rate validated ← baseline                   │
                         │  · Audit log written to InfluxDB                     │
                         │  · Partner teams notified via webhook                │
                         └───────────────────────────────────────────────────────┘
"""

_PSEUDOCODE = {
    "credential_rotation": '''\
async def agent_credential_rotation(incident: Incident) -> Resolution:
    """
    AI Agent: Automated Credential Rotation
    Runbook: APIGEE-IR-001 · Triggered by: 4xx sustained > 70%
    """
    log.info(f"[Agent] Starting credential rotation for {incident.proxy}")

    # ── Phase 1: Identify ────────────────────────────────────────────────
    tokens = await apigee.list_credentials(proxy=incident.proxy)
    suspect = [t for t in tokens if t.issued_at < incident.onset_time]

    if not suspect:
        raise AgentError("No suspect credentials found — manual review required")

    log.info(f"[Agent] Found {len(suspect)} suspect credential(s)")

    # ── Phase 2: Generate replacement ───────────────────────────────────
    new_creds = await apigee.rotate_credentials(
        tokens     = suspect,
        scope      = suspect[0].scope,
        expiry_ttl = timedelta(days=90),
    )

    # ── Phase 3: Stage ───────────────────────────────────────────────────
    await vault.write_secret(
        path  = f"apigee/{incident.proxy}/credentials",
        value = new_creds.to_dict(),
    )

    # ── Phase 4: Deploy (rolling restart, no downtime) ───────────────────
    deploy = await apigee.rolling_restart(
        proxy        = incident.proxy,
        health_check = "/health",
        max_surge    = 1,
    )
    await deploy.wait_until_healthy(timeout=300)

    # ── Phase 5: Validate ────────────────────────────────────────────────
    await asyncio.sleep(60)   # allow metrics to propagate
    rate = await influx.query_error_rate(proxy=incident.proxy, window="5m")

    if rate > 0.05:
        await apigee.rollback(deploy)
        raise AgentError(f"Post-deploy error rate {rate:.0%} — rolled back")

    # ── Notify ───────────────────────────────────────────────────────────
    await notify.send(
        channel  = "ops-incidents",
        message  = f"✅ Credential rotation complete for {incident.proxy}. "
                   f"Error rate: {rate:.1%} (was {incident.error_rate:.0%})",
    )

    return Resolution(
        status        = "resolved",
        action        = "credential_rotation",
        duration_secs = deploy.elapsed,
        new_error_rate = rate,
    )
''',
    "config_review": '''\
async def agent_config_review(incident: Incident) -> Resolution:
    """
    AI Agent: Configuration Review & Revert
    Runbook: APIGEE-IR-002 · Triggered by: 4xx sustained > 30%
    """
    log.info(f"[Agent] Starting config review for {incident.proxy}")

    # ── Phase 1: Retrieve current vs last-known-good ─────────────────────
    current_cfg = await apigee.get_proxy_config(incident.proxy)
    lkg_cfg     = await config_store.get_last_known_good(incident.proxy)
    diff        = DeepDiff(lkg_cfg, current_cfg, ignore_order=True)

    if not diff:
        log.warning("[Agent] No config drift detected — escalating to human")
        await pagerduty.escalate(incident, reason="no_config_drift")
        return Resolution(status="escalated")

    log.info(f"[Agent] Config drift detected: {list(diff.keys())}")

    # ── Phase 2: Classify drift ──────────────────────────────────────────
    risky_keys = {"rate_limit", "timeout_ms", "auth_policy", "target_url"}
    changed    = {k for k in diff if any(r in k for r in risky_keys)}

    # ── Phase 3: Revert ──────────────────────────────────────────────────
    reverted = await apigee.apply_config(
        proxy  = incident.proxy,
        config = lkg_cfg,
        reason = f"Auto-revert: config drift in {changed}",
    )
    await reverted.wait_for_propagation(timeout=120)

    # ── Phase 4: Validate ────────────────────────────────────────────────
    await asyncio.sleep(60)
    rate = await influx.query_error_rate(proxy=incident.proxy, window="5m")

    if rate > 0.05:
        await pagerduty.escalate(incident, reason="revert_did_not_resolve")
        raise AgentError("Config revert did not resolve errors — manual intervention needed")

    # ── Phase 5: Notify partners of any breaking changes ─────────────────
    if "auth_policy" in changed or "target_url" in changed:
        affected_apps = await influx.get_blast_radius(incident.proxy)
        await notify.send_to_teams(
            apps    = affected_apps,
            message = f"API contract change reverted for {incident.proxy}. "
                      f"Please verify your integration.",
        )

    return Resolution(
        status         = "resolved",
        action         = "config_revert",
        reverted_keys  = list(changed),
        new_error_rate = rate,
    )
''',
}


def _auto_resolve_page(settings: Settings) -> None:
    """Full-page auto-resolve view — shown immediately when triggered."""
    proxy   = st.session_state.ar_proxy
    ar_type = st.session_state.ar_type
    ec      = st.session_state.ar_ec
    name    = friendly_proxy(proxy)
    label, color = _AUTO_RESOLVE_LABELS.get(ar_type, ("Resolve", "#64748B"))
    runbook = {"credential_rotation": "APIGEE-IR-001", "config_review": "APIGEE-IR-002"}.get(ar_type, "APIGEE-IR-000")

    # Back button at top
    if st.button("← Back to Incident Response", key="ar_back_top"):
        st.session_state.ar_proxy      = None
        st.session_state.ar_type       = None
        st.session_state.ar_ec         = None
        st.session_state.ar_dispatched = False
        st.rerun()

    # Warning banner
    st.html(f"""
<div style="background:#FFF7ED;border:2px solid #F59E0B;border-radius:10px;
            padding:16px 20px;margin:12px 0 20px 0;">
    <div style="font-size:11px;font-weight:700;color:#92400E;text-transform:uppercase;
                letter-spacing:0.07em;margin-bottom:6px;">⚠ Production Action · Runbook {runbook}</div>
    <div style="font-size:14px;color:#78350F;">
        The following agent will execute changes against live production services for
        <b>{name}</b> [{ec} errors]. All steps are logged and reversible.
    </div>
</div>
""")

    # Header
    col_h, col_b = st.columns([4, 1])
    with col_h:
        st.subheader(f"{label}")
        st.caption(f"Target: {name}  ·  Class: {ec} errors  ·  Runbook: {runbook}")
    with col_b:
        st.html(f"""
<div style="background:{color};color:#FFFFFF;border-radius:8px;
            padding:12px 16px;text-align:center;margin-top:8px;">
    <div style="font-size:10px;font-weight:700;letter-spacing:0.07em;text-transform:uppercase;">
        Resolution
    </div>
    <div style="font-size:14px;font-weight:800;margin-top:2px;">
        {ar_type.replace('_',' ').title()}
    </div>
</div>
""")

    st.divider()
    tab_arch, tab_code, tab_dispatch = st.tabs([
        "🏗  Architecture", "📄  Agent Code", "🚀  Dispatch"
    ])

    # ── Architecture tab ──────────────────────────────────────────────────────
    with tab_arch:
        st.code(_ARCH_FLOW, language=None)
        st.divider()
        st.markdown("**Execution phases:**")
        phases = {
            "credential_rotation": [
                ("① Identify",  "Query API management for active credentials on the affected proxy. Flag tokens predating the incident onset time."),
                ("② Generate",  "Issue new credentials with identical scope via the Apigee management API. Old credentials remain active until step ④."),
                ("③ Stage",     "Write new credentials to the secrets vault under the proxy's path. No services updated yet."),
                ("④ Deploy",    "Trigger a rolling restart of the proxy. Instances pick up new credentials from vault sequentially — zero downtime."),
                ("⑤ Validate",  "Wait 60 seconds, query InfluxDB for 5-minute rolling error rate. Rollback if rate > 5%. Notify on success."),
            ],
            "config_review": [
                ("① Identify",  "Pull current proxy configuration and last-known-good snapshot from the config store. Deep-diff to find drift."),
                ("② Classify",  "Categorise changed keys — rate limits, timeouts, auth policies, target URLs. Only risky changes trigger revert."),
                ("③ Revert",    "Apply the last-known-good config via Apigee Management API. Wait for propagation across all gateway nodes."),
                ("④ Validate",  "Query error rate after 60 seconds. Escalate to PagerDuty if revert did not resolve."),
                ("⑤ Notify",    "If auth or URL changes were reverted, notify affected partner apps via webhook with migration guidance."),
            ],
        }
        for step, desc in phases.get(ar_type, []):
            with st.expander(step, expanded=True):
                st.markdown(desc)

    # ── Code tab ──────────────────────────────────────────────────────────────
    with tab_code:
        st.caption(
            "Pseudo-code representing the agent's execution plan. "
            "In production this would be compiled into an actual agent runbook "
            "and executed against the live infrastructure APIs."
        )
        code = _PSEUDOCODE.get(ar_type, "# No agent code available for this resolution type")
        st.code(code, language="python")

    # ── Dispatch tab ──────────────────────────────────────────────────────────
    with tab_dispatch:
        if not st.session_state.get("ar_dispatched"):
            st.markdown(f"""
**Pre-dispatch checklist:**

- [ ] Verified this is the correct proxy: **{name}**
- [ ] Confirmed error class: **{ec} errors ({ar_type.replace('_', ' ').title()})**
- [ ] Reviewed the architecture flow and agent code above
- [ ] Change window is open / on-call engineer is available
- [ ] Rollback plan understood (agent auto-rolls back on validation failure)
""")
            st.divider()
            col_1, col_2, col_3 = st.columns([1, 2, 1])
            with col_2:
                if st.button(
                    "🤖  Dispatch AI Agent",
                    use_container_width=True,
                    type="primary",
                    key="dispatch_btn",
                ):
                    st.session_state["ar_dispatched"] = True
                    st.rerun()
        else:
            # Mock execution output
            import time
            exec_id = f"agent-ir-{abs(hash(proxy)) % 100000:05d}"
            st.html(f"""
<div style="background:#F0FDF4;border:2px solid #22C55E;border-radius:10px;
            padding:20px 24px;margin-bottom:16px;">
    <div style="font-size:13px;font-weight:700;color:#166534;margin-bottom:10px;">
        ✓ Agent Dispatched — Execution in Progress
    </div>
    <div style="font-family:monospace;font-size:12px;color:#166534;line-height:1.9;">
        Execution ID: <b>{exec_id}</b><br>
        Agent:        <b>claude-opus-4-8 [tool_use mode]</b><br>
        Target:       <b>{name}</b><br>
        Runbook:      <b>{runbook} — {ar_type.replace('_',' ').title()}</b><br>
        Status:       <b>RUNNING · Phase 2/5</b><br>
        ETA:          <b>~3 minutes</b>
    </div>
</div>
""")
            st.code(f"""\
[{exec_id}] Agent started · runbook={runbook}
[{exec_id}] Phase 1/5: Identifying affected credentials...
[{exec_id}] Found 2 suspect credential(s) (issued before incident onset)
[{exec_id}] Phase 2/5: Generating replacement credentials...
[{exec_id}] New credentials staged in vault at apigee/{proxy[-20:]}/credentials
[{exec_id}] Phase 3/5: Staging deployment...
[{exec_id}] Rolling restart initiated (max_surge=1, health_check=/health)
[{exec_id}] ► Waiting for instance health checks...
""", language="bash")
            st.info(
                "**Mock execution** — this output simulates what the agent would report. "
                "No actual changes have been made to production systems. "
                "Integration with your infrastructure automation layer is required "
                "before live dispatch is enabled."
            )
            if st.button("← Back to incidents", key="ar_back_dispatched"):
                st.session_state.ar_proxy      = None
                st.session_state.ar_type       = None
                st.session_state.ar_ec         = None
                st.session_state.ar_dispatched = False
                st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Current Incidents tab
# ─────────────────────────────────────────────────────────────────────────────

def _current_incidents_tab(settings: Settings) -> None:
    st.subheader("Current Incidents — Prioritised by Business Impact")
    st.caption(
        "Sorted by estimated failed calls × error rate × duration. "
        "Server errors (5xx) are likely root causes; client errors (4xx) may be symptoms."
    )

    with st.spinner("Loading incident data..."):
        df = queries.get_incident_priorities(settings)

    if df.empty:
        st.success("No active incidents requiring immediate attention.")
        return

    # Summary
    n_server  = int((df["error_class"] == "server").sum())
    n_client  = int((df["error_class"] == "client").sum())
    n_auto    = int(df.apply(lambda r: _auto_resolve_type(r["error_class"], r["error_rate"], r["consecutive_hours"]) is not None, axis=1).sum())
    total_calls = int(df["total_calls"].sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Incidents",         len(df))
    c2.metric("Root Cause (server 5xx)", n_server)
    c3.metric("Symptom (client 4xx)",    n_client)
    c4.metric("Auto-Resolve eligible",   n_auto)

    st.divider()

    # Additional prioritisation signals beyond blast radius
    st.markdown("""
**Prioritisation considers:**
- 🔴 **Blast radius** — calls and partner apps directly affected
- ⏱ **Duration** — longer-running incidents weighted higher
- 🌍 **Geographic spread** — multi-country impact prioritised
- 🔗 **Root vs symptom** — server errors (root) above client errors (symptom)
""")
    st.divider()

    for _, row in df.iterrows():
        name     = friendly_proxy(row["proxy"])
        ec       = row["error_class"]
        er       = float(row["error_rate"])
        z        = abs(float(row["z_score"]))
        hours    = int(row["consecutive_hours"])
        calls    = int(row["total_calls"])
        n_apps   = int(row["unique_apps"])
        n_cntry  = int(row["unique_countries"])
        top_apps = row.get("top_apps", [])
        sustained = row.get("sustained", False)

        ar_type  = _auto_resolve_type(ec, er, hours)
        ec_color = "#EF4444" if ec == "server" else "#F59E0B"
        ec_label = "Server Failure (5xx)" if ec == "server" else "Client Errors (4xx)"

        effect     = _effect(name, ec, er, calls, n_apps, n_cntry, hours)
        hypothesis = _hypothesis(ec, er, hours, name)
        steps      = _steps(ec, er, hours)

        with st.expander(
            f"{'🔴' if ec=='server' else '🟡'} **{name}** — {ec_label} "
            f"{'· Sustained' if sustained else ''} "
            f"{'· ' + str(n_apps) + ' apps affected' if n_apps > 0 else ''}",
            expanded=(df.index[df["proxy"] == row["proxy"]][0] < 3),
        ):
            col_left, col_right = st.columns([3, 1])

            with col_left:
                st.markdown(f"**Effect:**  \n{effect}")
                st.markdown(f"**Root cause hypothesis:**  \n{hypothesis}")

            with col_right:
                st.metric("Signal strength", f"{z:.1f}σ")
                st.metric("Error rate",      f"{er:.0%}" if er > 0 else "—")
                st.metric("Duration",        f"{hours}h")
                if n_apps > 0:
                    st.metric("Apps at risk",    str(n_apps))

            if top_apps:
                st.caption(f"Top affected partners: {', '.join(top_apps[:3])}")

            st.markdown("**Suggested resolution steps:**")
            for i, step in enumerate(steps, 1):
                st.markdown(f"{i}. {step}")

            if ar_type:
                ar_label, ar_color = _AUTO_RESOLVE_LABELS[ar_type]
                btn_col, _ = st.columns([1, 3])
                with btn_col:
                    if st.button(f"{ar_label}", key=f"ar_{row['proxy']}_{ec}",
                                 use_container_width=True):
                        st.session_state.ar_proxy      = row["proxy"]
                        st.session_state.ar_type       = ar_type
                        st.session_state.ar_ec         = ec
                        st.session_state.ar_dispatched = False
                        st.rerun()   # immediately shows auto-resolve page


# ─────────────────────────────────────────────────────────────────────────────
# Page render
# ─────────────────────────────────────────────────────────────────────────────

def init_session_state() -> None:
    """Call once at the top of the hosting page, before checking ar_proxy."""
    for k, v in [("ar_proxy", None), ("ar_type", None),
                 ("ar_ec", None), ("ar_dispatched", False)]:
        if k not in st.session_state:
            st.session_state[k] = v


def render(settings: Settings, embedded: bool = False) -> None:
    """Render the 'Respond & Resolve' incident triage content.

    When embedded=True (nested inside Monitoring), the caller is responsible
    for the auto-resolve full-page takeover check via init_session_state() +
    _auto_resolve_page() — this function just renders the incident list.
    """
    if not embedded:
        init_session_state()
        if st.session_state.ar_proxy:
            _auto_resolve_page(settings)
            return
        st.header("Incident Response")

    _current_incidents_tab(settings)
