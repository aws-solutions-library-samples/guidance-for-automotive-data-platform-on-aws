# Service Records (`service_records`)

> **Domain**: Service &nbsp;·&nbsp; **Storage**: Iceberg
> &nbsp;·&nbsp; **Display name**: `Service Records`

Per-event log of every service appointment — scheduled maintenance,
warranty repair, safety / software recall, body repair, tire,
charging-system, battery replacement, HV-battery diagnostic, software
update. EV-relevant service types are weighted ~15% combined to
match real EV-startup service-bay traffic. Producer is
[`generator.py`](generator.py) (pandas tier); column formats follow
[`docs/data-contracts.md`](../../../../docs/data-contracts.md).

## Schema

| Column | Type | Nullable | PII | Description |
|---|---|---|---|---|
| `service_id` | string | no | – | Unique service event identifier (PK) |
| `service_date` | date | no | – | Service event date |
| `service_month` | date | no | – | First-of-month derived from `service_date`. **Partition key** (monthly grain) |
| `vin` | string | no | – | FK → `vins`; regex per [data-contracts](../../../../docs/data-contracts.md#identifier-formats) |
| `customer_id` | string | yes | 🔒 | FK → `customers`; null on warranty / recall services without a customer record |
| `dealer_id` | string | no | – | FK → `dealers`; pattern `DLR-[0-9]{5}` |
| `service_type` | string | no | – | enum: `scheduled_maintenance` / `warranty_repair` / `safety_recall` / `software_recall` / `body_repair` / `tire_service` / `charging_system` / `battery_replacement` / `hv_battery_diagnostic` / `software_update` |
| `complaint_text` | string | yes | 🔒 + drift | Customer-reported complaint (free-text; routinely contains PII) |
| `dtc_codes` | array&lt;string&gt; | yes | – | DTC codes captured at intake (e.g. `['P0AA6', 'P1A0F']`) |
| `parts_used` | array&lt;string&gt; | yes | – | List of `part_number`s replaced |
| `labor_hours` | double | yes | – | Total labor billed (0–80) |
| `total_cost_usd` | decimal(12,2) | yes | – | Total invoice; null if covered by warranty |
| `warranty_covered` | boolean | no | – | True if covered by manufacturer warranty |
| `technician_id` | string | yes | – | Servicing technician identifier (synthetic) |
| `outcome` | string | no | – | enum: `resolved` / `parts_pending` / `follow_up_required` / `lemon_law_buyback` |
| `csat_score` | int | yes | – | Customer satisfaction (1–5) |
| `linked_interaction_id` | string | yes | – | Optional link to `customer_interactions.interaction_id` |
| `linked_campaign_id` | string | yes | – | Optional link to `ota_campaigns.campaign_id` (for `software_recall` rows) |
| `event_time` | timestamp | no | – | Source-truth event time (= `service_date 00:00 UTC`) |
| `ingest_time` | timestamp | no | – | Loader write timestamp |

The `pii_drift_target: true` free-text column (`complaint_text`)
is the canonical field for `bad_pii` edge-case injection per Fix
Group C in
[`tasks.md`](../../../.kiro/specs/2026-05-28-adp-ev-startup-foundation/tasks.md).

## Partition keys

- **Partition**: `service_month` (literal `date` column derived as
  first-of-month from `service_date`). 10-year window × 12 = 120
  partitions at full scale — long-tail monthly grain per
  [data-contracts → Iceberg partition conventions](../../../../docs/data-contracts.md#iceberg-partition-conventions).
- **No bucketing**: monthly grain × ~83K rows/partition is naturally
  well-shaped.
- **Pruning**: filter on `service_month` (Iceberg hidden-partition
  prune; first-of-month literals only) AND optionally on
  `service_date` for intra-month windowing.

## Sample queries

Top DTC codes seen on `charging_system` services in the trailing
12 months:

```sql
SELECT dtc_code,
       COUNT(*)            AS service_visits,
       AVG(labor_hours)    AS avg_labor_hours,
       AVG(total_cost_usd) AS avg_cost_usd
FROM   adp_staging_service_records.service_records
CROSS JOIN UNNEST(dtc_codes) AS t(dtc_code)
WHERE  service_month >= DATE '2025-05-01'
  AND  service_type  = 'charging_system'
  AND  service_date >= DATE '2025-05-29'
GROUP BY dtc_code
ORDER BY service_visits DESC
LIMIT 20;
```

Battery-replacement rate by model year cohort:

```sql
SELECT vi.model_year,
       COUNT(DISTINCT sr.vin)                            AS vins_with_replacement,
       100.0 * COUNT(DISTINCT sr.vin) / COUNT(DISTINCT vi.vin) AS pct_of_cohort
FROM   adp_staging_vehicle_identity.vehicle_identity vi
LEFT JOIN adp_staging_service_records.service_records sr
       ON  sr.vin = vi.vin
       AND sr.service_type = 'battery_replacement'
       AND sr.service_month >= DATE '2025-05-01'
GROUP BY vi.model_year
ORDER BY vi.model_year;
```

Cross-product diagnoses (`customer × service × charging` complaint
correlation, OTA-recall ↔ service linkage) live in
[`docs/cvx-integration-contract.md` § 4](../../../../docs/cvx-integration-contract.md)
and the standalone files under
[`platform-foundation/source/athena-queries/`](../../athena-queries/).

## Lineage

- **Inputs**:
  - `vins` dimension (5M, FK on every row).
  - `customers` dimension (5M, ~90% populated).
  - `dealers` dimension (200, FK on every row).
  - `parts` dimension (50K, referenced via the `parts_used`
    `array<string>` column).
- **Producer**: [`generator.py`](generator.py) (pandas, sets
  `extra_dimensions = ("parts",)` so the base class loads parts in
  addition to the default dimensions). Runs from the master
  `make seed STAGE=...` target.
- **Consumers (cross-links via shared dimensions)**:
  - [`customer_360`](../customer_360/README.md) — same `customers`
    dimension; service-visit volume feeds the `health_score`
    composite there.
  - [`customer_interactions`](../customer_interactions/README.md) —
    same `customers` + `dealers`; temporally consistent (a service
    appointment generates a corresponding interaction row);
    `linked_interaction_id` is the optional explicit FK.
  - [`vehicle_identity`](../vehicle_identity/README.md) — same `vins`;
    supplies the per-VIN profile (model, model_year, powertrain) for
    cohort analysis.
  - [`charging_sessions`](../charging_sessions/README.md) — same
    `vins`; `service_type IN ('charging_system','hv_battery_diagnostic')`
    visits often follow elevated session-abort rates.
  - [`ota_campaigns`](../ota_campaigns/README.md) — `linked_campaign_id`
    structurally references `ota_campaigns.campaign_id` for
    `software_recall` rows (FK enforced by Fix-Group-B
    `test_zero_orphan_campaign_ids_in_events`-class integrity check
    on `linked_campaign_id`).
  - [`vehicle_telemetry_aggregated`](../vehicle_telemetry_aggregated/README.md)
    — same `vins`; `dtc_codes` captured at intake correlate with
    telemetry anomalies preceding the visit.
- **Lineage trace**: `SELECT * FROM
  adp_staging_service_records."service_records$snapshots"
  ORDER BY committed_at DESC LIMIT 5`. See
  [`cvx-integration-contract.md` § 6](../../../../docs/cvx-integration-contract.md).

## Data-quality summary

- **Row count**: 10M over 10 years; subset by `--scale` for dev runs.
  Beta(2, 4) recency-skewed time spread.
- **Service-type mix** (probability-weighted):
  `scheduled_maintenance` 30%, `warranty_repair` 15%,
  `safety_recall` 5%, `software_recall` 10% (links a campaign via
  `linked_campaign_id`), `body_repair` 5%, `tire_service` 10%,
  `charging_system` 5%, `battery_replacement` 2%,
  `hv_battery_diagnostic` 8%, `software_update` 10%. EV-relevant
  service types weighted ~15% combined.
- **Complaint-text shape**: 70% populated from a 10-template pool with
  EV-flavored failures (range loss, charging-port engagement, regen
  braking inconsistency, thermal warning, OTA install failure,
  drive-unit grinding, …). 30% NULL.
- **DTC codes**: `array<string>` with 0–3 codes per row sampled from
  a 13-code DTC pool (P / U / B / C families).
- **Edge-case injection** (1–3% per-product band per the six-code
  taxonomy in [`docs/tech.md`](../../../../docs/tech.md)). Smoke
  run reported aggregate **2.10%** (within target):
  - `missing_required` 0.75%
  - `late_arrival` 0.50%
  - `schema_drift` 0.35%
  - `bad_pii` 0.20% on `complaint_text` (NEVER FK columns)
  - `outlier_value` 0.40% on `csat_score` etc.
  - `orphan_fk` 0.00% (counter-example)
- **FK closure**: `vin` 100%; `customer_id` 90% (10% null per
  the warranty / recall narrative); `dealer_id` 100`. Verified
  by `tests/test_referential_integrity.py::test_zero_orphan_*`.
- **Profiling**: `quality-reports/service_records/profile.{json,md}`
  generated by [`scripts/profile-data.py`](../../../scripts/profile-data.py)
  and surfaced on the CloudWatch dashboard
  `adp-{stage}-foundation-data-quality`.

## See also

- Schema-of-record: [`schema.yaml`](schema.yaml)
- Producer: [`generator.py`](generator.py)
- Integration contract: [`docs/cvx-integration-contract.md` § 3.8](../../../../docs/cvx-integration-contract.md)
- Column formats: [`docs/data-contracts.md`](../../../../docs/data-contracts.md)
