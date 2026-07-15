# Energy Usage (`energy_usage`)

> **Domain**: EV-Operations &nbsp;·&nbsp; **Storage**: Iceberg
> (PySpark on Glue 5.1) &nbsp;·&nbsp; **Display name**: `Energy Usage`
> &nbsp;·&nbsp; **Net-new in v1**
>
> **Status**: ✅ **Shipped 2026-06-11** at sample tier (10M rows /
> 90 days) via spec
> [`2026-06-09-adp-pyspark-glue-products`](../../../../.kiro/specs/2026-06-09-adp-pyspark-glue-products/).
> See [`docs/DEPLOYMENT.md` § PySpark generators](../../../../docs/DEPLOYMENT.md)
> for the deploy command and `docs/tech.md` § "ADP PySpark via Glue 5.1"
> for run results. Production-scale upgrade (450M rows) is a P3
> follow-up; the same orchestration script handles it via `--rows
> 450000000` with proportional worker scaling.

Daily per-VIN rollup of energy consumed, energy charged, regen
recovered, and the temperature / battery-health signals that explain
efficiency drift. Producer is
[`generator.py`](generator.py) (Glue 5.1 PySpark on Spark 3.5.6 +
Python 3.11, 90-day rolling window); column formats follow
[`docs/data-contracts.md`](../../../../docs/data-contracts.md).

## Schema

| Column | Type | Nullable | Description |
|---|---|---|---|
| `vin` | string | no | FK → [`vins`](#lineage); regex per [data-contracts](../../../../docs/data-contracts.md#identifier-formats) |
| `usage_date` | date | no | Local-day rollup. **Partition key** |
| `start_soc_pct` / `end_soc_pct` | double | no | SoC at 00:00 / 23:59 local (0–100) |
| `min_soc_pct` / `max_soc_pct` / `avg_soc_pct` | double | no | Daily SoC envelope |
| `total_kwh_consumed` | double | no | Drive consumption (0–200 kWh) |
| `total_kwh_charged` | double | no | Reconciles to `SUM(charging_sessions.kwh_delivered)` for the VIN/day |
| `regen_kwh_recovered` | double | no | Energy recovered via regen braking (0–50 kWh) |
| `total_miles_driven` | double | no | US `_mi` deviation per data-contracts |
| `efficiency_kwh_per_100mi` | double | no | Derived: `total_kwh_consumed / total_miles_driven * 100` (10–100) |
| `range_estimate_start_mi` / `_end_mi` | double | yes | Vehicle-reported range estimates |
| `battery_pack_temp_avg_c` | double | yes | Daily mean pack temperature (°C; VSS row 12) |
| `ambient_temp_avg_c` | double | yes | Daily mean ambient (°C; VSS row 32) |
| `state_of_health_pct` | double | yes | Battery SoH (50–100); declines slowly per the narratives below |
| `battery_age_days` | int | no | Days since `vehicle_identity.manufacture_date` (0–7300) |
| `event_time` | timestamp | no | End-of-day timestamp (UTC) |
| `ingest_time` | timestamp | no | Loader write timestamp |

VSS column → ADP column mapping is authoritative in
[`docs/data-contracts.md` → VSS vocabulary subset](../../../../docs/data-contracts.md#vss-vocabulary-subset).

## Partition keys

- **Partition**: `usage_date` (literal `date` column, daily grain).
- **No bucketing**: daily grain × 5M VINs gives natural file-size shape;
  the schema deliberately omits a `bucketing:` block.
- **Pruning**: filter on `usage_date`. The grain is one row per
  `(vin, usage_date)` (PK), so most queries also predicate on `vin`.

## Sample queries

Fleet-average efficiency by week, last 90 days, with seasonality
side-output:

```sql
SELECT DATE_TRUNC('week', usage_date)              AS week,
       COUNT(DISTINCT vin)                         AS active_vins,
       AVG(efficiency_kwh_per_100mi)               AS avg_eff_kwh_per_100mi,
       AVG(ambient_temp_avg_c)                     AS avg_ambient_c,
       SUM(total_kwh_consumed)                     AS total_kwh_consumed,
       SUM(total_miles_driven)                     AS total_miles_driven
FROM   adp_staging_energy_usage.energy_usage
WHERE  usage_date BETWEEN DATE '2026-02-28' AND DATE '2026-05-29'
GROUP BY DATE_TRUNC('week', usage_date)
ORDER BY week;
```

State-of-health decline by battery age cohort:

```sql
SELECT FLOOR(battery_age_days / 365)               AS age_years,
       COUNT(DISTINCT vin)                         AS vins,
       AVG(state_of_health_pct)                    AS avg_soh_pct,
       APPROX_PERCENTILE(state_of_health_pct, 0.10) AS p10_soh_pct,
       APPROX_PERCENTILE(state_of_health_pct, 0.50) AS p50_soh_pct
FROM   adp_staging_energy_usage.energy_usage
WHERE  usage_date >= DATE '2026-04-29'
GROUP BY FLOOR(battery_age_days / 365)
ORDER BY age_years;
```

Cross-product joins (`VIN × OTA × energy` pre/post efficiency delta,
`customer × charging × energy` cost diagnosis) live in
[`docs/cvx-integration-contract.md` § 4](../../../../docs/cvx-integration-contract.md)
and the standalone Athena queries under
[`platform-foundation/source/athena-queries/`](../../athena-queries/).

## Lineage

- **Inputs**:
  - `vins` dimension (5M, 1:1).
  - `vehicle_identity` (for `manufacture_date` → `battery_age_days`
    derivation; in v1 the generator computes `battery_age_days`
    inline via deterministic per-VIN seeds — full denormalization
    lands in Group 6).
- **Producer**: [`generator.py`](generator.py) — Glue 4.0 PySpark job
  (Spark 3.3, Python 3.10). Sample-tier (10M rows / 90 days);
  full 450M-row production scale runs from the master `make seed`
  per `decisions.md` "pandas-full, Spark-sample" entry.
- **Consumers (cross-links via shared dimensions / reconciliation)**:
  - [`vehicle_identity`](../vehicle_identity/README.md) — same `vins`
    dimension; supplies battery chemistry / capacity that explains
    efficiency.
  - [`charging_sessions`](../charging_sessions/README.md) — same `vins`;
    `total_kwh_charged` here MUST reconcile to `SUM(kwh_delivered)` per
    `(vin, usage_date)`.
  - [`vehicle_telemetry_aggregated`](../vehicle_telemetry_aggregated/README.md)
    — same `vins`; the per-window telemetry rolls up to this product's
    daily grain.
  - [`ota_campaigns`](../ota_campaigns/README.md) — same `vins` (via
    `ota_campaign_events`); the post-OTA efficiency drift narrative
    below joins this product to OTA install timing.
- **Lineage trace**: `SELECT * FROM
  adp_staging_energy_usage."energy_usage$snapshots"
  ORDER BY committed_at DESC LIMIT 5`. See
  [`cvx-integration-contract.md` § 6](../../../../docs/cvx-integration-contract.md).

## Realistic narratives

Distribution choices in [`generator.py`](generator.py) are designed so
that the EV-startup analytics stories the spec PRD calls out — battery
aging, winter range loss, post-OTA efficiency improvement — are visible
in 90-day samples.

- **Battery age × SoH correlation (~2 pp / year decline)**: SoH drops
  linearly with `battery_age_days`. A new battery sits at ~100%; a
  7-year-old battery sits at ~86%. Matches Li-ion calendar-aging
  literature. `battery_age_days` is deterministic per VIN — vehicles in
  the 100K-VIN sample pool span 0–7 years (0–2555 days) of age,
  distributed uniformly so SoH correlations are visible at scale.
- **Seasonality (winter range loss ~30%)**: `ambient_temp_avg_c`
  follows a yearly sinusoid (winter cold, summer warm; baseline 12 °C,
  amplitude 18 °C, ±3 °C noise). Cold-weather rows
  (`ambient < 5 °C`) carry a `_cold_penalty ∈ [1.00, 1.30]` applied to
  `efficiency_kwh_per_100mi`; `range_estimate_start_mi` / `_end_mi`
  divide by the same penalty (kWh consumed up → range estimate down).
  `battery_pack_temp_avg_c` lags ambient by ~5 °C (thermal mass).
- **Post-OTA efficiency drift**: ~10% of VINs (deterministic by
  `vin_idx % 10 == 0`) carry a 3–5% efficiency improvement, visible as
  a step-function in the OTA-correlated subset when joined with
  [`ota_campaigns`](../ota_campaigns/README.md).
- **SoC envelope**: `start_soc_pct ∈ [40, 95]` gaussian-ish;
  `end_soc_pct` derived from start ± (consumption / charge) × 100 / 75 kWh
  battery; `min` / `max` / `avg_soc_pct` derived with mild noise.
- **Charge volume**: ~70% home L2 days contribute 20–60 kWh, ~10%
  public DC fast days contribute 30–80 kWh, ~20% no-charge days.
  `regen_kwh_recovered` ≈ 5–10% of consumption, matching observed
  EV regen yield.

## Data-quality summary

- **Row count**: ~10M sample / ~450M production (5M VINs × 90 days ×
  ~70% active days). The Athena `SELECT COUNT(*)` 450M ± 4.5M assertion
  runs against the master `seed` production re-run, not the v1
  sample-tier.
- **Edge-case injection** (1–3% per-product band per the six-code
  taxonomy in [`docs/tech.md`](../../../../docs/tech.md)):
  - `missing_required` 0.75% on edge_case_eligible numeric columns
  - `late_arrival` 0.50% (`ingest_time = event_time + 2 days`)
  - `schema_drift` 0.35% — applied as NULLing
    `efficiency_kwh_per_100mi` (the only drift target on this purely
    numeric product; matches the not-null contract break)
  - `bad_pii` is a **structural zero** here — `energy_usage` declares
    no `pii_drift_target` column (the only potentially-PII column is
    `vin`, which is FK and therefore never corrupted; see Fix Group C
    in [`tasks.md`](../../../.kiro/specs/2026-05-28-adp-ev-startup-foundation/tasks.md))
  - `outlier_value` 0.40% (5–10× of declared range on edge_case_eligible
    columns)
  - `orphan_fk` 0.00% (counter-example, never injected)
- **FK closure**: `vin` 100% (FK-by-construction — the generator samples
  `vin` from the `vins` dimension via Spark broadcast-join).
  Verified by `tests/test_referential_integrity.py::test_zero_orphan_vins`.
- **Cross-product reconciliation**: `total_kwh_charged` per
  `(vin, usage_date)` ≈ `SUM(charging_sessions.kwh_delivered)` per
  `(vin, session_date)` within ±5%.
- **Profiling**: `quality-reports/energy_usage/profile.{json,md}`
  generated by [`scripts/profile-data.py`](../../../scripts/profile-data.py)
  and surfaced on the CloudWatch dashboard
  `adp-{stage}-foundation-data-quality`.

## See also

- Schema-of-record: [`schema.yaml`](schema.yaml)
- Producer: [`generator.py`](generator.py) (PySpark on Glue 4.0)
- Sibling EV-Ops products:
  [`charging_sessions`](../charging_sessions/README.md) ·
  [`ota_campaigns`](../ota_campaigns/README.md)
- Integration contract: [`docs/cvx-integration-contract.md` § 3.4](../../../../docs/cvx-integration-contract.md)
- Column formats: [`docs/data-contracts.md`](../../../../docs/data-contracts.md)
