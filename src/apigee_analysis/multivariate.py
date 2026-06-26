"""Multivariate anomaly detection using Isolation Forest.

Trains on per-proxy feature vectors pulled from the Anomalies bucket:

    [traffic_z, client_z, server_z, client_rate, server_rate]

A single global model is trained across all proxies and all hours in the
7-day window. This means the model learns what combinations of metrics are
normal across the estate — and flags observations where the combination is
unusual even if each metric individually looks fine.

Typical patterns it catches that Z-score misses:
  - Traffic drops to near-zero while error rate stays low  (silent failure)
  - Traffic normal, but error mix flips from 4xx to 5xx   (backend swap)
  - Two correlated proxies suddenly diverge               (dependency split)

Model is serialised with joblib and retrained if older than MODEL_MAX_AGE_HOURS.
Results are written to the 'multivariate_anomaly' measurement in the Anomalies bucket.
"""
from __future__ import annotations

import logging
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from influxdb_client import Point, WritePrecision
from influxdb_client.client.warnings import MissingPivotFunction
from influxdb_client.client.write_api import SYNCHRONOUS
from sklearn.ensemble import IsolationForest

from .config import Settings
from .detect import _client

warnings.simplefilter("ignore", MissingPivotFunction)
log = logging.getLogger(__name__)

MODEL_DIR             = Path(__file__).parent.parent.parent / "models"
MODEL_PATH            = MODEL_DIR / "isolation_forest.pkl"
MODEL_MAX_AGE_HOURS   = 24
CONTAMINATION         = 0.05     # expect ~5% of observations to be anomalous
N_ESTIMATORS          = 100
FEATURES              = ["traffic_z", "client_z", "server_z", "client_rate", "server_rate"]
MIN_TRAINING_ROWS     = 100      # need at least this many proxy-hour observations


# ─────────────────────────────────────────────────────────────────────────────
# Feature extraction
# ─────────────────────────────────────────────────────────────────────────────

def _concat(result) -> pd.DataFrame:
    """Normalise query_data_frame output (single df or list of dfs)."""
    if result is None:
        return pd.DataFrame()
    if isinstance(result, list):
        result = [r for r in result if r is not None and not r.empty]
        if not result:
            return pd.DataFrame()
        return pd.concat(result, ignore_index=True)
    return result


def _fetch_features(settings: Settings, start_ts: str, stop_ts: str) -> pd.DataFrame:
    """Return a DataFrame with columns [proxy, time, traffic_z, client_z, server_z, client_rate, server_rate].

    Queries the Anomalies bucket for already-computed Z-scores and error rates,
    then merges the three series (traffic, client errors, server errors) on (proxy, hour).
    Missing error data for a proxy-hour is filled with 0.
    """
    with _client(settings) as client:
        api = client.query_api()

        # ── Traffic Z-scores ──────────────────────────────────────────────────
        t_raw = _concat(api.query_data_frame(f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: {start_ts}, stop: {stop_ts})
          |> filter(fn: (r) => r._measurement == "traffic_anomaly" and r._field == "z_score")
        '''))

        # ── Client error Z-scores + rates ─────────────────────────────────────
        c_raw = _concat(api.query_data_frame(f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: {start_ts}, stop: {stop_ts})
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly" and r.error_class == "client")
          |> filter(fn: (r) => r._field == "z_score" or r._field == "error_rate")
          |> pivot(rowKey:["_time","apiproxy"], columnKey:["_field"], valueColumn:"_value")
        '''))

        # ── Server error Z-scores + rates ─────────────────────────────────────
        s_raw = _concat(api.query_data_frame(f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: {start_ts}, stop: {stop_ts})
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly" and r.error_class == "server")
          |> filter(fn: (r) => r._field == "z_score" or r._field == "error_rate")
          |> pivot(rowKey:["_time","apiproxy"], columnKey:["_field"], valueColumn:"_value")
        '''))

    # ── Normalise each frame ──────────────────────────────────────────────────
    def _norm_traffic(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or "_value" not in df.columns:
            return pd.DataFrame(columns=["proxy", "time", "traffic_z"])
        out = df[["_time", "apiproxy", "_value"]].copy()
        out.columns = ["time", "proxy", "traffic_z"]
        out["time"] = pd.to_datetime(out["time"]).dt.floor("h")
        return out.dropna(subset=["proxy", "traffic_z"])

    def _norm_error(df: pd.DataFrame, z_col: str, rate_col: str) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=["proxy", "time", z_col, rate_col])
        cols = {"_time": "time", "apiproxy": "proxy"}
        if "z_score" in df.columns:
            cols["z_score"] = z_col
        if "error_rate" in df.columns:
            cols["error_rate"] = rate_col
        out = df.rename(columns=cols)[["time", "proxy"] +
              ([z_col] if z_col in cols.values() else []) +
              ([rate_col] if rate_col in cols.values() else [])].copy()
        out["time"] = pd.to_datetime(out["time"]).dt.floor("h")
        return out.dropna(subset=["proxy"])

    t_df = _norm_traffic(t_raw)
    c_df = _norm_error(c_raw, "client_z", "client_rate")
    s_df = _norm_error(s_raw, "server_z", "server_rate")

    if t_df.empty:
        return pd.DataFrame()

    # ── Merge on (proxy, time) ────────────────────────────────────────────────
    df = t_df
    df = df.merge(c_df, on=["proxy", "time"], how="left") if not c_df.empty else df
    df = df.merge(s_df, on=["proxy", "time"], how="left") if not s_df.empty else df

    # Fill NaN (proxy had no client/server error records that hour → rate was 0)
    for col in FEATURES:
        if col not in df.columns:
            df[col] = 0.0
    df[FEATURES] = df[FEATURES].fillna(0.0).clip(-20, 20)  # clip extreme z-scores

    return df[["proxy", "time"] + FEATURES].reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Model lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def _model_is_fresh() -> bool:
    if not MODEL_PATH.exists():
        return False
    age = (datetime.now() - datetime.fromtimestamp(MODEL_PATH.stat().st_mtime)).total_seconds()
    return age < MODEL_MAX_AGE_HOURS * 3600


def train(settings: Settings) -> IsolationForest | None:
    """Fetch 7 days of historical data, fit the model, and save it to disk."""
    now   = datetime.now(timezone.utc)
    start = (now - timedelta(hours=168)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stop  = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    log.info("training multivariate model on %s → %s", start, stop)
    df = _fetch_features(settings, start, stop)

    if len(df) < MIN_TRAINING_ROWS:
        log.warning("insufficient training data (%d rows, need %d) — skipping multivariate",
                    len(df), MIN_TRAINING_ROWS)
        return None

    X = df[FEATURES].values
    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        contamination=CONTAMINATION,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "trained_at": now.isoformat()}, MODEL_PATH)
    log.info("multivariate model trained on %d proxy-hour observations → %s",
             len(df), MODEL_PATH)
    return model


def load_or_train(settings: Settings) -> IsolationForest | None:
    """Load the cached model if it is fresh; otherwise retrain."""
    if _model_is_fresh():
        try:
            payload = joblib.load(MODEL_PATH)
            model   = payload["model"] if isinstance(payload, dict) else payload
            log.info("loaded multivariate model from disk (trained %s)",
                     payload.get("trained_at", "?") if isinstance(payload, dict) else "?")
            return model
        except Exception as exc:
            log.warning("could not load model (%s) — retraining", exc)
    return train(settings)


# ─────────────────────────────────────────────────────────────────────────────
# Scoring and writing
# ─────────────────────────────────────────────────────────────────────────────

def run_multivariate(settings: Settings, at: datetime) -> None:
    """Score the current hour's proxies and write results to the Anomalies bucket."""
    model = load_or_train(settings)
    if model is None:
        return

    start = (at - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stop  = (at + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    df = _fetch_features(settings, start, stop)
    if df.empty:
        log.info("no feature data for multivariate scoring at %s", at.isoformat())
        return

    X      = df[FEATURES].values
    scores = model.decision_function(X)   # higher = more normal
    preds  = model.predict(X)             # 1 = normal, -1 = anomaly

    df["anomaly_score"] = scores.astype(float)
    df["is_anomaly"]    = preds == -1

    points: list[Point] = []
    for _, row in df.iterrows():
        points.append(
            Point("multivariate_anomaly")
            .tag("apiproxy",    row["proxy"])
            .tag("is_anomaly",  str(bool(row["is_anomaly"])).lower())
            .field("anomaly_score",  float(row["anomaly_score"]))
            .field("traffic_z",      float(row["traffic_z"]))
            .field("client_z",       float(row["client_z"]))
            .field("server_z",       float(row["server_z"]))
            .field("client_rate",    float(row["client_rate"]))
            .field("server_rate",    float(row["server_rate"]))
            .time(at, WritePrecision.S)
        )

    with _client(settings) as client:
        client.write_api(write_options=SYNCHRONOUS).write(
            bucket=settings.anomaly_bucket, record=points
        )

    n_anomalous = int(df["is_anomaly"].sum())
    log.info("multivariate: %d proxies scored, %d flagged", len(points), n_anomalous)

    for _, row in df[df["is_anomaly"]].iterrows():
        log.warning(
            "MULTIVARIATE ANOMALY | proxy=%s score=%.4f "
            "[traffic_z=%.2f client_z=%.2f server_z=%.2f client_rate=%.1f%% server_rate=%.1f%%]",
            row["proxy"], row["anomaly_score"],
            row["traffic_z"], row["client_z"], row["server_z"],
            row["client_rate"] * 100, row["server_rate"] * 100,
        )
