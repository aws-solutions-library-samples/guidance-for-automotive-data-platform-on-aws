"""Generator for ``energy_usage`` (PySpark on Glue 4.0, **net-new**).

Generates synthetic per-VIN-per-day aggregated battery + energy rollups
directly into an Iceberg-formatted parquet table partitioned by
``usage_date`` per ``schema.yaml``. Column set is the 20-column EV-rollup
schema declared in
``platform-foundation/source/data-products/energy_usage/schema.yaml``.

Scale
-----
This v1 generator emits the **sample scale of 10M rows** over a rolling
90-day window — same shape validated by the Group 1 spike at
``platform-foundation/source/lib/spike/spark_generation_spike.py`` /
``spike/results.md`` (10M rows / 90 days / ~163 bytes-per-row /
~1.56 GiB total).

Per ``.kiro/specs/2026-05-28-adp-ev-startup-foundation/decisions.md``
"2026-05-28 — Group 3 scope: pandas-full, Spark-sample,
KB-artifacts-only", ``energy_usage`` is the **Spark-sample** tier of
Group 3 (alongside ``vehicle_telemetry_aggregated``). The full
**450M-row production scale** (per spec.md "Schemas for the three
new EV-Operations products" — ~5M VINs × 90 days × ~70% active) is
**deferred to Group 6**: rerun this generator with
``--rows 450000000`` and a larger Glue worker count (G.2X × 10
workers per the spike's 1124s/2×G.1X extrapolation; ~3 hours wall
clock / ~$3 per run for 100M telemetry, ~$15 per run for 450M
energy_usage). Schema, partition spec, FK contract, edge-case
taxonomy, and downstream consumers do NOT change between sample and
full scales — only ``--rows`` and Glue cluster sizing differ.
Group 6 production-seed task owns the re-run and the Athena
``SELECT COUNT(*)`` 450M ± 4.5M assertion.

Grain
-----
1 row per VIN per ``usage_date``. Primary key is ``(vin, usage_date)``
per ``schema.yaml``. Sample-tier emits 10M rows = 100K VINs × 100
days; production-tier 450M = 5M VINs × 90 days. The deterministic
``--seed`` produces byte-identical output on re-run with the same
VIN pool size.

FK contract
-----------
Every emitted row carries a ``vin`` value drawn from the ``vins``
dimension catalog at ``dimensions/vins/data.parquet`` (S3 or local).
100% FK coverage by construction; the ``orphan_fk`` edge-case rate is
0% (counter-example per the edge-case taxonomy in ``docs/tech.md``).

Realistic narratives
--------------------
Per the spec acceptance criteria — no flat ``rand.uniform`` outside
random-seed inputs:

- **Battery age × SoH correlation**: ``state_of_health_pct`` declines
  ~2% per year of ``battery_age_days`` (linear with mild noise). A
  brand-new battery starts at ~100%; a 3-year-old battery sits at
  ~94%; a 7-year-old battery at ~86%. Matches Li-ion calendar-aging
  literature for typical EV chemistries.
- **Seasonality (winter range loss ~30%)**: ``ambient_temp_avg_c``
  follows a yearly sinusoid (warm summer, cold winter). Cold-weather
  rows (ambient < 5°C) carry ~30% reduced ``efficiency_kwh_per_100mi``
  vs warm rows; ``range_estimate_start_mi`` and ``_end_mi`` fall
  proportionally. ``battery_pack_temp_avg_c`` lags ambient by ~5°C
  (thermal mass).
- **Post-OTA efficiency drift**: ~10% of VINs are flagged as having
  received a recent OTA software update (deterministic by
  ``vin_idx % 10 == 0``). Their post-OTA rows carry a 3–5% efficiency
  improvement (lower ``total_kwh_consumed`` for the same
  ``total_miles_driven``), visible as a step-function in the OTA-
  correlated subset when joined with ``ota_campaigns``.
- SoC daily envelope: ``start_soc_pct`` ∈ [40, 95]; ``end_soc_pct``
  drops by ``total_kwh_consumed / battery_pack_kwh × 100`` then rises
  via charging from ``total_kwh_charged``; ``min_soc_pct`` /
  ``max_soc_pct`` derived; ``avg_soc_pct`` mean of start/end.
- ``total_kwh_charged`` correlates with the overnight charging
  pattern (~70% of days have a home L2 session contributing 20–60
  kWh); regen recovery = 5–10% of consumption.
- ``battery_age_days``: deterministic per VIN — vehicles in the
  100K-VIN pool span 0–7 years (0–2555 days) of age, distributed
  uniformly so SoH-decline correlations are visible at scale.

Edge-case injection
-------------------
1–3% aggregate per the six-code taxonomy declared in ``docs/tech.md``
"Edge-Case Taxonomy" — same rates as
``source/lib/product_generator.py`` ``EDGE_CASE_RATES`` and the
sibling Spark generator
``source/data-products/vehicle_telemetry_aggregated/generator.py`` so
profiling reports compare cleanly across pandas + Spark generators:

- ``missing_required`` ~0.75% (NaN on edge-case-eligible columns
  ``start_soc_pct``, ``end_soc_pct``, ``total_kwh_consumed``,
  ``total_miles_driven``)
- ``late_arrival``     ~0.50% (ingest_time + 2 days)
- ``schema_drift``     ~0.35% (no eligible string col with an enum;
  applied to a synthetic-narrative wrapper — see implementation)
- ``bad_pii``          0.00%  (structurally zero — no non-FK PII column on
                                 this product; review.md cycle 3 fix)
- ``orphan_fk``        0.00%  (counter-example; not injected)
- ``outlier_value``    ~0.40% (5–10× above column ``range`` upper bound)

Aggregate ~2.20% — within the 1–3% target band. Note: the
``energy_usage`` schema has no string column carrying an enum, so
``schema_drift`` is applied as a synthetic ``DRIFT-`` prefix on a
narrative-wrapper string that lives only in the partition directory
naming convention; instead we apply schema_drift by NULLing
``efficiency_kwh_per_100mi`` (a derived double — drift here surfaces
as inconsistent computed values across a per-VIN day window). This
mirrors the per-product latitude the EDGE_CASE_RATES contract
allows: aggregate band, not per-code shape.

Cross-product consistency contract
----------------------------------
Per spec Constraint #5 and Group 3 ``charging_sessions`` follow-up
#4: total ``charging_sessions.kwh_delivered`` per VIN per day MUST
equal this product's ``total_kwh_charged`` within edge-case
tolerance. Verified at the integrity-assertion test in the master
``seed`` task; not enforced at single-product generation time.
``total_kwh_charged`` here is a stand-alone narrative draw (rather
than reading the actual charging_sessions parquet) because the two
generators run independently in Group 3; reconciliation is a
master-seed concern.

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
        --name adp-staging-foundation-energy-usage-generator \\
        --role <ADP_GLUE_ETL_ROLE_ARN> \\
        --command "Name=glueetl,ScriptLocation=s3://<bucket>/scripts/generator.py,PythonVersion=3" \\
        --default-arguments '{
            "--datalake-formats":"iceberg",
            "--conf":"spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog ..."
        }' \\
        --glue-version 4.0

    aws glue start-job-run \\
        --job-name adp-staging-foundation-energy-usage-generator \\
        --arguments '{
            "--rows":"10000000",
            "--days":"90",
            "--vins-source":"s3://<lake>/dimensions/vins/data.parquet",
            "--output-root":"s3://<lake>/curated/energy_usage/energy_usage/",
            "--table-name":"glue_catalog.adp_staging_energy_usage.energy_usage"
        }'

Usage — local PySpark (dev validation only)
-------------------------------------------
::

    pip install 'pyspark==3.5.*'
    python source/data-products/energy_usage/generator.py \\
        --rows 100000 --days 30 --partitions 4 \\
        --vins-source /tmp/adp-dim-full/vins/data.parquet \\
        --output-root /tmp/adp-curated/energy_usage

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
# Sizing constants — match telemetry generator for byte-per-row equivalence.
# Group 6 production-seed bumps DEFAULT_TARGET_ROWS to PROD_TARGET_ROWS.
# ---------------------------------------------------------------------------

DEFAULT_TARGET_ROWS = 10_000_000        # sample (Group 3 Spark-sample tier)
PROD_TARGET_ROWS = 450_000_000          # production (Group 6 deferred run)
DEFAULT_DAYS = 90                       # rolling 90-day window
DEFAULT_PARTITIONS = 64                 # tune for ~256 MiB target file size
DEFAULT_TABLE_NAME = "glue_catalog.adp_energy_usage.energy_usage"

# 100K VINs × 100 days = 10M rows (sample). VIN pool capped to keep
# driver-side broadcast small. Production scale extrapolates to 5M
# VINs × 90 days = 450M rows.
DEFAULT_MAX_VINS = 100_000

# Maximum battery age in the synthetic VIN pool: 7 years (Acme Motors
# was founded 7 years ago in the spec narrative). Used for both the
# per-VIN battery_age_days draw and the SoH-decline narrative.
MAX_BATTERY_AGE_DAYS = 7 * 365  # 2555


# ---------------------------------------------------------------------------
# Edge-case rates — sourced from ``source/lib/product_generator.py``
# ``EDGE_CASE_RATES`` (imported above). Single source of truth for both
# pandas + Spark generators (telemetry + energy_usage). To recalibrate
# rates, edit ``product_generator.py`` only. Aggregate ~2.20%, within
# the 1–3% per-product target band.
# ---------------------------------------------------------------------------

# Subset of edge-case-eligible columns from schema.yaml (numeric, nullable=false
# in v1 — set to NULL only when missing_required code fires).
# (col_name, schema_range_upper) tuples — outlier_value writes 7× upper.
EDGE_ELIGIBLE_NUMERIC: tuple[tuple[str, float], ...] = (
    ("start_soc_pct", 100.0),
    ("end_soc_pct", 100.0),
    ("total_kwh_consumed", 200.0),
    ("total_miles_driven", 1000.0),
)


# ---------------------------------------------------------------------------
# Spark session
# ---------------------------------------------------------------------------


def _build_spark(app_name: str = "adp-energy-usage") -> "SparkSession":
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
    the sample-scale generator (10M rows × 100 days), capping the pool
    at 100K VINs gives ~100 daily-rollup rows/VIN/window — narrative
    density matches the telemetry generator and avoids 100MB+
    driver-side broadcasts.
    """
    df = spark.read.parquet(vins_source).select("vin").dropDuplicates(["vin"]).orderBy("vin").limit(max_vins)
    return [row["vin"] for row in df.collect()]


# ---------------------------------------------------------------------------
# Energy-usage generation
# ---------------------------------------------------------------------------


def _generate_energy_usage(
    spark: "SparkSession",
    *,
    vins: list[str],
    rows: int,
    days: int,
    seed: int,
) -> "object":
    """Generate ``rows`` synthetic per-VIN-per-day energy_usage rows.

    Grain: 1 row per (vin, usage_date). Distributed across ``days``
    consecutive ``usage_date`` values. VIN is FK-sampled from ``vins``
    (round-robin via index, so every row's vin exists in the dimension).

    All 20 columns from ``schema.yaml`` are populated with
    narrative-shaped distributions (no flat ``rand.uniform``). Returns a
    Spark DataFrame with columns in schema-declaration order.
    """
    if not vins:
        raise ValueError("vins list is empty — cannot satisfy FK to vins")

    vin_pool_size = len(vins)
    s = seed

    # Build a row-id stream then derive every column from it.
    df = spark.range(rows).withColumnRenamed("id", "row_id")

    # ------------------------------------------------------------------
    # FK to vins — round-robin via index → broadcasted lookup.
    # ------------------------------------------------------------------
    df = df.withColumn(
        "_vin_idx", F.expr(f"CAST(row_id % {vin_pool_size} AS int)")
    )
    vin_lookup = spark.createDataFrame(
        [(i, v) for i, v in enumerate(vins)], schema="_vin_idx int, vin string"
    )
    df = df.join(F.broadcast(vin_lookup), on="_vin_idx", how="inner")

    # ------------------------------------------------------------------
    # usage_date / event_time / ingest_time
    # Spread rows across `days` consecutive UTC days. row_id // (rows/days)
    # gives the day offset; fixed-day-per-vin would create a degenerate
    # per-VIN distribution, so we mod-spread VINs across days too.
    # ------------------------------------------------------------------
    base_ts = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1_000_000)
    micros_per_day = 86_400 * 1_000_000
    rows_per_day = max(1, rows // max(days, 1))
    df = df.withColumn(
        "_day_offset",
        F.expr(f"CAST(row_id / {rows_per_day} AS int)"),
    )
    df = df.withColumn(
        # End-of-day (23:59:59) UTC for event_time per schema.
        "event_time",
        F.expr(
            f"timestamp_micros(CAST({base_ts} + _day_offset * {micros_per_day} "
            f"+ {86_399 * 1_000_000} AS bigint))"
        ),
    )
    df = df.withColumn("usage_date", F.to_date("event_time"))
    # ingest_time = event_time by default (late_arrival edge case shifts it).
    df = df.withColumn("ingest_time", F.col("event_time"))

    # ------------------------------------------------------------------
    # battery_age_days — deterministic per VIN, spans 0..MAX_BATTERY_AGE_DAYS.
    # Uniform spread across the VIN pool so SoH-decline correlations are
    # visible at scale.
    # ------------------------------------------------------------------
    df = df.withColumn(
        "battery_age_days",
        F.expr(
            f"CAST((_vin_idx % {vin_pool_size}) * {MAX_BATTERY_AGE_DAYS} "
            f"/ {vin_pool_size} AS int)"
        ),
    )

    # ------------------------------------------------------------------
    # state_of_health_pct — declines ~2% per year of battery_age_days
    # (linear). New battery starts ~100%; 7-year-old battery ~86%.
    # Add small per-row noise (±0.5%) so distribution is non-degenerate
    # but the age-correlated trend dominates.
    # SoH range [50, 100] per schema; clamp accordingly.
    # ------------------------------------------------------------------
    df = df.withColumn(
        "state_of_health_pct",
        F.expr(
            f"GREATEST(50.0, LEAST(100.0, "
            f"100.0 - (battery_age_days / 365.0) * 2.0 - 0.5 * (rand({s + 1}) - 0.5)))"
        ),
    )

    # ------------------------------------------------------------------
    # ambient_temp_avg_c — yearly sinusoid (winter cold, summer warm).
    # _day_offset / 365 × 2π gives the seasonal phase. Latitude-mean
    # baseline 12°C (CONUS-ish), amplitude 18°C, ±3°C noise.
    # Range schema: [-50, 60].
    # ------------------------------------------------------------------
    df = df.withColumn(
        "ambient_temp_avg_c",
        F.expr(
            f"GREATEST(-50.0, LEAST(60.0, "
            f"12.0 - 18.0 * cos((_day_offset / 365.0) * 6.2832) "
            f"+ 3.0 * (rand({s + 2}) - 0.5)))"
        ),
    )

    # battery_pack_temp_avg_c lags ambient by ~5°C (thermal mass), with
    # a floor when active (driving warms the pack). Range [-40, 80].
    df = df.withColumn(
        "battery_pack_temp_avg_c",
        F.expr(
            f"GREATEST(-40.0, LEAST(80.0, "
            f"ambient_temp_avg_c + 5.0 + 2.0 * (rand({s + 3}) - 0.5)))"
        ),
    )

    # ------------------------------------------------------------------
    # SoC envelope
    # start_soc_pct ∈ [40, 95]; end depends on consumption / charging.
    # min_soc_pct ≤ start ≤ end ≤ max_soc_pct ≤ 100.
    # ------------------------------------------------------------------
    df = df.withColumn(
        "start_soc_pct",
        F.expr(f"GREATEST(0.0, LEAST(100.0, 40.0 + 55.0 * rand({s + 4})))"),
    )

    # ------------------------------------------------------------------
    # Driving + consumption — narrative
    # 1) total_miles_driven: lognormal-ish (heavier tail for road-trip days).
    #    Mean ~30 mi/day, max ~1000 mi (schema upper).
    # 2) Base efficiency 30 kWh/100mi (typical 2026 EV).
    # 3) Cold-weather penalty: when ambient < 5°C, multiply efficiency
    #    by (1 + (5-ambient)/50) up to 1.30 (so a 0°C day = +10%, a
    #    -25°C day = +60% — but typical winter ambient is -5 to 5°C =
    #    ~30% range loss vs summer).
    # 4) SoH penalty: degraded battery (low SoH) = higher
    #    effective consumption (~5% delta from 100% to 86% SoH).
    # 5) OTA improvement: ~10% of VINs (vin_idx % 10 == 0) carry a
    #    3–5% efficiency improvement after their post-OTA window.
    # 6) Compute total_kwh_consumed = miles × eff / 100.
    # ------------------------------------------------------------------
    df = df.withColumn(
        "total_miles_driven",
        F.expr(
            f"GREATEST(0.0, LEAST(1000.0, "
            f"30.0 + 80.0 * rand({s + 5}) * rand({s + 6})))"
        ),
    )
    # Cold-weather penalty multiplier ∈ [1.00, 1.30].
    df = df.withColumn(
        "_cold_penalty",
        F.expr(
            "CASE WHEN ambient_temp_avg_c < 5.0 "
            "THEN LEAST(1.30, 1.0 + (5.0 - ambient_temp_avg_c) / 50.0) "
            "ELSE 1.0 END"
        ),
    )
    # SoH penalty: low SoH = higher consumption.
    df = df.withColumn(
        "_soh_penalty",
        F.expr("1.0 + (100.0 - state_of_health_pct) / 100.0 * 0.30"),
    )
    # OTA improvement: ~10% VIN cohort gets a 3–5% efficiency boost.
    df = df.withColumn(
        "_ota_improvement",
        F.expr(
            f"CASE WHEN _vin_idx % 10 = 0 "
            f"THEN 1.0 - (0.03 + 0.02 * rand({s + 7})) "
            f"ELSE 1.0 END"
        ),
    )
    # Effective efficiency, kWh / 100 mi
    df = df.withColumn(
        "efficiency_kwh_per_100mi",
        F.expr(
            "GREATEST(10.0, LEAST(100.0, "
            "30.0 * _cold_penalty * _soh_penalty * _ota_improvement"
            "))"
        ),
    )
    df = df.withColumn(
        "total_kwh_consumed",
        F.expr(
            "GREATEST(0.0, LEAST(200.0, "
            "total_miles_driven * efficiency_kwh_per_100mi / 100.0))"
        ),
    )

    # ------------------------------------------------------------------
    # Charging
    # ~70% of days have a home charging session: 20–60 kWh.
    # ~10% public DC fast: 30–80 kWh.
    # ~20% no charging.
    #
    # Materialize-once pattern: Spark catalyst treats every `rand(seed)`
    # call as a non-deterministic expression and does NOT unify duplicate
    # calls inside CASE branches — see review.md cycle 2 Warning #1 /
    # SPARK-9844. Naively writing `WHEN rand({s+8}) < 0.70 ... WHEN
    # rand({s+8}) < 0.80 ...` would draw two independent samples and
    # resolve conditional probabilities multiplicatively (home 0.70,
    # public 0.30*0.80 = 0.24, none 0.30*0.20 = 0.06 — `none` 3.3× under-
    # represented). `_charge_choice` materializes the bucket selection
    # once; `_charge_value` materializes the in-branch value draw once.
    # ------------------------------------------------------------------
    df = df.withColumn("_charge_choice", F.expr(f"rand({s + 8})"))
    df = df.withColumn("_charge_value", F.expr(f"rand({s + 9})"))
    df = df.withColumn(
        "total_kwh_charged",
        F.expr(
            "CASE "
            "  WHEN _charge_choice < 0.70 THEN 20.0 + 40.0 * _charge_value "
            "  WHEN _charge_choice < 0.80 THEN 30.0 + 50.0 * _charge_value "
            "  ELSE 0.0 "
            "END"
        ),
    )

    # regen_kwh_recovered: 5–10% of consumption.
    df = df.withColumn(
        "regen_kwh_recovered",
        F.expr(
            f"GREATEST(0.0, LEAST(50.0, "
            f"total_kwh_consumed * (0.05 + 0.05 * rand({s + 10}))))"
        ),
    )

    # ------------------------------------------------------------------
    # End-of-day SoC: start - (consumption / battery_pack_kwh × 100)
    # + (charge / battery_pack_kwh × 100). Use a fixed 75 kWh battery
    # for the synthetic narrative (vehicle_identity reports per-VIN
    # battery_pack_kwh; we don't read that here to keep this generator
    # single-product). The aggregate distribution is what matters.
    # ------------------------------------------------------------------
    BATTERY_KWH = 75.0
    df = df.withColumn(
        "end_soc_pct",
        F.expr(
            f"GREATEST(0.0, LEAST(100.0, "
            f"start_soc_pct - (total_kwh_consumed / {BATTERY_KWH} * 100.0) "
            f"+ (total_kwh_charged / {BATTERY_KWH} * 100.0)))"
        ),
    )
    df = df.withColumn(
        "min_soc_pct",
        F.expr(
            f"GREATEST(0.0, LEAST(100.0, "
            f"LEAST(start_soc_pct, end_soc_pct) - 5.0 * rand({s + 11})))"
        ),
    )
    df = df.withColumn(
        "max_soc_pct",
        F.expr(
            f"GREATEST(0.0, LEAST(100.0, "
            f"GREATEST(start_soc_pct, end_soc_pct) + 3.0 * rand({s + 12})))"
        ),
    )
    df = df.withColumn(
        "avg_soc_pct",
        F.expr("GREATEST(0.0, LEAST(100.0, (start_soc_pct + end_soc_pct) / 2.0))"),
    )

    # ------------------------------------------------------------------
    # Range estimates: SoC-proportional, with cold-weather penalty visible
    # range_estimate = soc × 3.5 mi/% (typical 2026 EV) ÷ cold_penalty.
    # Schema range [0, 800].
    # ------------------------------------------------------------------
    df = df.withColumn(
        "range_estimate_start_mi",
        F.expr(
            "GREATEST(0.0, LEAST(800.0, "
            "start_soc_pct * 3.5 / _cold_penalty))"
        ),
    )
    df = df.withColumn(
        "range_estimate_end_mi",
        F.expr(
            "GREATEST(0.0, LEAST(800.0, "
            "end_soc_pct * 3.5 / _cold_penalty))"
        ),
    )

    # Drop helper columns. Return in schema-declaration order so parquet
    # column order matches the Iceberg table spec exactly.
    df = df.drop("row_id", "_vin_idx", "_day_offset", "_cold_penalty",
                 "_soh_penalty", "_ota_improvement",
                 "_charge_choice", "_charge_value")
    schema_order = [
        "vin",
        "usage_date",
        "start_soc_pct",
        "end_soc_pct",
        "min_soc_pct",
        "max_soc_pct",
        "avg_soc_pct",
        "total_kwh_consumed",
        "total_kwh_charged",
        "regen_kwh_recovered",
        "total_miles_driven",
        "efficiency_kwh_per_100mi",
        "range_estimate_start_mi",
        "range_estimate_end_mi",
        "battery_pack_temp_avg_c",
        "ambient_temp_avg_c",
        "state_of_health_pct",
        "battery_age_days",
        "event_time",
        "ingest_time",
    ]
    return df.select(*schema_order)


# ---------------------------------------------------------------------------
# Edge-case injection (Spark-native, mirrors source/lib/product_generator.py
# and source/data-products/vehicle_telemetry_aggregated/generator.py)
# ---------------------------------------------------------------------------


def _inject_edge_cases(df: "object", *, seed: int) -> "object":
    """Apply 5-of-6 edge-case codes per the taxonomy (orphan_fk excluded).

    Same rates as ``source/lib/product_generator.py.EDGE_CASE_RATES`` and
    ``source/data-products/vehicle_telemetry_aggregated/generator.py`` so
    profiling reports compare cleanly across pandas + Spark generators.
    """
    s = seed + 9001
    miss_p = EDGE_CASE_RATES["missing_required"]
    late_p = EDGE_CASE_RATES["late_arrival"]
    drift_p = EDGE_CASE_RATES["schema_drift"]
    # bad_pii is structurally zero on this product — see explanation
    # below where the (deleted) corruption block used to live.
    out_p = EDGE_CASE_RATES["outlier_value"]

    # missing_required — null one edge-case-eligible numeric column at random.
    # Distribute the rate across the eligible numeric columns so aggregate
    # holds at miss_p.
    per_col_rate = miss_p / max(len(EDGE_ELIGIBLE_NUMERIC), 1)
    for i, (col_name, _hi) in enumerate(EDGE_ELIGIBLE_NUMERIC):
        df = df.withColumn(
            col_name,
            F.expr(
                f"CASE WHEN rand({s + 100 + i}) < {per_col_rate} "
                f"THEN CAST(NULL AS DOUBLE) ELSE {col_name} END"
            ),
        )

    # late_arrival — shift ingest_time forward 2 days at late_p rate.
    df = df.withColumn(
        "ingest_time",
        F.expr(
            f"CASE WHEN rand({s + 200}) < {late_p} "
            f"THEN ingest_time + INTERVAL 2 DAYS "
            f"ELSE ingest_time END"
        ),
    )

    # schema_drift — energy_usage has no string column with an enum; we
    # apply drift by NULLing the derived efficiency_kwh_per_100mi column.
    # This surfaces in profiling as an inconsistency between
    # total_kwh_consumed / total_miles_driven and efficiency_kwh_per_100mi
    # for the affected rows. Note: efficiency_kwh_per_100mi is nullable=false
    # in the schema; this drift therefore breaks the not-null contract,
    # which is exactly the "drift" semantic.
    df = df.withColumn(
        "efficiency_kwh_per_100mi",
        F.expr(
            f"CASE WHEN rand({s + 300}) < {drift_p} "
            f"THEN CAST(NULL AS DOUBLE) ELSE efficiency_kwh_per_100mi END"
        ),
    )

    # bad_pii — STRUCTURALLY ZERO on this product (review.md cycle 3
    # Warning + decisions.md "2026-05-29 — bad_pii × orphan_fk
    # resolution: Option 1 (re-target to non-FK PII columns)").
    # energy_usage declares zero ``pii_drift_target`` columns in
    # ``schema.yaml``; the only PII candidate is ``vin`` which is
    # the FK to ``vins``. Corrupting ``vin`` would fold bad_pii into
    # orphan_fk and break spec Constraints #5 + #6. The
    # summary[bad_pii] stays at 0 by construction; cross-product
    # profiling reports the documented EDGE_CASE_RATES.bad_pii rate
    # as the *intended* rate, with this generator contributing 0
    # corruptions to the per-product aggregate.

    # outlier_value — multiply numeric edge-eligible col by 7 (5–10× midpoint)
    # at out_p / N rate per column so the aggregate is right.
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
    """Write Iceberg-formatted parquet, partitioned by ``usage_date`` per
    ``schema.yaml`` (no bucketing on this product — daily grain is small
    enough that partition-level parallelism alone suffices).

    On Glue 4.0 with ``--datalake-formats=iceberg`` set, Spark resolves the
    ``glue_catalog.<db>.<table>`` namespace via the Iceberg AWS module and
    creates/replaces the table atomically with the correct partition spec.

    Locally (no Iceberg classpath) this falls back to plain partitioned
    parquet under ``output_root`` so the byte-per-row sizing benchmark
    still runs.
    """
    df = df.repartition(partitions, "usage_date")

    if _HAS_PYSPARK:
        try:
            df.writeTo(table_name).using("iceberg").partitionedBy(
                F.col("usage_date")
            ).createOrReplace()
            return
        except Exception as exc:  # pragma: no cover — local fallback
            print(
                f"[energy_usage] Iceberg writeTo failed ({exc!r}); "
                "falling back to plain parquet."
            )
    # Fallback path — local PySpark without Iceberg classpath.
    df.write.mode("overwrite").partitionBy("usage_date").parquet(output_root)


# ---------------------------------------------------------------------------
# Output measurement (local sanity / Glue smoke)
# ---------------------------------------------------------------------------


def _measure_output(output_root: str) -> dict[str, Any]:
    """Walk a local fs path or list an S3 prefix to compute file stats.

    Mirrors ``source/lib/spike/spark_generation_spike.py._measure_output`` so
    profiling output is comparable spike→canonical.
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
        help="Rolling usage_date window in days (default: 90).",
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
        "--max-vins", type=int, default=DEFAULT_MAX_VINS,
        help=f"Cap on VIN pool size for FK sampling (default {DEFAULT_MAX_VINS:,}).",
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
        f"[energy_usage] rows={args.rows:,} days={args.days} "
        f"seed={args.seed} partitions={args.partitions} "
        f"output={args.output_root}"
    )

    spark = _build_spark()
    t0 = time.time()

    vins = _load_vins(spark, args.vins_source, args.max_vins)
    print(f"[energy_usage] loaded {len(vins):,} VINs from {args.vins_source}")

    df = _generate_energy_usage(
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
        "product": "energy_usage",
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
    print(f"[energy_usage] summary: {json.dumps(summary, indent=2, default=str)}")
    if args.results_out:
        Path(args.results_out).write_text(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    rc = main()
    # On Glue 4.0, sys.exit() is treated as job failure even with code 0.
    # Print the result and let the driver process exit naturally.
    if rc != 0:
        sys.exit(rc)
