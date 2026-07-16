# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
governed_etl_job.py — PM Governed ETL Job
==========================================
PySpark Glue 5.0 script.  Reads three governed ADP platform-foundation data
products via Lake Formation-governed Glue catalog access (LF issues short-lived
S3 credentials; no hard-coded s3:GetObject on the lake bucket), joins them on
``vin`` + ``event_date``, and writes a training-ready Parquet dataset to the PM
training bucket.

Source products (all Iceberg, read via ``awsglue.context.GlueContext``):
  * ``adp_{stage}_tire_health.tire_health``
  * ``adp_{stage}_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated``
  * ``adp_{stage}_service_records.service_records``

Output layouts written to the PM training bucket:
  ``s3://{training-bucket}/training/rcf/``
      Unlabeled feature vector CSV: 10 columns (no label).
      Format expected by RCF ``text/csv;label_size=0``.
  ``s3://{training-bucket}/training/xgboost/``
      Labeled CSV: label (wear_category ordinal) + 10 feature columns.
      Format expected by XGBoost ``text/csv`` (label in column 0).

Join contract (per docs/tech.md §4.7):
  * tire_health ↔ VTA: LEFT JOIN on ``vin``, ``event_date``
    (daily grain; VTA has no per-tire granularity)
  * tire_health ↔ service_records: LEFT JOIN on ``vin``,
    filter ``service_type = 'tire_service'``, window-join on
    service_date within trailing 30 days of event_date

Features selected (10, matching RCF feature_dim=10):
  1.  tread_depth_mm           (tire_health)
  2.  pressure_psi_avg         (tire_health)
  3.  pressure_psi_min         (tire_health)
  4.  pressure_psi_max         (tire_health)
  5.  temp_c_avg               (tire_health)
  6.  temp_c_max               (tire_health)
  7.  wear_rate_mm_per_1k_km   (tire_health)
  8.  distance_km              (tire_health)
  9.  speed_kmh                (VTA, NULL-filled if no VTA row)
  10. ambient_temp_avg_c       (VTA, NULL-filled if no VTA row)

Label (for XGBoost supervised path):
  wear_category ordinal: ok=0, monitor=1, replace=2

Usage (invoked by Glue job via ``--default_arguments``):
  --stage                      staging | prod
  --training-s3-bucket-uri     s3://<pm-training-bucket>
  --normalization-stats-parameter  /tire-maintenance/normalization-stats
  --athena-workgroup           pm-staging-analytics | pm-prod-analytics
  --current-date               YYYY-MM-DD | "default" (uses today)
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from typing import Any, Optional

# Glue / PySpark imports (available in Glue 5.0 runtime)
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql import Window
from pyspark.sql.types import DoubleType, IntegerType

import boto3

# ---------------------------------------------------------------------------
# Glue job bootstrap
# ---------------------------------------------------------------------------
args = getResolvedOptions(
    sys.argv,
    [
        "JOB_NAME",
        "stage",
        "training-s3-bucket-uri",
        "normalization-stats-parameter",
        "athena-workgroup",
        "current-date",
    ],
)

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args["JOB_NAME"], args)

_STAGE = args["stage"]
_TRAINING_BUCKET = args["training_s3_bucket_uri"].rstrip("/")
_STATS_PARAM = args["normalization_stats_parameter"]
_WORKGROUP = args["athena_workgroup"]
_CURRENT_DATE: Optional[date] = (
    None
    if args["current_date"] == "default"
    else datetime.strptime(args["current_date"], "%Y-%m-%d").date()
)


# ---------------------------------------------------------------------------
# Helper: read Iceberg table from LF-governed Glue catalog
# ---------------------------------------------------------------------------

def read_governed_table(
    glue_context: GlueContext,
    database: str,
    table_name: str,
) -> DataFrame:
    """Read an Iceberg table via LF-governed Glue Data Catalog.

    GlueContext.create_dynamic_frame.from_catalog() uses the IAM role's
    ``lakeformation:GetDataAccess`` permission to obtain temporary S3
    credentials from LF — no direct s3:GetObject required on the lake
    bucket ARN.

    Parameters
    ----------
    database : str
        Glue database name, e.g. ``adp_staging_tire_health``.
    table_name : str
        Glue table name, e.g. ``tire_health``.
    """
    dyf = glue_context.create_dynamic_frame.from_catalog(
        database=database,
        table_name=table_name,
        additional_options={
            "useS3ListImplementation": True,
        },
    )
    return dyf.toDF()


# ---------------------------------------------------------------------------
# Load the three governed tables
# ---------------------------------------------------------------------------
tire_health_db = f"adp_{_STAGE}_tire_health"
vta_db = f"adp_{_STAGE}_vehicle_telemetry_aggregated"
sr_db = f"adp_{_STAGE}_service_records"

tire_health_df = read_governed_table(glueContext, tire_health_db, "tire_health")
vta_df = read_governed_table(glueContext, vta_db, "vehicle_telemetry_aggregated")
sr_df = read_governed_table(glueContext, sr_db, "service_records")

# ---------------------------------------------------------------------------
# Filter VTA to driving segments (not charging) — per tech.md §3.7
# ---------------------------------------------------------------------------
vta_filtered = vta_df.filter(F.col("is_charging") == False).select(
    "vin",
    "event_date",
    F.col("speed_kmh").cast(DoubleType()),
    F.col("ambient_temp_avg_c").cast(DoubleType()),
    F.col("total_miles_driven").cast(DoubleType()),
)

# ---------------------------------------------------------------------------
# Filter service_records to tire_service events only
# ---------------------------------------------------------------------------
tire_service_df = sr_df.filter(F.col("service_type") == "tire_service").select(
    "vin",
    F.col("service_date").alias("tire_service_date"),
)

# ---------------------------------------------------------------------------
# Join tire_health ↔ VTA (LEFT JOIN on vin + event_date)
# ---------------------------------------------------------------------------
joined_df = tire_health_df.join(
    vta_filtered,
    on=["vin", "event_date"],
    how="left",
)

# ---------------------------------------------------------------------------
# Join tire_health ↔ most recent tire_service within trailing 30 days.
# Window approach: for each (vin, event_date), find service_date
# in [event_date - 30d, event_date] and take the most recent.
# ---------------------------------------------------------------------------
# Add event_date as long (days since epoch) for window arithmetic
joined_df = joined_df.withColumn(
    "event_date_long", F.datediff(F.col("event_date"), F.lit("1970-01-01"))
)
tire_service_df = tire_service_df.withColumn(
    "service_date_long", F.datediff(F.col("tire_service_date"), F.lit("1970-01-01"))
)

# Broadcast the tire_service_df (much smaller) for the range join
tire_service_small = tire_service_df.alias("ts")
joined_df = joined_df.alias("jd")

# Range join: keep only the most recent tire_service within 30 days
joined_with_service = (
    joined_df
    .join(
        tire_service_small,
        on=(
            (F.col("jd.vin") == F.col("ts.vin"))
            & (F.col("ts.service_date_long") <= F.col("jd.event_date_long"))
            & (F.col("ts.service_date_long") >= F.col("jd.event_date_long") - 30)
        ),
        how="left",
    )
    .drop(F.col("ts.vin"))
)

# Keep only the most recent tire_service per (vin, event_date, tire_id)
window_spec = Window.partitionBy("jd.vin", "jd.event_date", "tire_id").orderBy(
    F.col("ts.service_date_long").desc()
)
joined_with_service = (
    joined_with_service
    .withColumn("row_num", F.row_number().over(window_spec))
    .filter(F.col("row_num") == 1)
    .drop("row_num")
)

# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------
# Encode wear_category as ordinal integer for XGBoost classification
wear_category_map = {"ok": 0, "monitor": 1, "replace": 2}
# Use a simple integer encoding; nulls → -1 (filtered before training)
joined_features = joined_with_service.withColumn(
    "wear_category_ordinal",
    F.when(F.col("wear_category") == "ok", 0)
    .when(F.col("wear_category") == "monitor", 1)
    .when(F.col("wear_category") == "replace", 2)
    .otherwise(-1),
)

# Select the 10-feature vector + label columns
feature_cols = [
    "tread_depth_mm",
    "pressure_psi_avg",
    "pressure_psi_min",
    "pressure_psi_max",
    "temp_c_avg",
    "temp_c_max",
    "wear_rate_mm_per_1k_km",
    "distance_km",
    "speed_kmh",
    "ambient_temp_avg_c",
]
label_col = "wear_category_ordinal"

# Replace nulls in VTA-derived columns (speed_kmh, ambient_temp_avg_c)
# with 0.0 so RCF / XGBoost get numeric values.
for col_name in ("speed_kmh", "ambient_temp_avg_c"):
    joined_features = joined_features.withColumn(
        col_name, F.coalesce(F.col(col_name), F.lit(0.0))
    )

# Drop rows with nulls in required feature columns
training_base = joined_features.dropna(subset=feature_cols)
# Drop rows with invalid label (only relevant for XGBoost path)
training_labeled = training_base.filter(F.col(label_col) >= 0)

# ---------------------------------------------------------------------------
# Write RCF layout: 10 unlabeled feature columns as CSV
# ---------------------------------------------------------------------------
rcf_output = _TRAINING_BUCKET + "/training/rcf"
training_base.select(feature_cols).write.mode("overwrite").option(
    "header", False
).csv(rcf_output)

# ---------------------------------------------------------------------------
# Write XGBoost layout: label col 0 + 10 feature columns as CSV
# ---------------------------------------------------------------------------
xgboost_output = _TRAINING_BUCKET + "/training/xgboost"
training_labeled.select([label_col] + feature_cols).write.mode("overwrite").option(
    "header", False
).csv(xgboost_output)

# ---------------------------------------------------------------------------
# Compute and persist normalization stats (mean + stddev per feature)
# for the real-time inference Lambda (re-uses existing SSM param).
# ---------------------------------------------------------------------------
stats: dict[str, Any] = {}
for col_name in feature_cols:
    row = training_base.select(
        F.mean(F.col(col_name)).alias("mean"),
        F.stddev(F.col(col_name)).alias("stddev"),
    ).first()
    stats[col_name] = {
        "mean": float(row["mean"]) if row["mean"] is not None else 0.0,
        "stddev": float(row["stddev"]) if row["stddev"] is not None else 1.0,
    }

ssm_client = boto3.client("ssm")
ssm_client.put_parameter(
    Name=_STATS_PARAM,
    Value=json.dumps(stats),
    Type="String",
    Overwrite=True,
)

job.commit()
