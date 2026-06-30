"""API Intelligence — Sankey cascade flow + correlation heatmap with drill-down."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from apigee_analysis.config import Settings
from apigee_analysis.dashboard import queries
from apigee_analysis.dashboard.labels import friendly_proxy

# Reuse the dual-panel history chart from predictions.py
from apigee_analysis.dashboard.views.predictions import _co_failure_chart

_DARK_BG   = "#0F0E2A"
_CARD_BG   = "#1A1933"
_TEXT      = "#E2E8F0"
_MUTED     = "#94A3B8"

_COL_FAIL  = "rgba(239,68,68,0.90)"
_COL_RISK  = "rgba(245,158,11,0.90)"
_COL_PART  = "rgba(59,130,246,0.80)"
_COL_HLTH  = "rgba(34,197,94,0.80)"


def _label(key: str) -> str:
    """Friendly short label from a proxy|ec key or plain app name."""
    if "|" not in key:
        return key[:28]
    proxy, ec = key.rsplit("|", 1)
    name = friendly_proxy(proxy)
    suffix = " [4xx]" if ec == "client" else " [5xx]"
    return (name[:28] + suffix) if len(name) > 28 else name + suffix


# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 — Sankey Cascade Flow
# ─────────────────────────────────────────────────────────────────────────────

def _sankey_tab(settings: Settings) -> None:
    st.subheader("Failure Cascade Flow")
    st.caption(
        "Read left to right: **currently failing APIs** (red) → "
        "**APIs at behavioural risk** (amber) → "
        "**affected partner applications** (blue). "
        "Flow width = estimated business impact. Click any node to see the 7-day history."
    )

    with st.spinner("Building cascade model..."):
        data = queries.get_cascade_sankey_data(settings)

    nodes    = data["nodes"]
    links    = data["links"]
    n_fail   = data["n_failing"]
    n_risk   = data["n_risk"]
    n_partner = data["n_partner"]

    if not nodes or (n_fail == 0 and n_risk == 0):
        st.info(
            "No cascade data available. This view requires at least one currently-failing "
            "API with correlated at-risk peers."
        )
        return

    # Node colours
    node_colors = []
    node_labels = []
    for n in nodes:
        node_labels.append(_label(n["key"]))
        if n["col"] == "failing":
            node_colors.append(_COL_FAIL)
        elif n["col"] == "atrisk":
            node_colors.append(_COL_RISK)
        else:
            node_colors.append(_COL_PART)

    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(
            label     = node_labels,
            color     = node_colors,
            pad       = 20,
            thickness = 22,
            line      = dict(color="#1E1B4B", width=1),
            hovertemplate = "%{label}<extra></extra>",
        ),
        link=dict(
            source     = [lk["source"] for lk in links],
            target     = [lk["target"] for lk in links],
            value      = [lk["value"]  for lk in links],
            color      = [lk["color"]  for lk in links],
            hovertemplate = "Flow: %{value:,} calls<extra></extra>",
        ),
    ))

    fig.update_layout(
        height           = 580,
        paper_bgcolor    = _DARK_BG,
        plot_bgcolor     = _DARK_BG,
        font             = dict(color=_TEXT, size=12, family="sans-serif"),
        margin           = dict(l=10, r=10, t=50, b=10),
        title            = dict(
            text = (
                f"<b style='color:#EF4444'>{n_fail} Failing APIs</b>"
                f"  →  "
                f"<b style='color:#F59E0B'>{n_risk} At-Risk APIs</b>"
                f"  →  "
                f"<b style='color:#3B82F6'>{n_partner} Partner Apps</b>"
            ),
            x    = 0.5,
            font = dict(size=14, color=_TEXT),
        ),
    )

    event = st.plotly_chart(
        fig,
        use_container_width = True,
        on_select           = "rerun",
        selection_mode      = "points",
        key                 = "sankey_chart",
    )

    # Node click → drill-down
    if event and event.selection and event.selection.points:
        pt  = event.selection.points[0]
        idx = pt.get("pointNumber")
        if idx is not None and idx < len(nodes):
            selected_key = nodes[idx]["key"]
            if "|" in selected_key:
                st.session_state.intel_selected = selected_key
                st.rerun()

    # Drill-down panel
    _drill_down(settings)

    # Legend
    st.html("""
<div style="display:flex;gap:24px;margin-top:8px;font-size:12px;color:#94A3B8;">
    <span><span style="display:inline-block;width:12px;height:12px;border-radius:2px;
          background:rgba(239,68,68,0.9);margin-right:6px;"></span>Currently failing</span>
    <span><span style="display:inline-block;width:12px;height:12px;border-radius:2px;
          background:rgba(245,158,11,0.9);margin-right:6px;"></span>At cascade risk</span>
    <span><span style="display:inline-block;width:12px;height:12px;border-radius:2px;
          background:rgba(59,130,246,0.8);margin-right:6px;"></span>Affected partners</span>
    <span style="margin-left:auto;">Flow width ∝ estimated call volume at risk</span>
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 — Correlation Heatmap
# ─────────────────────────────────────────────────────────────────────────────

def _heatmap_tab(settings: Settings) -> None:
    st.subheader("API Behavioral Correlation Map")
    st.caption(
        "Colour intensity = strength of behavioral cross-correlation on hourly error rate changes. "
        "APIs that move together are structurally linked — fixing one resolves others. "
        "Red-outlined axes = currently anomalous. Click any cell to see the 7-day paired history."
    )

    c1, _ = st.columns([1, 3])
    with c1:
        top_n = st.slider("APIs shown", 10, 40, 25, key="heatmap_n")

    with st.spinner("Computing correlation matrix..."):
        mat, keys, anomalous = queries.get_correlation_matrix(settings, top_n=top_n)

    if mat.empty or not keys:
        st.info("Insufficient history to compute correlation matrix (need ≥10 non-zero hours per proxy).")
        return

    # Axis labels
    axis_labels = [_label(k) for k in keys]

    # Build hover text matrix
    hover = []
    for i, ka in enumerate(keys):
        row = []
        for j, kb in enumerate(keys):
            v    = float(mat.iloc[i, j])
            name_a = _label(ka)
            name_b = _label(kb)
            row.append(f"<b>{name_a}</b><br>↔ {name_b}<br>Correlation: {v:.2f}" if v > 0 else "")
        hover.append(row)

    fig = go.Figure(go.Heatmap(
        z            = mat.values,
        x            = axis_labels,
        y            = axis_labels,
        colorscale   = [
            [0.00, "#0F0E2A"],
            [0.20, "#1E1B4B"],
            [0.40, "#312E81"],
            [0.65, "#7C3AED"],
            [0.85, "#C026D3"],
            [1.00, "#EF4444"],
        ],
        zmin         = 0,
        zmax         = 1,
        showscale    = True,
        text         = mat.values.round(2).astype(str),
        hovertext    = hover,
        hovertemplate = "%{hovertext}<extra></extra>",
        colorbar     = dict(
            title      = "Correlation",
            titlefont  = dict(color=_TEXT),
            tickfont   = dict(color=_TEXT),
            outlinecolor = _TEXT,
            outlinewidth = 0.5,
        ),
        xgap = 1,
        ygap = 1,
    ))

    # Highlight anomalous axes with tick color override
    tick_colors_x = [
        "#EF4444" if k in anomalous else _MUTED
        for k in keys
    ]

    fig.update_layout(
        height        = max(480, top_n * 16),
        paper_bgcolor = _DARK_BG,
        plot_bgcolor  = _DARK_BG,
        font          = dict(color=_TEXT, size=10),
        margin        = dict(l=10, r=10, t=20, b=10),
        xaxis         = dict(
            tickangle    = -45,
            tickfont     = dict(size=10, color=_MUTED),
            gridcolor    = "#1E1B4B",
            showline     = False,
        ),
        yaxis         = dict(
            tickfont     = dict(size=10, color=_MUTED),
            gridcolor    = "#1E1B4B",
            showline     = False,
            autorange    = "reversed",
        ),
    )

    event = st.plotly_chart(
        fig,
        use_container_width = True,
        on_select           = "rerun",
        selection_mode      = "points",
        key                 = "heatmap_chart",
    )

    # Cell click → select pair
    if event and event.selection and event.selection.points:
        pt  = event.selection.points[0]
        xi  = pt.get("pointIndex", [None, None])
        if isinstance(xi, (list, tuple)) and len(xi) == 2:
            row_i, col_j = xi[0], xi[1]
            if row_i is not None and col_j is not None and row_i != col_j:
                ka = keys[row_i]
                kb = keys[col_j]
                st.session_state.intel_selected   = ka
                st.session_state.intel_selected_b = kb
                st.rerun()

    _drill_down(settings)

    st.html(f"""
<div style="font-size:11px;color:#64748B;margin-top:6px;">
    Computed on first differences of hourly error rates — captures correlated rises and
    falls, not coincident threshold breaches. Min correlation shown: 0.35.
    <span style="color:#EF4444;margin-left:12px;">■</span> axis label = currently anomalous.
</div>
""")


# ─────────────────────────────────────────────────────────────────────────────
# Drill-down panel (shared by both tabs)
# ─────────────────────────────────────────────────────────────────────────────

def _drill_down(settings: Settings) -> None:
    key_a = st.session_state.get("intel_selected")
    key_b = st.session_state.get("intel_selected_b")

    if not key_a or "|" not in key_a:
        return

    proxy_a, ec_a = key_a.rsplit("|", 1)
    name_a = _label(key_a)

    st.divider()
    col_h, col_close = st.columns([5, 1])
    with col_h:
        st.subheader(f"Detail: {name_a}")
    with col_close:
        if st.button("✕ Close", key="intel_close", use_container_width=True):
            st.session_state.intel_selected   = None
            st.session_state.intel_selected_b = None
            st.rerun()

    if key_b and "|" in key_b:
        # Pair view
        proxy_b, ec_b = key_b.rsplit("|", 1)
        name_b = _label(key_b)

        # Metrics
        corr_pairs = queries.get_correlation_matrix(settings)[0]
        corr_val   = 0.0
        if not corr_pairs.empty and key_a in corr_pairs.index and key_b in corr_pairs.columns:
            corr_val = float(corr_pairs.loc[key_a, key_b])

        c1, c2, c3 = st.columns(3)
        c1.metric("Correlation strength", f"{corr_val:.2f}")
        c2.metric("API A", name_a)
        c3.metric("API B", name_b)

        with st.spinner("Loading 7-day history..."):
            _co_failure_chart(
                settings,
                proxy_a=proxy_a, ec_a=ec_a,
                proxy_b=proxy_b, ec_b=ec_b,
                driver_name=name_a,
                risk_name=name_b,
            )
    else:
        # Single-node view — find its best correlated partner
        with st.spinner("Loading pair history..."):
            mat, keys, _ = queries.get_correlation_matrix(settings)
        if not mat.empty and key_a in mat.index:
            row    = mat.loc[key_a].drop(key_a, errors="ignore")
            if not row.empty and row.max() > 0:
                best_b = row.idxmax()
                proxy_b, ec_b = best_b.rsplit("|", 1)
                name_b = _label(best_b)
                corr_v = float(row.max())

                c1, c2, c3 = st.columns(3)
                c1.metric("Strongest correlation", f"{corr_v:.2f}")
                c2.metric("This API", name_a)
                c3.metric("Most correlated peer", name_b)

                _co_failure_chart(
                    settings,
                    proxy_a=proxy_a, ec_a=ec_a,
                    proxy_b=proxy_b, ec_b=ec_b,
                    driver_name=name_a,
                    risk_name=name_b,
                )
            else:
                st.info(f"No strongly correlated peers found for {name_a}.")
        else:
            st.info(f"No correlation data available for {name_a}.")


# ─────────────────────────────────────────────────────────────────────────────
# Page render
# ─────────────────────────────────────────────────────────────────────────────

def render(settings: Settings) -> None:
    for k, v in [("intel_selected", None), ("intel_selected_b", None)]:
        if k not in st.session_state:
            st.session_state[k] = v

    st.html(f"""
<div style="background:{_DARK_BG};border-radius:12px;padding:20px 28px;margin-bottom:20px;">
    <div style="font-size:22px;font-weight:800;color:{_TEXT};margin-bottom:6px;">
        API Intelligence
    </div>
    <div style="font-size:13px;color:{_MUTED};line-height:1.6;">
        Structural dependencies between APIs derived from behavioral cross-correlation
        of error rate changes. Width and colour encode business impact and cascade risk.
    </div>
</div>
""")

    st.info(
        "**First load:** The behavioral correlation model runs O(N²) cross-correlations "
        "across all monitored APIs — this takes ~15 seconds on first load and is then "
        "cached for 1 hour. Subsequent visits within the hour are instant.",
        icon="⏳",
    )

    with st.spinner("Computing behavioral correlations across all APIs..."):
        # Warm the shared cache here so both tabs benefit from the same computation
        queries._get_corr_pairs(settings)

    tabs = st.tabs(["🌊  Cascade Flow", "🔥  Correlation Map"])

    with tabs[0]:
        _sankey_tab(settings)

    with tabs[1]:
        _heatmap_tab(settings)
