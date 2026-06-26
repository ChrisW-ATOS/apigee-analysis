"""Anomaly detection — rolling Z-score on traffic volume and error rates."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from .baseline import zscore_and_forecast
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


def _load_previous_anomalies(settings: Settings, at: datetime) -> dict:
    """Load all anomaly results from the previous hour into a lookup dict.

    Returns: {(measurement, key_tag_value): consecutive_hours}
    where key_tag_value is apiproxy for proxy measurements, xcountrycode for country_health.
    Only includes records where is_anomaly == "true".
    """
    prev_hour = at - timedelta(hours=1)
    start = (prev_hour - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stop  = (prev_hour + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    lookup: dict = {}
    try:
        with _client(settings) as client:
            flux = f'''
            from(bucket: "{settings.anomaly_bucket}")
              |> range(start: {start}, stop: {stop})
              |> filter(fn: (r) => r.is_anomaly == "true")
            '''
            tables = client.query_api().query(flux, org=settings.influx_org)
            for table in tables:
                for rec in table.records:
                    m = rec.get_measurement()
                    key = rec.values.get("apiproxy") or rec.values.get("xcountrycode", "")
                    error_class = rec.values.get("error_class", "")
                    lookup_key = (m, key, error_class)
                    prev_consec = rec.values.get("consecutive_hours", 1)
                    lookup[lookup_key] = int(prev_consec) if prev_consec else 1
    except Exception as exc:
        log.debug("could not load previous anomalies (first run?): %s", exc)
    return lookup


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
                       status_prefix: tuple, at: datetime,
                       prev: dict | None = None) -> list[Point]:
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

        zscore, _ = zscore_and_forecast(rates, forecast_hours=2)
        is_anomaly = abs(zscore) >= Z_THRESHOLD

        prev_consec = (prev or {}).get(("error_rate_anomaly", proxy, error_class), 0)
        consec = (prev_consec + 1) if is_anomaly else 0
        sustained = is_anomaly and consec >= 2

        points.append(
            Point("error_rate_anomaly")
            .tag("apiproxy", proxy)
            .tag("error_class", error_class)
            .tag("is_anomaly", str(is_anomaly).lower())
            .tag("sustained", str(sustained).lower())
            .field("z_score", float(round(zscore, 4)))
            .field("error_rate", float(round(rates.iloc[-1], 4)))
            .field("baseline_mean", float(round(rates.mean(), 4)))
            .field("consecutive_hours", consec)
            .time(at, WritePrecision.S)
        )
        if is_anomaly:
            log.warning("ANOMALY error_rate [%s] | proxy=%s z=%.2f rate=%.2f%% | sustained=%s hours=%d",
                        error_class, proxy, zscore, rates.iloc[-1] * 100, sustained, consec)
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


def detect_country_health(settings: Settings) -> list[Point]:
    """Compute a rolled-up health score per xcountrycode.

    Aggregates error rate across all proxies for each country and applies
    Z-score against a 7-day baseline. Writes to measurement 'country_health'
    with tags: xcountrycode, is_anomaly.
    Fields: error_rate, z_score, total_calls, total_errors.
    """
    with _client(settings) as client:
        flux = f'''
        from(bucket: "{settings.source_bucket}")
          |> range(start: -{BASELINE_HOURS + LAG_HOURS}h)
          |> filter(fn: (r) => r._field == "Sum of traffic")
          |> group(columns: ["xcountrycode", "response_status_code"])
          |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
        '''
        df = _query(client, flux)

    if df.empty:
        log.warning("country health query returned no data")
        return []

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    points: list[Point] = []

    for country, grp in df.groupby("xcountrycode"):
        if not country or country in ("(not set)", ""):
            continue
        grp = grp.copy()
        grp["is_error"] = grp["response_status_code"].astype(str).str.startswith(("4", "5"))

        # Build hourly error rate + call volume for this country
        by_time = grp.groupby("_time").apply(
            lambda g: pd.Series({
                "error_rate": g.loc[g["is_error"], "_value"].sum() / g["_value"].sum()
                              if g["_value"].sum() > 0 else 0.0,
                "total_calls": g["_value"].sum(),
                "total_errors": g.loc[g["is_error"], "_value"].sum(),
            })
        ).reset_index().sort_values("_time").set_index("_time")

        rates = by_time["error_rate"].astype(float)
        if len(rates) < 10:
            continue

        mean   = rates.mean()
        std    = rates.std()
        if std == 0:
            continue
        latest_rate   = rates.iloc[-1]
        zscore        = (latest_rate - mean) / std
        is_anomaly    = abs(zscore) >= Z_THRESHOLD
        total_calls   = float(by_time["total_calls"].iloc[-1])
        total_errors  = float(by_time["total_errors"].iloc[-1])

        points.append(
            Point("country_health")
            .tag("xcountrycode", country)
            .tag("is_anomaly", str(is_anomaly).lower())
            .field("error_rate", float(round(latest_rate, 4)))
            .field("z_score",    float(round(zscore, 4)))
            .field("total_calls",   total_calls)
            .field("total_errors",  total_errors)
            .field("baseline_mean", float(round(mean, 4)))
            .time(now, WritePrecision.S)
        )
        if is_anomaly:
            log.warning("ANOMALY country_health | country=%s z=%.2f error_rate=%.2f%%",
                        country, zscore, latest_rate * 100)

    log.info("country health: %d countries, %d anomalies",
             len(points), sum(1 for p in points if "true" in str(p.to_line_protocol())))
    return points


def _run_at(settings: Settings, at: datetime) -> list[Point]:
    """Run all detectors with the baseline window ending at `at`."""
    stop = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_ts = (at - timedelta(hours=BASELINE_HOURS + LAG_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev = _load_previous_anomalies(settings, at)

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
            zscore, forecast_z = zscore_and_forecast(values)
            is_anomaly = abs(zscore) >= Z_THRESHOLD
            prev_consec = prev.get(("traffic_anomaly", proxy, ""), 0)
            consec = (prev_consec + 1) if is_anomaly else 0
            points.append(
                Point("traffic_anomaly")
                .tag("apiproxy", proxy)
                .tag("is_anomaly", str(is_anomaly).lower())
                .tag("sustained", str(is_anomaly and consec >= 2).lower())
                .field("z_score", float(round(zscore, 4)))
                .field("traffic", float(values.iloc[-1]))
                .field("baseline_mean", float(round(values.mean(), 2)))
                .field("consecutive_hours", consec)
                .time(at, WritePrecision.S)
            )
            # Predictive alert — flag if forecast also crosses threshold
            if forecast_z is not None and abs(forecast_z) >= Z_THRESHOLD and not is_anomaly:
                points.append(
                    Point("predicted_anomaly")
                    .tag("apiproxy", proxy)
                    .tag("measurement", "traffic")
                    .field("forecast_z_score", float(round(forecast_z, 4)))
                    .field("hours_until_threshold", 2)
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
        points += _error_rate_points(df, "client", ("4",), at, prev)
        points += _error_rate_points(df, "server", ("5",), at, prev)

    # Blast radius for anomalous proxies in this window
    anomalous = {
        part.split("=", 1)[1].strip().strip('"')
        for p in points
        for part in (p.to_line_protocol() or "").split(",")
        if part.startswith("apiproxy=") and (
            "is_anomaly=true" in (p.to_line_protocol() or "") or
            'is_anomaly="true"' in (p.to_line_protocol() or "")
        )
    }
    points += detect_blast_radius(settings, anomalous, at)

    # Country health — using explicit time window for backfill accuracy
    with _client(settings) as client:
        flux = f'''
        from(bucket: "{settings.source_bucket}")
          |> range(start: {start_ts}, stop: {stop})
          |> filter(fn: (r) => r._field == "Sum of traffic")
          |> group(columns: ["xcountrycode", "response_status_code"])
          |> aggregateWindow(every: 1h, fn: sum, createEmpty: false)
        '''
        df = _query(client, flux)

    if not df.empty:
        for country, grp in df.groupby("xcountrycode"):
            if not country or country in ("(not set)", ""):
                continue
            grp = grp.copy()
            grp["is_error"] = grp["response_status_code"].astype(str).str.startswith(("4", "5"))
            by_time = grp.groupby("_time").apply(
                lambda g: pd.Series({
                    "error_rate": g.loc[g["is_error"], "_value"].sum() / g["_value"].sum()
                                  if g["_value"].sum() > 0 else 0.0,
                    "total_calls":  g["_value"].sum(),
                    "total_errors": g.loc[g["is_error"], "_value"].sum(),
                })
            ).reset_index().sort_values("_time").set_index("_time")
            rates = by_time["error_rate"].astype(float)
            if len(rates) < 10:
                continue
            mean = rates.mean()
            std  = rates.std()
            if std == 0:
                continue
            latest = rates.iloc[-1]
            zscore = (latest - mean) / std
            is_anomaly = abs(zscore) >= Z_THRESHOLD
            prev_consec = prev.get(("country_health", country, ""), 0)
            consec = (prev_consec + 1) if is_anomaly else 0
            points.append(
                Point("country_health")
                .tag("xcountrycode", country)
                .tag("is_anomaly", str(is_anomaly).lower())
                .tag("sustained", str(is_anomaly and consec >= 2).lower())
                .field("error_rate",       float(round(latest, 4)))
                .field("z_score",          float(round(zscore, 4)))
                .field("total_calls",      float(by_time["total_calls"].iloc[-1]))
                .field("total_errors",     float(by_time["total_errors"].iloc[-1]))
                .field("baseline_mean",    float(round(mean, 4)))
                .field("consecutive_hours", consec)
                .time(at, WritePrecision.S)
            )

    return points


def detect_blast_radius(settings: Settings, anomalous_proxies: set[str],
                        at: datetime) -> list[Point]:
    """For each anomalous proxy, find which developer_apps and countries are affected.

    Queries the last LAG_HOURS+1 hours of traffic for the anomalous proxies and
    returns one Point per (apiproxy, developer_app, xcountrycode) combination.
    Measurement: blast_radius. Fields: call_count.
    """
    if not anomalous_proxies:
        return []

    stop     = at.strftime("%Y-%m-%dT%H:%M:%SZ")
    start_ts = (at - timedelta(hours=LAG_HOURS + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with _client(settings) as client:
        flux = f'''
        from(bucket: "{settings.source_bucket}")
          |> range(start: {start_ts}, stop: {stop})
          |> filter(fn: (r) => r._field == "Sum of traffic")
          |> group(columns: ["apiproxy", "developer_app", "xcountrycode"])
          |> sum()
        '''
        df = _query(client, flux)

    if df.empty:
        return []

    points: list[Point] = []
    for _, row in df.iterrows():
        proxy = row.get("apiproxy", "")
        if proxy not in anomalous_proxies:
            continue
        app     = row.get("developer_app", "(not set)")
        country = row.get("xcountrycode", "(not set)")
        calls   = float(row.get("_value", 0))
        if calls == 0:
            continue
        points.append(
            Point("blast_radius")
            .tag("apiproxy",      proxy)
            .tag("developer_app", app)
            .tag("xcountrycode",  country)
            .field("call_count", calls)
            .time(at, WritePrecision.S)
        )

    log.info("blast radius: %d affected app/country combinations across %d anomalous proxies",
             len(points), len(anomalous_proxies))
    return points


def run_all(settings: Settings, at: datetime | None = None) -> None:
    """Run all detectors and write results to the anomaly bucket."""
    at = at or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    points  = _run_at(settings, at)
    points += detect_country_health(settings)

    # Blast radius — identify affected apps/countries for anomalous proxies
    anomalous_proxies: set[str] = set()
    for p in points:
        lp = p.to_line_protocol() or ""
        if "is_anomaly=true" in lp or 'is_anomaly="true"' in lp:
            # Extract apiproxy tag value from line protocol
            for part in lp.split(","):
                if part.startswith("apiproxy="):
                    proxy = part.split("=", 1)[1].strip().strip('"')
                    if proxy:
                        anomalous_proxies.add(proxy)
    points += detect_blast_radius(settings, anomalous_proxies, at)

    if not points:
        log.info("no anomaly points to write")
        return

    with _client(settings) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)
        write_api.write(bucket=settings.anomaly_bucket, record=points)
        log.info("wrote %d anomaly points to '%s' at %s",
                 len(points), settings.anomaly_bucket, at.strftime("%Y-%m-%dT%H:%M:%SZ"))

    # Multivariate anomaly detection — runs after Z-score results are written
    from .multivariate import run_multivariate
    run_multivariate(settings, at)

    # Generate incident brief if anomalies were found
    from .intelligence import run_intelligence
    run_intelligence(settings, at)


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
