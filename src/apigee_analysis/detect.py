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


def _query(client: InfluxDBClient, flux: str) -> pd.DataFrame:
    return client.query_api().query_data_frame(flux)


def detect_traffic_anomalies(settings: Settings) -> list[Point]:
    """Detect traffic volume anomalies per apiproxy using rolling Z-score.

    Returns a list of InfluxDB Points to write to the anomaly bucket.
    """
    with InfluxDBClient(url=settings.influx_url, token=settings.influx_token,
                        org=settings.influx_org) as client:
        flux = f'''
        from(bucket: "{settings.source_bucket}")
          |> range(start: -{BASELINE_HOURS}h)
          |> filter(fn: (r) => r._measurement == "Sum of traffic" or r._field == "Sum of traffic")
          |> group(columns: ["apiproxy", "_time"])
          |> sum()
          |> group(columns: ["apiproxy"])
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
            .time(now, WritePrecision.SECONDS)
        )
        points.append(p)
        if is_anomaly:
            log.warning("ANOMALY traffic | proxy=%s z=%.2f", proxy, latest)

    log.info("traffic anomaly check: %d proxies, %d anomalies",
             len(points), sum(1 for p in points if "true" in str(p.to_line_protocol())))
    return points


def detect_error_rate_anomalies(settings: Settings) -> list[Point]:
    """Detect error rate anomalies (4xx+5xx / total) per apiproxy."""
    with InfluxDBClient(url=settings.influx_url, token=settings.influx_token,
                        org=settings.influx_org) as client:
        flux = f'''
        from(bucket: "{settings.source_bucket}")
          |> range(start: -{BASELINE_HOURS}h)
          |> filter(fn: (r) => r._field == "Sum of traffic")
          |> group(columns: ["apiproxy", "response_status_code", "_time"])
          |> sum()
          |> group(columns: ["apiproxy", "response_status_code"])
        '''
        df = _query(client, flux)

    if df.empty:
        log.warning("error rate query returned no data")
        return []

    points: list[Point] = []
    now = datetime.now(timezone.utc)

    for proxy, grp in df.groupby("apiproxy"):
        grp = grp.copy()
        grp["is_error"] = grp["response_status_code"].astype(str).str.startswith(("4", "5"))
        by_time = grp.groupby("_time").apply(
            lambda g: g.loc[g["is_error"], "_value"].sum() / g["_value"].sum()
            if g["_value"].sum() > 0 else 0.0
        ).rename("error_rate").reset_index()
        by_time = by_time.sort_values("_time").set_index("_time")

        rates = by_time["error_rate"].astype(float)
        if len(rates) < 10:
            continue

        mean  = rates.rolling(BASELINE_HOURS, min_periods=10).mean()
        std   = rates.rolling(BASELINE_HOURS, min_periods=10).std().replace(0, np.nan)
        zscore = ((rates - mean) / std).fillna(0)

        latest = zscore.iloc[-1]
        is_anomaly = abs(latest) >= Z_THRESHOLD

        p = (
            Point("error_rate_anomaly")
            .tag("apiproxy", proxy)
            .tag("is_anomaly", str(is_anomaly).lower())
            .field("z_score", float(round(latest, 4)))
            .field("error_rate", float(round(rates.iloc[-1], 4)))
            .field("baseline_mean", float(round(mean.iloc[-1], 4)))
            .time(now, WritePrecision.SECONDS)
        )
        points.append(p)
        if is_anomaly:
            log.warning("ANOMALY error_rate | proxy=%s z=%.2f rate=%.2f%%",
                        proxy, latest, rates.iloc[-1] * 100)

    return points


def run_all(settings: Settings) -> None:
    """Run all detectors and write results to the anomaly bucket."""
    points: list[Point] = []
    points += detect_traffic_anomalies(settings)
    points += detect_error_rate_anomalies(settings)

    if not points:
        log.info("no anomaly points to write")
        return

    with InfluxDBClient(url=settings.influx_url, token=settings.influx_token,
                        org=settings.influx_org) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        write_api.write(bucket=settings.anomaly_bucket, record=points)
        log.info("wrote %d anomaly points to '%s'", len(points), settings.anomaly_bucket)
