# Apigee Analysis — Enhancement Roadmap

## Current State

The system detects anomalies in real-time using statistical Z-score analysis across
four measurements: traffic volume, error rates (4xx/5xx), country health, and blast
radius. It runs hourly, maintains a 7-day rolling baseline, and distinguishes sustained
incidents from one-off spikes.

---

## Bundle A — Incident Intelligence

### What it solves

Today the system detects *that* something is wrong. An on-call engineer still needs to
manually interpret multiple Grafana panels, cross-reference the blast radius, form a
hypothesis, and write a summary before they can act or communicate. This takes time
— often the most critical minutes of an incident.

Bundle A removes that interpretation step entirely.

### Benefits

| Benefit | Detail |
|---|---|
| Faster time-to-action | Engineer receives a plain-English summary at the moment of detection — no Grafana required |
| Consistent incident documentation | Every incident auto-generates a structured brief, removing variability between engineers |
| Root cause hypothesis | System suggests the most likely cause category based on the pattern, reducing cognitive load |
| Scalable on-call | A single engineer can triage more incidents simultaneously |

### How it works

After each hourly detection run, if any anomalies are found:

1. **Context gathering** — query the Anomalies bucket to collect all active anomalies,
   their blast radius (affected apps and countries), sustained duration, and country health
2. **Brief generation** — send the structured context to the Claude API with a prompt
   that asks for (a) a plain-English incident summary and (b) a root cause hypothesis
3. **Storage** — write the generated summary back to InfluxDB as an `incident_summary`
   measurement so it is displayable in Grafana panels and queryable over time
4. **Notification (optional)** — push the summary to a webhook (Slack, Teams, PagerDuty)

### High-level implementation

```
Anomalies bucket
    │
    ▼
intelligence.gather_incident_context()
    │  — queries anomalous proxies, blast radius, country health
    │  — structures data into incident payload
    ▼
intelligence.generate_incident_brief()
    │  — calls Claude API (structured prompt)
    │  — returns: summary (string), root_cause (string), severity (low/medium/high)
    ▼
InfluxDB  →  incident_summary measurement
                fields: summary, root_cause, severity, anomaly_count
                tags:   hour
```

**New files:** `src/apigee_analysis/intelligence.py`
**Changed files:** `detect.py` (call intelligence after detection), `.env` (API key)
**New dependencies:** `anthropic`

**Only fires when anomalies exist** — clean hours make no API call.

---

## Bundle B — Predictive Baseline

### What it solves

The current Z-score uses a flat rolling mean that treats all hours equally. API traffic
has strong patterns — Monday morning is busier than Saturday night, and an error rate
of 5% at 3am is more alarming than 5% at 2pm. The flat baseline generates false
positives during predictable traffic swings and misses real anomalies masked by
seasonal variation.

Additionally, detection is entirely reactive — the system only flags after the anomaly
has already occurred. For high-impact proxies, earlier warning (even 1–2 hours) allows
preventive action before users are affected.

### Benefits

| Benefit | Detail |
|---|---|
| Fewer false positives | Seasonal patterns removed before Z-score — normal Monday morning traffic no longer triggers alerts |
| Earlier detection | Forecast projects 2 hours ahead; alert fires before threshold is crossed |
| More accurate baselines | Residual-based Z-score is sensitive to genuine deviations, not seasonal noise |
| Capacity planning | Forecast data gives visibility into expected traffic growth |

### How it works

**Seasonality-aware baseline (replaces flat rolling mean):**

1. For each proxy, apply STL decomposition to the 7-day hourly series
2. STL separates the data into three components: trend + seasonal + residual
3. Apply Z-score to the *residual only* — the part that is neither trend nor seasonal
4. A Z-score of ±3 on the residual means genuinely unexpected behaviour, not just
   "it's Monday"

**Predictive alerting (new, runs alongside):**

1. Fit the decomposition model on historical data
2. Project the trend and seasonal components forward 2 hours
3. If the projected value crosses the anomaly threshold, write a `predicted_anomaly`
   measurement with a `hours_until_threshold` field

### High-level implementation

```
7-day hourly series per proxy
    │
    ▼
baseline.decompose()          ← STL (statsmodels, no API call)
    │  trend + seasonal + residual
    │
    ├──▶ zscore_residual()    → feeds existing detect.py (replaces flat Z-score)
    │
    └──▶ forecast(hours=2)    → predicted_anomaly measurement
                                 fields: predicted_value, hours_until_threshold
                                 tags: apiproxy, is_predicted_anomaly
```

**New files:** `src/apigee_analysis/baseline.py`
**Changed files:** `detect.py` (swap Z-score calculation), `.env` (no new keys needed)
**New dependencies:** `statsmodels`

---

## Implementation Order

| Phase | Bundle | Estimated effort |
|---|---|---|
| 1 | Bundle A — Incident Intelligence | 1–2 days |
| 2 | Bundle B — Predictive Baseline | 3–5 days (validation required) |

Bundle A is implemented first because:
- Lower complexity — no algorithmic changes to the core detection
- Immediately visible value for incident response
- Bundle B requires careful validation to avoid regressions in detection accuracy
