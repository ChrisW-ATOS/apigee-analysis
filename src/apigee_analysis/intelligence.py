"""Incident Intelligence — natural language summaries and root cause hypotheses.

Queries the Anomalies bucket after each detection run, structures the active
incident context, and calls the Claude API to generate a plain-English brief.
Writes results back to InfluxDB as an 'incident_summary' measurement.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from .config import Settings
from .detect import _client

log = logging.getLogger(__name__)

# Load from the analysis project's .env regardless of working directory
# __file__ = src/apigee_analysis/intelligence.py → go up 3 levels to project root
_env_file = Path(__file__).parent.parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=True)

CLAUDE_MODEL = "claude-opus-4-8"


def gather_incident_context(settings: Settings, at: datetime) -> dict | None:
    """Query the Anomalies bucket and build a structured incident context dict.

    Returns None if no anomalies exist at the given hour.
    """
    start = (at - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stop  = (at + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    context: dict = {
        "hour": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "anomalies": [],
        "blast_radius": [],
        "country_health": [],
    }

    with _client(settings) as client:
        api = client.query_api()

        # Active anomalies
        tables = api.query(f'''
            from(bucket: "{settings.anomaly_bucket}")
              |> range(start: {start}, stop: {stop})
              |> filter(fn: (r) => r.is_anomaly == "true" and
                        (r._measurement == "error_rate_anomaly" or
                         r._measurement == "traffic_anomaly"))
              |> pivot(rowKey:["_time","apiproxy"], columnKey:["_field"], valueColumn:"_value")
        ''', org=settings.influx_org)

        for table in tables:
            for rec in table.records:
                entry = {
                    "proxy":       rec.values.get("apiproxy", ""),
                    "type":        rec.get_measurement(),
                    "error_class": rec.values.get("error_class", ""),
                    "z_score":     rec.values.get("z_score"),
                    "error_rate":  rec.values.get("error_rate"),
                    "traffic":     rec.values.get("traffic"),
                    "consecutive": rec.values.get("consecutive_hours", 1),
                    "sustained":   rec.values.get("sustained", "false"),
                }
                context["anomalies"].append(entry)

        # Blast radius
        br_tables = api.query(f'''
            from(bucket: "{settings.anomaly_bucket}")
              |> range(start: {start}, stop: {stop})
              |> filter(fn: (r) => r._measurement == "blast_radius")
              |> sort(columns:["_value"], desc:true)
              |> limit(n:30)
        ''', org=settings.influx_org)

        for table in br_tables:
            for rec in table.records:
                context["blast_radius"].append({
                    "proxy":   rec.values.get("apiproxy", ""),
                    "app":     rec.values.get("developer_app", ""),
                    "country": rec.values.get("xcountrycode", ""),
                    "calls":   rec.get_value(),
                })

        # Country health anomalies
        ch_tables = api.query(f'''
            from(bucket: "{settings.anomaly_bucket}")
              |> range(start: {start}, stop: {stop})
              |> filter(fn: (r) => r._measurement == "country_health" and r.is_anomaly == "true")
              |> pivot(rowKey:["_time","xcountrycode"], columnKey:["_field"], valueColumn:"_value")
        ''', org=settings.influx_org)

        for table in ch_tables:
            for rec in table.records:
                context["country_health"].append({
                    "country":    rec.values.get("xcountrycode", ""),
                    "error_rate": rec.values.get("error_rate"),
                    "z_score":    rec.values.get("z_score"),
                })

    if not context["anomalies"]:
        return None

    return context


def _build_prompt(context: dict) -> str:
    anomaly_count = len(context["anomalies"])
    sustained = [a for a in context["anomalies"] if str(a.get("sustained", "")).lower() == "true"]
    server_errors = [a for a in context["anomalies"] if a.get("error_class") == "server"]
    client_errors = [a for a in context["anomalies"] if a.get("error_class") == "client"]

    # Top blast radius entries
    top_blast = sorted(context["blast_radius"], key=lambda x: x.get("calls", 0), reverse=True)[:10]

    return f"""You are an API operations analyst. Analyse this incident data and respond with JSON only.

INCIDENT DATA ({context['hour']}):

ANOMALIES ({anomaly_count} total, {len(sustained)} sustained):
{json.dumps(context['anomalies'], indent=2)}

TOP AFFECTED APPLICATIONS (blast radius):
{json.dumps(top_blast, indent=2)}

COUNTRY HEALTH ANOMALIES:
{json.dumps(context['country_health'], indent=2)}

Respond with this exact JSON structure:
{{
  "summary": "2-3 sentence plain English incident summary for an on-call engineer",
  "root_cause": "Most likely root cause hypothesis in 1-2 sentences",
  "severity": "low|medium|high",
  "recommended_action": "Single most important immediate action"
}}

Rules:
- summary: factual, specific, mention proxy names, error rates, and affected apps
- root_cause: distinguish client errors (4xx, likely bad requests/auth) from server errors (5xx, likely backend failure)
- severity: high if sustained or >20% error rate or >5 apps affected; medium if new anomaly or 2-5 apps; low otherwise
- recommended_action: concrete, not generic
- JSON only, no other text"""


def generate_incident_brief(context: dict) -> dict | None:
    """Call Claude API with the incident context and return a structured brief."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set — skipping incident brief")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": _build_prompt(context)}],
        )
        raw = message.content[0].text.strip()
        log.debug("raw API response: %s", raw[:200])
        if not raw:
            log.error("Claude API returned empty response")
            return None
        # Strip markdown code fences if model wrapped the JSON
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        brief = json.loads(raw)
        log.info("incident brief generated | severity=%s", brief.get("severity", "?"))
        return brief
    except Exception as exc:
        log.error("failed to generate incident brief: %s | key_set=%s", exc, bool(api_key))
        return None


def write_incident_summary(settings: Settings, brief: dict, context: dict, at: datetime) -> None:
    """Write the incident brief to the incident_summary measurement."""
    p = (
        Point("incident_summary")
        .tag("severity", brief.get("severity", "unknown"))
        .field("summary",            brief.get("summary", ""))
        .field("root_cause",         brief.get("root_cause", ""))
        .field("recommended_action", brief.get("recommended_action", ""))
        .field("anomaly_count",      len(context.get("anomalies", [])))
        .field("affected_apps",      len({r["app"] for r in context.get("blast_radius", []) if r["app"] not in ("(not set)", "")}))
        .time(at, WritePrecision.S)
    )

    with _client(settings) as client:
        client.write_api(write_options=SYNCHRONOUS).write(
            bucket=settings.anomaly_bucket, record=p
        )
    log.info("incident summary written to '%s'", settings.anomaly_bucket)


def run_intelligence(settings: Settings, at: datetime) -> None:
    """Gather context, generate brief, and write summary if anomalies exist."""
    context = gather_incident_context(settings, at)
    if not context:
        log.info("no anomalies — skipping incident brief")
        return

    brief = generate_incident_brief(context)
    if not brief:
        return

    write_incident_summary(settings, brief, context, at)
    log.info("summary=%s | root_cause=%s", brief.get("summary", "")[:80], brief.get("root_cause", "")[:60])
