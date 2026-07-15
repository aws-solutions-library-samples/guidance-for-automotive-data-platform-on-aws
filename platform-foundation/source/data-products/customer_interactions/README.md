# Customer Interactions (`customer_interactions`)

> **Domain**: Customer &nbsp;·&nbsp; **Storage**: Iceberg
> &nbsp;·&nbsp; **Display name**: `Customer Interactions`

Per-event log of customer touch-points across dealer, service,
website, mobile app, call center, OTA notifications, chatbot, and
email — with EV-startup-relevant subtypes
(`mobile_app_charging_issue`, `ota_update_notification`) elevated to
top-level channels. Producer is [`generator.py`](generator.py)
(pandas tier; PySpark port deferred per `decisions.md`); column
formats follow
[`docs/data-contracts.md`](../../../../docs/data-contracts.md).

## Schema

| Column | Type | Nullable | PII | Description |
|---|---|---|---|---|
| `interaction_id` | string | no | – | Unique interaction identifier (UUIDv5, PK) |
| `customer_id` | string | no | 🔒 | FK → `customers`; regex per [data-contracts](../../../../docs/data-contracts.md#identifier-formats) |
| `interaction_date` | date | no | – | UTC calendar day. **Partition key** |
| `interaction_time` | timestamp | no | – | Source-truth interaction time (UTC) |
| `channel` | string | no | – | enum: `dealer` / `service_center` / `website` / `mobile_app` / `call_center` / `mobile_app_charging_issue` / `ota_update_notification` / `chatbot` / `email` |
| `interaction_type` | string | no | – | Subtype of interaction |
| `outcome` | string | yes | – | enum: `resolved` / `escalated` / `abandoned` / `in_progress` / `scheduled` |
| `duration_seconds` | bigint | yes | – | Interaction duration (0–86400) |
| `vin` | string | yes | – | Optional VIN context (FK → `vins`) |
| `dealer_id` | string | yes | – | Optional dealer context (FK → `dealers`); pattern `DLR-[0-9]{5}` |
| `agent_id` | string | yes | – | Servicing agent identifier (synthetic) |
| `sentiment_score` | double | yes | – | Sentiment classifier output (-1.0 to 1.0) |
| `subject` | string | yes | 🔒 + drift | Subject summary (free-text; routinely contains PII) |
| `notes` | string | yes | 🔒 + drift | Free-text notes (capped to 4 KB; routinely contains PII) |
| `csat_score` | int | yes | – | Customer satisfaction (1–5) |
| `event_time` | timestamp | no | – | = `interaction_time` |
| `ingest_time` | timestamp | no | – | Loader write timestamp |

The two `pii_drift_target: true` free-text columns (`subject` /
`notes`) are the canonical fields for `bad_pii` edge-case injection
per Fix Group C in
[`tasks.md`](../../../.kiro/specs/2026-05-28-adp-ev-startup-foundation/tasks.md).

## Partition keys

- **Partition**: `interaction_date` (literal `date` column, daily
  grain).
- **Bucketing**: `bucket(16, customer_id)` per the schema's
  `bucketing:` block. Frequently-querying-by-customer use cases
  (`WHERE customer_id = '…'`) benefit from the bucket prune.
- **Pruning**: filter on `interaction_date` (Iceberg hidden-partition
  prune) AND optionally on `interaction_time` for sub-day windowing
  — see [data-contracts → Iceberg partition conventions](../../../../docs/data-contracts.md#iceberg-partition-conventions).

## Sample queries

Channel-mix of charging-related contacts in May 2026 and resolution
rates:

```sql
SELECT channel,
       COUNT(*)                                            AS contacts,
       SUM(CASE WHEN outcome = 'resolved'  THEN 1 ELSE 0 END) AS resolved,
       SUM(CASE WHEN outcome = 'escalated' THEN 1 ELSE 0 END) AS escalated,
       AVG(sentiment_score)                                AS avg_sentiment,
       AVG(csat_score)                                     AS avg_csat
FROM   adp_staging_customer_interactions.customer_interactions
WHERE  interaction_date BETWEEN DATE '2026-05-01' AND DATE '2026-05-29'
  AND  channel IN ('mobile_app_charging_issue', 'call_center', 'service_center')
GROUP BY channel
ORDER BY contacts DESC;
```

OTA-notification volume after recent campaigns:

```sql
SELECT DATE_TRUNC('week', interaction_date) AS week,
       COUNT(*)                              AS notifications,
       AVG(sentiment_score)                  AS avg_sentiment
FROM   adp_staging_customer_interactions.customer_interactions
WHERE  interaction_date >= DATE '2026-04-29'
  AND  channel = 'ota_update_notification'
GROUP BY DATE_TRUNC('week', interaction_date)
ORDER BY week;
```

Cross-product diagnoses (`customer × service × charging` complaint
correlation) live in
[`docs/cvx-integration-contract.md` § 4.3](../../../../docs/cvx-integration-contract.md)
and the standalone files under
[`platform-foundation/source/athena-queries/`](../../athena-queries/).

## Lineage

- **Inputs**:
  - `customers` dimension (5M, FK on every row).
  - `vins` dimension (5M, ~60% populated as optional VIN context).
  - `dealers` dimension (200, ~30% populated).
- **Producer**: [`generator.py`](generator.py) (pandas tier per the
  `decisions.md` "pandas-full, Spark-sample" entry; the spec catalog
  classifies this as PySpark on Glue but the v1 implementation is
  pandas with a deferred Spark port that doesn't change the schema).
  Runs from the master `make seed STAGE=...` target.
- **Consumers (cross-links via shared dimensions)**:
  - [`customer_360`](../customer_360/README.md) — same `customers`
    dimension; this product's interaction volume feeds the `health_score`
    composite there.
  - [`service_records`](../service_records/README.md) — same
    `customers` + `dealers` dimensions; a service appointment
    typically generates a corresponding interaction row (temporal
    consistency, no precomputed link — join on demand).
  - [`charging_sessions`](../charging_sessions/README.md) — same
    `customers`; `mobile_app_charging_issue` rows correlate with
    `interrupted = true` charging sessions on the same customer.
  - [`ota_campaigns`](../ota_campaigns/README.md) —
    `ota_update_notification` channel rows correlate with OTA
    dispatch activity; same `vins` dimension via the optional `vin`
    column.
  - [`vehicle_telemetry_aggregated`](../vehicle_telemetry_aggregated/README.md)
    — same `vins` dimension (via optional `vin` column).
- **Lineage trace**: `SELECT * FROM
  adp_staging_customer_interactions."customer_interactions$snapshots"
  ORDER BY committed_at DESC LIMIT 5`. See
  [`cvx-integration-contract.md` § 6](../../../../docs/cvx-integration-contract.md).

## Data-quality summary

- **Row count**: 50M over 10 years at `--scale 1.0` (~5 min wall
  clock per the source docstring); subset by `--scale` for dev runs.
- **Channel mix** (probability-weighted; matches spec Accept):
  `dealer` 15%, `service_center` 10%, `website` 20%, `mobile_app` 18%,
  `call_center` 7%, **`mobile_app_charging_issue` 8%**,
  **`ota_update_notification` 10%**, `chatbot` 7%, `email` 5%. The
  two EV-startup-relevant channels are present and weighted ≥7% each.
- **Time spread**: Beta(2, 5) recency-skewed over the 10-year window;
  more interactions in the last 12 months than the first 12 months.
- **Edge-case injection** (1–3% per-product band per the six-code
  taxonomy in [`docs/tech.md`](../../../../docs/tech.md)):
  - `missing_required` 0.75% on edge_case_eligible columns
  - `late_arrival` 0.50%
  - `schema_drift` 0.35% (`DRIFT-` prefix on enum columns)
  - `bad_pii` 0.20% on `subject` / `notes` (NEVER `customer_id` or
    `vin`; the `pii_drift_target` flag excludes FK columns)
  - `outlier_value` 0.40% on `duration_seconds`, `csat_score`,
    `sentiment_score`
  - `orphan_fk` 0.00% (counter-example)
- **FK closure**: `customer_id` 100%; `vin` and `dealer_id` 100% on
  populated rows. Verified by
  `tests/test_referential_integrity.py::test_zero_orphan_*`.
- **Outcome mix**: `resolved` 65% / `escalated` 10% / `abandoned` 5% /
  `in_progress` 10% / `scheduled` 10`.
- **Profiling**: `quality-reports/customer_interactions/profile.{json,md}`
  generated by [`scripts/profile-data.py`](../../../scripts/profile-data.py)
  and surfaced on the CloudWatch dashboard
  `adp-{stage}-foundation-data-quality`.

## See also

- Schema-of-record: [`schema.yaml`](schema.yaml)
- Producer: [`generator.py`](generator.py) (pandas; Spark port
  deferred to Group 6 per `decisions.md`)
- Integration contract: [`docs/cvx-integration-contract.md` § 3.7](../../../../docs/cvx-integration-contract.md)
- Column formats: [`docs/data-contracts.md`](../../../../docs/data-contracts.md)
