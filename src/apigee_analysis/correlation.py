"""Behavioral cross-correlation model for cascade risk prediction.

Replaces the binary co-occurrence approach (which only detected anomaly/not-anomaly
overlap) with cross-correlation on first differences of error rates. This captures
the actual behavioral relationship: when API A's error rate rises or falls, does
API B's error rate move similarly, and with what lag?

Two APIs that are both stuck at 100% all week have high binary co-occurrence but
near-zero cross-correlation on changes — they are not behaviorally linked.
Two APIs where one rising 20pp consistently precedes the other rising 20pp within
1 hour have high cross-correlation and ARE structurally related.

The prediction step combines:
  - The magnitude of the current rate change for each active (failing) API
  - The strength of that API's behavioral correlation with non-failing peers
to produce a ranked list of APIs most at risk of following the same pattern.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MAX_LAG_HOURS    = 4    # maximum look-ahead for co-failure relationships
MIN_CORR         = 0.35 # minimum cross-correlation to consider a pair related
MIN_NONZERO      = 10   # minimum non-zero hours in a series to compute correlation
MIN_VAR          = 1e-6 # minimum variance — constant series are uninformative


# ─────────────────────────────────────────────────────────────────────────────
# Rate matrix
# ─────────────────────────────────────────────────────────────────────────────

def build_rate_matrix(history_df: pd.DataFrame) -> pd.DataFrame:
    """Pivot history into a wide matrix: rows=hours, columns=proxy|ec keys.

    Args:
        history_df: DataFrame with columns [proxy, error_class, hour, rate].
                    `hour` is a tz-aware pd.Timestamp truncated to the hour.

    Returns:
        Wide DataFrame, fill_value=0, sorted by hour ascending.
    """
    if history_df.empty:
        return pd.DataFrame()

    history_df = history_df.copy()
    history_df["key"] = history_df["proxy"] + "|" + history_df["error_class"]

    matrix = (
        history_df
        .pivot_table(index="hour", columns="key", values="rate", aggfunc="last", fill_value=0)
    )
    return matrix.sort_index()


# ─────────────────────────────────────────────────────────────────────────────
# Cross-correlation
# ─────────────────────────────────────────────────────────────────────────────

def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation between two arrays. Returns 0.0 on any error."""
    if len(a) < 5 or len(b) < 5:
        return 0.0
    try:
        va, vb = np.var(a), np.var(b)
        if va < MIN_VAR or vb < MIN_VAR:
            return 0.0
        return float(np.corrcoef(a, b)[0, 1])
    except Exception:
        return 0.0


def compute_crosscorr_pairs(
    rate_matrix: pd.DataFrame,
    max_lag: int = MAX_LAG_HOURS,
) -> pd.DataFrame:
    """Compute cross-correlation on first differences for every proxy pair.

    First differences (Δrate) capture CHANGES in error rate — rises and falls —
    rather than absolute levels. A constant series at 100% has zero variance in
    its differences and correctly shows no behavioral relationship with anything.

    For each ordered pair (A, B) and each lag k ∈ {0 … max_lag}:
        corr(Δrate_A[t], Δrate_B[t+k])
    Records the lag with the highest positive correlation.

    Pairs are retained only when:
    - Both series have >= MIN_NONZERO non-zero rate hours
    - Max positive cross-correlation >= MIN_CORR

    Returns DataFrame with columns:
        key_a, key_b, best_lag, best_corr, corr_at_lag (list)
    """
    if rate_matrix.empty or rate_matrix.shape[1] < 2:
        return pd.DataFrame()

    # First differences — rate of change per hour
    diffs = rate_matrix.diff().dropna()
    nonzero_counts = (rate_matrix > 0).sum()

    cols = [c for c in rate_matrix.columns if nonzero_counts[c] >= MIN_NONZERO]
    log.info("Cross-correlation: %d proxies with sufficient history", len(cols))

    rows = []
    for i, key_a in enumerate(cols):
        da = diffs[key_a].values
        for key_b in cols:
            if key_a == key_b:
                continue
            db = diffs[key_b].values

            # Compute correlation at each lag
            lag_corrs = []
            for lag in range(0, max_lag + 1):
                if lag == 0:
                    c = _pearson(da, db)
                else:
                    # A at t, B at t+lag: does A's change LEAD B's change?
                    c = _pearson(da[:-lag], db[lag:])
                lag_corrs.append(c)

            best_lag  = int(np.argmax(lag_corrs))
            best_corr = float(lag_corrs[best_lag])

            if best_corr >= MIN_CORR:
                rows.append({
                    "key_a":     key_a,
                    "key_b":     key_b,
                    "best_lag":  best_lag,
                    "best_corr": best_corr,
                })

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["key_a", "key_b", "best_lag", "best_corr"]
    )


# ─────────────────────────────────────────────────────────────────────────────
# Prediction
# ─────────────────────────────────────────────────────────────────────────────

def predict_cascade(
    corr_pairs:        pd.DataFrame,
    current_changes:   dict[str, float],  # key -> Δrate over last 2h (positive = rising)
    current_anomalous: set[str],
    all_keys:          set[str],
    min_score:         float = 0.10,
) -> pd.DataFrame:
    """Rank non-failing APIs by cascade risk using behavioral correlation.

    Score for proxy B given active driver A:
        score = |Δrate_A| × corr(A, B, best_lag)

    where Δrate_A is the driver's current rate of change. This means:
    - High correlation + large current change = strong prediction
    - High correlation + flat trend = weaker prediction
    - Low correlation = no prediction regardless of current change

    Multiple drivers are combined by summing their individual scores.

    Args:
        corr_pairs:        Output of compute_crosscorr_pairs().
        current_changes:   {key: rate_change} for currently-active APIs.
                           Rate change in 0-1 units (e.g., 0.20 = rose 20pp).
        current_anomalous: Keys currently anomalous (to exclude from results).
        all_keys:          All known proxy keys.
        min_score:         Minimum combined score to include in results.

    Returns DataFrame with columns:
        key_b, score, best_driver_key, best_driver_corr,
        best_driver_lag, best_driver_change, n_drivers
    """
    if corr_pairs.empty or not current_changes:
        return pd.DataFrame()

    # Only consider drivers that are currently anomalous AND changing
    active_drivers = {k: v for k, v in current_changes.items()
                      if k in current_anomalous and abs(v) > 0.01}

    if not active_drivers:
        return pd.DataFrame()

    at_risk_keys = all_keys - current_anomalous
    # Filter corr_pairs to rows where A is an active driver
    active_conds = corr_pairs[corr_pairs["key_a"].isin(active_drivers)]

    results = []
    for key_b in at_risk_keys:
        relevant = active_conds[active_conds["key_b"] == key_b]
        if relevant.empty:
            continue

        # Score each driver: |Δrate_A| × correlation
        scores = relevant.apply(
            lambda r: abs(active_drivers[r["key_a"]]) * r["best_corr"], axis=1
        )
        combined = float(scores.sum())
        if combined < min_score:
            continue

        best_idx    = scores.idxmax()
        best        = relevant.loc[best_idx]
        driver_key  = best["key_a"]

        results.append({
            "key_b":             key_b,
            "score":             combined,
            "best_driver_key":   driver_key,
            "best_driver_corr":  float(best["best_corr"]),
            "best_driver_lag":   int(best["best_lag"]),
            "best_driver_change": float(active_drivers[driver_key]),
            "n_drivers":         len(relevant),
        })

    if not results:
        return pd.DataFrame()

    return (
        pd.DataFrame(results)
        .sort_values("score", ascending=False)
        .reset_index(drop=True)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline integration — compute and persist to InfluxDB
# ─────────────────────────────────────────────────────────────────────────────

def update_correlation_pairs(settings) -> None:
    """Compute behavioral cross-correlation pairs and write them to InfluxDB.

    Called from run_all() in detect.py so the result is available to the
    dashboard without any compute on the dashboard side. The dashboard reads
    the 'api_correlation' measurement (fast) instead of recomputing (slow).

    Writes one Point per correlated pair to the Anomalies bucket:
        measurement: api_correlation
        tags: key_a, key_b
        fields: best_corr (float), best_lag (int)
    """
    from .config import Settings
    from influxdb_client import InfluxDBClient, Point, WritePrecision
    from influxdb_client.client.write_api import SYNCHRONOUS

    try:
        # Query last 7 days of hourly error rates
        from influxdb_client.client.warnings import MissingPivotFunction
        import warnings
        warnings.simplefilter("ignore", MissingPivotFunction)

        with InfluxDBClient(url=settings.influx_url, token=settings.influx_token,
                            org=settings.influx_org, timeout=60_000) as client:
            result = client.query_api().query_data_frame(f'''
            from(bucket: "{settings.anomaly_bucket}")
              |> range(start: -7d)
              |> filter(fn: (r) => r._measurement == "error_rate_anomaly")
              |> filter(fn: (r) => r._field == "error_rate")
              |> group(columns: ["apiproxy", "error_class"])
              |> aggregateWindow(every: 1h, fn: last, createEmpty: false)
            ''')

        if result is None or (isinstance(result, list) and not result):
            log.warning("update_correlation_pairs: no rate data returned")
            return

        if isinstance(result, list):
            result = pd.concat(result, ignore_index=True)
        if result.empty:
            return

        # Build rate matrix — guard against NaN tags (query_data_frame quirk
        # where tags become NaN floats when not present for a table group)
        rows = []
        for _, row in result.iterrows():
            proxy = row.get("apiproxy", "")
            ec    = row.get("error_class", "")
            # query_data_frame can return NaN (float) for missing tags
            if not isinstance(ec, str) or not ec:
                continue
            ts    = pd.Timestamp(row["_time"]).floor("h")
            rate  = float(row.get("_value") or 0)
            if proxy:
                rows.append({"proxy": proxy, "error_class": ec, "hour": ts, "rate": rate})

        if not rows:
            return

        history_df = pd.DataFrame(rows)
        matrix     = build_rate_matrix(history_df)
        pairs      = compute_crosscorr_pairs(matrix)

        if pairs.empty:
            log.info("update_correlation_pairs: no significant pairs found")
            return

        # Write pairs to InfluxDB
        now    = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        # Store best_lag as a TAG (not a field) so the dashboard can read
        # best_corr with a simple last() query — no pivot needed, much faster.
        points = []
        for _, row in pairs.iterrows():
            points.append(
                Point("api_correlation")
                .tag("key_a",    row["key_a"])
                .tag("key_b",    row["key_b"])
                .tag("best_lag", str(int(row["best_lag"])))
                .field("best_corr", float(row["best_corr"]))
                .time(now, WritePrecision.S)
            )

        with InfluxDBClient(url=settings.influx_url, token=settings.influx_token,
                            org=settings.influx_org, timeout=60_000) as client:
            client.write_api(write_options=SYNCHRONOUS).write(
                bucket=settings.anomaly_bucket, record=points
            )

        log.info("correlation pairs written: %d pairs → Anomalies bucket", len(points))

    except Exception as exc:
        log.error("update_correlation_pairs failed: %s", exc)
