"""Co-failure correlation model for cascade risk prediction.

Learns conditional failure probabilities from historical anomaly data:
    P(proxy B becomes anomalous within lag_hours | proxy A is currently anomalous)

These probabilities are used to generate ranked cascade risk predictions:
given the set of currently-failing APIs, score every non-failing API by how
likely it is to fail in the next 1-4 hours based purely on historical patterns.

The model does NOT extrapolate trends. It answers a different question:
"Given what's failing right now, what has historically followed?"

This is appropriate for data with 1-hour resolution and 1-2 hour Apigee lag.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# Minimum number of times proxy A must have been anomalous before we
# compute conditional probabilities involving it. Fewer occurrences
# produce unreliable probability estimates.
MIN_A_OCCURRENCES = 5    # need at least 5 observations of A to trust P(B|A)
MIN_AB_OCCURRENCES = 3  # need at least 3 co-failures to consider the relationship real

# Maximum hours ahead to consider for co-failure relationships.
MAX_LAG_HOURS = 4


def build_anomaly_events(history_df: pd.DataFrame) -> dict[str, set]:
    """Convert history DataFrame to a dict of proxy → set of anomalous UTC hours.

    Args:
        history_df: DataFrame with columns [proxy, hour, is_anomalous].
                    `hour` is a timezone-aware pd.Timestamp truncated to the hour.

    Returns:
        {proxy_key: {hour_timestamp, ...}}
    """
    events: dict[str, set] = defaultdict(set)
    for _, row in history_df[history_df["is_anomalous"]].iterrows():
        key = f"{row['proxy']}|{row['error_class']}"
        ts  = row["hour"]
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        events[key].add(ts)
    return dict(events)


def compute_conditional_probs(
    events:      dict[str, set],
    lag_hours:   int = MAX_LAG_HOURS,
) -> pd.DataFrame:
    """Compute P(B anomalous within lag_hours | A anomalous) for every (A, B) pair.

    Only pairs where P >= 0.20 and count_a >= MIN_A_OCCURRENCES are retained.

    Returns DataFrame with columns:
        key_a, key_b, count_a, count_ab, prob, best_lag
    """
    keys = list(events.keys())
    rows = []

    for key_a in keys:
        times_a = events[key_a]
        if len(times_a) < MIN_A_OCCURRENCES:
            continue

        for key_b in keys:
            if key_a == key_b:
                continue
            times_b = events[key_b]
            if not times_b:
                continue

            # Count how many of A's anomalous hours were followed by B within lag_hours
            count_ab  = 0
            best_lag  = lag_hours
            for ta in times_a:
                for lag in range(1, lag_hours + 1):
                    if (ta + timedelta(hours=lag)) in times_b:
                        count_ab += 1
                        best_lag  = min(best_lag, lag)
                        break

            prob = count_ab / len(times_a)
            # Require both meaningful co-occurrence count and probability.
            # Laplace-smoothed probability shrinks extreme values from sparse data.
            prob_smoothed = (count_ab + 1) / (len(times_a) + 2)
            if prob >= 0.30 and count_ab >= MIN_AB_OCCURRENCES:
                rows.append({
                    "key_a":         key_a,
                    "key_b":         key_b,
                    "count_a":       len(times_a),
                    "count_ab":      count_ab,
                    "prob":          prob,
                    "prob_smoothed": prob_smoothed,
                    "best_lag":      best_lag,
                })

    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["key_a", "key_b", "count_a", "count_ab", "prob", "best_lag"]
    )


def predict_cascade(
    cond_probs:         pd.DataFrame,
    current_anomalous:  set[str],
    all_proxies:        set[str],
    min_display_prob:   float = 0.25,
) -> pd.DataFrame:
    """Given currently-anomalous proxy keys, score non-anomalous proxies for cascade risk.

    Combination rule (independence assumption / naive Bayes):
        P(B fails | A1 failing, A2 failing, ...) = 1 - ∏(1 - P(B|Ai))

    Args:
        cond_probs:        Output of compute_conditional_probs().
        current_anomalous: Set of proxy keys currently anomalous.
        all_proxies:       Set of all known proxy keys.
        min_display_prob:  Minimum combined probability to include in results.

    Returns DataFrame with columns:
        key_b, combined_prob, best_driver_key, driver_prob,
        driver_count_a, driver_count_ab, best_lag
    """
    if cond_probs.empty or not current_anomalous:
        return pd.DataFrame()

    at_risk_keys = all_proxies - current_anomalous
    results = []

    # Filter cond_probs to rows where A is currently anomalous
    active_conds = cond_probs[cond_probs["key_a"].isin(current_anomalous)]

    for key_b in at_risk_keys:
        relevant = active_conds[active_conds["key_b"] == key_b]
        if relevant.empty:
            continue

        # Naive Bayes combination: 1 - ∏(1 - P(B|Ai))
        combined = 1.0 - np.prod(1.0 - relevant["prob"].values)

        # Rank by the BEST single driver's smoothed probability.
        # The combined naive-Bayes score inflates quickly with many active failures
        # and obscures which relationship is actually meaningful.
        best        = relevant.loc[relevant["prob_smoothed"].idxmax()]
        best_single = float(best["prob_smoothed"])

        if best_single < min_display_prob:
            continue

        results.append({
            "key_b":           key_b,
            "combined_prob":   float(combined),      # for reference
            "best_single_prob": best_single,         # primary ranking score
            "best_driver_key": best["key_a"],
            "driver_prob":     float(best["prob"]),  # raw proportion for display
            "driver_count_a":  int(best["count_a"]),
            "driver_count_ab": int(best["count_ab"]),
            "best_lag":        int(best["best_lag"]),
            "n_drivers":       len(relevant),
        })

    if not results:
        return pd.DataFrame()

    return (
        pd.DataFrame(results)
        .sort_values("best_single_prob", ascending=False)
        .reset_index(drop=True)
    )
