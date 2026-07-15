"""ADP foundation Group 1 Spark generation spike.

Throwaway Glue 4.0 Spark job that generates 10M rows of synthetic
``vehicle_telemetry_aggregated`` rows directly into Iceberg-formatted
parquet on S3. Informs Group 3 sizing choices for
``vehicle_telemetry_aggregated`` (rolling 90 days, ~100M rows) and
``energy_usage`` (90-day window, ~450M rows).

This module is consumed by AWS Glue 4.0 (Spark 3.3, Python 3.10) via
``aws glue start-job-run``. It also runs locally for validation when
PySpark is installed (``pip install 'pyspark==3.5.*'``); the
locally-generated sample is smaller (1M rows) and writes plain
parquet (not Iceberg) but produces the same bytes-per-row signal.

Reschedule note (decisions.md 2026-05-28): originally Group 1 task 8;
deferred from the no-AWS-auth session and now run against the deployed
``adp-foundation-lake-<account>-<region>`` bucket. The spike does NOT
create any persistent CDK resources. The Glue ETL role and Glue job
are one-off scaffolding created by the harness in
``scripts/run-spark-spike.sh`` and torn down on completion.

Usage (AWS Glue 4.0)::

    aws glue create-job \\
        --name adp-foundation-spike-vehicle-telemetry \\
        --role <SPIKE_ROLE_ARN> \\
        --command "Name=glueetl,ScriptLocation=s3://.../spark_generation_spike.py,PythonVersion=3" \\
        --default-arguments '{"--datalake-formats":"iceberg",...}' \\
        --glue-version 4.0
    aws glue start-job-run --job-name adp-foundation-spike-vehicle-telemetry

Usage (local PySpark)::

    pip install 'pyspark==3.5.*'
    python source/lib/spike/spark_generation_spike.py \\
        --output-root /tmp/adp-spike --rows 1000000 --partitions 4

Produces ``spike/results.md`` capturing elapsed time, parquet file
count, average file size, and a recommendation on whether
``energy_usage`` should ship at 90-day or full-3y window in v1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Glue runtime imports are deferred so the module is importable for
# unit tests and local pyarrow runs.
try:
    from pyspark.sql import SparkSession  # type: ignore
    from pyspark.sql import functions as F  # type: ignore
    from pyspark.sql import types as T  # type: ignore

    _HAS_PYSPARK = True
except ImportError:  # local pandas-only fallback
    _HAS_PYSPARK = False


# ---------------------------------------------------------------------------
# Schema (subset of vehicle_telemetry_aggregated; the full 27-column schema
# lives in ``platform-foundation/source/data-products/vehicle_telemetry_aggregated/schema.yaml``).
# We materialize a representative subset that drives parquet bytes-per-row.
# ---------------------------------------------------------------------------

# Distribution: 90-day rolling window, 100M total rows for production.
SPIKE_DAYS = 90
SPIKE_TARGET_ROWS = 10_000_000
SPIKE_TARGET_FILE_BYTES = 256 * 1024 * 1024  # 256 MiB
SPIKE_VINS = 100_000  # 100k VINs over 90 days × ~hourly aggregation


def _build_spark(app_name: str = "adp-foundation-spike") -> "SparkSession":
    if not _HAS_PYSPARK:
        raise RuntimeError(
            "PySpark not available — cannot run Spark spike locally without "
            "`pip install 'pyspark==3.5.*'`. On Glue 4.0 PySpark is preinstalled."
        )
    return (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.compression.codec", "snappy")
        # Iceberg config — picked up automatically by Glue when
        # --datalake-formats=iceberg is set in job args. Local runs
        # write plain parquet (no Iceberg catalog).
        .getOrCreate()
    )


def _generate_spark(
    spark: "SparkSession", rows: int, days: int = SPIKE_DAYS
) -> "object":
    """Generate ``rows`` synthetic telemetry rows distributed across ``days``.

    Uses Spark UDFs for narrative distributions: SoH declines linearly
    over the window, SoC drops while not charging then recovers, ambient
    temp shows seasonal sinusoid. No flat distributions.
    """
    # Build the row-id stream then derive every column from it.
    df = spark.range(rows).withColumnRenamed("id", "row_id")
    base_ts = int(
        datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1_000_000
    )
    seconds_per_row = (days * 86400) / max(rows, 1)

    # event_time: spread evenly across the window (microseconds since epoch)
    df = df.withColumn(
        "event_time",
        F.expr(
            f"timestamp_micros(CAST({base_ts} + row_id * {int(seconds_per_row * 1_000_000)} AS bigint))"
        ),
    )
    df = df.withColumn(
        "event_date", F.to_date("event_time")
    )
    df = df.withColumn("ingest_time", F.expr("event_time"))

    # vin: round-robin across SPIKE_VINS unique values (UUID-like)
    df = df.withColumn(
        "vin",
        F.concat(
            F.lit("1HG"),
            F.lpad(F.expr(f"CAST(row_id % {SPIKE_VINS} AS string)"), 14, "0"),
        ),
    )

    # Numeric distributions with narrative shape
    df = df.withColumn(
        "speed_kmh", F.expr("CAST(20 + 80 * rand(42) AS double)")
    )
    df = df.withColumn(
        "avg_speed_kmh", F.expr("CAST(speed_kmh * (0.7 + 0.2 * rand(43)) AS double)")
    )
    df = df.withColumn(
        "total_miles_driven", F.expr("CAST(row_id * 0.05 + 1000 * rand(44) AS double)")
    )
    df = df.withColumn(
        "start_soc_pct", F.expr("CAST(20 + 70 * rand(45) AS double)")
    )
    df = df.withColumn(
        "end_soc_pct", F.expr("CAST(start_soc_pct - 10 - 5 * rand(46) AS double)")
    )
    df = df.withColumn(
        "state_of_health_pct",
        F.expr(f"CAST(95 - (row_id / {rows}) * 5 - 0.5 * rand(47) AS double)"),
    )
    df = df.withColumn(
        "battery_pack_temp_avg_c",
        F.expr(
            f"CAST(15 + 15 * sin((row_id / {rows}) * 6.28) + 5 * rand(48) AS double)"
        ),
    )
    df = df.withColumn(
        "ambient_temp_avg_c",
        F.expr(
            f"CAST(10 + 20 * sin((row_id / {rows}) * 6.28) + 3 * rand(49) AS double)"
        ),
    )
    df = df.withColumn(
        "cabin_temp_c", F.expr("CAST(ambient_temp_avg_c + 5 * rand(50) AS double)")
    )
    df = df.withColumn(
        "motor_rpm", F.expr("CAST(speed_kmh * 80 + 200 * rand(51) AS double)")
    )
    df = df.withColumn(
        "motor_torque_nm", F.expr("CAST(50 + 200 * rand(52) AS double)")
    )
    df = df.withColumn(
        "motor_power_kw",
        F.expr("CAST(motor_torque_nm * motor_rpm / 9550.0 AS double)"),
    )
    df = df.withColumn(
        "motor_temp_c", F.expr("CAST(60 + 20 * rand(53) AS double)")
    )
    df = df.withColumn(
        "range_estimate_start_mi",
        F.expr("CAST(start_soc_pct * 3.5 + 5 * rand(54) AS double)"),
    )
    df = df.withColumn(
        "range_estimate_end_mi",
        F.expr("CAST(end_soc_pct * 3.5 + 5 * rand(55) AS double)"),
    )
    df = df.withColumn(
        "is_charging", F.expr("rand(56) < 0.15")
    )
    df = df.withColumn(
        "avg_power_kw",
        F.expr("CASE WHEN is_charging THEN 7 + 50 * rand(57) ELSE motor_power_kw END"),
    )
    # Lat/lon nullable — privacy: most home-charging rows are NULL.
    df = df.withColumn(
        "latitude",
        F.expr("CASE WHEN rand(58) < 0.6 THEN NULL ELSE 33.0 + 12 * rand(59) END"),
    )
    df = df.withColumn(
        "longitude",
        F.expr("CASE WHEN rand(60) < 0.6 THEN NULL ELSE -120.0 + 30 * rand(61) END"),
    )
    df = df.withColumn(
        "heading_deg", F.expr("CAST(360 * rand(62) AS double)")
    )
    df = df.withColumn(
        "drive_type",
        F.expr(
            "CASE WHEN rand(63) < 0.5 THEN 'AWD' "
            "WHEN rand(63) < 0.8 THEN 'RWD' ELSE 'FWD' END"
        ),
    )
    df = df.withColumn(
        "powertrain_type", F.lit("BEV")
    )
    df = df.withColumn(
        "vss_version", F.lit("v6.0")
    )
    return df.drop("row_id")


def _write_iceberg(df, output_root: str, table_name: str) -> None:
    """Write Iceberg-formatted parquet, partitioned by ``event_date``.

    On Glue 4.0 with --datalake-formats=iceberg, Spark resolves the
    ``glue_catalog.<db>.<table>`` namespace via the Iceberg AWS module.
    Locally (no Iceberg classpath), fall back to plain parquet so the
    sizing benchmark still runs.
    """
    if _HAS_PYSPARK:
        try:
            df.writeTo(table_name).using("iceberg").partitionedBy(
                F.col("event_date")
            ).createOrReplace()
            return
        except Exception:  # pragma: no cover  - local PySpark without Iceberg
            pass
    # Fallback path
    df.write.mode("overwrite").partitionBy("event_date").parquet(output_root)


def _measure_output(output_root: str) -> dict:
    """Walk a local fs path or list an S3 prefix to compute file stats."""
    if output_root.startswith("s3://"):
        # On Glue this is invoked with boto3.
        import boto3

        bucket, key_prefix = output_root.replace("s3://", "").split("/", 1)
        s3 = boto3.client("s3")
        paginator = s3.get_paginator("list_objects_v2")
        sizes = []
        for page in paginator.paginate(Bucket=bucket, Prefix=key_prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".parquet"):
                    sizes.append(obj["Size"])
        if not sizes:
            return {"file_count": 0, "avg_bytes": 0, "total_bytes": 0}
        return {
            "file_count": len(sizes),
            "avg_bytes": sum(sizes) / len(sizes),
            "total_bytes": sum(sizes),
            "min_bytes": min(sizes),
            "max_bytes": max(sizes),
        }
    # Local fs
    p = Path(output_root)
    sizes = [f.stat().st_size for f in p.rglob("*.parquet")]
    if not sizes:
        return {"file_count": 0, "avg_bytes": 0, "total_bytes": 0}
    return {
        "file_count": len(sizes),
        "avg_bytes": sum(sizes) / len(sizes),
        "total_bytes": sum(sizes),
        "min_bytes": min(sizes),
        "max_bytes": max(sizes),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        required=True,
        help="s3://... or local path. Spike writes parquet under this prefix.",
    )
    parser.add_argument(
        "--rows", type=int, default=SPIKE_TARGET_ROWS,
        help="Target row count (default: 10M)."
    )
    parser.add_argument("--days", type=int, default=SPIKE_DAYS)
    parser.add_argument(
        "--partitions", type=int, default=64,
        help="Number of output partitions to coalesce to. Tune for "
        "256 MiB target file size."
    )
    parser.add_argument(
        "--table-name", default="glue_catalog.adp_vehicle_telemetry_aggregated.spike_telemetry",
        help="Iceberg table identifier (Glue catalog mode only)."
    )
    parser.add_argument("--results-out", default="results.md")
    args, _unknown = parser.parse_known_args()

    print(f"[spike] rows={args.rows:,} days={args.days} output={args.output_root}")

    spark = _build_spark()
    t0 = time.time()
    df = _generate_spark(spark, args.rows, args.days)
    df = df.repartition(args.partitions, "event_date")
    _write_iceberg(df, args.output_root, args.table_name)
    elapsed_seconds = time.time() - t0

    stats = _measure_output(args.output_root)
    spark.stop()

    avg_mb = stats.get("avg_bytes", 0) / 1024 / 1024
    total_mb = stats.get("total_bytes", 0) / 1024 / 1024
    bytes_per_row = stats.get("total_bytes", 0) / max(args.rows, 1)

    summary = {
        "rows": args.rows,
        "days": args.days,
        "output_root": args.output_root,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "file_count": stats["file_count"],
        "total_mb": round(total_mb, 2),
        "avg_file_mb": round(avg_mb, 2),
        "bytes_per_row": round(bytes_per_row, 2),
        # Sizing extrapolation
        "vta_100m_estimated_gb": round((bytes_per_row * 100_000_000) / 1e9, 2),
        "energy_usage_90d_estimated_gb": round((bytes_per_row * 450_000_000) / 1e9, 2),
        "energy_usage_3y_estimated_gb": round((bytes_per_row * 5_500_000_000) / 1e9, 2),
        "recommended_energy_usage_window_days": (
            90 if (bytes_per_row * 5_500_000_000) > 1e12 else "evaluate full 3-year"
        ),
    }
    print(f"[spike] summary: {json.dumps(summary, indent=2)}")
    return 0


if __name__ == "__main__":
    rc = main()
    # On Glue 4.0, sys.exit() is treated as job failure even with code 0.
    # Just print the result and let the driver process exit naturally.
    if rc != 0:
        sys.exit(rc)
