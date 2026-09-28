# Batch-Only ML Deployment Guide

This guide documents the default, cost-optimized batch inference mode for ADP's tire prediction pipeline, and how to opt into real-time inference if needed.

## Overview

The tire prediction pipeline supports two inference modes:

| Mode | Cost | Latency | Use Case | Default |
|------|------|---------|----------|---------|
| **Batch Transform** | ~$0.02/day (~$11/month training only) | Daily | Daily tire health snapshots, integration with maintenance scheduling | ✅ Yes |
| **Real-time Endpoint** | ~$168/month endpoint + training | <1 second | On-demand predictions during customer interactions | No; opt-in |

The **batch mode is the default posture**. Training and inference are scheduled daily on a cron schedule; predictions are written to the `cms-{stage}-storage-maintenance-alerts` DynamoDB table with full provenance.

## Batch-Only Deployment (Default)

### Deploy

The default stack deployment (`make deploy`) deploys batch-only:

```bash
make build
make deploy
```

This provisions:
- Monthly training step function (`cron(0 3 1 * ? *)` — 03:00 UTC on the 1st of each month)
- Daily batch inference (`cron(30 2 * * ? *)` — daily at 02:30 UTC)
- `daily_tire_check` Lambda: transforms predictions and writes alerts

**No SageMaker endpoints are created.**

### Cost

For staging, the monthly cost consists of:

| Component | Cost | Notes |
|---|---|---|
| Training (1× monthly) | $11.37 | 4 × `ml.m5.12xlarge` for ≤1 hour; per live AWS pricing as of 2026-08 |
| Batch transform | ~$0.02–0.10/day | Depends on data volume; typically negligible |
| S3 + CloudWatch logs | <$2 | Storage for training data and predictions |
| **Total (staging)** | ~$12–14/month | Conservative estimate |

For production with weekly training, multiply the training cost by 4 (~$45/month). **Recommendation for staging: disable or lengthen training schedule after initial verification**, since staging training only validates the pipeline, not production data.

### Configuration: CMS_TABLE_REGION and CMS_STAGE

The batch-only pipeline **requires two environment variables** to know which CMS tables to read and write:

| Variable | Required | Example Values | Purpose |
|---|---|---|---|
| `CMS_TABLE_REGION` | Yes | `us-west-2` (staging), `us-east-1` (prod) | AWS region where CMS stores its telemetry and alerts tables |
| `CMS_STAGE` | Yes | `staging`, `prod` | Stage name; drives table names like `cms-{stage}-storage-maintenance-alerts` |

**Mapping (as of 2026-08):**

| Deployment Stage | CMS_STAGE | CMS_TABLE_REGION | Notes |
|---|---|---|---|
| Staging (ADP us-east-1) | `staging` | `us-west-2` | CMS staging tables are in us-west-2 |
| Prod (ADP us-east-1) | `prod` | `us-east-1` | CMS prod tables are in us-east-1 |
| (Unknown stage) | — | — | **Deployment fails at synth time** with `UnknownStageError` |

These are set as Lambda environment variables in the CDK stack (`lib/constructs/cms_integration.py`). When deploying via `make deploy DEPLOYMENT_STAGE=staging`, the stack automatically resolves the region mapping.

**Important**: The stack always deploys to **us-east-1** (where the ADP lake, training data buckets, and DataZone catalog live). The `CMS_TABLE_REGION` is separate — it specifies where the pipeline writes alerts, not where it runs.

## Real-Time Endpoint (Opt-In)

### Enable Real-Time Inference

To provision a SageMaker real-time inference endpoint alongside batch inference, set the flag when deploying:

```bash
make build
make deploy DEPLOY_REALTIME_ENDPOINT=true
```

This adds to the stack:
- SageMaker endpoint configuration and endpoint resource
- `realtime_blowout_risk` Lambda with permission to invoke the endpoint
- API Gateway route for real-time predictions (optional; not deployed by default)

**Cost**: ~$168/month for 1 × `ml.m5.xlarge` `AllTraffic` variant, plus training costs (~$45–50/month weekly).

### Real-Time Endpoint Name

The endpoint is named `tpe-{stage}-{region}` to ensure uniqueness and prevent accidental adoption of orphan endpoints from prior deployments. Example: `tpe-staging-us-east-1`.

If a prior endpoint with this name exists, `CreateEndpoint` fails and you must either:
1. Delete the prior endpoint manually
2. Rename it to a different name and re-deploy

This explicit naming prevents silent re-use of stale endpoints.

## Predictions: Provenance Contract

Every alert written to `cms-{stage}-storage-maintenance-alerts` carries five provenance fields to distinguish ML predictions from other sources:

| Field | Type | Example | Purpose |
|---|---|---|---|
| `source` | string | `"adp-tire-ml"` | Identifies ML predictions; existing rows have `"fwe-uds-dtc"` or no source |
| `modelVersion` | string | `"tpm-ba688665-63c9-40e1-b6f1-368b6fba1ec5-model"` | SageMaker model ARN or name; identifies which model produced this prediction |
| `confidence` | enum | `"high"` \| `"medium"` \| `"low"` | Data sufficiency (reading count vs. `MIN_READINGS`), NOT numeric |
| `trendMagnitude` | float | `-0.5877` | Normalized pressure-trend slope per day; negative = leak |
| `computedAt` | ISO-8601 | `"2026-08-10T19:11:01Z"` | When batch inference ran; allows staleness tracking |

**Critical**: `confidence` and `trendMagnitude` are separate fields. The slope is reported as `trendMagnitude`; `confidence` is a categorical judgment of data sufficiency. A downstream consumer reading `confidence` must interpret it as "how much data did we have?", not as a numeric anomaly score.

### Example Query

To audit the batch-only pipeline's output:

```bash
# Count ML-sourced predictions
aws dynamodb scan \
  --table-name cms-staging-storage-maintenance-alerts \
  --filter-expression 'attribute_exists(#s) AND #s = :src' \
  --expression-attribute-names '{"#s": "source"}' \
  --expression-attribute-values '{":src": {"S": "adp-tire-ml"}}' \
  --select COUNT \
  --region us-west-2

# Retrieve the most recent ML prediction
aws dynamodb query \
  --table-name cms-staging-storage-maintenance-alerts \
  --key-condition-expression 'begins_with(alertId, :prefix)' \
  --expression-attribute-values '{":prefix": {"S": "PRED-"}}' \
  --order-by-expression 'computedAt DESC' \
  --limit 1 \
  --region us-west-2
```

## Staging Limitations

The limitation is **coverage and recency, not schema.** An earlier revision of this section claimed
the staging telemetry table has no tire-pressure attributes. That was wrong, and the correction
matters because it changes the fix: nothing needs to be added to the simulator's data model and the
Lambda needs no schema change.

### What is actually true (measured 2026-08-10, full table scan)

Tire pressure is present on the **FWE onboard** path and absent on the **OEM1 cloud** path. The
Lambda reads the correct attribute names, and the CMS simulator models tire pressure directly
(`deployment/ecr/cms-sim-service/realtime_telemetry_simulator.py:120-123`).

| Metric | Value |
|---|---|
| Rows in `cms-staging-storage-telemetry` | 6,472,163 |
| Rows on the OEM1 cloud path (`source="oem"`, no tire pressure) | 6,413,785 (99.2%) |
| Rows carrying `tire_pressure_fl` | 6,690 (0.10%) |
| Distinct vehicles with any tire pressure | **6 of 54** |
| Vehicles with ≥ `MIN_READINGS` (10) inside the 7-day window | **3** — of which **2 are genuine** and 1 is the synthetic seed |

The two genuine in-window vehicles are `VEH-1780081115` (4,643 readings, `source=fleetwise`/absent)
and `VEH-MICH-001` (85 readings, `source=fleetwise`). The third, `1FDEU6PG3PKA99844`, carries
`source=adp-seed` — see § Synthetic Seed Data below.

Adding tire pressure to the OEM1 path is explicitly **not** the fix. That path models a real OEM's
cloud-connector signal set; inventing signals it does not carry would misrepresent the reference
architecture.

### Real data still produces zero alerts — and that is now the correct answer

A re-run against real fleet data on 2026-08-10 produced no alert from a genuine vehicle. Two causes
were in play and only one was a defect:

1. **A pagination defect — FIXED 2026-08-10.** `daily_tire_check` called `Table.query()` once without
   following `LastEvaluatedKey`, and DynamoDB pages *ascending*, so on high-volume vehicles the Lambda
   saw only the oldest slice of its own 7-day window — `VEH-1780081115` had 4,643 in-window readings
   and the Lambda read 272 of them, spanning 67 minutes, which then failed the `time_span_days < 0.1`
   guard. Now paginated and newest-first: the same vehicle analyses 4,431 readings over 1.06 days, and
   a full sweep reads 160 pages across 54 vehicles for ~$0.0013 per run. Resolved at
   `issues/2026-08-10-daily-tire-check-unpaginated-query-truncation/`.
2. **Healthy tires (correct behaviour, not a defect).** `VEH-1780081115` trends **-0.01 PSI/day at
   32.0 PSI** — both alert gates (slope < -0.3 PSI/day AND current < 30 PSI) correctly fail.
   `VEH-MICH-001`'s 85 readings span only 72 minutes, legitimately below the `time_span_days` guard.

So with a correct read the pipeline still writes zero genuine alerts today. **Zero alerts is the right
answer for a healthy fleet**, and the pipeline must not be tuned until it produces one. What changed is
that the two cases are now distinguishable: the run logs a per-vehicle skip reason and returns
`{"query_errors", "truncated_reads", "skips"}`, so "healthy fleet" and "read nothing" no longer look
identical.

**Staleness is now surfaced.** The 7-day window admits old readings — the freshest real tire reading
in staging is 142h old — so every alert carries `metadata.newest_reading_age_hours` and
`metadata.trend_span_days` alongside `computedAt`.

### Synthetic seed data — DELETED 2026-08-11

22 synthetic pressure rows (`source="adp-seed"`, vehicle `1FDEU6PG3PKA99844`) seeded by
`scripts/generate_training_data.py`, and the 6 `source="adp-tire-ml"` alert rows they produced, were
**deleted on 2026-08-11** on user authorization. Record:
`issues/2026-08-10-daily-tire-check-unpaginated-query-truncation/seed-deletion-2026-08-11.md`.

They had been retained the previous day under a removal trigger of "pagination fixed AND a genuine
vehicle has alerted". **That trigger was unsatisfiable** — its second condition depends on an event
healthy data cannot produce — and retention turned out to have an active cost: the daily schedule
re-detected the same seeded leak every run and, because `alertId` is a fresh UUID per detection,
appended a new `OPEN` alert rather than updating one. The table went from 1 row to 6 in under a day.

**Consequence, stated plainly:** the alerts table now holds **zero** `source="adp-tire-ml"` rows, and
the daily run will write none until a real vehicle develops a qualifying trend. A reader checking
`SELECT COUNT(*) WHERE source="adp-tire-ml"` gets 0.

That reintroduces some of the ambiguity the parent issue was about — a table with no ML rows resembles
a pipeline that never ran. What resolves it now is the run's own telemetry rather than a fabricated
row: the Lambda logs a per-vehicle skip reason and returns `{"query_errors", "truncated_reads",
"skips"}`, so a healthy fleet and a broken read are distinguishable without fake data needing to
exist. A row manufactured to prove a pipeline works is, after all, indistinguishable from a row that
proves nothing.

> ⚠️ **`make deploy` targets prod, not staging.** `tire_predictive_maintenance_stack.py:74-77` resolves
> stage as `try_get_context("deploymentStage") or os.environ.get("DEPLOYMENT_STAGE", "prod")`, and the
> `Makefile` `deploy` target passes neither. A `cdk diff` with no stage context repoints this stack at
> `cms-prod-storage-*` and the prod DataZone domain. Always pass the stage explicitly:
>
> ```bash
> cdk deploy tire-predictive-maintenance-stack -c deploymentStage=staging
> ```
>
> With the stage supplied, a code-only change diffs as a single Lambda asset key. Tracked as an open
> item in `issues/2026-08-10-daily-tire-check-unpaginated-query-truncation/summary.md`.

> ⚠️ **Invoke this Lambda with `--cli-read-timeout 0`.** A run takes ~90s; the AWS CLI's default 60s
> socket read timeout fires and then **retries silently**, producing duplicate alerts. Two of the six
> deleted rows were created this way, during a step intended to verify the table.

**For production**, the binding constraint is how many vehicles report tire pressure often enough to
fill the 7-day window — not whether the field exists. Fix the pagination defect before drawing any
conclusion from a zero-alert run.

## Training Cadence

The default training schedule is **monthly** — `cron(0 3 1 * ? *)`, 03:00 UTC on the 1st of each
month — at roughly $11.37 per run. It was changed from the original weekly
`cron(0 3 ? * FRI *)` (about $49.26/month) on 2026-08-10; the source comment in
`tire_predictive_maintenance_stack.py` recommends as little as one training run per year once the
dataset grows, so monthly is still conservative. After staging verification, consider lengthening or
disabling it — nothing in this portfolio monitors idle spend, and two orphan SageMaker endpoints
accrued $7,813 before anyone noticed.

**Rationale**: 
- Weekly training at 4 × `ml.m5.12xlarge` costs ~$49/month
- Monthly training costs ~$11.37
- For staging validation, monthly is sufficient; production should assess data drift and retrain more frequently if needed

To adjust the training schedule, edit `lib/stacks/tire_predictive_maintenance_stack.py:35` (the `ml_training_cron_string`) and redeploy.

### Disable Training in Staging After Verification

Once the ML pipeline is validated to be working (predictions flowing, provenance correct), **disable the training schedule in staging to eliminate idle spend**:

```python
# In tire_predictive_maintenance_stack.py, set:
ENABLE_ML_TRAINING = False
```

This preserves the already-trained model in SageMaker and uses it for daily batch inference, but stops running new training jobs. Inference still runs daily.

## Monitoring & Troubleshooting

### Check Training Job Status

```bash
aws sagemaker list-training-jobs \
  --sort-by CreationTime \
  --sort-order Descending \
  --max-results 5 \
  --region us-east-1
```

### Check Batch Inference Status

```bash
aws sagemaker list-transform-jobs \
  --sort-by CreationTime \
  --sort-order Descending \
  --max-results 5 \
  --region us-east-1
```

### Verify SSM Model Name Parameter

```bash
aws ssm get-parameter \
  --name /tire-maintenance/model-name \
  --region us-east-1 --query 'Parameter.Value' --output text
```

### Check Lambda Logs

```bash
# Batch inference Lambda
aws logs tail /aws/lambda/daily_tire_check --follow --region us-east-1

# Training job logs (if using CloudWatch log group)
aws logs tail /aws/sagemaker/TrainingJobs --follow --region us-east-1
```

### Verify Predictions in DynamoDB

```bash
# Count total alerts by source
aws dynamodb scan \
  --table-name cms-staging-storage-maintenance-alerts \
  --projection-expression "source" \
  --region us-west-2 | \
  jq -r '.Items[].source.S' | sort | uniq -c
```

## Cost Controls

1. **Disable training in staging after validation** (see "Training Cadence" above)
2. **Lengthen training schedule** if data drift is infrequent (e.g., quarterly instead of weekly)
3. **Disable real-time endpoint flag** to avoid $168/month endpoint costs
4. **Monitor SageMaker spend** via CloudWatch dashboards or Cost Explorer to detect idle endpoints

## Next Steps

- **Prod deployment**: Apply the same batch-only pattern to production after staging validation
- **Real-time endpoint**: Enable if real-time predictions are needed for customer interactions
- **Consumer integration**: CVX's Tier 2 health agent will consume these predictions (follow-on work)
