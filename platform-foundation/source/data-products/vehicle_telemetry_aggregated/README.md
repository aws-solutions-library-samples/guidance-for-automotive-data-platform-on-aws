# Vehicle Telemetry — Aggregated (`vehicle_telemetry_aggregated`)

> **Domain**: Automotive &nbsp;·&nbsp; **Storage**: Iceberg
> (PySpark on Glue 5.1) &nbsp;·&nbsp; **Display name**:
> `Vehicle Telemetry (Aggregated)`
>
> **Status**: ✅ **Shipped 2026-06-11** at sample tier (10M rows /
> 90 days) via spec
> [`2026-06-09-adp-pyspark-glue-products`](../../../../.kiro/specs/2026-06-09-adp-pyspark-glue-products/).
> See [`docs/DEPLOYMENT.md` § PySpark generators](../../../../docs/DEPLOYMENT.md)
> for the deploy command and `docs/tech.md` § "ADP PySpark via Glue 5.1"
> for run results. Production-scale upgrade is a P3 follow-up; the same
> orchestration script runs at production scale via `--rows 100000000`
> with proportional worker scaling.

Per-VIN-per-time-window rollup of VSS-aligned telemetry signals — speed,
SoC, motor, GPS, environment. **Not raw 1 Hz signals** (that's CMS's
domain); this is the analytics-tier rollup an EV startup publishes
into the data lake. Producer is [`generator.py`](generator.py)
(Glue 5.1 PySpark on Spark 3.5.6 + Python 3.11, 90-day rolling
window). Column names align with the VSS subset in
[`docs/data-contracts.md`](../../../../docs/data-contracts.md).

## Schema

| Column | Type | Nullable | PII | Description |
|---|---|---|---|---|
| `vin` | string | no | – | FK → [`vins`](#lineage); regex per [data-contracts](../../../../docs/data-contracts.md#identifier-formats) |
| `event_date` | date | no | – | UTC calendar day. **Partition key** |
| `event_time` | timestamp | no | – | Source-truth event time (UTC microsecond) |
| `ingest_time` | timestamp | no | – | Loader write timestamp |
| `speed_kmh` / `avg_speed_kmh` | double | yes | – | VSS `Vehicle.Speed` / `.AverageSpeed` (km/h) |
| `total_miles_driven` | double | yes | – | VSS `Vehicle.TraveledDistance` (US `_mi` deviation) |
| `start_soc_pct` / `end_soc_pct` | double | yes | – | VSS `.StateOfCharge.Current` at window boundaries (0–100) |
| `state_of_health_pct` | double | yes | – | VSS `.StateOfHealth` (0–100) |
| `battery_pack_temp_avg_c` / `ambient_temp_avg_c` / `cabin_temp_c` | double | yes | – | VSS temperature signals (°C) |
| `motor_rpm` / `motor_torque_nm` / `motor_power_kw` / `motor_temp_c` | double | yes | – | VSS `.ElectricMotor.*` signals |
| `range_estimate_start_mi` / `_end_mi` | double | yes | – | VSS `.Range` at boundaries (US `_mi` deviation) |
| `is_charging` | boolean | no | – | VSS `.IsCharging` |
| `avg_power_kw` | double | yes | – | VSS `.ChargeRate` average (kW) |
| `latitude` / `longitude` | double | yes | 🔒 | VSS `.CurrentLocation.*` (degrees) |
| `heading_deg` | double | yes | – | VSS `.Heading` (0–360) |
| `drive_type` | string | yes | – | enum: `awd` / `fwd` / `rwd` |
| `powertrain_type` | string | yes | – | enum: `electric` / `hybrid` / `erev` |
| `vss_version` | string | no | – | VSS catalog version (e.g. `"6.0"`) |

VSS path → ADP column mapping is authoritative in
[`docs/data-contracts.md` → VSS vocabulary subset](../../../../docs/data-contracts.md#vss-vocabulary-subset).

## Partition keys

- **Partition**: `event_date` (literal `date` column, daily grain).
- **Bucketing**: `bucket(16, vin)` per the schema's `bucketing:` block.
  PySpark 3.5+ uses `F.bucket(16, "vin")`; PySpark 3.3 (Glue 4.0
  classpath) falls back to `F.expr("bucket(16, vin)")` — the generator
  detects and resolves both paths.
- **Pruning**: filter on `event_date` (Iceberg hidden-partition
  prune) AND optionally on `event_time` for sub-day windowing — see
  [data-contracts → Iceberg partition conventions](../../../../docs/data-contracts.md#iceberg-partition-conventions).

## Sample queries

Top-10 hottest battery-pack VINs over the last 7 days, drive segments
only:

```sql
SELECT vin,
       AVG(battery_pack_temp_avg_c) AS avg_pack_temp_c,
       MAX(battery_pack_temp_avg_c) AS peak_pack_temp_c,
       COUNT(*)                     AS samples
FROM   adp_staging_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated
WHERE  event_date BETWEEN DATE '2026-05-22' AND DATE '2026-05-29'
  AND  event_time BETWEEN TIMESTAMP '2026-05-22 00:00:00' AND TIMESTAMP '2026-05-29 00:00:00'
  AND  is_charging = false
  AND  battery_pack_temp_avg_c IS NOT NULL
GROUP BY vin
ORDER BY peak_pack_temp_c DESC
LIMIT 10;
```

VSS-version drift surveillance — fleet rows by `vss_version`:

```sql
SELECT vss_version,
       COUNT(DISTINCT vin) AS vins,
       COUNT(*)            AS rows,
       MIN(event_date)     AS first_seen,
       MAX(event_date)     AS last_seen
FROM   adp_staging_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated
WHERE  event_date >= DATE '2026-04-29'
GROUP BY vss_version
ORDER BY rows DESC;
```

Cross-product diagnostics (hot-pack alerts joined with `service_records`
visits, predictive-maintenance feature joins) live in
[`docs/cvx-integration-contract.md` § 4](../../../../docs/cvx-integration-contract.md)
and the predictive-maintenance reference notebook under
[`platform-foundation/source/reference-consumers/`](../../reference-consumers/).

## Lineage

- **Inputs**:
  - `vins` dimension (5M, sampled with replacement; default 100K-VIN
    pool gives ~100 rows/VIN over 90 days).
- **Producer**: [`generator.py`](generator.py) — Glue 4.0 PySpark job
  (Spark 3.3, Python 3.10). Sample-tier (10M rows / 90 days);
  full 100M-row production scale runs from the master `make seed`
  per `decisions.md` "pandas-full, Spark-sample" entry.
- **Consumers (cross-links via shared dimensions)**:
  - [`vehicle_identity`](../vehicle_identity/README.md) — same `vins`;
    supplies the per-VIN battery / motor / connector covariates.
  - [`energy_usage`](../energy_usage/README.md) — same `vins`; this
    product's per-window rollup feeds `energy_usage`'s daily grain.
  - [`charging_sessions`](../charging_sessions/README.md) — same
    `vins`; `is_charging = true` rows here align with charging
    sessions on the same VIN/window.
  - [`ota_campaigns`](../ota_campaigns/README.md) — same `vins`;
    per-VIN `current_software_version` step-function visible after
    `install_completed_time`.
  - [`service_records`](../service_records/README.md) — same `vins`;
    `dtc_codes` captured at intake correlate with telemetry anomalies
    (hot pack, overspeed motor, low SoH).
- **Lineage trace**: `SELECT * FROM
  adp_staging_vehicle_telemetry_aggregated."vehicle_telemetry_aggregated$snapshots"
  ORDER BY committed_at DESC LIMIT 5`. See
  [`cvx-integration-contract.md` § 6](../../../../docs/cvx-integration-contract.md).

## Data-quality summary

- **Row count**: 10M sample / 100M production. The Athena
  `SELECT COUNT(*)` 100M ± 1M assertion runs against the master
  `seed` production re-run, not the v1 sample-tier.
- **Aggregation grain**: per-VIN-per-time-window rollup
  (~hourly density via `rows / vin_pool` over 90 days = ~100
  rows/VIN), NOT raw 1 Hz signals.
- **Edge-case injection** (1–3% per-product band per the six-code
  taxonomy in [`docs/tech.md`](../../../../docs/tech.md)):
  - `missing_required` 0.75% on numeric edge_case_eligible columns
  - `late_arrival` 0.50% (`ingest_time = event_time + 2 days`)
  - `schema_drift` 0.35% (`DRIFT-` prefix on `drive_type` /
    `powertrain_type`)
  - `bad_pii` is a **structural zero** — telemetry has no
    `pii_drift_target` column (`vin` is FK and never corrupted; see
    Fix Group C in
    [`tasks.md`](../../../.kiro/specs/2026-05-28-adp-ev-startup-foundation/tasks.md))
  - `outlier_value` 0.40% (5–10× declared range on edge_case_eligible
    columns, e.g. `range_estimate_*_mi`)
  - `orphan_fk` 0.00% (counter-example, never injected)
- **Distribution shape**: SoH declines linearly 95% → 90% across the
  90-day window; ambient + battery-pack temps follow seasonal
  sinusoids; speed gaussian; `motor_power = T × ω / 9550` (physics);
  GPS NULL on ~60% of rows (privacy: home rows have no GPS).
- **Powertrain weighting**: `electric` 85% / `hybrid` 10% / `erev` 5%
  — matches the EV-startup narrative.
- **FK closure**: `vin` 100% (FK-by-construction via Spark
  broadcast-join against the `vins` dimension parquet).
- **Profiling**: `quality-reports/vehicle_telemetry_aggregated/profile.{json,md}`
  generated by [`scripts/profile-data.py`](../../../scripts/profile-data.py)
  and surfaced on the CloudWatch dashboard
  `adp-{stage}-foundation-data-quality`.

## Contract

**Provenance**: `single-vintage`

This product produces one partition per seed run and overwrites the previous partition on re-generation. The lake publishes each generation's output additively to the curated directory. For operator details on publishing behavior and single-vintage handling (including the optional `` `--allow-purge` `` flag for multi-partition cleanup), see [`docs/DEPLOYMENT.md` § "Publishing single-vintage products"](../../../../docs/DEPLOYMENT.md).

## See also

- Schema-of-record: [`schema.yaml`](schema.yaml)
- Producer: [`generator.py`](generator.py) (PySpark on Glue 4.0)
- Integration contract: [`docs/cvx-integration-contract.md` § 3.1](../../../../docs/cvx-integration-contract.md)
- Predictive-maintenance notebook: [`reference-consumers/predictive-maintenance/`](../../reference-consumers/predictive-maintenance/)
- Column formats: [`docs/data-contracts.md`](../../../../docs/data-contracts.md)
