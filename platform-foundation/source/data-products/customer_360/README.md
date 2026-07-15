# Customer 360 (`customer_360`)

> **Domain**: Customer &nbsp;·&nbsp; **Storage**: Iceberg
> &nbsp;·&nbsp; **Display name**: `Customer 360`

Daily snapshot of customer profile + engagement signals — identity
(PII), portfolio size, lifetime value, EV-relevant rollups (30-day
charging sessions, 30-day kWh consumed), and predictive scores
(health, churn, NPS). Producer is [`generator.py`](generator.py)
(pandas tier); column formats follow
[`docs/data-contracts.md`](../../../../docs/data-contracts.md).

## Schema

| Column | Type | Nullable | PII | Description |
|---|---|---|---|---|
| `customer_id` | string | no | 🔒 | FK → `customers`; regex per [data-contracts → Identifier formats](../../../../docs/data-contracts.md#identifier-formats) (PK part) |
| `snapshot_date` | date | no | – | Snapshot date (PK part). **Partition key** |
| `full_name` | string | yes | 🔒 + drift | Customer full name (synthetic Faker-generated) |
| `email` | string | yes | 🔒 + drift | Email (synthetic) |
| `phone` | string | yes | 🔒 + drift | Phone (synthetic) |
| `address_line1` / `city` / `state` / `postal_code` | string | yes | 🔒 | Postal address (synthetic) |
| `country` | string | no | – | ISO 3166-1 alpha-2 country code |
| `lifetime_value_usd` | decimal(12,2) | yes | – | Cumulative spend with the manufacturer |
| `vehicles_owned_count` | int | no | – | Number of VINs in this customer's portfolio (0–20) |
| `primary_vin` | string | yes | – | Most-used VIN (FK → `vins`) |
| `customer_segment` | string | no | – | enum: `enthusiast` / `family` / `fleet` / `commercial` / `prospect` |
| `health_score` | double | yes | – | Composite engagement score (0–100) |
| `churn_probability` | double | yes | – | Predicted 90-day churn (0–1) |
| `nps_score` | int | yes | – | Latest Net Promoter Score (-100..100) |
| `total_charging_sessions_30d` | int | yes | – | Trailing-30-day charging session count |
| `total_kwh_consumed_30d` | double | yes | – | Trailing-30-day energy consumed (kWh) |
| `opted_in_marketing` | boolean | no | – | Marketing opt-in flag |
| `created_at` | timestamp | no | – | Customer record creation time |
| `ingest_time` | timestamp | no | – | Snapshot ingest time |

PII columns are tagged `pii: true` in [`schema.yaml`](schema.yaml);
the three `pii_drift_target: true` columns (`full_name` / `email` /
`phone`) are the canonical free-text fields for `bad_pii` edge-case
injection per Fix Group C in
[`tasks.md`](../../../.kiro/specs/2026-05-28-adp-ev-startup-foundation/tasks.md).

## Partition keys

- **Partition**: `snapshot_date` — daily-snapshot grain. Each run
  emits one partition (today's UTC `snapshot_date`); operators run
  the generator once per target date for backfill.
- **No bucketing**: one snapshot per day × 5M customers gives a
  ~360 MB partition at full scale — naturally well-shaped.
- **Pruning**: most queries predicate `snapshot_date = (SELECT
  MAX(snapshot_date) FROM ...)` to read the latest snapshot only.

## Sample queries

Churn-risk top-100 EV-startup customers (most-recent snapshot,
high-LTV bucket):

```sql
WITH latest_snapshot AS (
  SELECT MAX(snapshot_date) AS d FROM adp_staging_customer_360.customer_360
)
SELECT c.customer_id,
       c.customer_segment,
       c.lifetime_value_usd,
       c.health_score,
       c.churn_probability,
       c.total_charging_sessions_30d,
       c.total_kwh_consumed_30d
FROM   adp_staging_customer_360.customer_360 c
JOIN   latest_snapshot ls ON c.snapshot_date = ls.d
WHERE  c.lifetime_value_usd >= 50000
  AND  c.churn_probability  >= 0.40
ORDER BY c.churn_probability DESC, c.lifetime_value_usd DESC
LIMIT 100;
```

Customer-segment efficiency comparison (joined with `energy_usage`):

```sql
WITH latest AS (
  SELECT MAX(snapshot_date) AS d FROM adp_staging_customer_360.customer_360
)
SELECT c.customer_segment,
       COUNT(DISTINCT c.customer_id)            AS customers,
       AVG(eu.efficiency_kwh_per_100mi)         AS avg_eff_kwh_per_100mi,
       AVG(c.health_score)                      AS avg_health_score
FROM   adp_staging_customer_360.customer_360 c
JOIN   latest ls ON c.snapshot_date = ls.d
JOIN   adp_staging_energy_usage.energy_usage eu
       ON  eu.vin = c.primary_vin
       AND eu.usage_date >= DATE '2026-04-29'
GROUP BY c.customer_segment
ORDER BY avg_eff_kwh_per_100mi;
```

Cross-product diagnoses (`customer × charging × energy` cost analysis,
`customer × service × charging` complaint-correlation) live in
[`docs/cvx-integration-contract.md` § 4](../../../../docs/cvx-integration-contract.md)
and the standalone files under
[`platform-foundation/source/athena-queries/`](../../athena-queries/).

## Lineage

- **Inputs**:
  - `customers` dimension (5M, 1:1 with this product's
    `customer_id`).
  - `vins` dimension — `primary_vin` sampled from here.
- **Producer**: [`generator.py`](generator.py) (pandas; ports
  customer-360 logic from
  `guidance-for-agentic-customer-360/source/synthetic-data/`,
  drops QuickSight + Bedrock-agent dependencies which are out of
  foundation v1 scope). Runs from the master `make seed STAGE=...`
  target.
- **Consumers (cross-links via shared dimensions)**:
  - [`customer_interactions`](../customer_interactions/README.md) —
    same `customers` dimension; `total_charging_sessions_30d` here
    correlates with `mobile_app_charging_issue` channel volume there.
  - [`charging_sessions`](../charging_sessions/README.md) — same
    `customers`; this product's 30-day rollups derive from there.
  - [`service_records`](../service_records/README.md) — same
    `customers`; service-visit volume correlates with `health_score`.
  - [`vehicle_identity`](../vehicle_identity/README.md) — same `vins`
    (via `primary_vin`); supplies the per-VIN profile that explains
    customer behavior.
  - [`energy_usage`](../energy_usage/README.md) — same `vins` (via
    `primary_vin`).
- **Lineage trace**: `SELECT * FROM
  adp_staging_customer_360."customer_360$snapshots"
  ORDER BY committed_at DESC LIMIT 5`. See
  [`cvx-integration-contract.md` § 6](../../../../docs/cvx-integration-contract.md).

## Data-quality summary

- **Row count**: 5M × `--scale` per snapshot_date — at `--scale 1.0`,
  exactly 5,000,000 rows for the one snapshot equal to
  `len(customers)`. Smoke run @ scale=0.001 produces 5,000 rows in
  one partition.
- **Edge-case injection** (1–3% per-product band per the six-code
  taxonomy in [`docs/tech.md`](../../../../docs/tech.md)). Smoke
  run reported aggregate **2.18%** (within target):
  - `missing_required` 0.75% on numeric edge_case_eligible columns
    (e.g. `health_score`)
  - `late_arrival` 0.50%
  - `schema_drift` 0.35% (`DRIFT-` prefix on enum columns)
  - `bad_pii` 0.20% on `full_name` / `email` / `phone` (NEVER
    `customer_id` or `primary_vin`; the `pii_drift_target` flag
    excludes FK columns by design)
  - `outlier_value` 0.40% on `health_score`, `churn_probability`,
    etc.
  - `orphan_fk` 0.00% (counter-example)
- **FK closure**: `customer_id` ~99.80% (10 orphans / 5,000 from
  `bad_pii` injection at target rate 0.2% on `customer_id` — but
  only on the `pii_drift_target` columns, NOT on `customer_id`
  itself, post-Fix-Group-C; the historical baseline noted
  ~99.80% pre-fix for reference);
  `primary_vin` 100% (not edge-case-eligible). Verified by
  `tests/test_referential_integrity.py::test_zero_orphan_*`.
- **Distribution shape**: `health_score` ~ N(70, 15) clipped to
  [0, 100]; `churn_probability` ~ Beta(2, 8); `nps_score` ∈
  [-100, 100]; `total_charging_sessions_30d` ~ Poisson(λ=30);
  `total_kwh_consumed_30d` correlates with sessions.
- **Profiling**: `quality-reports/customer_360/profile.{json,md}`
  generated by [`scripts/profile-data.py`](../../../scripts/profile-data.py)
  and surfaced on the CloudWatch dashboard
  `adp-{stage}-foundation-data-quality`.

## See also

- Schema-of-record: [`schema.yaml`](schema.yaml)
- Producer: [`generator.py`](generator.py)
- Integration contract: [`docs/cvx-integration-contract.md` § 3.6](../../../../docs/cvx-integration-contract.md)
- Column formats: [`docs/data-contracts.md`](../../../../docs/data-contracts.md)
