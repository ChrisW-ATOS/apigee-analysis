"""Anomaly detection — rolling Z-score on traffic volume and error rates."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from .config import Settings

log = logging.getLogger(__name__)

# Number of standard deviations to flag as anomalous
Z_THRESHOLD = 3.0

# Rolling window used to compute baseline (hours)
BASELINE_HOURS = 168  # 7 days

# Apigee analytics lag — data is typically 1-2 hours behind real-time.
# Queries use range(start: -(BASELINE_HOURS + LAG_HOURS)) so the most
# recent data point in the dataset is always LAG_HOURS old, not missing.
LAG_HOURS = 2


def _client(settings: Settings) -> InfluxDBClient:
    return InfluxDBClient(
        url=settings.influx_url,
        token=settings.influx_token,
        org=settings.influx_org,
        timeout=120_000,  # 2 minutes
    )


def _query(client: InfluxDBClient, flux: str) -> pd.DataFrame:
    return client.query_api().query_data_frame(flux)


def detect_traffic_anomalies(settings: Settings) -> list[Point]:
    """Detect traffic volume anomalies per apiproxy using rolling Z-score.

    Returns a list of InfluxDB Points to write to the anomaly bucket.
    """
    with _client(settings) as client:
        flux = f'''
        from(bucket: "{settings.source_bucket}")
          |> range(start: -{BASELINE_HOURS + LAG_HOURS}h)
          |> filter(fn: (r) => r._field == "Sum of traffic")
          |> group(columns: ["apiproxy"])
          |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
        '''
        df = _query(client, flux)

    if df.empty:
        log.warning("traffic query returned no data")
        return []

    points: list[Point] = []
    now = datetime.now(timezone.utc)

    for proxy, grp in df.groupby("apiproxy"):
        grp = grp.sort_values("_time").set_index("_time")
        values = grp["_value"].astype(float)
        if len(values) < 10:
            continue

        mean = values.rolling(BASELINE_HOURS, min_periods=10).mean()
        std  = values.rolling(BASELINE_HOURS, min_periods=10).std().replace(0, np.nan)
        zscore = ((values - mean) / std).fillna(0)

        latest = zscore.iloc[-1]
        is_anomaly = abs(latest) >= Z_THRESHOLD

        p = (
            Point("traffic_anomaly")
            .tag("apiproxy", proxy)
            .tag("is_anomaly", str(is_anomaly).lower())
            .field("z_score", float(round(latest, 4)))
            .field("traffic", float(values.iloc[-1]))
            .field("baseline_mean", float(round(mean.iloc[-1], 2)))
            .time(now, WritePrecision.S)
        )
        points.append(p)
        if is_anomaly:
            log.warning("ANOMALY traffic | proxy=%s z=%.2f", proxy, latest)

    log.info("traffic anomaly check: %d proxies, %d anomalies",
             len(points), sum(1 for p in points if "true" in str(p.to_line_protocol())))
    return points


def _error_rate_points(df: pd.DataFrame, error_class: str,
                       status_prefix: tuple, at: datetime) -> list[Point]:
    """Compute Z-score anomaly points for a specific error class (client/server)."""
    points: list[Point] = []
    df = df.copy()
    df["is_error"] = df["response_status_code"].astype(str).str.startswith(status_prefix)

    for proxy, grp in df.groupby("apiproxy"):
        by_time = grp.groupby("_time").apply(
            lambda g: g.loc[g["is_error"], "_value"].sum() / g["_value"].sum()
            if g["_value"].sum() > 0 else 0.0
        ).rename("error_rate").reset_index()
        by_time = by_time.sort_values("_time").set_index("_time")

        rates = by_time["error_rate"].astype(float)
        if len(rates) < 10:
            continue

        mean   = rates.mean()
        std    = rates.std()
        if std == 0:
            continue
        latest = rates.iloc[-1]
        zscore = (latest - mean) / std
        is_anomaly = abs(zscore) >= Z_THRESHOLD

        points.append(
            Point("error_rate_anomaly")
            .tag("apiproxy", proxy)
            .tag("error_class", error_class)
            .tag("is_anomaly", str(is_anomaly).lower())
            .field("z_score", float(round(zscore, 4)))
            .field("error_rate", float(round(latest, 4)))
            .field("baseline_mean", float(round(mean, 4)))
            .time(at, WritePrecision.S)
        )
        if is_anomaly:
            log.warning("ANOMALY error_rate [%s] | proxy=%s z=%.2f rate=%.2f%%",
                        error_class, proxy, zscore, latest * 100)
    return points


def detect_error_rate_anomalies(settings: Settings) -> list[Point]:
    """Detect error rate anomalies per apiproxy, split by client (4xx) and server (5xx)."""
    with _client(settings) as client:
        flux = f'''
        from(bucket: "{settings.source_bucket}")
          |> range(start: -{BASELINE_HOURS + LAG_HOURS}h)
          |> filter(fn: (r) => r._field == "Sum of traffic")
          |> group(columns: ["apiproxy", "response_status_code"])
          |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
        '''
        df = _query(client, flux)

    if df.empty:
        log.warning("error rate query returned no data")
        return []

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    points  = _error_rate_points(df, "client", ("4",), now)
    points += _error_rate_points(df, "server", ("5",), now)
    return points


def _run_at(settings: Settings, at: datetime) -> list[Point]:
    """Run all detectors with the baseline window ending at `at`."""
    stop = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_ts = (at - timedelta(hours=BASELINE_HOURS + LAG_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    points: list[Point] = []

    with _client(settings) as client:
        # Traffic volume
        flux = f'''
        from(bucket: "{settings.source_bucket}")
          |> range(start: {start_ts}, stop: {stop})
          |> filter(fn: (r) => r._field == "Sum of traffic")
          |> group(columns: ["apiproxy"])
          |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
        '''
        df = _query(client, flux)

    if not df.empty:
        for proxy, grp in df.groupby("apiproxy"):
            grp = grp.sort_values("_time").set_index("_time")
            values = grp["_value"].astype(float)
            if len(values) < 10:
                continue
            mean = values.mean()
            std  = values.std()
            if std == 0:
                continue
            latest = values.iloc[-1]
            zscore = (latest - mean) / std
            is_anomaly = abs(zscore) >= Z_THRESHOLD
            points.append(
                Point("traffic_anomaly")
                .tag("apiproxy", proxy)
                .tag("is_anomaly", str(is_anomaly).lower())
                .field("z_score", float(round(zscore, 4)))
                .field("traffic", float(latest))
                .field("baseline_mean", float(round(mean, 2)))
                .time(at, WritePrecision.S)
            )

    with _client(settings) as client:
        # Error rates — split by client (4xx) and server (5xx)
        flux = f'''
        from(bucket: "{settings.source_bucket}")
          |> range(start: {start_ts}, stop: {stop})
          |> filter(fn: (r) => r._field == "Sum of traffic")
          |> group(columns: ["apiproxy", "response_status_code"])
          |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
        '''
        df = _query(client, flux)

    if not df.empty:
        points += _error_rate_points(df, "client", ("4",), at)
        points += _error_rate_points(df, "server", ("5",), at)

    return points


def run_all(settings: Settings, at: datetime | None = None) -> None:
    """Run all detectors and write results to the anomaly bucket."""
    at = at or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    points = _run_at(settings, at)

    if not points:
        log.info("no anomaly points to write")
        return

    with _client(settings) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        write_api.write(bucket=settings.anomaly_bucket, record=points)
        log.info("wrote %d anomaly points to '%s' at %s",
                 len(points), settings.anomaly_bucket, at.strftime("%Y-%m-%dT%H:%M:%SZ"))


def backfill(settings: Settings, hours: int = 24) -> None:
    """Run detection for each of the last `hours` hours using a sliding window."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    all_points: list[Point] = []

    for h in range(hours, 0, -1):
        at = now - timedelta(hours=h)
        log.info("backfill %d/%d — window ending %s", hours - h + 1, hours,
                 at.strftime("%Y-%m-%dT%H:%M:%SZ"))
        pts = _run_at(settings, at)
        all_points.extend(pts)
        anomalies = sum(1 for p in pts if '"is_anomaly":"true"' in p.to_line_protocol()
                        or "is_anomaly=true" in p.to_line_protocol())
        log.info("  → %d points, %d anomalies", len(pts), anomalies)

    if not all_points:
        log.info("no points to write")
        return

    with _client(settings) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        write_api.write(bucket=settings.anomaly_bucket, record=all_points)
        log.info("backfill complete — wrote %d total points", len(all_points))
