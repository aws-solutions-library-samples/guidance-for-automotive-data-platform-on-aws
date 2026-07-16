# Data Quality / Observability Dashboard

CloudWatch dashboard for the ADP Foundation data-quality and
profiling pipeline.

| | |
|---|---|
| **Dashboard name** | `adp-{stage}-foundation-data-quality` |
| **Metric namespace** | `ADP/Foundation/{stage}` |
| **Region** | `us-east-1` (foundation pin) |
| **Owner** | platform-team |
| **Implements** | Group 5 task "Data quality / observability dashboard" |
| **Source contract** | [`metrics.py`](./metrics.py) (single source of truth) |

The dashboard surfaces five categories of signal published by the seed
and profile pipeline:

1. **Per-product row counts** — latest `RowCount` per Iceberg table
   (and KB chunk count for `vehicle_knowledge_base`). 10 entries
   total (9 products plus the multi-table `ota_campaigns` split into
   `ota_campaigns` header + `ota_campaign_events`).
2. **Edge-case aggregate rate per product** — overall edge-case
   injection fraction per product. The 1–3% target band is annotated
   on the y-axis so out-of-band products are visually obvious.
3. **Per-EdgeCode breakdown** — six widgets (one per edge-case code:
   `missing_required`, `late_arrival`, `schema_drift`, `bad_pii`,
   `orphan_fk`, `outlier_value`) each showing per-product rate. Lets
   operators see "is `bad_pii` regressing on customer_360?" at a
   glance. `orphan_fk` is a counter-example — its target rate is 0%
   per `docs/tech.md` § Edge-Case Taxonomy.
4. **Drift-detection cycle summary** — pass/fail counts per drift
   check (`TestKeyFormats`, `TestVSSColumnPresence`,
   `TestPartitionConventions`) summed over the last 30 days.
5. **Last seed-run timestamp** — Unix epoch seconds of the most
   recent successful seed run per product. CloudWatch console
   tooltips render the human-readable date/time.

## Files

- [`metrics.py`](./metrics.py) — namespace, metric names, dimension
  names, and dimension-value catalog. **Both** the dashboard and
  `scripts/profile-data.py` (Group 6) import from here so a typo
  fails the test in
  `tests/test_quality_dashboard.py` rather than silently emitting an
  empty widget.
- [`dashboard.py`](./dashboard.py) — `build_dashboard_body(stage)`
  returns the dashboard body dict; `QualityDashboard` is a thin CDK
  construct wrapping the body in a `CfnDashboard` resource. CLI
  emits the JSON for the deploy script.
- [`__init__.py`](./__init__.py) — package re-exports.

## Deploy (descopable — JSON path, no CDK stack needed)

```bash
# From repo root, with venv active
.venv/bin/python platform-foundation/source/quality-dashboard/dashboard.py \
    --stage staging > /tmp/adp-staging-quality-dashboard.json

aws cloudwatch put-dashboard \
    --dashboard-name adp-staging-foundation-data-quality \
    --dashboard-body file:///tmp/adp-staging-quality-dashboard.json \
    --region us-east-1 \
    --no-cli-pager
```

Or use the wrapper script (does both steps and the post-deploy
verify):

```bash
./platform-foundation/scripts/deploy-quality-dashboard.sh staging
```

For prod, swap `staging` → `prod` everywhere.

## Verify

**Pre-deploy** (no AWS account access required):

```bash
.venv/bin/python -m pytest \
    platform-foundation/tests/test_quality_dashboard.py -v
```

The test exercises:

- Dashboard body parses as JSON
- Namespace matches `ADP/Foundation/{stage}` for the given stage
- Every metric referenced by the body is in `METRIC_NAMES`
- Every product / edge-code / drift-check dimension value is from
  the published catalog
- Body fits within CloudWatch's 100 KB limit
- All five required widget categories are present (row counts,
  edge-case aggregate, edge-code breakdown, drift summary, last
  seed-run)

**Post-deploy** (against the live dashboard):

```bash
aws cloudwatch get-dashboard \
    --dashboard-name adp-staging-foundation-data-quality \
    --region us-east-1 \
    --no-cli-pager
```

Returns the dashboard body if the dashboard exists; non-zero exit
with `ResourceNotFoundException` otherwise.

## Publishing metrics (contract for `scripts/profile-data.py`, Group 6)

Future publishers (`scripts/profile-data.py`,
`tests/test_data_contracts.py` CI hooks) MUST import the namespace
and metric names from this package — never hard-code them.

Example publisher snippet:

```python
import boto3
from quality_dashboard.metrics import (
    DIMENSION_TABLE,
    METRIC_ROW_COUNT,
    METRIC_EDGE_CASE_AGGREGATE_RATE,
    namespace,
)

cw = boto3.client("cloudwatch", region_name="us-east-1")
ns = namespace("staging")  # 'ADP/Foundation/staging'

cw.put_metric_data(
    Namespace=ns,
    MetricData=[
        {
            "MetricName": METRIC_ROW_COUNT,
            "Dimensions": [{"Name": DIMENSION_TABLE, "Value": "vehicle_telemetry_aggregated"}],
            "Value": 10_000_000,
            "Unit": "Count",
        },
        {
            "MetricName": METRIC_EDGE_CASE_AGGREGATE_RATE,
            "Dimensions": [{"Name": DIMENSION_TABLE, "Value": "vehicle_telemetry_aggregated"}],
            "Value": 0.022,
            "Unit": "None",
        },
    ],
)
```

## Cost

Dashboards are billed at **$3.00 per dashboard per month** in
us-east-1 (current pricing — verify on the
[AWS pricing page](https://aws.amazon.com/cloudwatch/pricing/) when
deploying). Custom metrics (the data the dashboard reads) are
billed separately at $0.30 per metric per month — with ~70 unique
(metric × dimension) tuples we expect ~$21/mo per stage. The first
3 dashboards per account per region are free.

## Anti-patterns

This dashboard intentionally avoids:

- **Stale unused metrics** — every widget references metrics the
  Group 6 publisher will emit. If Group 6 is descoped or delayed,
  the dashboard renders empty cells (CloudWatch's "no data"
  rendering); no data points = no cost beyond the flat dashboard
  fee.
- **Alarms** — alarms belong in their own task. This dashboard is
  for human-in-the-loop investigation, not paging. The
  cloudwatch-dashboards skill calls this out: dashboards for
  context, alarms for detection.
- **Cross-account / cross-region widgets** — single-account,
  single-region by design (foundation pin per
  `staging-prod-design.md`).

## Descope path

Per Group 5 Risk #10, this task is the **fourth** in the descope
order. If descoped:

1. The dashboard JSON still ships (this directory) and Group 6's
   `profile-data.py` still publishes metrics — operators can build
   their own dashboards on top of the metric contract.
2. The `decisions.md` entry for the descope cites this README as
   the contract publishers reference.
3. Re-prioritise as a follow-up after the foundation stabilises.
