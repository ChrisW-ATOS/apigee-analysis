# How the AI Analysis Works
## A Plain-English Guide to the Algorithms

---

## The Big Picture

Every hour, hundreds of APIs across MTN's 15 countries are processing millions of calls.
The system watches all of them simultaneously and asks a simple question for each one:

> **"Is something unusual happening right now?"**

To answer that, it uses a chain of techniques — each one building on the last. None of
them require human intervention. They run automatically, around the clock.

---

## Technique 1: Spotting What's Unusual — The Z-Score

### The Problem

Imagine you manage a shop and you want to know if today's sales are abnormal. If you
sell 100 items on a Tuesday, is that good or bad? You can't know without context.
But if your average Tuesday is 95 items, and you've rarely sold fewer than 85 or more
than 105, then 100 is completely normal. If you sold 200, something unusual is happening.

APIs work the same way. A proxy handling 10,000 calls in an hour might be completely
normal — or it might be a crisis — depending on what "normal" looks like for that proxy.

### The Solution: Z-Score

The Z-score measures how far away from normal something is, expressed in units of
"how surprising is this?":

- A Z-score of **0** means: exactly average, nothing to see here
- A Z-score of **±1** means: slightly off, well within normal variation
- A Z-score of **±3** means: this would only happen by random chance 3 times in 1,000 hours

The system uses **±3 as its alarm threshold**. Anything beyond that is flagged as an anomaly.

### What It Watches

The system applies this test to three things per proxy, every hour:

**Traffic volume** — how many calls came in. A proxy that suddenly goes very quiet
(large negative Z-score) may have gone offline. A proxy with a massive spike may be
under an unusual load.

**Client error rate (4xx)** — the proportion of calls that were rejected because the
*caller* did something wrong: bad credentials, expired tokens, malformed requests.
A spike here usually means a developer app has broken, or an auth token has expired.

**Server error rate (5xx)** — the proportion of calls that failed because the *API
itself* broke: a backend system went down, a database timed out, a dependency failed.
This is usually more serious and needs infrastructure investigation.

Separating 4xx from 5xx is important. They look the same on a traffic graph but point
to completely different causes and completely different teams to call.

---

## Technique 2: Accounting for Daily Patterns — STL Decomposition

### The Problem with Simple Averages

The Z-score above works well, but it has a blind spot. APIs don't behave the same way
all day. During business hours, traffic is high. At 3am, it drops to almost nothing.
On Monday mornings, certain APIs spike every single week.

If you use a simple average as your baseline, the system would fire a false alarm every
Monday morning when the weekly rush hits — even though that rush is completely expected.
Conversely, if traffic drops at night (as it always does), the system might think
something is wrong when it's actually just Wednesday at 2am.

### The Solution: STL (Seasonal-Trend Decomposition)

STL is a technique that separates a time series into three layers, like peeling an onion:

```
What we observe = the underlying trend
               + the predictable daily pattern
               + genuine unexplained variation
```

**Trend** — the slow drift upward or downward over weeks. An API that is gaining
adoption will show a gentle upward trend. One being deprecated will drift down.

**Seasonal** — the repeating daily cycle. Busy in the morning, quieter at lunch,
busy again in the afternoon, quiet overnight. This layer captures that predictable
rhythm, including the fact that Mondays are busier than Sundays.

**Residual** — what's left over after you strip away the trend and the daily pattern.
This is the "unexplained" part — the signal that doesn't fit the pattern.

The key insight: **the Z-score is applied only to the residual layer**, not to the
raw number. This means:

- Monday morning traffic is high → captured by the seasonal layer → not flagged
- Traffic that is high *beyond* what Monday morning predicts → shows up in the residual → flagged

Think of it like a seasoned weather forecaster. They don't call a 30°C day in July
a heatwave — that's expected. But 30°C in January? That's in the residual.

STL was developed at Bell Labs in the 1990s and is one of the most reliable techniques
for separating predictable patterns from genuine anomalies in time-series data.

The system requires at least 3 days of hourly data (72 data points) before applying
STL. For newer proxies with less history, it falls back to the simple Z-score instead.

---

## Technique 3: Looking Ahead — Predictive Alerting

### The Problem with Reacting

Both techniques above look at the *current* hour. By the time something is flagged as
anomalous, the incident has already started. The team is reacting, not preparing.

### The Solution: Forward Projection

Once STL has broken a time series into its three layers (trend, seasonal, residual),
we can project those layers forward in time:

- The **trend** moves in a consistent direction — if traffic has been growing at
  500 calls per hour every day, we can reasonably assume it will continue for the
  next couple of hours.

- The **seasonal** component is periodic by definition — tomorrow at 9am will look
  similar to today at 9am and last Monday at 9am. We can read off what the seasonal
  pattern predicts for the next hour or two.

Adding these projections together gives a forecast of where a proxy's traffic or error
rate is *likely* to be in 2 hours, before it gets there.

If that forecast crosses the anomaly threshold, the system writes a **predicted anomaly**
record — a flag that says: *"this proxy is currently fine, but at its current trajectory,
it will be anomalous within 2 hours."*

This is the difference between a smoke alarm and a fire alarm. Both are valuable,
but the smoke alarm gives you more time.

---

## Technique 4: Filtering Out Noise — Sustained Anomaly Detection

### The Problem: False Positives

Even with STL and Z-scores, a system watching hundreds of proxies every hour will
occasionally flag something that looks anomalous but self-corrects a few minutes later —
a momentary network blip, a one-off timeout, a brief spike from a single retry storm.

If every one-off spike triggers a page-out to an on-call engineer, the team quickly
learns to ignore the alerts. This is called **alert fatigue** and it's one of the most
common failure modes in monitoring systems.

### The Solution: Consecutive Hour Tracking

Before writing an anomaly record, the system checks: *was this proxy also anomalous
last hour?*

If yes, the anomaly is tagged `sustained = true` and a counter increments tracking
how many consecutive hours the issue has persisted.

If no, the anomaly is recorded but tagged `sustained = false` — it exists in the data
for analysis, but Grafana alerts are filtered to only fire on sustained events.

The result: genuine incidents (which persist hour after hour) always surface. Transient
blips (which self-resolve) are recorded but don't wake anyone up.

---

## Technique 5: Finding Who Is Affected — Blast Radius

### The Problem: "Which teams do I call?"

When an API proxy is confirmed anomalous, the operational question is immediately:
*who is affected, and how badly?*

An engineer without this information has two options: either broadcast to everyone
(causing unnecessary panic) or spend time manually investigating the logs to figure
out which apps were calling the broken proxy.

### The Solution: Impact Mapping

For each anomalous proxy, the system automatically queries the traffic data and builds
a ranked list of every application and country that was calling that proxy in the
affected hour, along with their call volumes:

```
Proxy: customer-subscriptions-api
  tchokokash (Cameroon)   — 29,033 calls
  timwe-prod  (Ghana)     —  7,566 calls
  ayo-gha-dev (Ghana)     —  2,907 calls
  ...
```

The developer teams behind the top applications are the ones to notify. The countries
tell you the geographic scope of the incident.

This information is stored in InfluxDB and surfaced in Grafana, so the on-call engineer
sees the blast radius at the same time as the anomaly alert — no manual digging required.

---

## Technique 6: The Bigger Picture — Country Health Score

### The Problem: Missing the Forest for the Trees

The proxy-level anomaly detection is precise but granular. Sometimes an incident
affects many proxies in the same country simultaneously — a shared infrastructure
dependency goes down, or a regional network issue hits everything at once.

Looking at 50 individual proxy alerts, each with their own Z-scores, makes it harder
to see that they all share a common cause: "Ghana is broadly degraded."

### The Solution: Rolled-Up Country Score

Every hour, the system aggregates all API calls across all proxies for each of the
15 OpCos and computes an overall error rate for that country:

```
Ghana error rate this hour = (all failed calls in GHA) / (all calls in GHA)
```

This single number is then Z-scored against Ghana's own historical baseline. A country
health anomaly fires when the *entire country's* error rate is unexpectedly high —
a strong signal that this isn't a single broken API, but a systemic issue.

Country health and per-proxy anomalies complement each other:
- Many proxy anomalies + country health anomaly → likely a shared infrastructure issue
- A single proxy anomaly + healthy country score → likely an isolated API problem

---

## Technique 7: Turning Data into Words — AI Incident Briefs

### The Problem: Data ≠ Understanding

After all the above techniques have run, the system has a collection of structured
records: anomaly Z-scores, error rates, sustained flags, blast radius tables, country
health scores. This data is precise and correct, but it requires an analyst to read and
synthesise it into an actionable incident description.

At 3am, that's a lot to ask of an on-call engineer.

### The Solution: Large Language Model Summary

Once per hour — but *only* when anomalies are present — the system packages all of
the above data into a structured message and sends it to Claude, Anthropic's AI model.

The prompt instructs Claude to act as an API operations analyst and return a structured
JSON response with four fields:

**Summary** — 2–3 sentences in plain English, naming the specific proxies, error rates,
and affected applications. Written for someone who just woke up and needs to understand
the situation in 10 seconds.

**Root cause hypothesis** — a 1–2 sentence best guess at the cause, specifically
distinguishing whether the evidence points to client-side failures (bad requests from
apps) or server-side failures (broken backends). This guides where to look first.

**Severity** — a rating of low, medium, or high, based on rules: high if the anomaly
has persisted for more than one hour, or if the error rate is above 20%, or if more
than 5 applications are affected.

**Recommended action** — a single concrete next step. Not "investigate the issue" —
something specific like "check the Nigeria KYC backend health and review recent
deployments to consent-validation-v1."

The brief is then stored back in InfluxDB and displayed in Grafana alongside the raw
anomaly data — so the same dashboard that shows the Z-scores also shows the plain-English
interpretation.

**What Claude is and isn't doing here:**
Claude is not detecting the anomalies — the statistical techniques above do that.
Claude is taking the already-detected, already-structured output and translating it
into natural language faster and more coherently than a template could. The underlying
maths is not delegated to the AI; the communication is.

---

## How They Work Together

Each technique handles a different piece of the problem:

| Technique | Question it answers |
|---|---|
| Z-score | Is this number unusual compared to history? |
| STL decomposition | Is it unusual *beyond* what the daily pattern predicts? |
| Predictive alerting | Will it become unusual in the next 2 hours? |
| Sustained detection | Has it been unusual for more than one hour? |
| Blast radius | Which apps and countries are affected? |
| Country health | Is this an isolated API issue or a country-wide problem? |
| AI brief | What does all of the above mean, in plain English? |

A typical incident progresses through all of them:

1. STL residual Z-score exceeds ±3 → anomaly flagged
2. Previous hour also flagged → `sustained = true`, alert fires
3. Blast radius query → top 5 affected apps identified
4. Country health also anomalous → confirms systemic issue, not isolated
5. Predictive model shows 2 more hours of degradation projected
6. Claude generates a brief: *"Nigeria KYC APIs showing sustained 5xx failures for 3
   consecutive hours. Blast radius includes tchokokash and FCMB apps. Likely backend
   dependency failure — check the KYC verification service health dashboard."*

The on-call engineer receives the brief, knows exactly where to look, and can begin
remediation without needing to manually cross-reference five different data sources.

---

*All techniques run automatically every hour with no human intervention required.*
