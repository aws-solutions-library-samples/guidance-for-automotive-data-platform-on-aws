"""Generator for ``vehicle_telemetry_aggregated`` (PySpark on Glue 4.0).

Generates synthetic per-VIN-per-time-window aggregated telemetry directly
into an Iceberg-formatted parquet table, partitioned by ``event_date`` and
bucketed by ``vin`` (16 buckets) per ``schema.yaml``. Column set is the
27-column VSS-aligned schema defined in
``platform-foundation/source/data-products/vehicle_telemetry_aggregated/schema.yaml``
and ``docs/data-contracts.md`` "VSS vocabulary subset".

Scale
-----
This v1 generator emits the **sample scale of 10M rows** over a rolling
90-day window — the same shape validated by the Group 1 spike at
``platform-foundation/source/lib/spike/spark_generation_spike.py`` /
``spike/results.md`` (10M rows / 90 days / 163.41 bytes-per-row /
~1.56 GiB total).

Per ``.kiro/specs/2026-05-28-adp-ev-startup-foundation/decisions.md``
"2026-05-28 — Group 3 scope: pandas-full, Spark-sample,
KB-artifacts-only", ``vehicle_telemetry_aggregated`` is the
**Spark-sample** tier of Group 3. The full **100M-row production scale**
(per ``tasks.md`` Group 3 Accept criteria — ~100M rows over a rolling
90-day window) is **deferred to Group 6**: rerun this generator with
``--rows 100000000`` and a larger Glue worker count (G.2X × 5–10
workers per the spike's 1124s/2×G.1X extrapolation). Schema, partition
spec, FK contract, edge-case taxonomy, and downstream consumers do
NOT change between sample and full scales — only the row count and
Glue cluster sizing differ. Group 6 production-seed task owns the
re-run and the Athena ``SELECT COUNT(*)`` 100M ± 1M assertion.

FK contract
-----------
Every emitted row carries a ``vin`` value drawn from the ``vins``
dimension catalog at ``dimensions/vins/data.parquet`` (S3 or local).
100% FK coverage by construction; the ``orphan_fk`` edge-case rate is
0% (counter-example per the edge-case taxonomy in ``docs/tech.md``).

Edge-case injection
-------------------
1–3% aggregate per the six-code taxonomy declared in ``docs/tech.md``
"Edge-Case Taxonomy" — same rates as ``source/lib/product_generator.py``
``EDGE_CASE_RATES`` so cross-product profiling reports compare cleanly:

- ``missing_required`` ~0.75% (NaN on edge-case-eligible columns)
- ``late_arrival``     ~0.50% (ingest_time + 1–3 days)
- ``schema_drift``     ~0.35% ("DRIFT-" prefix on string cells)
- ``bad_pii``          0.00%  (structurally zero — no non-FK PII column on
                                 this product; review.md cycle 3 fix)
- ``orphan_fk``        0.00%  (counter-example; not injected)
- ``outlier_value``    ~0.40% (5–10× above column ``range`` upper bound)

Aggregate ~2.20% — within the 1–3% target band.

Distributions (no flat ``rand()`` outside random-seed inputs)
-------------------------------------------------------------
- SoH declines linearly across the window (95% → 90%) with noise.
- SoC drops while not charging then recovers (correlated with
  ``is_charging``).
- Ambient + battery-pack temps follow a seasonal sinusoid.
- Speed gaussian; motor power derived from torque×rpm (physics).
- ``latitude``/``longitude`` NULL on ~60% of rows (privacy: home rows).
- ``drive_type`` weighted [awd 0.50, rwd 0.30, fwd 0.20] matching
  vehicle_identity's distribution.
- ``powertrain_type`` weighted [electric 0.85, hybrid 0.10, erev 0.05]
  matching the EV-startup narrative.

Glue 4.0 vs local
-----------------
Module is **importable without PySpark** (deferred try/except). On
Glue 4.0 PySpark 3.3 + Python 3.10 are preinstalled. Local validation
requires::

    pip install 'pyspark==3.5.*'

The PySpark 3.5 ``writeTo`` Iceberg API used here is API-compatible
with Glue 4.0 (Spark 3.3) when ``--datalake-formats=iceberg`` is set
in job arguments.

Usage — AWS Glue 4.0 (production path)
--------------------------------------
::

    aws glue create-job \\
        --name adp-staging-foundation-vehicle-telemetry-generator \\
        --role <ADP_GLUE_ETL_ROLE_ARN> \\
        --command "Name=glueetl,ScriptLocation=s3://<bucket>/scripts/generator.py,PythonVersion=3" \\
        --default-arguments '{
            "--datalake-formats":"iceberg",
            "--conf":"spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog ..."
        }' \\
        --glue-version 4.0

    aws glue start-job-run \\
        --job-name adp-staging-foundation-vehicle-telemetry-generator \\
        --arguments '{
            "--rows":"10000000",
            "--days":"90",
            "--vins-source":"s3://<lake>/dimensions/vins/data.parquet",
            "--output-root":"s3://<lake>/curated/vehicle_telemetry_aggregated/vehicle_telemetry_aggregated/",
            "--table-name":"glue_catalog.adp_staging_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated"
        }'

Usage — local PySpark (dev validation only)
-------------------------------------------
::

    pip install 'pyspark==3.5.*'
    python source/data-products/vehicle_telemetry_aggregated/generator.py \\
        --rows 100000 --days 7 --partitions 4 \\
        --vins-source /tmp/adp-dim-full/vins/data.parquet \\
        --output-root /tmp/adp-curated/vehicle_telemetry_aggregated

Local mode falls back to plain parquet (no Iceberg classpath) so the
shape can be inspected with ``pyarrow.parquet.read_table()``. The
sizing benchmark is still meaningful — bytes-per-row is ~constant
between Iceberg-parquet and plain parquet.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Glue/Spark imports are deferred so the module is importable for
# unit tests, schema validation, and dry-run inspection without
# PySpark on the import path. Glue 4.0 ships PySpark 3.3 in the
# default classpath; local validation needs `pip install 'pyspark==3.5.*'`.
try:
    from pyspark.sql import SparkSession  # type: ignore
    from pyspark.sql import functions as F  # type: ignore

    _HAS_PYSPARK = True
except ImportError:  # pragma: no cover - covered by local-no-pyspark path
    _HAS_PYSPARK = False


# ---------------------------------------------------------------------------
# Shared library imports (sys.path bootstrap mirrors the pandas generators).
# ``EDGE_CASE_RATES`` is the single-source-of-truth in
# ``source/lib/product_generator.py``; importing it here keeps the Spark
# generator's edge-case rates in lockstep with the pandas tier — review.md
# cycle 2 Suggestion #1 / cycle 3 Suggestion (carry-over).
# ``product_generator`` lazy-imports ``boto3`` inside ``upload_to_s3`` /
# ``register_iceberg_table`` only — module import does NOT pull boto3 onto
# ``sys.modules``, preserving the offline-import contract.
# ---------------------------------------------------------------------------
# 2026-06-11: try/except wrap added per spec
# `2026-06-09-adp-pyspark-glue-products` Constraint #2 relaxation. Local-dev
# path is `parents[3] = platform-foundation/`. On Glue the script is
# extracted to flat `/tmp/glue-job-XXX/generator.py` — `parents[3]` raises
# IndexError before any Spark code runs. Glue runtime provides
# `product_generator` via `--extra-py-files=s3://.../scripts/lib/product_generator.py`,
# so the local-fs bootstrap is unnecessary in that environment.
try:
    _LIB = Path(__file__).resolve().parents[3] / "source" / "lib"
    if str(_LIB) not in sys.path:
        sys.path.insert(0, str(_LIB))
except IndexError:
    pass  # Glue runtime: --extra-py-files puts product_generator on sys.path

from product_generator import EDGE_CASE_RATES  # noqa: E402


# ---------------------------------------------------------------------------
# Sizing constants — match spike for byte-per-row equivalence.
# Group 6 production-seed bumps DEFAULT_TARGET_ROWS to 100_000_000.
# ---------------------------------------------------------------------------

DEFAULT_TARGET_ROWS = 10_000_000        # sample (Group 3 Spark-sample tier)
PROD_TARGET_ROWS = 100_000_000          # production (Group 6 deferred run)
DEFAULT_DAYS = 90                       # rolling 90-day window
DEFAULT_PARTITIONS = 64                 # tune for ~256 MiB target file size
DEFAULT_TABLE_NAME = (
    "glue_catalog.adp_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated"
)


# ---------------------------------------------------------------------------
# Edge-case rates — sourced from ``source/lib/product_generator.py``
# ``EDGE_CASE_RATES`` (imported above). Single source of truth for both
# pandas + Spark generators so cross-product profiling reports compare
# cleanly. To recalibrate rates, edit ``product_generator.py`` only.
# Aggregate ~2.20%, within the 1–3% per-product target band.
# ---------------------------------------------------------------------------

# Subset of edge-case-eligible columns (must match schema.yaml).
EDGE_ELIGIBLE_NUMERIC: tuple[tuple[str, float], ...] = (
    ("speed_kmh", 300.0),
    ("total_miles_driven", 1_000_000.0),
    ("start_soc_pct", 100.0),
    ("end_soc_pct", 100.0),
    ("battery_pack_temp_avg_c", 80.0),
)


# ---------------------------------------------------------------------------
# Spark session
# ---------------------------------------------------------------------------


def _build_spark(app_name: str = "adp-vehicle-telemetry-aggregated") -> "SparkSession":
    """Build (or reuse) the Spark session.

    On Glue 4.0 the SparkContext is pre-bound by the runtime; calling
    ``getOrCreate()`` returns the existing session. Locally this creates
    a fresh session — Iceberg classpath is absent, so writes fall back
    to plain parquet.
    """
    if not _HAS_PYSPARK:
        raise RuntimeError(
            "PySpark not available — install with `pip install 'pyspark==3.5.*'` "
            "for local execution. On Glue 4.0 PySpark is preinstalled."
        )
    return (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.parquet.compression.codec", "snappy")
        # Iceberg classpath is set by Glue via --datalake-formats=iceberg.
        # Local runs without Iceberg fall back to plain parquet writes.
        .getOrCreate()
    )


# ---------------------------------------------------------------------------
# VIN dimension load — broadcast for FK sampling
# ---------------------------------------------------------------------------


def _load_vins(spark: "SparkSession", vins_source: str, max_vins: int) -> list[str]:
    """Load the VIN list from the ``vins`` dimension parquet.

    ``vins_source`` may be ``s3://...`` or a local path. Returns at most
    ``max_vins`` distinct VIN values for round-robin sampling.

    The ``vins`` dimension at full scale contains 5,000,000 VINs. For
    the sample-scale generator (10M rows × 90 days), capping the pool
    at 100K VINs gives ~100 telemetry rows/VIN/window — matching the
    spike's narrative density and avoiding 100MB driver-side broadcasts.
    """
    df = spark.read.parquet(vins_source).select("vin").dropDuplicates(["vin"]).orderBy("vin").limit(max_vins)
    return [row["vin"] for row in df.collect()]


# ---------------------------------------------------------------------------
# Telemetry generation
# ---------------------------------------------------------------------------


def _generate_telemetry(
    spark: "SparkSession",
    *,
    vins: list[str],
    rows: int,
    days: int,
    seed: int,
) -> "object":
    """Generate ``rows`` synthetic telemetry rows distributed across ``days``.

    All columns from ``schema.yaml`` are populated with narrative-shaped
    distributions (no flat ``rand.uniform``). VIN is FK-sampled from
    ``vins`` (round-robin, every VIN used). Returns a Spark DataFrame.
    """
    if not vins:
        raise ValueError("vins list is empty — cannot satisfy FK to vins")

    # Build a row-id stream then derive every column from it.
    df = spark.range(rows).withColumnRenamed("id", "row_id")

    # VIN: round-robin across the VIN pool so every row's vin exists in vins.
    vin_pool_size = len(vins)
    df = df.withColumn(
        "_vin_idx", F.expr(f"CAST(row_id % {vin_pool_size} AS int)")
    )
    # Map index → VIN via broadcasted DataFrame (avoids 5MB+ literal IN list).
    vin_lookup = spark.createDataFrame(
        [(i, v) for i, v in enumerate(vins)], schema="_vin_idx int, vin string"
    )
    df = df.join(F.broadcast(vin_lookup), on="_vin_idx", how="inner").drop("_vin_idx")

    # event_time: spread evenly across the window (microseconds since epoch).
    base_ts = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1_000_000)
    micros_per_row = max(1, int((days * 86400 * 1_000_000) / max(rows, 1)))
    df = df.withColumn(
        "event_time",
        F.expr(
            f"timestamp_micros(CAST({base_ts} + row_id * {micros_per_row} AS bigint))"
        ),
    )
    df = df.withColumn("event_date", F.to_date("event_time"))
    df = df.withColumn("ingest_time", F.col("event_time"))

    # Use seeded rand(...) calls so the same seed yields identical output.
    s = seed

    # speed_kmh: gaussian around 60 km/h, clipped to [0, 300]
    df = df.withColumn(
        "speed_kmh",
        F.expr(f"GREATEST(0.0, LEAST(300.0, 60.0 + 25.0 * (rand({s + 1}) - 0.5) * 4.0))"),
    )
    df = df.withColumn(
        "avg_speed_kmh",
        F.expr(f"GREATEST(0.0, LEAST(300.0, speed_kmh * (0.7 + 0.2 * rand({s + 2}))))"),
    )
    df = df.withColumn(
        "total_miles_driven",
        F.expr(f"GREATEST(0.0, row_id * 0.05 + 1000.0 * rand({s + 3}))"),
    )

    # SoC: starts in [20, 90], drops when not charging, rises when charging.
    df = df.withColumn(
        "is_charging", F.expr(f"rand({s + 4}) < 0.15")
    )
    df = df.withColumn(
        "start_soc_pct",
        F.expr(f"GREATEST(0.0, LEAST(100.0, 20.0 + 70.0 * rand({s + 5})))"),
    )
    df = df.withColumn(
        "end_soc_pct",
        F.expr(
            f"GREATEST(0.0, LEAST(100.0, "
            f"CASE WHEN is_charging "
            f"THEN start_soc_pct + 5.0 + 25.0 * rand({s + 6}) "
            f"ELSE start_soc_pct - 8.0 - 5.0 * rand({s + 6}) END))"
        ),
    )

    # SoH declines linearly across the window: 95% at row 0 → 90% at row N.
    df = df.withColumn(
        "state_of_health_pct",
        F.expr(
            f"GREATEST(0.0, LEAST(100.0, "
            f"95.0 - (row_id / {rows}) * 5.0 - 0.5 * rand({s + 7})))"
        ),
    )

    # Seasonal sinusoid for ambient + battery temps over the window.
    df = df.withColumn(
        "battery_pack_temp_avg_c",
        F.expr(
            f"GREATEST(-40.0, LEAST(80.0, "
            f"15.0 + 15.0 * sin((row_id / {rows}) * 6.2832) + 5.0 * (rand({s + 8}) - 0.5)))"
        ),
    )
    df = df.withColumn(
        "ambient_temp_avg_c",
        F.expr(
            f"GREATEST(-50.0, LEAST(60.0, "
            f"10.0 + 20.0 * sin((row_id / {rows}) * 6.2832) + 3.0 * (rand({s + 9}) - 0.5)))"
        ),
    )
    df = df.withColumn(
        "cabin_temp_c",
        F.expr(
            f"GREATEST(-10.0, LEAST(60.0, "
            f"ambient_temp_avg_c + 5.0 * rand({s + 10})))"
        ),
    )

    # Motor: rpm ~ speed × gear-ratio + noise; torque uniform; power = T×ω/9550.
    df = df.withColumn(
        "motor_rpm",
        F.expr(f"GREATEST(0.0, LEAST(25000.0, speed_kmh * 80.0 + 200.0 * rand({s + 11})))"),
    )
    df = df.withColumn(
        "motor_torque_nm",
        F.expr(f"GREATEST(-1000.0, LEAST(1500.0, 50.0 + 200.0 * rand({s + 12})))"),
    )
    df = df.withColumn(
        "motor_power_kw",
        F.expr(
            "GREATEST(-400.0, LEAST(600.0, motor_torque_nm * motor_rpm / 9550.0))"
        ),
    )
    df = df.withColumn(
        "motor_temp_c",
        F.expr(f"GREATEST(-40.0, LEAST(200.0, 60.0 + 20.0 * rand({s + 13})))"),
    )

    # Range estimates: linearly correlated with SoC.
    df = df.withColumn(
        "range_estimate_start_mi",
        F.expr(f"GREATEST(0.0, LEAST(800.0, start_soc_pct * 3.5 + 5.0 * rand({s + 14})))"),
    )
    df = df.withColumn(
        "range_estimate_end_mi",
        F.expr(f"GREATEST(0.0, LEAST(800.0, end_soc_pct * 3.5 + 5.0 * rand({s + 15})))"),
    )

    # Charging power: 7-50 kW when charging, else equal to motor power.
    df = df.withColumn(
        "avg_power_kw",
        F.expr(
            f"GREATEST(0.0, LEAST(400.0, "
            f"CASE WHEN is_charging "
            f"THEN 7.0 + 50.0 * rand({s + 16}) "
            f"ELSE motor_power_kw END))"
        ),
    )

    # Latitude / longitude — NULL ~60% (privacy: home charging, no GPS)
    df = df.withColumn(
        "latitude",
        F.expr(
            f"CASE WHEN rand({s + 17}) < 0.6 THEN CAST(NULL AS DOUBLE) "
            f"ELSE 24.5 + 24.5 * rand({s + 18}) END"
        ),
    )
    df = df.withColumn(
        "longitude",
        F.expr(
            f"CASE WHEN rand({s + 19}) < 0.6 THEN CAST(NULL AS DOUBLE) "
            f"ELSE -124.7 + 57.7 * rand({s + 20}) END"
        ),
    )

    df = df.withColumn(
        "heading_deg",
        F.expr(f"GREATEST(0.0, LEAST(360.0, 360.0 * rand({s + 21})))"),
    )

    # drive_type — enum awd/fwd/rwd, weighted [fwd 0.20, rwd 0.30, awd 0.50].
    # Materialize a single rand() draw per row into `_drive_rand`, then CASE
    # WHEN against the materialized column. Spark catalyst treats every
    # `rand(seed)` call as a non-deterministic expression and does NOT unify
    # duplicate calls inside CASE branches, so naively writing
    # `WHEN rand({s + 22}) < 0.50 ... WHEN rand({s + 22}) < 0.80 ...` would
    # produce two independent draws and resolve conditional probabilities
    # multiplicatively — see review.md cycle 2 Warning #1 / SPARK-9844.
    df = df.withColumn("_drive_rand", F.expr(f"rand({s + 22})"))
    df = df.withColumn(
        "drive_type",
        F.expr(
            "CASE WHEN _drive_rand < 0.20 THEN 'fwd' "
            "WHEN _drive_rand < 0.50 THEN 'rwd' ELSE 'awd' END"
        ),
    )

    # powertrain_type — enum electric/hybrid/erev, EV-startup narrative
    # weighted [electric 0.85, hybrid 0.10, erev 0.05]. Materialize-once
    # pattern matches drive_type (see comment above).
    df = df.withColumn("_powertrain_rand", F.expr(f"rand({s + 23})"))
    df = df.withColumn(
        "powertrain_type",
        F.expr(
            "CASE WHEN _powertrain_rand < 0.05 THEN 'erev' "
            "WHEN _powertrain_rand < 0.15 THEN 'hybrid' ELSE 'electric' END"
        ),
    )

    df = df.withColumn("vss_version", F.lit("6.0"))

    # Drop helper columns, return in schema-declaration order so parquet
    # column order matches the Iceberg table spec exactly.
    df = df.drop("row_id", "_drive_rand", "_powertrain_rand")
    schema_order = [
        "vin",
        "event_date",
        "event_time",
        "ingest_time",
        "speed_kmh",
        "avg_speed_kmh",
        "total_miles_driven",
        "start_soc_pct",
        "end_soc_pct",
        "state_of_health_pct",
        "battery_pack_temp_avg_c",
        "ambient_temp_avg_c",
        "cabin_temp_c",
        "motor_rpm",
        "motor_torque_nm",
        "motor_power_kw",
        "motor_temp_c",
        "range_estimate_start_mi",
        "range_estimate_end_mi",
        "is_charging",
        "avg_power_kw",
        "latitude",
        "longitude",
        "heading_deg",
        "drive_type",
        "powertrain_type",
        "vss_version",
    ]
    return df.select(*schema_order)


# ---------------------------------------------------------------------------
# Edge-case injection (Spark-native, mirrors source/lib/product_generator.py)
# ---------------------------------------------------------------------------


def _inject_edge_cases(df: "object", *, seed: int) -> "object":
    """Apply 5-of-6 edge-case codes per the taxonomy (orphan_fk excluded).

    Same rates as ``source/lib/product_generator.py.EDGE_CASE_RATES`` so
    profiling reports compare cleanly across pandas + Spark generators.
    """
    s = seed + 9001
    miss_p = EDGE_CASE_RATES["missing_required"]
    late_p = EDGE_CASE_RATES["late_arrival"]
    drift_p = EDGE_CASE_RATES["schema_drift"]
    # bad_pii is structurally zero on this product — see explanation
    # below where the (deleted) corruption block used to live.
    out_p = EDGE_CASE_RATES["outlier_value"]

    # missing_required — null one edge-case-eligible column at random.
    # Distribute the rate across the eligible numeric columns.
    per_col_rate = miss_p / max(len(EDGE_ELIGIBLE_NUMERIC), 1)
    for i, (col_name, _hi) in enumerate(EDGE_ELIGIBLE_NUMERIC):
        df = df.withColumn(
            col_name,
            F.expr(
                f"CASE WHEN rand({s + 100 + i}) < {per_col_rate} "
                f"THEN CAST(NULL AS DOUBLE) ELSE {col_name} END"
            ),
        )

    # late_arrival — shift ingest_time forward 1-3 days at late_p rate.
    df = df.withColumn(
        "ingest_time",
        F.expr(
            f"CASE WHEN rand({s + 200}) < {late_p} "
            f"THEN ingest_time + INTERVAL 2 DAYS "
            f"ELSE ingest_time END"
        ),
    )

    # schema_drift — prepend "DRIFT-" to drive_type at drift_p rate
    # (only string edge-case-eligible col flagged in schema is none, but
    # vss_version + drive_type are reasonable drift surfaces).
    df = df.withColumn(
        "drive_type",
        F.expr(
            f"CASE WHEN rand({s + 300}) < {drift_p} "
            f"THEN concat('DRIFT-', drive_type) ELSE drive_type END"
        ),
    )

    # bad_pii — STRUCTURALLY ZERO on this product (review.md cycle 3
    # Warning + decisions.md "2026-05-29 — bad_pii × orphan_fk
    # resolution: Option 1 (re-target to non-FK PII columns)").
    # vehicle_telemetry_aggregated declares zero ``pii_drift_target``
    # columns in ``schema.yaml``; the only PII candidate is ``vin``
    # which is the FK to ``vins``. Corrupting ``vin`` would fold
    # bad_pii into orphan_fk and break spec Constraints #5 + #6.
    # The summary[bad_pii] stays at 0 by construction; cross-product
    # profiling reports the documented EDGE_CASE_RATES.bad_pii rate
    # as the *intended* rate, with this generator contributing 0
    # corruptions to the per-product aggregate.

    # outlier_value — multiply numeric edge-eligible col by 7 (5–10× midpoint)
    # at out_p rate. Apply per-column at out_p / N rate so the aggregate is right.
    per_col_out = out_p / max(len(EDGE_ELIGIBLE_NUMERIC), 1)
    for i, (col_name, hi) in enumerate(EDGE_ELIGIBLE_NUMERIC):
        df = df.withColumn(
            col_name,
            F.expr(
                f"CASE WHEN rand({s + 500 + i}) < {per_col_out} "
                f"THEN CAST({hi * 7.0} AS DOUBLE) "
                f"ELSE {col_name} END"
            ),
        )

    # orphan_fk — never injected (target rate 0% per taxonomy).
    return df


# ---------------------------------------------------------------------------
# Iceberg / parquet write
# ---------------------------------------------------------------------------


def _write_iceberg(
    df: "object",
    *,
    table_name: str,
    output_root: str,
    partitions: int,
) -> None:
    """Write Iceberg-formatted parquet, partitioned by ``event_date`` and
    bucketed by ``vin`` (16 buckets) per ``schema.yaml``.

    On Glue 4.0 with ``--datalake-formats=iceberg`` set, Spark resolves the
    ``glue_catalog.<db>.<table>`` namespace via the Iceberg AWS module and
    creates/replaces the table atomically with the correct partition spec.

    Locally (no Iceberg classpath) this falls back to plain partitioned
    parquet under ``output_root`` so the byte-per-row sizing benchmark
    still runs.
    """
    df = df.repartition(partitions, "event_date")

    if _HAS_PYSPARK:
        try:
            # F.bucket(N, col) is in PySpark 3.5+. On Spark 3.3 (Glue 4.0)
            # use F.expr("bucket(16, vin)") which Iceberg resolves.
            try:
                bucket_transform = F.bucket(16, "vin")  # type: ignore[attr-defined]
            except AttributeError:
                bucket_transform = F.expr("bucket(16, vin)")
            df.writeTo(table_name).using("iceberg").partitionedBy(
                F.col("event_date"), bucket_transform
            ).createOrReplace()
            return
        except Exception as exc:  # pragma: no cover — local fallback
            # 2026-06-11: dump full Java exception under spec Constraint #2
            # relaxation. Glue 5.1's SQLExecutionObfuscatedInfo + log4j OOM
            # during error formatting suppress the actual exception otherwise.
            import traceback
            print("[telemetry] >>> FULL TRACEBACK START")
            traceback.print_exc()
            print("[telemetry] <<< FULL TRACEBACK END")
            if hasattr(exc, "java_exception") and exc.java_exception is not None:
                try:
                    print(f"[telemetry] Java exception toString: {exc.java_exception.toString()}")
                    print(f"[telemetry] Java exception message: {exc.java_exception.getMessage()}")
                    print(f"[telemetry] Java exception class: {exc.java_exception.getClass().getName()}")
                except Exception as inner:
                    print(f"[telemetry] (failed to introspect java_exception: {inner!r})")
            print(
                f"[telemetry] Iceberg writeTo failed ({exc!r}); "
                "falling back to plain parquet."
            )
    # Fallback path — local PySpark without Iceberg classpath.
    df.write.mode("overwrite").partitionBy("event_date").parquet(output_root)


# ---------------------------------------------------------------------------
# Output measurement (local sanity / Glue smoke)
# ---------------------------------------------------------------------------


def _measure_output(output_root: str) -> dict[str, Any]:
    """Walk a local fs path or list an S3 prefix to compute file stats.

    Mirrors ``source/lib/spike/spark_generation_spike.py._measure_output``
    so profiling output is comparable spike→canonical.
    """
    if output_root.startswith("s3://"):
        import boto3

        bucket, key_prefix = output_root.replace("s3://", "").split("/", 1)
        s3 = boto3.client("s3")
        paginator = s3.get_paginator("list_objects_v2")
        sizes: list[int] = []
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


# ---------------------------------------------------------------------------
# Glue argument parsing — works with both ``getResolvedOptions`` (Glue) and
# argparse (local), via ``parse_known_args`` so unknown Glue flags pass through.
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else "")
    parser.add_argument(
        "--rows",
        type=int,
        default=DEFAULT_TARGET_ROWS,
        help=f"Target row count. Default {DEFAULT_TARGET_ROWS:,} (sample). "
             f"Group 6 production seed: {PROD_TARGET_ROWS:,}.",
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help="Rolling event_date window in days (default: 90).",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Deterministic seed for narrative + edge-case reproducibility.",
    )
    parser.add_argument(
        "--partitions", type=int, default=DEFAULT_PARTITIONS,
        help="Number of Spark partitions before write. Tune for ~256 MiB files.",
    )
    parser.add_argument(
        "--vins-source",
        required=True,
        help="Path to vins dimension parquet (s3://... or local). FK source.",
    )
    parser.add_argument(
        "--max-vins", type=int, default=100_000,
        help="Cap on VIN pool size for FK sampling (default 100K, matches spike).",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="s3:// or local path. Local mode writes plain parquet under this prefix.",
    )
    parser.add_argument(
        "--table-name",
        default=DEFAULT_TABLE_NAME,
        help="Iceberg table identifier (Glue catalog mode only).",
    )
    parser.add_argument(
        "--results-out",
        default=None,
        help="Optional path to write JSON summary (sizing, elapsed, edge-case rates).",
    )
    args, _unknown = parser.parse_known_args(argv)
    return args


# ---------------------------------------------------------------------------
# Main entrypoint — Glue 4.0 invokes via spark-submit
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    print(
        f"[telemetry] rows={args.rows:,} days={args.days} "
        f"seed={args.seed} partitions={args.partitions} "
        f"output={args.output_root}"
    )

    spark = _build_spark()
    t0 = time.time()

    vins = _load_vins(spark, args.vins_source, args.max_vins)
    print(f"[telemetry] loaded {len(vins):,} VINs from {args.vins_source}")

    df = _generate_telemetry(
        spark,
        vins=vins,
        rows=args.rows,
        days=args.days,
        seed=args.seed,
    )
    df = _inject_edge_cases(df, seed=args.seed)
    _write_iceberg(
        df,
        table_name=args.table_name,
        output_root=args.output_root,
        partitions=args.partitions,
    )

    elapsed_seconds = time.time() - t0
    stats = _measure_output(args.output_root)
    spark.stop()

    avg_mb = stats.get("avg_bytes", 0) / 1024 / 1024
    total_mb = stats.get("total_bytes", 0) / 1024 / 1024
    bytes_per_row = stats.get("total_bytes", 0) / max(args.rows, 1)

    summary: dict[str, Any] = {
        "product": "vehicle_telemetry_aggregated",
        "scale_tier": "sample" if args.rows <= DEFAULT_TARGET_ROWS else "production",
        "rows": args.rows,
        "days": args.days,
        "seed": args.seed,
        "vins_used": len(vins),
        "output_root": args.output_root,
        "table_name": args.table_name,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "file_count": stats.get("file_count", 0),
        "total_mb": round(total_mb, 2),
        "avg_file_mb": round(avg_mb, 2),
        "bytes_per_row": round(bytes_per_row, 2),
        "edge_case_rates": EDGE_CASE_RATES,
        "edge_case_aggregate_target": round(sum(EDGE_CASE_RATES.values()), 4),
    }
    print(f"[telemetry] summary: {json.dumps(summary, indent=2, default=str)}")
    if args.results_out:
        Path(args.results_out).write_text(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    rc = main()
    # On Glue 4.0, sys.exit() is treated as job failure even with code 0.
    # Print the result and let the driver process exit naturally.
    if rc != 0:
        sys.exit(rc)
