# MTN API Intelligence Platform
## From Data Collection to AI-Powered Incident Response

---

## Executive Summary

MTN operates hundreds of API proxies across 15 Operating Companies (OpCos), processing
millions of transactions per hour. Until now, understanding the health of this ecosystem
required manual analysis of raw logs and reactive investigation after incidents had already
impacted customers.

This document describes the design and implementation of an end-to-end API Intelligence
Platform — a system that automatically collects API performance data, detects anomalies
in real time, identifies which customers are affected, and uses AI to generate plain-English
incident briefs and root cause hypotheses.

The platform is fully operational and running on an hourly cycle.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA COLLECTION                          │
│                                                                 │
│   Apigee Analytics ──► Playwright Automation ──► InfluxDB      │
│   (API traffic,          (browser fetch,         (time-series  │
│    dimensions,            bg-job download,         storage)     │
│    status codes)          normalisation)                        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         PRODUCT DATA                            │
│                                                                 │
│   MTN OpCo API ──► REST Fetch ──► InfluxDB (OpCo Products,     │
│   (product lists,                  OpCo Apps buckets)           │
│    app subscriptions)                                           │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       AI ANALYSIS ENGINE                        │
│                                                                 │
│   STL Decomposition ──► Z-score Detection ──► Anomalies bucket  │
│   (seasonality removal)   (statistical)                         │
│                                                                 │
│   Forecasting ──────────► Predictive Alerts                     │
│   (2-hour projection)                                           │
│                                                                 │
│   Claude API ───────────► Incident Summaries + Root Cause       │
│   (language model)                                              │
└─────────────────────────────────────────────────────────────────┘
```

All components run as Docker services on a single host, with InfluxDB as the shared
time-series store and Grafana for visualisation.

---

## Part 1: Data Collection Foundation

### 1.1 Apigee Analytics — The Data Source

Apigee is MTN's API gateway, processing every API call made across all OpCos. Its
analytics engine aggregates traffic data into custom reports containing:

- **API proxy** — which API was called (e.g. `customer-subscriptions_v2`)
- **Developer app** — which application made the call
- **Response status code** — whether the call succeeded (2xx) or failed (4xx/5xx)
- **Country code** — which OpCo the call originated from
- **Request path and URI** — the specific endpoint called
- **Traffic volume** — call count per time interval

Apigee does not expose this data via a straightforward API at the granularity required.
Reports must be generated interactively through the web UI, submitted as background jobs,
and downloaded as compressed ZIP files.

### 1.2 Automated Browser Extraction

Rather than manual extraction, the platform uses **Playwright** — a browser automation
framework — to drive the Apigee web interface programmatically:

1. Authenticates with email, password, and TOTP two-factor authentication
2. Navigates to the custom reports section
3. Opens the date picker and selects the required time window
4. Submits the report as a background job via the "Submit Job" button
5. Monitors the Report Jobs page, polling until the job status shows "Report completed"
6. Identifies the correct completed job using UTC time range matching and submission
   timestamp proximity (to avoid downloading stale results from concurrent sessions)
7. Hovers to reveal the download icon and triggers the download
8. Monitors the `.crdownload` temporary file for real-time progress and stall detection
9. Extracts and normalises the CSV from the downloaded ZIP

This process runs every hour via a Docker-based cron scheduler.

### 1.3 Data Normalisation

Apigee produces two distinct report formats depending on data volume — an inline
format (small datasets) and a background-job format (larger datasets). The platform
normalises both into a unified schema:

```
organization, environment, Time Unit, apiproxy, developer_app,
response_status_code, xcountrycode, request_path, request_uri, Sum of traffic
```

Timestamps are preserved in their original timezone (matching the container and Apigee's
local timezone) and converted to RFC3339 for InfluxDB compatibility. Future hours that
appear in Apigee's output as "Invalid date" are automatically dropped.

### 1.4 Storage — InfluxDB

All data is written to **InfluxDB v2**, a purpose-built time-series database. InfluxDB's
data model maps naturally to this use case:

- **Measurement** — the report name (e.g. `apigee_mso_reporting_chrisw`)
- **Tags** — indexed dimensions used for filtering (proxy, app, status code, country, path)
- **Fields** — the numeric value (`Sum of traffic`)
- **Timestamp** — the minute/hour of the data point

The bucket retains data indefinitely, giving the analysis engine full historical depth.

### 1.5 OpCo Product and App Data

A second data source provides the product and application landscape per OpCo. The
MTN OpCo Insights API (`/opco/product/list` and `/opco/apps/list`) returns:

- Which API products are available in each of the 15 OpCos
- Which developer applications subscribe to each product

This data is fetched hourly and stored in two dedicated InfluxDB buckets:
- **OpCo Products** — one point per product per OpCo per hour
- **OpCo Apps** — one point per app-product subscription per OpCo per hour

This enables tracking of API adoption trends and product landscape changes over time.

---

## Part 2: AI Analysis Engine

The analysis engine runs in a separate repository (`apigee-analysis`) and connects
to the same InfluxDB instance. It reads from the traffic data bucket and writes
its results to a dedicated `Anomalies` bucket. The separation ensures that analysis
code can evolve independently of the data collection pipeline.

### 2.1 The Core Challenge: Defining "Normal"

The fundamental challenge in API monitoring is distinguishing genuine incidents from
normal variation. API traffic is not constant — it follows strong daily patterns
(busy during business hours, quiet at night) and weekly patterns (weekdays vs weekends).
A naive alert on absolute thresholds generates excessive false positives.

The platform addresses this through statistical anomaly detection: instead of asking
"is this number high?", it asks "is this number *unexpectedly* high relative to
historical behaviour?"

### 2.2 Statistical Method — Z-Score Anomaly Detection

The Z-score is a classical statistical measure of how many standard deviations a
value is from its mean:

```
Z = (current_value - mean) / standard_deviation
```

A Z-score of 0 means the value is exactly average. A Z-score of ±3 means the value
is 3 standard deviations from the mean — statistically, this occurs by chance less
than 0.3% of the time. Values beyond ±3 are flagged as anomalous.

The platform applies Z-score detection across three dimensions:

**Traffic volume** — detects proxies with unexpectedly high or low call volume.
A large negative Z-score (e.g. -8.4) indicates a proxy has gone quiet, which may
signal an outage upstream. A large positive Z-score indicates a traffic spike.

**Error rates** — for each proxy, the platform computes:
```
error_rate = (4xx calls + 5xx calls) / total_calls
```
This rate is tracked hourly and Z-scored against its historical baseline. Critically,
the platform separates 4xx (client errors) from 5xx (server errors), as these
have different causes and require different responses:
- 4xx spikes suggest bad client requests, expired credentials, or breaking API changes
- 5xx spikes indicate backend failures or infrastructure issues

**Country health** — error rates are aggregated across all proxies for each of the
15 OpCos, producing a single rolled-up health score per country. This answers
"is GHA broadly degraded?" rather than "is this specific proxy degraded?"

### 2.3 Seasonality-Aware Baselines — STL Decomposition

A simple 7-day rolling mean does not account for predictable traffic patterns. An
API that is always 10× busier on Monday mornings would falsely trigger anomaly
alerts every Monday.

The platform addresses this using **STL decomposition** (Seasonal-Trend decomposition
using Loess, developed by Cleveland et al. at Bell Labs). STL separates a time series
into three components:

```
observed = trend + seasonal + residual
```

- **Trend** — the long-term direction of change (growth or decline over weeks)
- **Seasonal** — the predictable repeating pattern (daily cycle for hourly data)
- **Residual** — what remains after trend and seasonality are removed

The Z-score is then computed on the **residual only**. A value that is high because
it is Monday morning is not anomalous — that is captured by the seasonal component.
A value that is high *beyond what the seasonal pattern predicts* is a genuine anomaly.

STL is applied to each proxy independently, fitting a daily period (24 hours) to
the 7-day historical window. For proxies with insufficient data (fewer than 72
hourly data points), the system falls back to the flat Z-score.

### 2.4 Predictive Alerting — Forward Projection

Once the STL model is fitted on historical data, the seasonal component (being periodic)
and trend component (extrapolated linearly) can be projected forward in time.

The platform projects 2 hours ahead and evaluates whether the forecast would cross the
anomaly threshold. If a proxy is currently within normal range but the model predicts
it will breach the threshold within 2 hours, a `predicted_anomaly` record is written
to InfluxDB.

This shifts the team from **reactive** (responding after the incident) to **proactive**
(preparing before the threshold is crossed).

### 2.5 Sustained Anomaly Detection

Single-hour anomalies frequently self-resolve and do not represent real incidents. To
reduce alert fatigue, the platform tracks consecutive anomalous hours per proxy.

Each detection run queries the previous hour's result from the Anomalies bucket before
writing. If both the current and previous hours are anomalous, the record is tagged
`sustained=true` and a `consecutive_hours` field increments. A Grafana alert filtered
to `sustained=true` fires only for confirmed, persistent incidents — not transient spikes.

### 2.6 Blast Radius Analysis

When an anomaly is confirmed, the immediate operational question is: *who is affected?*

For each anomalous proxy, the platform queries the traffic data to identify every unique
combination of developer application and country that called that proxy in the anomaly
hour, along with their call volumes:

```
proxy: customer-subscriptions_v2
  app: tchokokash    | country: CMR | calls: 29,033
  app: timwe-prod    | country: GHA | calls: 7,566
  app: ayo-gha-dev   | country: GHA | calls: 2,907
  ...
```

This blast radius data is stored in InfluxDB and queryable from Grafana, enabling
incident communications to be scoped accurately — notifying only the affected
development teams rather than broadcasting broadly.

### 2.7 AI-Generated Incident Briefs — Claude API

The five detection outputs (traffic anomalies, error rate anomalies, country health,
sustained flags, blast radius) collectively describe an incident in structured data.
However, a structured dataset is not the same as an actionable incident brief.

After each hourly detection run, if anomalies are present, the platform:

1. **Assembles a structured context** — collects all active anomalies, their error
   classes, Z-scores, sustained duration, and the top blast radius entries

2. **Sends to Claude** — the assembled context is sent to Anthropic's Claude language
   model with a structured prompt requesting a JSON response containing:
   - A 2–3 sentence plain-English summary naming the affected proxies, error rates,
     and affected applications
   - A root cause hypothesis distinguishing client-side from server-side failures
   - A severity rating (low / medium / high) based on blast radius and error magnitude
   - A single recommended immediate action

3. **Stores the brief** — the generated output is written back to InfluxDB as an
   `incident_summary` measurement, making it queryable and displayable in Grafana

**Example output:**

> *"10 anomalies detected at 2026-06-26T08:00Z. The highest server-error signal is
> TMF621_TroubleTicket_prod at 11.11% (z=5.02), with the Nigeria
> consent-monetization-sms proxy showing a 62.56% client error rate. The customer-loans
> proxy has the widest blast radius across CMR, ZMB, CIV, BEN and LBR."*
>
> **Root cause:** *"Two distinct issues: 5xx failures on TMF621 indicate a backend
> dependency fault; 4xx errors on Nigeria consent-monetization-sms point to malformed
> requests or auth failures from calling applications."*
>
> **Action:** *"Investigate TMF621 backend health logs and triage the Nigeria 4xx surge
> for a bad client deployment or auth misconfiguration."*

The AI brief is generated only when anomalies exist — clean hours make no API call.

---

## Part 3: Outputs and Operational Impact

### 3.1 InfluxDB Anomalies Bucket — Six Measurements

| Measurement | Contents |
|---|---|
| `traffic_anomaly` | Z-score and sustained flag per proxy per hour |
| `error_rate_anomaly` | 4xx/5xx Z-scores and error rates per proxy per hour |
| `country_health` | Rolled-up error rate and Z-score per OpCo per hour |
| `blast_radius` | Affected applications and countries per anomalous proxy |
| `predicted_anomaly` | Proxies projected to breach threshold within 2 hours |
| `incident_summary` | Claude-generated brief, root cause, severity, and action |

### 3.2 Grafana Dashboards

All six measurements are queryable in Grafana using standard Flux queries. Recommended
panels:

- **Anomaly timeline** — heatmap of `is_anomaly=true` points by proxy over time
- **Sustained incidents** — filter to `sustained=true` for confirmed incidents only
- **Country health** — stat panel per OpCo showing current Z-score with colour thresholds
- **Blast radius** — table of affected apps sorted by call count for the current incident
- **Predictive alerts** — proxies with `predicted_anomaly` records (early warning)
- **Incident brief** — text panel showing the latest Claude-generated summary

### 3.3 OpCo Coverage

| OpCo | Products | Apps | Status |
|---|---|---|---|
| GHA | 55 | 361 | Largest ecosystem |
| UGA | 63 | 368 | Most products |
| ZAF | 51 | 375 | Most apps |
| NGA | 3 | 22 | Growth opportunity |
| ... | ... | ... | ... |

Product and app counts are tracked hourly, enabling detection of additions, removals,
and adoption trends across the OpCo ecosystem.

---

## Part 4: Technical Implementation

### 4.1 Infrastructure

| Component | Technology | Purpose |
|---|---|---|
| Data collection | Python + Playwright | Automated Apigee report extraction |
| Scheduling | Docker cron service | Hourly execution |
| Storage | InfluxDB v2 | Time-series data and anomaly results |
| Analysis | Python + statsmodels + scikit-learn | STL decomposition, Z-score detection |
| AI | Claude API (Anthropic) | Incident summarisation and root cause |
| Visualisation | Grafana | Dashboards and alerting |
| Reverse proxy | nginx | Subdomain routing with Cloudflare |

### 4.2 Repositories

- **`apigee-fetch`** — data collection pipeline (Playwright, normalisation, InfluxDB load)
- **`apigee-analysis`** — AI analysis engine (STL, Z-score, blast radius, Claude API)

Separation of concerns ensures each can be maintained, deployed, and scaled independently.

### 4.3 Data Volume

| Bucket | Points (7-day window) |
|---|---|
| Apigee Reports | ~400,000 per day |
| OpCo Products | ~360 per day (15 OpCos × 24 hours) |
| OpCo Apps | ~47,000 per day |
| Anomalies | ~25,000 per day |

---

## Part 5: Roadmap

The current implementation represents Phase 1. Future enhancements include:

**Near-term:**
- Anomaly correlation — group simultaneous anomalies across proxies into single incidents
  when they share a likely common cause (e.g. 8 Nigeria KYC proxies failing together)
- Slack / Teams / PagerDuty integration — push incident briefs as notifications

**Medium-term:**
- Per-proxy adaptive thresholds — learn the optimal Z-score threshold for each proxy
  based on historical false positive rates, replacing the universal ±3 threshold
- App-level anomaly detection — apply the same Z-score framework to individual
  developer applications, not just API proxies

**Longer-term:**
- Unused product detection — cross-reference OpCo Products with Apigee traffic to
  identify products with zero calls over a rolling 7-day window
- Cross-OpCo incident correlation — detect when the same product fails across multiple
  OpCos simultaneously, indicating a shared platform dependency

---

*Platform developed and operational as of June 2026.*
*Repositories: github.com/ChrisW-ATOS/apigee-fetch | github.com/ChrisW-ATOS/apigee-analysis*
