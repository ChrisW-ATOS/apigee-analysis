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
# Auto-Resolve mock
# ─────────────────────────────────────────────────────────────────────────────

def _auto_resolve_tab(settings: Settings) -> None:
    """Mock auto-resolve UI — shown when a routine fix is triggered."""
    if "ar_proxy" not in st.session_state or not st.session_state.ar_proxy:
        st.info("Select an **Auto-Resolve** action from the Current Incidents tab to continue.")
        return

    proxy    = st.session_state.ar_proxy
    ar_type  = st.session_state.ar_type
    ec       = st.session_state.ar_ec
    name     = friendly_proxy(proxy)
    label, color = _AUTO_RESOLVE_LABELS.get(ar_type, ("Resolve", "#64748B"))

    st.html(f"""
<div style="background:#FFF7ED;border:2px solid #F59E0B;border-radius:10px;
            padding:16px 20px;margin-bottom:20px;">
    <div style="font-size:11px;font-weight:700;color:#92400E;text-transform:uppercase;
                letter-spacing:0.07em;margin-bottom:6px;">⚠ Production Action</div>
    <div style="font-size:14px;color:#78350F;">
        The following steps will affect live production services for
        <b>{name}</b> [{ec} errors]. Review each step before dispatching.
    </div>
</div>
""")

    st.subheader(f"{label} — {name}")
    st.caption(f"Resolution type: {ar_type.replace('_', ' ').title()}")

    if ar_type == "credential_rotation":
        st.markdown("""
**Automated resolution plan — Credential Rotation**

1. **Identify affected credentials**
   - Query the API management system for all active tokens associated with this proxy
   - Flag tokens older than the error onset time as suspect

2. **Generate replacement credentials**
   - Issue new API key / OAuth client secret via the API management portal
   - Assign the same permissions scope as the current credential set

3. **Stage the credential update**
   - Store new credentials in the secrets manager
   - Update environment variable bindings for the affected service

4. **Deploy the update**
   - Trigger a rolling restart of the affected proxy service
   - New credentials take effect without downtime

5. **Verify resolution**
   - Monitor error rate for 10 minutes post-deploy
   - Confirm 4xx errors return to baseline (<2%)
   - Notify affected partner teams of the credential update
""")

    elif ar_type == "config_review":
        st.markdown("""
**Automated resolution plan — Configuration Review**

1. **Retrieve current configuration**
   - Pull the active rate limit, timeout, and endpoint configuration for this proxy
   - Compare against the last-known-good configuration snapshot

2. **Identify configuration drift**
   - Check for rate limit reductions in the last 24 hours
   - Verify API contract version compatibility with calling applications

3. **Apply corrected configuration**
   - Revert any rate limit changes applied in the anomaly window
   - Update endpoint configuration to match the validated specification

4. **Notify downstream teams**
   - Inform partner development teams of any contract changes
   - Provide migration guide if API version has changed

5. **Verify resolution**
   - Monitor for 15 minutes — 4xx rate should return to baseline
   - Run synthetic validation request to confirm endpoint behaviour
""")

    st.divider()
    st.subheader("Dispatch AI Agent")
    st.caption(
        "The AI agent will execute the steps above, monitor the outcome, "
        "and report back. This is a mock integration — in production this would "
        "connect to your infrastructure automation layer."
    )

    c1, c2, c3 = st.columns([2, 1, 2])
    with c2:
        dispatch = st.button("🤖  Dispatch Agent", use_container_width=True, type="primary")

    if dispatch or st.session_state.get("ar_dispatched"):
        st.session_state["ar_dispatched"] = True
        st.html("""
<div style="background:#F0FDF4;border:2px solid #22C55E;border-radius:10px;
            padding:20px 24px;margin-top:16px;">
    <div style="font-size:14px;font-weight:700;color:#166534;margin-bottom:8px;">
        ✓ Agent Dispatched
    </div>
    <div style="font-size:13px;color:#166534;line-height:1.6;">
        The AI agent has been dispatched and is executing the resolution plan.<br>
        Execution ID: <code>agent-ir-{proxy[-8:]}-mock</code><br>
        Estimated completion: 3–5 minutes<br>
        You will be notified when the error rate returns to baseline.
    </div>
</div>
""")
        st.caption("⚠ Mock only — no actual changes have been made to production systems.")

    if st.button("← Back to incidents", key="ar_back"):
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
                        # Switch to auto-resolve tab by setting flag
                        st.session_state.ir_tab = 2
                        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Predicted Issues tab
# ─────────────────────────────────────────────────────────────────────────────

def _predicted_tab(settings: Settings) -> None:
    st.subheader("Predicted Issues — Pre-emptive Action")
    st.caption(
        "APIs at elevated cascade risk based on behavioral correlation with currently-failing APIs. "
        "Act now to prevent the failure propagating."
    )

    with st.spinner("Loading predictions..."):
        pred = queries.get_cascade_predictions(settings)

    if pred.empty:
        st.success(
            "No APIs at elevated cascade risk. Either no significant correlation patterns "
            "are active, or no APIs are currently showing meaningful rate changes."
        )
        return

    high = pred[(pred["score"] >= 0.4) & (pred["correlation"] >= 0.60)]
    med  = pred[~((pred["score"] >= 0.4) & (pred["correlation"] >= 0.60)) &
                (pred["score"] >= 0.20) & (pred["correlation"] >= 0.40)]

    st.markdown(
        f"**{len(pred)} APIs at risk** — {len(high)} HIGH, {len(med)} MEDIUM. "
        f"Address the driver APIs first to prevent the cascade."
    )
    st.divider()

    for _, row in pred.head(8).iterrows():
        name        = friendly_proxy(row["proxy"])
        ec          = row["error_class"]
        driver      = friendly_proxy(row["driver_proxy"])
        driver_ec   = row["driver_ec"]
        corr        = float(row["correlation"])
        lag         = int(row["driver_lag"])
        change_pct  = float(row["driver_change_pct"])

        label, color = ("HIGH", "#EF4444") if row["score"] >= 0.4 and corr >= 0.6 \
                    else ("MEDIUM", "#F59E0B")
        lag_str   = "simultaneously" if lag == 0 else f"within {lag}h"
        ec_str    = "4xx" if ec == "client" else "5xx"
        drv_ec_str = "4xx" if driver_ec == "client" else "5xx"

        # Pre-emptive effect
        pre_effect = (
            f"If the historical pattern repeats, **{name}** ({ec_str}) is likely to "
            f"follow **{driver}** ({drv_ec_str}) — which rose {change_pct:+.0f}pp in the "
            f"last 2 hours — {lag_str}. Correlation strength: **{corr:.2f}**."
        )
        # Pre-emptive hypothesis
        pre_hyp = (
            f"The behavioral correlation suggests a shared dependency with {driver}. "
            f"The root cause of {driver}'s current failure is likely also the "
            f"failure mechanism for {name} — investigate the same infrastructure, "
            f"authentication chain, or backend service."
        )
        # Pre-emptive action
        pre_steps = [
            f"Identify what {driver} and {name} share — authentication service, database, backend API",
            f"Investigate the root cause of {driver}'s current {change_pct:+.0f}pp rise",
            f"Pre-emptively check {name}'s health indicators before the cascade reaches it",
            f"If a shared dependency is failing, prioritise fixing that over individual proxies",
            f"Alert the team managing {name} to stand by for potential incident",
        ]

        with st.expander(
            f"{'🔴' if label == 'HIGH' else '🟡'} **{name}** — {label} cascade risk "
            f"(corr {corr:.2f} with {driver})",
            expanded=(pred.index[pred["proxy"] == row["proxy"]][0] < 2),
        ):
            col_l, col_r = st.columns([3, 1])
            with col_l:
                st.markdown(f"**Predicted effect:**  \n{pre_effect}")
                st.markdown(f"**Hypothesis:**  \n{pre_hyp}")
            with col_r:
                st.metric("Correlation",    f"{corr:.2f}")
                st.metric("Driver change",  f"{change_pct:+.0f}pp")
                st.metric("Expected lag",   f"{lag}h" if lag > 0 else "Now")

            st.markdown("**Pre-emptive steps:**")
            for i, step in enumerate(pre_steps, 1):
                st.markdown(f"{i}. {step}")


# ─────────────────────────────────────────────────────────────────────────────
# Page render
# ─────────────────────────────────────────────────────────────────────────────

def render(settings: Settings) -> None:
    # Initialise session state
    for k, v in [("ar_proxy", None), ("ar_type", None),
                 ("ar_ec", None), ("ar_dispatched", False), ("ir_tab", 0)]:
        if k not in st.session_state:
            st.session_state[k] = v

    st.header("Incident Response")
    st.caption(
        "Triage existing incidents by business impact · Pre-empt predicted cascades · "
        "Auto-resolve routine issues"
    )

    # If auto-resolve was triggered, open that tab
    default_tab = st.session_state.get("ir_tab", 0)

    tabs = st.tabs([
        "🚨  Current Incidents",
        "⚡  Predicted Issues",
        "🤖  Auto-Resolve",
    ])

    with tabs[0]:
        _current_incidents_tab(settings)

    with tabs[1]:
        _predicted_tab(settings)

    with tabs[2]:
        _auto_resolve_tab(settings)
