# Tire Health (`tire_health`)

> **Domain**: Vehicle &nbsp;·&nbsp; **Storage**: Iceberg
> &nbsp;·&nbsp; **Display name**: `Tire Health`

Aggregated tire health metrics and predictive scores — pressure, tread depth, temperature, anomaly indicators, and remaining useful life (RUL) predictions. Enables predictive maintenance and fleet risk assessment. Producer is [`generator.py`](generator.py) (pandas tier); column formats follow [`docs/data-contracts.md`](../../../../docs/data-contracts.md).

## Schema

Refer to [`schema.yaml`](schema.yaml) for the authoritative schema. Key columns:

| Column | Type | Nullable | Description |
|---|---|---|---|
| `vin` | string | no | Vehicle Identification Number (FK → `vins`); regex `^[A-HJ-NPR-Z0-9]{17}$`. PK part. |
| `tire_position` | string | no | Tire position: enum `[FL, FR, RL, RR]` (PK part). |
| `event_date` | date | no | UTC calendar day. **Partition key** and PK part. Directly joinable to `vehicle_telemetry_aggregated.event_date`. |
| `tread_depth_mm` | double | no | Daily average tread depth (mm). Range 0–12. New tyre ~8mm; legal minimum ~1.6mm; replace at <2mm. |
| `pressure_psi_avg` | double | no | Average tyre pressure over the day (PSI). Range 15–55. |
| `pressure_psi_min` | double | yes | Minimum tyre pressure observed during the day (PSI). Range 0–55. |
| `pressure_psi_max` | double | yes | Maximum tyre pressure observed during the day (PSI). Range 15–80. |
| `temp_c_avg` | double | yes | Average tyre temperature over the day (Celsius). Range -30–120. |
| `temp_c_max` | double | yes | Peak tyre temperature during the day (Celsius). Range -30–150. |
| `distance_km` | double | no | Distance driven on this tyre during the day (km). Cumulative odometer delta. Range 0–1500. |
| `wear_rate_mm_per_1k_km` | double | yes | Derived: tread depth loss per 1,000 km (monotonically increasing with noise). NULL when `distance_km == 0`. Range 0–2. |
| `needs_replacement` | boolean | no | Supervised label: `true` when `tread_depth_mm < 2.0` OR pressure anomaly indicates structural risk. |
| `wear_category` | string | no | Ordinal wear label: enum `[ok, monitor, replace]` (`ok`: tread ≥ 4mm; `monitor`: 2mm ≤ tread < 4mm; `replace`: tread < 2mm). |
| `event_time` | timestamp | no | Source-truth event time (UTC microseconds) — midnight of `event_date`. |
| `ingest_time` | timestamp | no | When the loader wrote this row (UTC microseconds). |

See [`schema.yaml`](schema.yaml) for complete schema and lineage metadata.

## Contract

**Provenance**: `single-vintage`

This product produces one partition per seed run (one partition per `event_date` across all tire positions and VINs) and overwrites the previous partition on re-generation. The lake publishes each generation's output additively to the curated directory. For operator details on publishing behavior and single-vintage handling (including the optional `--allow-purge` flag for multi-partition cleanup), see [`docs/DEPLOYMENT.md` § "Publishing single-vintage products"](../../../../docs/DEPLOYMENT.md).

## See also

- Schema-of-record: [`schema.yaml`](schema.yaml)
- Producer: [`generator.py`](generator.py)
- Column formats: [`docs/data-contracts.md`](../../../../docs/data-contracts.md)
