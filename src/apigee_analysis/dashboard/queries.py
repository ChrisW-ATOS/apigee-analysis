"""InfluxDB query functions for the Streamlit dashboard.

All functions are decorated with @st.cache_data so results are cached for 60s
(300s for slow/static queries like proxy lists). Pass Settings directly — it is
a frozen dataclass and therefore hashable.
"""
from __future__ import annotations

import warnings

import pandas as pd
import streamlit as st
from influxdb_client import InfluxDBClient
from influxdb_client.client.warnings import MissingPivotFunction

from apigee_analysis.config import Settings

warnings.simplefilter("ignore", MissingPivotFunction)


def _client(settings: Settings) -> InfluxDBClient:
    return InfluxDBClient(
        url=settings.influx_url,
        token=settings.influx_token,
        org=settings.influx_org,
        timeout=30_000,
    )


def _query_raw(settings: Settings, flux: str):
    with _client(settings) as client:
        return client.query_api().query(flux, org=settings.influx_org)


# ─────────────────────────────────────────────────────────────────────────────
# Incident Brief
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def get_latest_incident_brief(settings: Settings) -> dict | None:
    flux = f'''
    from(bucket: "{settings.anomaly_bucket}")
      |> range(start: -25h)
      |> filter(fn: (r) => r._measurement == "incident_summary")
      |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
      |> sort(columns:["_time"], desc: true)
      |> limit(n: 1)
    '''
    try:
        tables = _query_raw(settings, flux)
    except Exception:
        return None

    for table in tables:
        for rec in table.records:
            return {
                "timestamp":          rec.get_time(),
                "severity":           rec.values.get("severity", "unknown"),
                "summary":            rec.values.get("summary", ""),
                "root_cause":         rec.values.get("root_cause", ""),
                "recommended_action": rec.values.get("recommended_action", ""),
                "anomaly_count":      int(float(rec.values.get("anomaly_count") or 0)),
                "affected_apps":      int(float(rec.values.get("affected_apps") or 0)),
            }
    return None


@st.cache_data(ttl=60, show_spinner=False)
def get_active_anomalies(settings: Settings) -> pd.DataFrame:
    rows: list[dict] = []

    try:
        # Traffic anomalies — last() per proxy gives CURRENT state, not historical max.
        # Filter is_anomaly=true after last() so proxies that recovered are excluded.
        flux = f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -25h)
          |> filter(fn: (r) => r._measurement == "traffic_anomaly")
          |> filter(fn: (r) => r._field == "z_score")
          |> group(columns: ["apiproxy"])
          |> last()
          |> filter(fn: (r) => r.is_anomaly == "true")
        '''
        for table in _query_raw(settings, flux):
            for rec in table.records:
                rows.append({
                    "time":              rec.get_time(),
                    "proxy":             rec.values.get("apiproxy", ""),
                    "type":              "Traffic",
                    "error_class":       "",
                    "z_score":           float(rec.get_value() or 0),
                    "error_rate":        None,
                    "traffic":           None,
                    "sustained":         rec.values.get("sustained", "false") == "true",
                    "consecutive_hours": int(float(rec.values.get("consecutive_hours") or 1)),
                })

        # Error rate anomalies — same pattern: last() per (proxy, error_class)
        flux = f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -25h)
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly")
          |> filter(fn: (r) => r._field == "z_score")
          |> group(columns: ["apiproxy", "error_class"])
          |> last()
          |> filter(fn: (r) => r.is_anomaly == "true")
        '''
        for table in _query_raw(settings, flux):
            for rec in table.records:
                rows.append({
                    "time":              rec.get_time(),
                    "proxy":             rec.values.get("apiproxy", ""),
                    "type":              "Error Rate",
                    "error_class":       rec.values.get("error_class", ""),
                    "z_score":           float(rec.get_value() or 0),
                    "error_rate":        None,
                    "traffic":           None,
                    "sustained":         rec.values.get("sustained", "false") == "true",
                    "consecutive_hours": int(float(rec.values.get("consecutive_hours") or 1)),
                })

        # Multivariate anomalies — last() per proxy
        flux = f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -25h)
          |> filter(fn: (r) => r._measurement == "multivariate_anomaly")
          |> filter(fn: (r) => r._field == "anomaly_score")
          |> group(columns: ["apiproxy"])
          |> last()
          |> filter(fn: (r) => r.is_anomaly == "true")
        '''
        for table in _query_raw(settings, flux):
            for rec in table.records:
                rows.append({
                    "time":              rec.get_time(),
                    "proxy":             rec.values.get("apiproxy", ""),
                    "type":              "Multivariate",
                    "error_class":       "",
                    "z_score":           float(rec.get_value() or 0),
                    "error_rate":        None,
                    "traffic":           None,
                    "sustained":         False,
                    "consecutive_hours": 1,
                })
    except Exception:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.sort_values("z_score", key=lambda s: s.abs(), ascending=False)
    return df.drop_duplicates(subset=["proxy", "type", "error_class"]).reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def get_error_rate_trend(settings: Settings, top_n: int = 5) -> pd.DataFrame:
    """Last 25h of hourly error rates for the top N most anomalous proxies.

    Step 1: find top_n proxies by peak |z_score| in the last 4h.
    Step 2: fetch 25h of error_rate history for those proxies.
    Returns columns: time, proxy, error_class, error_rate, z_score, is_anomaly.
    """
    try:
        # Top proxies by highest actual error_rate in the last 4h.
        # Using error_rate (not z_score) and a short window means we select
        # APIs that are currently elevated — not ones that spiked hours ago
        # and have since resolved back to 0%.
        top_tables = _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -4h)
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly")
          |> filter(fn: (r) => r._field == "error_rate")
          |> group(columns: ["apiproxy"])
          |> max()
          |> group()
          |> sort(columns: ["_value"], desc: true)
          |> limit(n: {top_n})
        ''')
        top_proxies = [
            rec.values.get("apiproxy", "")
            for t in top_tables for rec in t.records
            if rec.values.get("apiproxy")
        ]
        if not top_proxies:
            return pd.DataFrame()

        proxy_filter = " or ".join(f'r.apiproxy == "{p}"' for p in top_proxies)
        rows = []
        for table in _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -25h)
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly")
          |> filter(fn: (r) => {proxy_filter})
          |> filter(fn: (r) => r._field == "error_rate" or r._field == "z_score")
          |> pivot(rowKey:["_time","apiproxy","error_class","is_anomaly"], columnKey:["_field"], valueColumn:"_value")
        '''):
            for rec in table.records:
                proxy = rec.values.get("apiproxy", "")
                ec    = rec.values.get("error_class", "")
                if proxy and ec:
                    rows.append({
                        "time":        rec.get_time(),
                        "proxy":       proxy,
                        "error_class": ec,
                        "error_rate":  float(rec.values.get("error_rate") or 0),
                        "z_score":     float(rec.values.get("z_score") or 0),
                        "is_anomaly":  rec.values.get("is_anomaly", "false") == "true",
                    })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"])
        return df

    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60, show_spinner=False)
def get_multivariate_anomalies(settings: Settings) -> pd.DataFrame:
    """Return anomalous proxies with full feature breakdown from Isolation Forest."""
    flux = f'''
    from(bucket: "{settings.anomaly_bucket}")
      |> range(start: -25h)
      |> filter(fn: (r) => r._measurement == "multivariate_anomaly" and r.is_anomaly == "true")
      |> pivot(rowKey:["_time","apiproxy"], columnKey:["_field"], valueColumn:"_value")
      |> sort(columns:["anomaly_score"])
    '''
    rows = []
    try:
        for table in _query_raw(settings, flux):
            for rec in table.records:
                proxy = rec.values.get("apiproxy", "")
                if not proxy:
                    continue
                rows.append({
                    "time":         rec.get_time(),
                    "proxy":        proxy,
                    "score":        float(rec.values.get("anomaly_score") or 0),
                    "traffic_z":    float(rec.values.get("traffic_z") or 0),
                    "client_z":     float(rec.values.get("client_z") or 0),
                    "server_z":     float(rec.values.get("server_z") or 0),
                    "client_rate":  float(rec.values.get("client_rate") or 0),
                    "server_rate":  float(rec.values.get("server_rate") or 0),
                })
    except Exception:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.sort_values("score").drop_duplicates("proxy").reset_index(drop=True)
    return df


@st.cache_data(ttl=60, show_spinner=False)
def get_predicted_anomalies(settings: Settings) -> pd.DataFrame:
    flux = f'''
    from(bucket: "{settings.anomaly_bucket}")
      |> range(start: -25h)
      |> filter(fn: (r) => r._measurement == "predicted_anomaly")
      |> filter(fn: (r) => r._field == "forecast_z_score")
      |> group(columns: ["apiproxy"])
      |> last()
    '''
    rows = []
    try:
        for table in _query_raw(settings, flux):
            for rec in table.records:
                proxy = rec.values.get("apiproxy", "")
                if proxy:
                    rows.append({
                        "proxy":           proxy,
                        "measurement":     rec.values.get("measurement", ""),
                        "forecast_z_score": float(rec.get_value() or 0),
                    })
    except Exception:
        pass
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Country Health
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def get_country_health(settings: Settings) -> pd.DataFrame:
    flux = f'''
    from(bucket: "{settings.anomaly_bucket}")
      |> range(start: -25h)
      |> filter(fn: (r) => r._measurement == "country_health")
      |> pivot(rowKey:["_time","xcountrycode","is_anomaly"], columnKey:["_field"], valueColumn:"_value")
    '''
    rows = []
    try:
        for table in _query_raw(settings, flux):
            for rec in table.records:
                country = rec.values.get("xcountrycode", "")
                if not country or country in ("(not set)", ""):
                    continue
                rows.append({
                    "time":           rec.get_time(),
                    "country":        country,
                    "z_score":        float(rec.values.get("z_score") or 0),
                    "error_rate":     float(rec.values.get("error_rate") or 0),
                    "error_rate_pct": float(rec.values.get("error_rate") or 0) * 100,
                    "total_calls":    int(float(rec.values.get("total_calls") or 0)),
                    "total_errors":   int(float(rec.values.get("total_errors") or 0)),
                    "is_anomaly":     rec.values.get("is_anomaly", "false") == "true",
                })
    except Exception:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.sort_values("time", ascending=False).drop_duplicates("country")
    return df.drop(columns=["time"]).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Blast Radius
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def get_blast_radius(settings: Settings, hours_back: int = 4) -> pd.DataFrame:
    flux = f'''
    from(bucket: "{settings.anomaly_bucket}")
      |> range(start: -{hours_back}h)
      |> filter(fn: (r) => r._measurement == "blast_radius")
      |> filter(fn: (r) => r._field == "call_count")
    '''
    rows = []
    try:
        for table in _query_raw(settings, flux):
            for rec in table.records:
                proxy   = rec.values.get("apiproxy", "")
                app     = rec.values.get("developer_app", "(not set)")
                country = rec.values.get("xcountrycode", "(not set)")
                calls   = float(rec.get_value() or 0)
                if proxy and calls > 0:
                    rows.append({"proxy": proxy, "app": app, "country": country, "call_count": calls})
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Anomaly Explorer
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def get_anomaly_trend(
    settings: Settings,
    hours: int = 24,
    measurement: str = "traffic_anomaly",
    proxy: str | None = None,
) -> pd.DataFrame:
    proxy_filter = f'|> filter(fn: (r) => r.apiproxy == "{proxy}")' if proxy else ""
    flux = f'''
    from(bucket: "{settings.anomaly_bucket}")
      |> range(start: -{hours}h)
      |> filter(fn: (r) => r._measurement == "{measurement}")
      |> filter(fn: (r) => r._field == "z_score")
      {proxy_filter}
    '''
    try:
        with _client(settings) as client:
            result = client.query_api().query_data_frame(flux)
    except Exception:
        return pd.DataFrame()

    if result is None:
        return pd.DataFrame()
    if isinstance(result, list):
        if not result:
            return pd.DataFrame()
        result = pd.concat(result, ignore_index=True)
    if result.empty:
        return pd.DataFrame()

    return pd.DataFrame({
        "time":      pd.to_datetime(result["_time"]),
        "proxy":     result["apiproxy"] if "apiproxy" in result.columns else "",
        "z_score":   result["_value"].astype(float),
        "is_anomaly": (result["is_anomaly"] == "true") if "is_anomaly" in result.columns else False,
        "sustained":  (result["sustained"] == "true") if "sustained" in result.columns else False,
    })


@st.cache_data(ttl=60, show_spinner=False)
def get_error_rate_predictions(settings: Settings) -> pd.DataFrame:
    """AR(1) predicted error rates from the MOST RECENT detection run only.

    Correctness rules applied here:
    1. Only predictions from the most recent detection run — using `last()` across
       25 hours pulled in stale records from earlier runs (a proxy anomalous at
       01:00 but recovered by 11:00 would return the 01:00 prediction, showing
       plot_times deep in the past).
    2. Only predictions whose plot_time (detection_time + hours_ahead) is still
       in the future — past plot_times are meaningless as forward projections.

    Returns columns: proxy, error_class, detection_time, hours_ahead,
                     predicted_rate, plot_time, generated_at (detection_time str).
    Empty DataFrame when no future predictions exist (e.g. analysis hasn't run
    recently enough for any hours_ahead window to remain in the future).
    """
    from datetime import datetime, timezone as tz

    now = datetime.now(tz.utc)

    # Step 1: find the single most recent detection timestamp in the bucket.
    # Limit the window to 90 minutes so we only see 1-2 runs, then take the latest.
    latest_detection = None
    try:
        for table in _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -90m)
          |> filter(fn: (r) => r._measurement == "predicted_anomaly"
                            and r.measurement == "error_rate")
          |> filter(fn: (r) => r._field == "predicted_error_rate")
          |> group() |> last()
        '''):
            for rec in table.records:
                latest_detection = rec.get_time()
    except Exception:
        pass

    if latest_detection is None:
        return pd.DataFrame()   # no recent predictions at all

    # Step 2: pull ALL predictions written at that exact detection timestamp.
    # Use a ±90s window around it to account for sub-minute write spread.
    from datetime import timedelta
    t_start = (latest_detection - timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    t_stop  = (latest_detection + timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = []
    try:
        for table in _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: {t_start}, stop: {t_stop})
          |> filter(fn: (r) => r._measurement == "predicted_anomaly"
                            and r.measurement == "error_rate")
          |> filter(fn: (r) => r._field == "predicted_error_rate")
        '''):
            for rec in table.records:
                proxy = rec.values.get("apiproxy", "")
                ec    = rec.values.get("error_class", "")
                rate  = rec.get_value()
                h     = int(rec.values.get("hours_ahead", 1))
                if proxy and ec and rate is not None:
                    rows.append({
                        "proxy":          proxy,
                        "error_class":    ec,
                        "detection_time": rec.get_time(),
                        "hours_ahead":    h,
                        "predicted_rate": float(rate),
                    })
    except Exception:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["plot_time"] = pd.to_datetime(df["detection_time"]) + pd.to_timedelta(df["hours_ahead"], unit="h")

    # Step 3: only keep predictions that are still in the future
    df["plot_time_utc"] = df["plot_time"].apply(
        lambda t: t.to_pydatetime().replace(tzinfo=tz.utc)
    )
    df = df[df["plot_time_utc"] > now].drop(columns=["plot_time_utc"])

    if df.empty:
        return pd.DataFrame()

    # Carry the detection timestamp as a display string for chart caption
    df["generated_at"] = latest_detection.strftime("%H:%M UTC")
    return df.reset_index(drop=True)


@st.cache_data(ttl=1800, show_spinner=False)
def get_sla_trajectory(settings: Settings, days: int = 30) -> pd.DataFrame:
    """Daily availability % per OpCo over the last `days` days."""
    flux = f'''
    from(bucket: "{settings.source_bucket}")
      |> range(start: -{days}d)
      |> filter(fn: (r) => r._field == "Sum of traffic")
      |> filter(fn: (r) => r.xcountrycode != "" and r.xcountrycode != "(not set)")
      |> group(columns: ["xcountrycode", "response_status_code"])
      |> aggregateWindow(every: 1d, fn: sum, createEmpty: false)
    '''
    rows = []
    try:
        with _client(settings) as client:
            result = client.query_api().query_data_frame(flux)
        if result is None: return pd.DataFrame()
        if isinstance(result, list):
            if not result: return pd.DataFrame()
            result = pd.concat(result, ignore_index=True)
        if result.empty: return pd.DataFrame()

        result["is_error"] = result["response_status_code"].astype(str).str.startswith(("4","5"))
        for (country, date), grp in result.groupby(["xcountrycode", "_time"]):
            total  = float(grp["_value"].sum())
            errors = float(grp.loc[grp["is_error"], "_value"].sum())
            if total > 0:
                rows.append({
                    "country":          country,
                    "date":             pd.Timestamp(date).date(),
                    "availability_pct": (1 - errors / total) * 100,
                    "error_rate_pct":   errors / total * 100,
                    "total_calls":      int(total),
                })
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def get_chronic_proxies(settings: Settings, days: int = 30, top_n: int = 20) -> pd.DataFrame:
    """Proxies ranked by total anomalous hours over the last `days` days."""
    flux = f'''
    from(bucket: "{settings.anomaly_bucket}")
      |> range(start: -{days}d)
      |> filter(fn: (r) => r._measurement == "traffic_anomaly"
                        or r._measurement == "error_rate_anomaly")
      |> filter(fn: (r) => r.is_anomaly == "true")
      |> filter(fn: (r) => r._field == "z_score")
      |> group(columns: ["apiproxy"])
      |> count()
      |> group()
      |> sort(columns: ["_value"], desc: true)
      |> limit(n: {top_n})
    '''
    rows = []
    try:
        for table in _query_raw(settings, flux):
            for rec in table.records:
                proxy = rec.values.get("apiproxy", "")
                if proxy:
                    rows.append({"proxy": proxy, "incident_hours": int(rec.get_value() or 0)})
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def get_partner_experience(settings: Settings, days: int = 30, top_n: int = 25) -> pd.DataFrame:
    """Error rate experienced by each developer app over the last `days` days."""
    flux = f'''
    from(bucket: "{settings.source_bucket}")
      |> range(start: -{days}d)
      |> filter(fn: (r) => r._field == "Sum of traffic")
      |> filter(fn: (r) => r.developer_app != "" and r.developer_app != "(not set)")
      |> group(columns: ["developer_app", "response_status_code"])
      |> sum()
    '''
    rows = []
    try:
        with _client(settings) as client:
            result = client.query_api().query_data_frame(flux)
        if result is None: return pd.DataFrame()
        if isinstance(result, list):
            if not result: return pd.DataFrame()
            result = pd.concat(result, ignore_index=True)
        if result.empty: return pd.DataFrame()

        result["is_error"] = result["response_status_code"].astype(str).str.startswith(("4","5"))
        for app, grp in result.groupby("developer_app"):
            total  = float(grp["_value"].sum())
            errors = float(grp.loc[grp["is_error"], "_value"].sum())
            if total >= 100:   # ignore micro-traffic apps
                rows.append({
                    "app":           app,
                    "total_calls":   int(total),
                    "error_calls":   int(errors),
                    "error_rate_pct": errors / total * 100,
                })
    except Exception:
        return pd.DataFrame()
    if not rows: return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("total_calls", ascending=False).head(top_n)
    return df.reset_index(drop=True)


@st.cache_data(ttl=1800, show_spinner=False)
def get_traffic_trend(settings: Settings, days: int = 30) -> pd.DataFrame:
    """Daily total API calls per OpCo over the last `days` days."""
    flux = f'''
    from(bucket: "{settings.source_bucket}")
      |> range(start: -{days}d)
      |> filter(fn: (r) => r._field == "Sum of traffic")
      |> filter(fn: (r) => r.xcountrycode != "" and r.xcountrycode != "(not set)")
      |> group(columns: ["xcountrycode"])
      |> aggregateWindow(every: 1d, fn: sum, createEmpty: false)
    '''
    rows = []
    try:
        with _client(settings) as client:
            result = client.query_api().query_data_frame(flux)
        if result is None: return pd.DataFrame()
        if isinstance(result, list):
            if not result: return pd.DataFrame()
            result = pd.concat(result, ignore_index=True)
        if result.empty: return pd.DataFrame()
        for _, row in result.iterrows():
            rows.append({
                "country":     row["xcountrycode"],
                "date":        pd.Timestamp(row["_time"]).date(),
                "total_calls": float(row["_value"]),
            })
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def get_availability_scorecard(settings: Settings, days: int = 30) -> pd.DataFrame:
    """Per-OpCo API availability over the last `days` days.

    Queries the source bucket directly (Apigee Reports) so data goes back as far
    as the fetch pipeline has collected, regardless of the Anomalies backfill.

    Returns columns: country, name, availability_pct, error_rate_pct,
                     total_calls, error_calls, sla_met, prev_availability_pct.
    prev_availability_pct is NaN when there is insufficient history for comparison.
    """
    _COUNTRY_NAMES = {
        "GHA": "Ghana",        "NGA": "Nigeria",       "ZAF": "South Africa",
        "UGA": "Uganda",       "CMR": "Cameroon",       "ZMB": "Zambia",
        "CIV": "Côte d'Ivoire","BEN": "Benin",          "LBR": "Liberia",
        "RWA": "Rwanda",       "SWZ": "Eswatini",       "GIN": "Guinea",
        "SDN": "Sudan",        "MOZ": "Mozambique",     "COD": "DR Congo",
    }

    def _compute(flux_range_start: str) -> pd.DataFrame:
        flux = f'''
        from(bucket: "{settings.source_bucket}")
          |> range(start: {flux_range_start})
          |> filter(fn: (r) => r._field == "Sum of traffic")
          |> filter(fn: (r) => r.xcountrycode != "" and r.xcountrycode != "(not set)")
          |> group(columns: ["xcountrycode", "response_status_code"])
          |> sum()
        '''
        rows = []
        try:
            with _client(settings) as client:
                result = client.query_api().query_data_frame(flux)
            if result is None:
                return pd.DataFrame()
            if isinstance(result, list):
                if not result:
                    return pd.DataFrame()
                result = pd.concat(result, ignore_index=True)
            if result.empty:
                return pd.DataFrame()
            result["is_error"] = result["response_status_code"].astype(str).str.startswith(("4", "5"))
            for country, grp in result.groupby("xcountrycode"):
                total  = float(grp["_value"].sum())
                errors = float(grp.loc[grp["is_error"], "_value"].sum())
                if total == 0:
                    continue
                rows.append({
                    "country":      country,
                    "total_calls":  int(total),
                    "error_calls":  int(errors),
                    "error_rate":   errors / total,
                    "availability": (1 - errors / total) * 100,
                })
        except Exception:
            pass
        return pd.DataFrame(rows) if rows else pd.DataFrame()

    current  = _compute(f"-{days}d")
    previous = _compute(f"-{days * 2}d")

    if current.empty:
        return pd.DataFrame()

    if not previous.empty:
        prev_map = previous.set_index("country")["availability"].to_dict()
        current["prev_availability"] = current["country"].map(prev_map)
        current["trend_pp"] = current["availability"] - current["prev_availability"]
    else:
        current["prev_availability"] = float("nan")
        current["trend_pp"]          = float("nan")

    current["name"]          = current["country"].map(_COUNTRY_NAMES).fillna(current["country"])
    current["error_rate_pct"] = current["error_rate"] * 100
    current["sla_met"]        = current["availability"] >= 99.5
    return current.sort_values("availability").reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def get_time_to_failure(settings: Settings) -> pd.DataFrame:
    """Proxies predicted to breach the anomaly threshold, with real time-to-failure.

    Key correctness points:
    - Only positive forecast_z (error rate rising above baseline). Negative z means
      the rate is BELOW the baseline — not a failure risk.
    - hours_until_breach is computed as (detection_time + hours_ahead) - now,
      not just hours_ahead. The model writes points at detection time; the
      actual failure window is hours_ahead hours AFTER that timestamp.
    - Only includes predictions still in the future (hours_remaining > 0).
    - Takes the most recent detection run per proxy (last() per proxy+class+step).
    - Filters out numerically degenerate forecasts (|z| > 100 = AR(1) overflow).

    Returns columns: proxy, error_class, hours_remaining (float), failure_at (datetime),
                     forecast_z, predicted_rate_pct, confidence_pct, is_currently_anomalous
    """
    from datetime import datetime, timedelta, timezone as tz

    Z_THRESHOLD = 3.0
    now = datetime.now(tz.utc)

    rows = []
    try:
        for table in _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -4h)
          |> filter(fn: (r) => r._measurement == "predicted_anomaly"
                            and r.measurement == "error_rate")
          |> filter(fn: (r) => r._field == "forecast_z_score"
                            or r._field == "predicted_error_rate")
          |> group(columns: ["apiproxy", "error_class", "hours_ahead", "_field"])
          |> last()
          |> pivot(rowKey:["_time","apiproxy","error_class","hours_ahead"],
                   columnKey:["_field"], valueColumn:"_value")
        '''):
            for rec in table.records:
                proxy       = rec.values.get("apiproxy", "")
                ec          = rec.values.get("error_class", "")
                h           = int(rec.values.get("hours_ahead", 1))
                fz          = float(rec.values.get("forecast_z_score") or 0)
                pr          = float(rec.values.get("predicted_error_rate") or 0)
                detect_time = rec.get_time()
                if proxy and detect_time:
                    rows.append({"proxy": proxy, "error_class": ec, "hours_ahead": h,
                                 "forecast_z": fz, "predicted_rate": pr,
                                 "detect_time": detect_time})
    except Exception:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Only positive z (error rate rising) — negative means rate below baseline = not a failure
    df = df[df["forecast_z"] >= Z_THRESHOLD]
    # Drop numerically degenerate (AR(1) overflow on sparse/degenerate series)
    df = df[df["forecast_z"] < 100]

    if df.empty:
        return pd.DataFrame()

    # Compute actual failure window and time remaining from NOW
    df["failure_at"] = df.apply(
        lambda r: r["detect_time"] + pd.Timedelta(hours=r["hours_ahead"]), axis=1
    )
    df["hours_remaining"] = df["failure_at"].apply(
        lambda t: (t.to_pydatetime().replace(tzinfo=tz.utc) - now).total_seconds() / 3600
    )

    # Only keep predictions still in the future
    df = df[df["hours_remaining"] > 0]
    if df.empty:
        return pd.DataFrame()

    # For each proxy+class take the earliest upcoming breach
    results = []
    for (proxy, ec), grp in df.groupby(["proxy", "error_class"]):
        grp = grp.sort_values("hours_remaining")
        best = grp.iloc[0]
        results.append({
            "proxy":              proxy,
            "error_class":        ec,
            "hours_remaining":    float(best["hours_remaining"]),
            "failure_at":         best["failure_at"],
            "forecast_z":         float(best["forecast_z"]),
            "predicted_rate_pct": float(best["predicted_rate"]) * 100,
            "confidence_pct":     min(100.0, (float(best["forecast_z"]) - Z_THRESHOLD) / Z_THRESHOLD * 100),
        })

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results).sort_values("hours_remaining")

    try:
        active = get_active_anomalies(settings)
        active_proxies = set(active["proxy"].unique()) if not active.empty else set()
    except Exception:
        active_proxies = set()

    out["is_currently_anomalous"] = out["proxy"].isin(active_proxies)
    return out.reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False)
def get_proxy_context(settings: Settings, proxy: str) -> dict:
    """Gather all context needed to explain a failure prediction for one proxy.

    Returns a dict with: z_score_trend (list), current_error_rate, blast_radius_apps,
    total_calls_at_risk, incident_hours_30d, forecast_rates (list by hours_ahead),
    error_class.
    """
    ctx: dict = {
        "proxy":               proxy,
        "z_score_trend":       [],
        "current_error_rate":  None,
        "error_class":         "unknown",
        "blast_apps":          [],
        "total_calls_at_risk": 0,
        "incident_hours_30d":  0,
        "forecast_rates":      {},   # hours_ahead → predicted_rate_pct
    }

    try:
        # 12h z-score trend
        for table in _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -12h)
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly"
                            and r.apiproxy == "{proxy}")
          |> filter(fn: (r) => r._field == "z_score")
          |> group(columns: ["error_class"])
          |> sort(columns: ["_time"])
        '''):
            for rec in table.records:
                ctx["z_score_trend"].append(float(rec.get_value() or 0))
                ctx["error_class"] = rec.values.get("error_class", "unknown")

        # Current error rate
        for table in _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -4h)
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly"
                            and r.apiproxy == "{proxy}")
          |> filter(fn: (r) => r._field == "error_rate")
          |> group(columns: ["error_class"])
          |> last()
        '''):
            for rec in table.records:
                ctx["current_error_rate"] = float(rec.get_value() or 0) * 100
                ctx["error_class"] = rec.values.get("error_class", "unknown")

        # Blast radius — who gets affected
        br_rows = []
        for table in _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -25h)
          |> filter(fn: (r) => r._measurement == "blast_radius"
                            and r.apiproxy == "{proxy}")
          |> filter(fn: (r) => r._field == "call_count")
          |> group(columns: ["developer_app", "xcountrycode"])
          |> sum()
          |> group() |> sort(columns: ["_value"], desc: true) |> limit(n: 8)
        '''):
            for rec in table.records:
                app   = rec.values.get("developer_app", "(not set)")
                cntry = rec.values.get("xcountrycode", "")
                calls = float(rec.get_value() or 0)
                if app not in ("(not set)", "") and calls > 0:
                    br_rows.append({"app": app, "country": cntry, "calls": int(calls)})
        ctx["blast_apps"]          = br_rows
        ctx["total_calls_at_risk"] = sum(r["calls"] for r in br_rows)

        # Incident hours in last 30 days
        for table in _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -30d)
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly"
                            and r.apiproxy == "{proxy}"
                            and r.is_anomaly == "true")
          |> filter(fn: (r) => r._field == "z_score")
          |> group() |> count()
        '''):
            for rec in table.records:
                ctx["incident_hours_30d"] = int(rec.get_value() or 0)

        # 4-hour predicted error rates
        for table in _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -4h)
          |> filter(fn: (r) => r._measurement == "predicted_anomaly"
                            and r.apiproxy == "{proxy}"
                            and r.measurement == "error_rate")
          |> filter(fn: (r) => r._field == "predicted_error_rate")
          |> group(columns: ["hours_ahead"])
          |> last()
        '''):
            for rec in table.records:
                h = int(rec.values.get("hours_ahead", 1))
                ctx["forecast_rates"][h] = float(rec.get_value() or 0) * 100

    except Exception:
        pass

    return ctx


@st.cache_data(ttl=3600, show_spinner=False)
def get_proxy_explanation(
    settings: Settings,
    proxy: str,
    hour_key: str,           # YYYY-MM-DD-HH — cache key
    error_class: str = "",
    hours_until_breach: int = 2,
    current_error_rate: float = 0.0,
    forecast_rate_pct: float = 0.0,
    total_calls_at_risk: int = 0,
    n_apps: int = 0,
    incident_hours_30d: int = 0,
) -> dict:
    """Generate a cause-and-effect explanation for a predicted API failure.

    Template mode: fills real data into plain-English sentences.
    Claude mode: deeper analysis using the Claude API (when INTELLIGENCE_ENABLED=true).
    Returns: {"text": str, "mode": "claude"|"template", "generated_at": str}
    """
    import os
    from datetime import datetime, timezone as tz
    from apigee_analysis.dashboard.labels import friendly_proxy

    generated_at = datetime.now(tz.utc).strftime("%H:%M UTC")
    name         = friendly_proxy(proxy)

    error_type = "app errors (4xx — requests being rejected)" if error_class == "client" \
                 else "service failures (5xx — backend errors)" if error_class == "server" \
                 else "error rate anomalies"

    def _template() -> dict:
        current_str  = f"{current_error_rate:.1f}%" if current_error_rate else "currently normal"
        forecast_str = f"{forecast_rate_pct:.1f}%" if forecast_rate_pct else "above the alert threshold"
        timing       = f"within {hours_until_breach} hour{'s' if hours_until_breach != 1 else ''}"
        impact_str   = (
            f"{total_calls_at_risk:,} API calls across {n_apps} partner "
            f"application{'s' if n_apps != 1 else ''} will be at risk"
        ) if total_calls_at_risk > 0 else f"{n_apps} partner applications may be affected"
        history_str  = (
            f"This API has experienced {incident_hours_30d} anomalous hours in the last 30 days, "
            f"suggesting a recurring issue."
        ) if incident_hours_30d > 5 else "This appears to be an emerging issue — no significant recent history."

        text = (
            f"**What is happening:** {name} is showing rising {error_type}. "
            f"The current error rate is {current_str}, and the predictive model forecasts "
            f"it will reach {forecast_str} — breaching the alert threshold — {timing}.\n\n"
            f"**Likely cause:** {'App-side request failures (4xx errors) typically indicate bad requests, '
             'expired authentication tokens, or a breaking change in the API contract. '
             'Check for recent client deployments or credential rotations.'
             if error_class == 'client' else
             'Backend service failures (5xx errors) typically indicate an infrastructure problem — '
             'a downstream service dependency, database timeout, or capacity issue. '
             'Check the backend service health and recent deployments.'}\n\n"
            f"**Who is affected:** If this API fails, {impact_str}. "
            f"These partners will be unable to complete requests to this API until the issue resolves.\n\n"
            f"**History:** {history_str}"
        )
        return {"text": text, "mode": "template", "generated_at": generated_at}

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    enabled = os.environ.get("INTELLIGENCE_ENABLED", "false").lower() == "true"

    if not (api_key and enabled):
        return _template()

    try:
        import anthropic as _anthropic
        from apigee_analysis.intelligence import CLAUDE_MODEL

        prompt = f"""You are an API reliability engineer. Explain this predicted failure in plain English for a technical audience. Use markdown formatting with bold headers.

API: {name}
Error type: {error_type}
Current error rate: {current_error_rate:.1f}%
Predicted error rate in {hours_until_breach}h: {forecast_rate_pct:.1f}%
Partner apps at risk: {n_apps} ({total_calls_at_risk:,} calls)
Historical anomalous hours (30d): {incident_hours_30d}

Write exactly 4 short paragraphs with bold headers:
1. **What is happening** — describe the current trend and prediction
2. **Likely cause** — based on error type ({error_class}), what is probably wrong
3. **Who is affected** — partners, call volumes, business impact
4. **Recommended action** — one or two concrete steps to investigate

Be specific. Use the actual numbers. Plain English — no jargon."""

        client  = _anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=CLAUDE_MODEL, max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        if text:
            return {"text": text, "mode": "claude", "generated_at": generated_at}
    except Exception:
        pass

    return _template()


@st.cache_data(ttl=3600, show_spinner=False)
def get_platform_briefing(
    settings: Settings,
    hour_key: str,          # "YYYY-MM-DD-HH" — auto-expires cache on the hour
    n_incidents: int   = 0,
    n_sustained: int   = 0,
    n_predicted: int   = 0,
    n_degraded: int    = 0,
    worst_country: str = "—",
    platform_avail: float = 100.0,
    n_apps_impacted: int  = 0,
) -> dict:
    """Return a platform briefing dict with keys: text, mode, generated_at.

    Template mode: fills real data into sentence templates — no API call.
    Claude mode:   short management-focused prose from the Claude API.
    Cached for 1 hour per hour_key. Call get_platform_briefing.clear()
    to force regeneration on demand.
    """
    import os
    from datetime import datetime, timezone as tz

    generated_at = datetime.now(tz.utc).strftime("%H:%M UTC")

    def _template() -> dict:
        if n_incidents == 0:
            state = "operating normally with no active incidents"
        elif n_incidents <= 5:
            state = "showing localised incidents across a small number of APIs"
        else:
            state = "under elevated stress with widespread API anomalies"

        sla_note = (
            f"below the 99.5% SLA target" if platform_avail < 99.5
            else "above the 99.5% SLA target"
        )
        sustained_note = (
            f", with {n_sustained} ongoing for multiple consecutive hours"
            if n_sustained else ""
        )
        prediction_note = (
            f" Early warning systems have flagged {n_predicted} APIs projected "
            f"to worsen over the next 4 hours."
            if n_predicted else " No further deterioration is currently projected."
        )
        degraded_note = (
            f" {n_degraded} Operating {'Country' if n_degraded == 1 else 'Countries'} "
            f"{'is' if n_degraded == 1 else 'are'} showing elevated error rates."
            if n_degraded else ""
        )
        text = (
            f"The MTN API platform is currently {state}. "
            f"{n_incidents} {'API is' if n_incidents == 1 else 'APIs are'} showing "
            f"anomalous behaviour{sustained_note}. "
            f"Platform-wide availability stands at {platform_avail:.1f}%, {sla_note}."
            f"{degraded_note}"
            f"{prediction_note}"
        )
        return {"text": text, "mode": "template", "generated_at": generated_at}

    # Use Claude API only when explicitly enabled
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    enabled = os.environ.get("INTELLIGENCE_ENABLED", "false").lower() == "true"

    if not (api_key and enabled):
        return _template()

    try:
        import anthropic as _anthropic
        from apigee_analysis.intelligence import CLAUDE_MODEL

        prompt = f"""You are briefing MTN senior leadership on API platform health.
Write exactly 3-4 sentences of executive prose. No bullets, no headers, no jargon.
Focus on business impact — how many APIs, which countries, what the trend is.

Current platform state:
- {n_incidents} APIs currently anomalous ({n_sustained} sustained for multiple hours)
- Most affected country: {worst_country}
- Platform availability: {platform_avail:.1f}% vs 99.5% SLA target
- {n_apps_impacted} partner applications impacted in the last 25 hours
- {n_predicted} APIs flagged by early-warning system as likely to worsen

Write the briefing now:"""

        client  = _anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        if text:
            return {"text": text, "mode": "claude", "generated_at": generated_at}
    except Exception:
        pass

    return _template()


@st.cache_data(ttl=300, show_spinner=False)
def get_proxy_list(settings: Settings) -> list[str]:
    flux = f'''
    import "influxdata/influxdb/schema"
    schema.tagValues(
        bucket: "{settings.anomaly_bucket}",
        tag: "apiproxy",
        predicate: (r) => r._measurement == "traffic_anomaly",
        start: -7d,
    )
    '''
    proxies = []
    try:
        for table in _query_raw(settings, flux):
            for rec in table.records:
                val = rec.get_value()
                if val:
                    proxies.append(str(val))
    except Exception:
        pass
    return sorted(proxies)


@st.cache_data(ttl=60, show_spinner=False)
def get_incident_priorities(settings: Settings) -> pd.DataFrame:
    """Active anomalous proxies ranked by business impact for incident response.

    Joins error_rate_anomaly (z_score + error_rate + duration) with blast_radius
    (affected apps and call volumes) to produce a prioritised incident list.

    Priority = total_calls_at_risk × error_rate × (1 + consecutive_hours / 10)

    Returns columns: proxy, error_class, z_score, error_rate, consecutive_hours,
                     sustained, total_calls, unique_apps, unique_countries,
                     priority, top_apps (list of top affected app names).
    """
    # Step 1: get currently-anomalous proxies using the same approach as get_active_anomalies
    # (group by proxy+ec, last() per group, filter is_anomaly=true — no pivot needed)
    z_rows = []
    for table in _query_raw(settings, f'''
    from(bucket: "{settings.anomaly_bucket}")
      |> range(start: -25h)
      |> filter(fn: (r) => r._measurement == "error_rate_anomaly")
      |> filter(fn: (r) => r._field == "z_score")
      |> group(columns: ["apiproxy", "error_class"])
      |> last()
      |> filter(fn: (r) => r.is_anomaly == "true")
    '''):
        for rec in table.records:
            proxy = rec.values.get("apiproxy", "")
            ec    = rec.values.get("error_class", "")
            if proxy and ec:
                z_rows.append({
                    "proxy":             proxy,
                    "error_class":       ec,
                    "z_score":           float(rec.get_value() or 0),
                    "consecutive_hours": int(float(rec.values.get("consecutive_hours") or 1)),
                    "sustained":         rec.values.get("sustained", "false") == "true",
                })

    if not z_rows:
        return pd.DataFrame()

    incidents = pd.DataFrame(z_rows).drop_duplicates(subset=["proxy", "error_class"])

    # Step 2: fetch error rates separately for those proxies
    anomalous_keys = set(incidents["proxy"].unique())
    er_rows = []
    for table in _query_raw(settings, f'''
    from(bucket: "{settings.anomaly_bucket}")
      |> range(start: -25h)
      |> filter(fn: (r) => r._measurement == "error_rate_anomaly")
      |> filter(fn: (r) => r._field == "error_rate")
      |> group(columns: ["apiproxy", "error_class"])
      |> last()
    '''):
        for rec in table.records:
            proxy = rec.values.get("apiproxy", "")
            ec    = rec.values.get("error_class", "")
            if proxy in anomalous_keys and ec:
                er_rows.append({
                    "proxy":      proxy,
                    "error_class": ec,
                    "error_rate": float(rec.get_value() or 0),
                })

    if er_rows:
        er_df = pd.DataFrame(er_rows)
        incidents = incidents.merge(er_df, on=["proxy", "error_class"], how="left")
    else:
        incidents["error_rate"] = 0.0

    incidents["error_rate"] = incidents["error_rate"].fillna(0.0)

    # Join with blast radius for business impact
    blast = get_blast_radius(settings, hours_back=25)
    if not blast.empty:
        br_agg = (
            blast[blast["proxy"].isin(set(incidents["proxy"]))]
            .groupby("proxy")
            .agg(
                total_calls=("call_count", "sum"),
                unique_apps=("app",         lambda x: x[x != "(not set)"].nunique()),
                unique_countries=("country", "nunique"),
                top_apps=("app", lambda x: x[x != "(not set)"].value_counts().head(3).index.tolist()),
            )
            .reset_index()
        )
        incidents = incidents.merge(br_agg, on="proxy", how="left")
    else:
        incidents["total_calls"]      = 0
        incidents["unique_apps"]      = 0
        incidents["unique_countries"] = 0
        incidents["top_apps"]         = [[] for _ in range(len(incidents))]

    incidents = incidents.fillna({"total_calls": 0, "unique_apps": 0, "unique_countries": 0})
    incidents["top_apps"] = incidents["top_apps"].apply(lambda x: x if isinstance(x, list) else [])

    # Priority score
    incidents["priority"] = (
        incidents["total_calls"] * incidents["error_rate"] * (1 + incidents["consecutive_hours"] / 10)
    ).fillna(0)

    # Fall back to z_score × calls when error_rate not available
    mask = incidents["priority"] == 0
    incidents.loc[mask, "priority"] = (
        incidents.loc[mask, "total_calls"] * incidents.loc[mask, "z_score"].abs()
    )

    return incidents.sort_values("priority", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False)
def get_co_failure_history(
    settings: Settings,
    proxy_a: str, ec_a: str,
    proxy_b: str, ec_b: str,
    days: int = 7,
) -> pd.DataFrame:
    """Hourly error rate + anomaly flag for two proxies over `days` days.

    Returns columns: hour, a_rate, a_anomalous, b_rate, b_anomalous.
    Used to plot the co-failure pattern that drives a cascade prediction.
    """
    rows: dict = {}   # hour -> {a_rate, a_anom, b_rate, b_anom}

    flux = f'''
    from(bucket: "{settings.anomaly_bucket}")
      |> range(start: -{days}d)
      |> filter(fn: (r) => r._measurement == "error_rate_anomaly")
      |> filter(fn: (r) => r._field == "error_rate")
      |> filter(fn: (r) =>
          (r.apiproxy == "{proxy_a}" and r.error_class == "{ec_a}") or
          (r.apiproxy == "{proxy_b}" and r.error_class == "{ec_b}"))
      |> group(columns: ["apiproxy", "error_class"])
      |> sort(columns: ["_time"])
    '''
    try:
        for table in _query_raw(settings, flux):
            for rec in table.records:
                proxy = rec.values.get("apiproxy", "")
                ec    = rec.values.get("error_class", "")
                ts    = pd.Timestamp(rec.get_time()).floor("h")
                rate  = float(rec.get_value() or 0)
                anom  = rec.values.get("is_anomaly", "false") == "true"

                rows.setdefault(ts, {"a_rate": 0.0, "a_anomalous": False,
                                     "b_rate": 0.0, "b_anomalous": False})
                if proxy == proxy_a and ec == ec_a:
                    rows[ts]["a_rate"]      = rate
                    rows[ts]["a_anomalous"] = anom
                elif proxy == proxy_b and ec == ec_b:
                    rows[ts]["b_rate"]      = rate
                    rows[ts]["b_anomalous"] = anom
    except Exception:
        return pd.DataFrame()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([{"hour": h, **v} for h, v in sorted(rows.items())])
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Co-failure correlation model
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def get_rate_history(settings: Settings, days: int = 14) -> pd.DataFrame:
    """Hourly error rates for all proxies — the raw behavioral time series.

    Used to build the cross-correlation model. Returns actual error RATES,
    not binary anomaly flags, so the correlation captures rises and falls
    rather than coincident threshold breaches.

    Returns columns: proxy, error_class, hour, rate.
    """
    rows = []
    try:
        for table in _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -{days}d)
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly")
          |> filter(fn: (r) => r._field == "error_rate")
          |> group(columns: ["apiproxy", "error_class"])
          |> aggregateWindow(every: 1h, fn: last, createEmpty: false)
        '''):
            for rec in table.records:
                proxy = rec.values.get("apiproxy", "")
                ec    = rec.values.get("error_class", "")
                ts    = rec.get_time()
                rate  = rec.get_value()
                if proxy and ec and rate is not None:
                    rows.append({
                        "proxy":       proxy,
                        "error_class": ec,
                        "hour":        pd.Timestamp(ts).floor("h"),
                        "rate":        float(rate),
                    })
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _get_corr_pairs(settings: Settings) -> pd.DataFrame:
    """Shared cached computation: rate history → correlation pairs.

    The heavy work (InfluxDB query + O(N²) cross-correlation) runs ONCE and is
    cached for 1 hour. Both get_cascade_predictions() and get_correlation_matrix()
    call this function so they share the same cached result rather than each
    rerunning the expensive computation.

    First call: ~10-15 seconds. Subsequent calls within the hour: instant.
    """
    from apigee_analysis.correlation import build_rate_matrix, compute_crosscorr_pairs

    rate_df = get_rate_history(settings, days=7)   # 7 days is sufficient for correlation
    if rate_df.empty:
        return pd.DataFrame()
    matrix = build_rate_matrix(rate_df)
    return compute_crosscorr_pairs(matrix)


@st.cache_data(ttl=300, show_spinner=False)
def get_cascade_predictions(settings: Settings) -> pd.DataFrame:
    """Predict at-risk APIs using behavioral cross-correlation on error rate changes.

    Reuses _get_corr_pairs() (cached 1h) to avoid recomputing the O(N²)
    correlation on every call.

    Returns columns: proxy, error_class, score, correlation, driver_proxy,
                     driver_ec, driver_lag, driver_change_pct, n_drivers,
                     history_days.
    """
    from apigee_analysis.correlation import (
        build_rate_matrix,
        predict_cascade,
    )

    corr_pairs = _get_corr_pairs(settings)          # shared cache
    active_df  = get_active_anomalies(settings)

    if corr_pairs.empty:
        return pd.DataFrame()

    # Need the rate matrix only for current rate-of-change calculation
    rate_df = get_rate_history(settings, days=7)    # also cached
    if rate_df.empty:
        return pd.DataFrame()

    history_days = (
        (pd.Timestamp.now(tz="UTC") - rate_df["hour"].min().tz_localize("UTC")
         if rate_df["hour"].min().tzinfo is None
         else pd.Timestamp.now(tz="UTC") - rate_df["hour"].min())
        .days
    )

    matrix = build_rate_matrix(rate_df)

    if corr_pairs.empty:
        return pd.DataFrame()

    # Current anomalous keys
    current_anomalous: set[str] = set()
    if not active_df.empty:
        for _, row in active_df.iterrows():
            current_anomalous.add(f"{row['proxy']}|{row['error_class']}")

    # Recent rate-of-change for each currently-anomalous API (last 2 hours)
    current_changes: dict[str, float] = {}
    recent_hours = matrix.index[-3:] if len(matrix) >= 3 else matrix.index
    if len(recent_hours) >= 2:
        for key in current_anomalous:
            if key in matrix.columns:
                series     = matrix.loc[recent_hours, key].values.astype(float)
                rate_change = float(series[-1] - series[0])   # change over last 2h
                current_changes[key] = rate_change

    all_keys = set(matrix.columns.tolist())

    predictions = predict_cascade(corr_pairs, current_changes, current_anomalous, all_keys)
    if predictions.empty:
        return pd.DataFrame()

    def split_key(key: str) -> tuple[str, str]:
        parts = key.rsplit("|", 1)
        return (parts[0], parts[1]) if len(parts) == 2 else (key, "")

    predictions[["proxy", "error_class"]]       = predictions["key_b"].apply(
        lambda k: pd.Series(split_key(k))
    )
    predictions[["driver_proxy", "driver_ec"]]  = predictions["best_driver_key"].apply(
        lambda k: pd.Series(split_key(k))
    )
    predictions["history_days"]        = history_days
    predictions["driver_change_pct"]   = predictions["best_driver_change"] * 100
    predictions["correlation"]         = predictions["best_driver_corr"]
    predictions["driver_lag"]          = predictions["best_driver_lag"]

    return predictions[[
        "proxy", "error_class", "score", "correlation",
        "driver_proxy", "driver_ec", "driver_lag", "driver_change_pct",
        "n_drivers", "history_days",
    ]].reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# API Intelligence — Sankey + Heatmap data
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def get_cascade_sankey_data(settings: Settings) -> dict:
    """Build node + link lists for a Sankey cascade diagram.

    Three node columns:
      Left  (red):   currently-failing APIs
      Centre(amber): correlated at-risk APIs (from cascade predictions)
      Right (blue):  affected partner applications (from blast radius)

    Link values:
      Failing → At-risk: correlation × blast_calls (importance of the link)
      At-risk  → Partner: partner app call volume
    """
    failing_df = get_active_anomalies(settings)
    risk_df    = get_cascade_predictions(settings)
    blast_df   = get_blast_radius(settings, hours_back=25)

    # ── Failing nodes ─────────────────────────────────────────────────────────
    failing_keys: list[str] = []
    if not failing_df.empty:
        uni = failing_df[failing_df["type"] != "Multivariate"]
        failing_keys = [
            f"{r['proxy']}|{r['error_class']}"
            for _, r in uni.drop_duplicates("proxy").head(12).iterrows()
        ]

    # ── At-risk nodes (cascade predictions, top 12) ───────────────────────────
    risk_keys: list[str] = []
    risk_corr: dict[str, float] = {}
    if not risk_df.empty:
        top_risk = risk_df[
            ~risk_df.apply(lambda r: f"{r['proxy']}|{r['error_class']}", axis=1)
                     .isin(set(failing_keys))
        ].head(12)
        for _, r in top_risk.iterrows():
            k = f"{r['proxy']}|{r['error_class']}"
            risk_keys.append(k)
            risk_corr[k] = float(r["correlation"])

    # ── Partner nodes (top 10 apps from blast radius of failing proxies) ───────
    partner_calls: dict[str, int] = {}
    if not blast_df.empty:
        failing_proxies = {k.split("|")[0] for k in failing_keys}
        filtered = blast_df[
            blast_df["proxy"].isin(failing_proxies) &
            ~blast_df["app"].isin(["(not set)", ""])
        ]
        for app, grp in filtered.groupby("app"):
            partner_calls[app] = int(grp["call_count"].sum())
        # Keep top 10
        partner_calls = dict(
            sorted(partner_calls.items(), key=lambda x: x[1], reverse=True)[:10]
        )

    # Build unified node list with offset indices
    all_nodes: list[dict] = []
    for k in failing_keys:
        all_nodes.append({"key": k, "col": "failing"})
    for k in risk_keys:
        all_nodes.append({"key": k, "col": "atrisk"})
    for app in partner_calls:
        all_nodes.append({"key": app, "col": "partner"})

    node_idx = {n["key"]: i for i, n in enumerate(all_nodes)}

    # ── Links ─────────────────────────────────────────────────────────────────
    links: list[dict] = []

    # Failing → At-risk (via cascade predictions)
    if not risk_df.empty and failing_keys and risk_keys:
        for _, r in risk_df.iterrows():
            rk = f"{r['proxy']}|{r['error_class']}"
            dk = f"{r['driver_proxy']}|{r['driver_ec']}"
            if rk not in node_idx or dk not in node_idx:
                continue
            # Scale value by correlation and driver's blast radius
            driver_calls = int(blast_df[blast_df["proxy"] == r["driver_proxy"]]["call_count"].sum()) if not blast_df.empty else 1000
            value = max(100, int(float(r["correlation"]) * max(driver_calls, 1000)))
            links.append({
                "source": node_idx[dk],
                "target": node_idx[rk],
                "value":  value,
                "color":  "rgba(239,68,68,0.35)",
            })

    # At-risk → Partner apps (via blast radius of at-risk proxies)
    if not blast_df.empty and risk_keys and partner_calls:
        risk_proxies = {k.split("|")[0] for k in risk_keys}
        for app, total in partner_calls.items():
            if app not in node_idx:
                continue
            # Distribute app calls across at-risk APIs proportionally
            for rk in risk_keys:
                rp = rk.split("|")[0]
                sub = blast_df[(blast_df["proxy"] == rp) & (blast_df["app"] == app)]
                if sub.empty:
                    continue
                v = int(sub["call_count"].sum())
                if v > 0:
                    links.append({
                        "source": node_idx[rk],
                        "target": node_idx[app],
                        "value":  v,
                        "color":  "rgba(245,158,11,0.35)",
                    })

    return {
        "nodes":    all_nodes,
        "node_idx": node_idx,
        "links":    links,
        "n_failing": len(failing_keys),
        "n_risk":    len(risk_keys),
        "n_partner": len(partner_calls),
    }


@st.cache_data(ttl=3600, show_spinner=False)
def get_correlation_matrix(settings: Settings, top_n: int = 30) -> tuple:
    """Build a square correlation matrix for the heatmap.

    Reuses _get_corr_pairs() (cached 1h) — no redundant recomputation.

    Returns (matrix_df, key_list, anomalous_keys) where:
      matrix_df:     square DataFrame, index=columns=key strings, values=best_corr
      key_list:      ordered list of keys (rows/columns)
      anomalous_keys: set of keys currently anomalous (for highlighting)
    """
    corr_pairs = _get_corr_pairs(settings)          # shared cache — instant if warm
    if corr_pairs.empty:
        return pd.DataFrame(), [], set()

    # Select top_n most-connected proxies
    connection_counts = (
        pd.concat([corr_pairs["key_a"], corr_pairs["key_b"]])
        .value_counts()
        .head(top_n)
    )
    top_keys = connection_counts.index.tolist()

    # Filter pairs to only top_n proxies
    filtered = corr_pairs[
        corr_pairs["key_a"].isin(top_keys) & corr_pairs["key_b"].isin(top_keys)
    ]

    # Pivot to square matrix
    mat = filtered.pivot(index="key_a", columns="key_b", values="best_corr").fillna(0)
    # Ensure all top_keys appear in both axes
    mat = mat.reindex(index=top_keys, columns=top_keys, fill_value=0)

    # Currently anomalous keys
    active_df = get_active_anomalies(settings)
    anomalous: set[str] = set()
    if not active_df.empty:
        for _, r in active_df.iterrows():
            anomalous.add(f"{r['proxy']}|{r['error_class']}")

    return mat, top_keys, anomalous
