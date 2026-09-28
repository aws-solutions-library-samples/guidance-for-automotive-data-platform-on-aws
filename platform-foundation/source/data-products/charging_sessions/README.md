# Charging Sessions (`charging_sessions`)

> **Domain**: EV-Operations &nbsp;·&nbsp; **Storage**: Iceberg &nbsp;·&nbsp;
> **Display name**: `Charging Sessions` &nbsp;·&nbsp; **Net-new in v1**

One row per completed (or interrupted) charging session — home L1/L2,
public DC fast, and destination L2 — joining vehicles, customers, and
the charging-station catalog. The narrative engine that drives the
distributions below lives in
[`generator.py`](generator.py); column formats follow
[`docs/data-contracts.md`](../../../../docs/data-contracts.md).

## Schema

| Column | Type | Nullable | PII | Description |
|---|---|---|---|---|
| `session_id` | string | no | – | UUIDv5 from `(vin, start_time)` (PK) |
| `vin` | string | no | – | FK → [`vins`](#lineage); regex per [data-contracts → Identifier formats](../../../../docs/data-contracts.md#identifier-formats) |
| `customer_id` | string | yes | 🔒 | FK → `customers`; null on guest charges |
| `session_date` | date | no | – | UTC calendar day of `start_time`. **Partition key** |
| `start_time` / `end_time` | timestamp | no | – | UTC microsecond session boundaries |
| `duration_seconds` | bigint | no | – | `end_time - start_time` |
| `station_id` | string | no | – | FK → `charging_stations`; pattern `STN-(TS\|EA\|EVGO\|CP\|HOME\|DEST)-[0-9]{8}` |
| `station_type` | string | no | – | enum: `home_l1` / `home_l2` / `public_dc_fast` / `destination_l2` |
| `network_provider` | string | yes | – | Tesla SC, Electrify America, EVgo, ChargePoint, … |
| `connector_type` | string | no | – | enum: `J1772` / `CCS1` / `NACS` / `CHAdeMO` |
| `start_soc_pct` / `end_soc_pct` | double | no | – | State of charge at session boundaries (0–100) |
| `kwh_delivered` | double | no | – | Energy delivered (0–250 kWh) |
| `peak_power_kw` / `avg_power_kw` | double | yes | – | Charging power (0–400 kW) |
| `cost_usd` | decimal(10,4) | yes | – | Total session cost; null for free home charging |
| `cost_per_kwh_usd` | decimal(10,6) | yes | – | Per-kWh rate paid |
| `latitude` / `longitude` | double | yes | 🔒 | Public-station GPS only; **null for home / destination** (privacy) |
| `interrupted` | boolean | no | – | `true` if session ended abnormally |
| `interrupt_reason` | string | yes | – | enum: `user_unplug` / `station_fault` / `vehicle_fault` / `network_drop` |
| `event_time` | timestamp | no | – | Source-truth event time (= `start_time`) |
| `ingest_time` | timestamp | no | – | Loader write timestamp |

Column units, ranges, and identifier regex are authoritative in
[`docs/data-contracts.md`](../../../../docs/data-contracts.md). The
schema-of-record is [`schema.yaml`](schema.yaml).

## Partition keys

- **Partition**: `session_date` (literal `date` column, daily grain).
- **Bucketing**: `bucket(16, vin)` per the schema's `bucketing:` block.
- **Pruning**: filter on `session_date` (Iceberg hidden-partition prune)
  AND optionally on `start_time` for sub-day windowing — see
  [data-contracts → Iceberg partition conventions](../../../../docs/data-contracts.md#iceberg-partition-conventions).

## Sample queries

Charging-network share of public DC-fast energy delivered, May 2026:

```sql
SELECT network_provider,
       COUNT(*)                AS sessions,
       SUM(kwh_delivered)      AS total_kwh,
       AVG(peak_power_kw)      AS avg_peak_kw,
       SUM(cost_usd)            AS total_revenue_usd
FROM   adp_staging_charging_sessions.charging_sessions
WHERE  session_date BETWEEN DATE '2026-05-01' AND DATE '2026-06-01'
  AND  start_time   BETWEEN TIMESTAMP '2026-05-01 00:00:00'
                        AND TIMESTAMP '2026-06-01 00:00:00'
  AND  station_type = 'public_dc_fast'
GROUP BY network_provider
ORDER BY total_kwh DESC;
```

Interruption rate by network provider over the trailing 30 days:

```sql
SELECT network_provider,
       COUNT(*)                                            AS sessions,
       SUM(CASE WHEN interrupted THEN 1 ELSE 0 END)        AS aborted,
       100.0 * SUM(CASE WHEN interrupted THEN 1 ELSE 0 END) / COUNT(*)
                                                           AS abort_rate_pct
FROM   adp_staging_charging_sessions.charging_sessions
WHERE  session_date >= DATE '2026-04-29'
  AND  station_type = 'public_dc_fast'
GROUP BY network_provider
ORDER BY abort_rate_pct DESC;
```

The full cross-product query catalog (charging × energy × customer
diagnosis, station-utilization rollups) lives in
[`docs/cvx-integration-contract.md` § 4](../../../../docs/cvx-integration-contract.md)
and the standalone files under
[`platform-foundation/source/athena-queries/`](../../athena-queries/).

## Lineage

- **Inputs**:
  - `vins` dimension (5M rows, 1:1 mapping); regenerated via
    [`platform-foundation/source/dimensions/generate_all.py`](../../dimensions/generate_all.py).
  - `customers` dimension (5M rows, ~10% null on public sessions).
  - `charging_stations` dimension (50K rows, distribution: Tesla SC ~10K,
    Electrify America ~10K, EVgo ~5K, ChargePoint ~5K, home/destination
    synthetic ~30K).
- **Producer**: [`generator.py`](generator.py), pandas tier; runs from
  the master `make seed STAGE=...` target.
- **Consumers (cross-links via shared dimensions)**:
  - [`vehicle_identity`](../vehicle_identity/README.md) — same `vins`
    dimension; provides the per-VIN battery + connector covariates that
    explain charging power.
  - [`energy_usage`](../energy_usage/README.md) — same `vins` dimension;
    `total_kwh_charged` per `(vin, usage_date)` MUST reconcile to
    `SUM(kwh_delivered)` for that VIN/day (see Constraints below).
  - [`customer_360`](../customer_360/README.md) — same `customers`
    dimension; `total_charging_sessions_30d` /
    `total_kwh_consumed_30d` derive from this product.
  - [`customer_interactions`](../customer_interactions/README.md) — same
    `customers` dimension; `mobile_app_charging_issue` channel rows
    typically correlate with `interrupted = true` here.
  - [`service_records`](../service_records/README.md) — same `customers`
    dimension; `service_type IN ('charging_system','hv_battery_diagnostic')`
    visits often follow elevated abort rates.
  - [`vehicle_telemetry_aggregated`](../vehicle_telemetry_aggregated/README.md)
    — same `vins` dimension; `is_charging = true` rows in telemetry
    overlap each session window.
- **Lineage trace**: `SELECT * FROM
  adp_staging_charging_sessions."charging_sessions$snapshots"
  ORDER BY committed_at DESC LIMIT 5`. See
  [`cvx-integration-contract.md` § 6](../../../../docs/cvx-integration-contract.md).

## Realistic narratives

Distribution choices in [`generator.py`](generator.py) reflect a
real-world EV-startup charging mix; flat `random.uniform` was rejected
because it produces noise that would break downstream profiling tests
([`tests/test_distribution_profile.py`](../../../tests/test_distribution_profile.py)).

- **Station-type mix (~70% home / 25% public DC fast / 5% destination L2)**:
  matches the broad consensus from EV-driver telemetry studies that the
  vast majority of sessions are slow overnight L2; public DC fast is the
  minority but dominates revenue and operational complexity. Hard-wired
  via the `type_choices` weights `home_l1` 14% + `home_l2` 56% +
  `public_dc_fast` 25% + `destination_l2` 5%.
- **Per-station-type duration / power / cost**:
  - DC fast: 15–60 min, 50–250 kW, ~$0.45/kWh (taper-compliant: peak
    power applies for the first ~30 min, then ramps down).
  - L2: 4–8 h, 7–11.5 kW, ~$0.13/kWh.
  - L1: 8–14 h (rare; almost always overnight emergency charging).
- **SoC envelope**: `start_soc_pct` U(10, 50) — drivers don't usually
  start charging at 80%; `end_soc_pct = start + U(20, 60)` clipped to
  100. The distribution centers around `delta ≈ 40 pp`, matching observed
  fleet behavior.
- **GPS privacy carve-out**: `latitude` / `longitude` are populated only
  for `station_type IN ('public_dc_fast', 'destination_l2')` — home
  sessions emit NULL by design. This matches the privacy convention in
  [`docs/data-contracts.md` → Time / privacy notes](../../../../docs/data-contracts.md).
- **Connector type derived from station prefix**: NACS for Tesla
  Superchargers (`STN-TS-*`), CCS1 for EA / EVgo (`STN-EA-*` / `STN-EVGO-*`),
  J1772 elsewhere — matches the actual physical connector landscape.
- **Interruption mix (4% aggregate)**: weighted reasons —
  `user_unplug` 55%, `station_fault` 20%, `vehicle_fault` 15%,
  `network_drop` 10%. User unplugs dominate; station faults are the
  primary public-DC-fast complaint vector and feed the
  `customer_interactions.mobile_app_charging_issue` channel.
- **Time spread**: Beta(2, 3) over a 3-year window — recency-skewed
  (more sessions in the last 6 months than the first 6 months) so
  trailing-30-day analytics see realistic density.

## Data-quality summary

- **Row count**: 20M sessions over 3 years (`SELECT COUNT(*) FROM
  adp_staging_charging_sessions.charging_sessions` returns 20M ± 200K
  per the spec Verify gate).
- **Edge-case injection** (1–3% per-product band per the six-code
  taxonomy in [`docs/tech.md` → Edge-Case Taxonomy](../../../../docs/tech.md));
  `manifest.json` carries `edge_case_aggregate_rate` per run:
  - `missing_required` 0.75% on numeric edge_case_eligible columns
  - `late_arrival` 0.50% (`ingest_time = event_time + 2 days`)
  - `schema_drift` 0.35% (`DRIFT-` prefix on enum columns)
  - `bad_pii` 0.20% on `pii_drift_target` columns (NEVER FK columns —
    see Fix Group C in
    [`tasks.md`](../../../.kiro/specs/2026-05-28-adp-ev-startup-foundation/tasks.md))
  - `outlier_value` 0.40% (5–10× of declared range on edge_case_eligible)
  - `orphan_fk` 0.00% (counter-example, never injected; `vin`,
    `customer_id`, `station_id` always resolve in their dimension)
- **FK closure**: `vin` and `station_id` 100%; `customer_id` ~90%
  (10% null on public sessions per the guest-charge narrative).
  Verified by `tests/test_referential_integrity.py::test_zero_orphan_*`.
- **Cross-product reconciliation**: `SUM(kwh_delivered)` per
  `(vin, session_date)` ≈ `energy_usage.total_kwh_charged` per
  `(vin, usage_date)` within ±5% (edge-case-injection tolerance).
- **Profiling**: `quality-reports/charging_sessions/profile.{json,md}`
  generated by [`scripts/profile-data.py`](../../../scripts/profile-data.py)
  and surfaced on the CloudWatch dashboard
  `adp-{stage}-foundation-data-quality`.

## Contract

**Provenance**: `single-vintage`

This product produces one partition per seed run and overwrites the previous partition on re-generation. The lake publishes each generation's output additively to the curated directory. For operator details on publishing behavior and single-vintage handling (including the optional `` `--allow-purge` `` flag for multi-partition cleanup), see [`docs/DEPLOYMENT.md` § "Publishing single-vintage products"](../../../../docs/DEPLOYMENT.md).

## See also

- Schema-of-record: [`schema.yaml`](schema.yaml)
- Producer: [`generator.py`](generator.py)
- Sibling EV-Ops products:
  [`energy_usage`](../energy_usage/README.md) ·
  [`ota_campaigns`](../ota_campaigns/README.md)
- Integration contract: [`docs/cvx-integration-contract.md` § 3.3](../../../../docs/cvx-integration-contract.md)
- Column formats: [`docs/data-contracts.md`](../../../../docs/data-contracts.md)
