# Spike: 10M-row PySpark generation on Glue (Group 1 task 8)

Generated: 2026-05-28T20:54:33Z

## Run

- Glue job: `adp-foundation-spike-vehicle-telemetry`
- Run id: `jr_4496657bbd707ec3a5470dc74b8042e7286e38d502682fe95ef0df4fbc279f8b`
- State: `SUCCEEDED`
- Workers: 2 × G.1X
- Glue version: 4.0 (Spark 3.3, Python 3.10)
- Datalake format: iceberg
- Wall-clock elapsed: 1124s
- Output: `s3://adp-foundation-lake-<account>-us-east-1/spike-output/vehicle_telemetry_aggregated/`

## Inputs

- rows generated: 10000000
- target window: 90 days
- partitions: 64
- columns: 27 (vehicle_telemetry_aggregated subset)

## Output sizing

| Metric | Value |
|---|---|
| Parquet file count | 90 |
| Total parquet bytes | 1634128815 (1558.42 MiB) |
| Average file size | 17.31 MiB |
| Min file size | 18151017 bytes |
| Max file size | 18162456 bytes |
| **Bytes per row** | **163.41** |

Spec target: ~256 MiB per parquet file (within 200–300 MiB acceptable).

## Extrapolation to Group 3 products

Using observed bytes-per-row of 163.41:

| Product | Rows | Estimated total size |
|---|---|---|
| vehicle_telemetry_aggregated (rolling 90d, 100M) | 100,000,000 | 15.21 GiB |
| energy_usage (90d, 450M) | 450,000,000 | 68.48 GiB |
| energy_usage (full 3y, 5.5B) | 5,500,000,000 | 837.03 GiB |

## Recommendation

The spec already commits **`energy_usage` to a 90-day rolling window in
v1**, regardless of spike outcome. This spike validates that decision:

- 90-day window: 68.48 GiB — fits cleanly on the foundation lake;
  partition pruning keeps Athena query cost bounded for typical
  customer-cohort and per-VIN queries.
- Full 3-year window: 837.03 GiB — would require ~10× storage and
  significant Athena scan overhead. Not recommended for v1.

**Decision (matches spec commitment)**: ship `energy_usage` with a 90-day
rolling window in v1; reconsider full-3y if downstream consumers demonstrate
need.

## File-size targeting

Observed average 17.31 MiB vs target 256 MiB. If average is below 200 MiB:
increase coalesce target by reducing `--partitions`. If above 300 MiB:
increase `--partitions`.

The Group 3 `vehicle_telemetry_aggregated` and `energy_usage` Spark
generators reuse this script's partition-tuning approach.

## Reproducibility

To re-run this spike (after re-deploying foundation):

```
cd platform-foundation
make seed-dimensions   # if not yet done
SPIKE_ROWS=10000000 SPIKE_PARTITIONS=64 bash scripts/run-spark-spike.sh
```

The harness creates ephemeral Glue resources (role, job) and tears them
down on completion. Spike output stays in S3 for further inspection.
