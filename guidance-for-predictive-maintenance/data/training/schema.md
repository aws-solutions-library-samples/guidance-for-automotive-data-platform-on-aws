# Training Data Schema

Schema derived from `tire_telemetry_2025-01.parquet`.

| Column | Type | Description |
|--------|------|-------------|
| `vehicle_id` | `large_string` | |
| `tire_id` | `large_string` | |
| `timestamp` | `large_string` | |
| `pressure` | `double` | |
| `temperature` | `double` | |
| `tread_depth` | `double` | |
| `speed` | `double` | |
| `ambient_temp` | `double` | |
| `latitude` | `double` | |
| `longitude` | `double` | |
| `label` | `large_string` | |
| `delta_pressure` | `double` | |
| `delta_temp` | `double` | |

## Notes

- Data is partitioned by month in individual parquet files.
- The `label` column indicates anomaly type: `normal`, `slow_leak`, `puncture`, `valve_failure`, `overinflation`.
- Pressure values are in PSI; temperature values are in °F.
- `delta_pressure` and `delta_temp` are engineered features (change from previous reading).
