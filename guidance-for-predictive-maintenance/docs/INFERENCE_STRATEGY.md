# Tire Prediction: Inference Strategy

## Why Two Approaches

We implement two inference strategies for tire health prediction because the failure modes have fundamentally different time scales:

| Failure Mode | Time Scale | Detection Window | Inference Needed |
|---|---|---|---|
| Slow leak | Days to weeks | 3-7 days before threshold | Daily batch |
| Valve failure | Intermittent over weeks | Days | Daily batch |
| Highway blowout | Minutes | Seconds to minutes | Real-time |

### Daily Batch: Slow Leak Detection

**What it does:** Queries the last 7 days of tire telemetry, computes pressure trends per tire using linear regression, and writes predictive warnings for tires losing pressure consistently.

**Why daily and not real-time:**
A slow leak drops 0.5-1.2 PSI per day. The window from "detectable trend" to the 28 PSI alert threshold is 3-7 days. Checking once per day gives 4+ days of advance warning. Checking every 15 minutes gives the same 4+ days — the extra granularity adds cost without adding value for a condition that changes over days.

**Cost analysis:**
```
Daily batch (Lambda + DDB query):     ~$0.02/day  = $0.60/month
Real-time endpoint (ml.m5.large):     $2.76/day   = $83/month
```

At 50 vehicles with ~2 slow leaks per year, the real-time approach costs $1,000/year to save $2,000-3,400. The daily batch costs $7/year for the same outcome.

**When the ML model adds value over simple trend detection:**
- Temperature-related pressure changes (cold morning vs warm afternoon) look like leaks to a simple trend line but the ML model accounts for ambient temperature correlation
- Intermittent valve failures show irregular pressure patterns that linear regression misses
- Altitude changes during mountain routes cause temporary pressure drops

**Implementation:** `source/lambda/daily_tire_check/main.py`
- Triggered by EventBridge schedule (daily at 6 AM)
- Queries DynamoDB telemetry table for last 7 days
- Computes linear regression slope per tire
- Alerts if slope < -0.3 PSI/day AND current pressure < 30 PSI
- Writes `prediction.tire_slow_leak` alerts to maintenance-alerts table

### Real-Time: Highway Blowout Risk

**What it does:** Evaluates multi-signal tire risk patterns during highway driving using the SageMaker Random Cut Forest model. Only called when a vehicle is at highway speed with concerning tire signals.

**Why real-time for this:**
A tire under combined stress (high speed + high temperature + low tread + borderline pressure) can fail catastrophically in minutes. Each signal individually is "fine" — pressure at 29 PSI (above 28 threshold), temperature at 140°F (high but not alarming alone), tread at 3.5mm (above 3mm threshold). But the combination is dangerous.

A rule-based system can't catch this because no single threshold is crossed. The ML model recognizes the multi-signal pattern that preceded blowouts in the training data.

**Cost justification:**
```
SageMaker endpoint:           $83/month
Highway blowout cost:         $10,000+ (tow, tire, cargo damage, downtime, liability)
At 5,000 vehicles:            ~5 blowouts/year prevented = $50,000+ saved
ROI:                          50x
```

**Pre-filtering to control cost:**
The endpoint is NOT called for every telemetry message. It's only invoked when:
1. Vehicle speed > 60 mph (highway driving), AND
2. Any tire pressure < 30 PSI OR tire temperature > 120°F

This filters 90%+ of telemetry. Instead of 19,200 inferences/day (50 vehicles × 4 tires × 4/hour × 24 hours), we get ~50-100 inferences/day for vehicles in active risk conditions.

**Implementation:** `source/lambda/realtime_blowout_risk/main.py`
- Invoked by Flink MaintenanceProcessor when pre-filter conditions are met
- Normalizes features using stats from SSM Parameter Store
- Calls SageMaker endpoint for anomaly score
- Writes `prediction.blowout_risk` alerts (CRITICAL/HIGH) to maintenance-alerts table

## Architecture

```
                    DAILY BATCH                          REAL-TIME
                    (slow leaks)                         (blowout risk)

EventBridge         Telemetry → Flink
(daily 6 AM)        MaintenanceProcessor
    │                    │
    ▼                    │ speed > 60 AND
Lambda:                  │ (pressure < 30 OR temp > 120)
daily_tire_check         │
    │                    ▼
    │               Lambda:
    │               realtime_blowout_risk
    │                    │
    │                    ▼
    │               SageMaker Endpoint
    │               (Random Cut Forest)
    │                    │
    ▼                    ▼
DynamoDB: maintenance-alerts
    │
    ├── prediction.tire_slow_leak (WARNING, $35)
    │   "Tire FL losing 0.8 PSI/day, threshold in 5 days"
    │
    └── prediction.blowout_risk (CRITICAL, $800)
        "Tire FL at 29 PSI, 140°F, 75 mph — anomaly score 0.87"
```

## SSM Parameters

| Parameter | Description |
|---|---|
| `/tire-prediction/prod/endpoint-name` | SageMaker endpoint for real-time inference |
| `/tire-prediction/prod/normalization-stats` | Feature normalization (mean/std per feature) |
| `/tire-prediction/prod/anomaly-threshold` | Anomaly score threshold for blowout risk |

## Training Data

Generated by `scripts/generate_training_data.py`:
- 721,024 records, 50 vehicles, 6 months
- Normal driving + injected anomalies (slow leaks, punctures, valve failures, overinflation)
- Seasonal temperature effects, city-specific climate, sensor noise
- Features: pressure, temperature, delta_pressure, delta_temp, tread_depth, speed

Model trained by `scripts/train_model.py`:
- SageMaker Random Cut Forest (unsupervised anomaly detection)
- Trained on normal data only — learns what "healthy" looks like
- 100 trees, 256 samples per tree, 4 features
- Anomaly threshold set at 95th percentile of normal scores
