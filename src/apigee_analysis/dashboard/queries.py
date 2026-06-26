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
        # Traffic anomalies
        flux = f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -25h)
          |> filter(fn: (r) => r._measurement == "traffic_anomaly" and r.is_anomaly == "true")
          |> pivot(rowKey:["_time","apiproxy"], columnKey:["_field"], valueColumn:"_value")
          |> sort(columns:["_time"], desc: true)
        '''
        for table in _query_raw(settings, flux):
            for rec in table.records:
                rows.append({
                    "time":              rec.get_time(),
                    "proxy":             rec.values.get("apiproxy", ""),
                    "type":              "Traffic",
                    "error_class":       "",
                    "z_score":           float(rec.values.get("z_score") or 0),
                    "error_rate":        None,
                    "traffic":           float(rec.values.get("traffic") or 0),
                    "sustained":         rec.values.get("sustained", "false") == "true",
                    "consecutive_hours": int(float(rec.values.get("consecutive_hours") or 1)),
                })

        # Error rate anomalies
        flux = f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -25h)
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly" and r.is_anomaly == "true")
          |> pivot(rowKey:["_time","apiproxy","error_class"], columnKey:["_field"], valueColumn:"_value")
          |> sort(columns:["_time"], desc: true)
        '''
        for table in _query_raw(settings, flux):
            for rec in table.records:
                rows.append({
                    "time":              rec.get_time(),
                    "proxy":             rec.values.get("apiproxy", ""),
                    "type":              "Error Rate",
                    "error_class":       rec.values.get("error_class", ""),
                    "z_score":           float(rec.values.get("z_score") or 0),
                    "error_rate":        float(rec.values.get("error_rate") or 0),
                    "traffic":           None,
                    "sustained":         rec.values.get("sustained", "false") == "true",
                    "consecutive_hours": int(float(rec.values.get("consecutive_hours") or 1)),
                })
        # Multivariate anomalies
        flux = f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -25h)
          |> filter(fn: (r) => r._measurement == "multivariate_anomaly" and r.is_anomaly == "true")
          |> filter(fn: (r) => r._field == "anomaly_score")
          |> sort(columns:["_time"], desc: true)
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
    # Deduplicate to most recent per proxy+type+error_class
    df = df.drop_duplicates(subset=["proxy", "type", "error_class"])
    return df.reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def get_error_rate_trend(settings: Settings, top_n: int = 5) -> pd.DataFrame:
    """Last 25h of hourly error rates for the top N most anomalous proxies.

    Step 1: find top_n proxies by peak |z_score| in the last 4h.
    Step 2: fetch 25h of error_rate history for those proxies.
    Returns columns: time, proxy, error_class, error_rate, z_score, is_anomaly.
    """
    try:
        # Top proxies by worst z_score in the same 25h window used for history.
        # group() after max() collapses all per-proxy groups into one table so
        # sort() and limit() operate globally, not per-group.
        top_tables = _query_raw(settings, f'''
        from(bucket: "{settings.anomaly_bucket}")
          |> range(start: -25h)
          |> filter(fn: (r) => r._measurement == "error_rate_anomaly" and r.is_anomaly == "true")
          |> filter(fn: (r) => r._field == "z_score")
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
