# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import json
import sys
from collections import namedtuple
from typing import Dict, List
from datetime import datetime, timedelta

# Third Party Libraries
import boto3
from awsglue.utils import getResolvedOptions
from pyspark.ml import Transformer
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import col, isnan, lag, lit, lower, coalesce, to_timestamp, mean as spark_mean, stddev as spark_std, when, first, last, count
from pyspark.sql.types import FloatType
from pyspark.sql.window import Window

# Initialize Spark session
spark = SparkSession.builder.appName("ETLSession").getOrCreate()

class CleanAndFormatDataAndAddMetadata(Transformer):  # type: ignore[misc]
    def __init__(self) -> None:
        return

    def _transform(
        self,
        df: DataFrame,  # pylint: disable=redefined-outer-name
    ) -> [DataFrame, List[str]]:
        # Calculate additional metadata columns
        # Get first and last pressure values and timestamps
        # Only drop rows where essential columns are null
        df = df.na.drop(subset=["vehicle_id", "tire_id", "timestamp"])

        df = df.withColumn(
        "timestamp",
            coalesce(
                to_timestamp(col("timestamp"), "yyyy-MM-dd HH:mm:ss.SSSX"),
                to_timestamp(col("timestamp"), "yyyy-MM-dd HH:mm:ss.SSS"),
                to_timestamp(col("timestamp"), "yyyy-MM-dd HH:mm:ssX"),
                to_timestamp(col("timestamp"), "yyyy-MM-dd HH:mm:ss"),
            ),
        )

        w = Window.partitionBy("vehicle_id", "tire_id").orderBy("timestamp")
        df = df.withColumn("first_timestamp", first("timestamp").over(w))
        df = df.withColumn("last_timestamp", last("timestamp").over(w))

        return [df, ["first_timestamp", "last_timestamp"]]

class AddEngineeredNumericFeatures(Transformer):  # type: ignore[misc]
    def __init__(self) -> None:
        return

    def _transform(self, dataframe: DataFrame) -> [DataFrame, List[str]]:
        # Calculate daily pressure differences
        w = Window.partitionBy("vehicle_id", "tire_id").orderBy("timestamp")

        dataframe = dataframe.withColumn(
            "prev_pressure", lag("pressure").over(w)
        )
        dataframe = dataframe.withColumn(
            "prev_temp", lag("temperature").over(w)
        )
        dataframe = dataframe.withColumn(
            "delta_pressure", col("prev_pressure") - col("pressure")
        )
        dataframe = dataframe.withColumn(
            "delta_temp", col("temperature") - col("prev_temp")
        )

        # Keep daily deltas for now, will aggregate later
        dataframe = dataframe.drop("prev_pressure", "prev_temp")
        engineered_numeric_features = ["delta_pressure", "delta_temp"]
        return [dataframe, engineered_numeric_features]

class CategorizeAndNormalizeFeatAndMetaData(Transformer):  # type: ignore[misc]
    def __init__(self, existing_stats: Dict[str, Dict[str, float]]) -> None:
        super().__init__()
        bool_cat_cols_map = namedtuple(
            "bool_cat_cols_map", ["column_name", "col_type", "mappings"]
        )
        self.bool_and_cat_cols: List[bool_cat_cols_map] = []
        self.existing_stats = existing_stats
        self.updated_stats = {}

    def _transform(
        self,
        df: DataFrame,  # pylint: disable=redefined-outer-name
        numeric_features: List[str],
    ) -> DataFrame:
        # Encode categorical and boolean columns
        for bool_and_cat_col_tuple in self.bool_and_cat_cols:
            col_name, col_type, mapping = (
                bool_and_cat_col_tuple.column_name,
                bool_and_cat_col_tuple.col_type,
                bool_and_cat_col_tuple.mappings,
            )
            if col_type == "bool":
                df = df.withColumn(col_name, col(col_name).cast("int"))
            else:
                map_expr = when(col(col_name).isNull(), -1)
                for k, v in mapping.items():
                    map_expr = map_expr.when(lower(col(col_name)) == k.lower(), v)
                df = df.withColumn(col_name, map_expr.cast("int"))
            df = df.withColumn(
                col_name,
                when(isnan(col(col_name)) | col(col_name).isNull(), lit(0)).otherwise(
                    col(col_name)
                ),
            )

        # Normalize numerical continuous data with running statistics
        for feat in numeric_features:
            # Get current batch statistics
            batch_stats = df.select(
                spark_mean(feat).alias("mean"),
                spark_std(feat).alias("std"),
                count(feat).alias("count"),
            ).collect()[0]

            batch_mean = batch_stats["mean"] or 0.0
            batch_std = batch_stats["std"] or 1.0
            batch_count = batch_stats["count"] or 0

            # Get existing stats from SSM
            existing_mean = self.existing_stats.get(feat, {}).get("mean")
            existing_std = self.existing_stats.get(feat, {}).get("std")
            existing_count = self.existing_stats.get(feat, {}).get("count", 0)

            # Handle edge case: first run with None values
            if existing_mean is None or existing_std is None or existing_count == 0:
                # First run - use batch statistics directly
                updated_mean = batch_mean
                updated_std = batch_std
                updated_count = batch_count
            else:
                # Subsequent runs - combine statistics using Welford's algorithm
                total_count = existing_count + batch_count

                # Combined mean
                updated_mean = (
                    existing_count * existing_mean + batch_count * batch_mean
                ) / total_count

                # Combined variance
                existing_var = existing_std**2
                batch_var = batch_std**2
                combined_var = (
                    (existing_count - 1) * existing_var
                    + (batch_count - 1) * batch_var
                    + (existing_count * batch_count / total_count)
                    * (existing_mean - batch_mean) ** 2
                ) / (total_count - 1) if total_count > 1 else 0.0

                updated_std = combined_var**0.5 if combined_var > 0 else 1.0
                updated_count = total_count

            # Normalize using updated statistics
            df = df.withColumn(
                feat, ((col(feat) - lit(updated_mean)) / lit(updated_std)).cast(FloatType())
            )
            df = df.withColumn(
                feat,
                when(isnan(col(feat)) | col(feat).isNull(), lit(0.0)).otherwise(
                    col(feat)
                ),
            )

            # Store updated stats for writing back to SSM
            self.updated_stats[feat] = {
                "mean": float(updated_mean),
                "std": float(updated_std),
                "count": int(updated_count),
            }

        df = df.dropna("any")
        return df


args = getResolvedOptions(
    sys.argv,
    [
        "normalization-stats-parameter",
        "source-s3-bucket-uri",
        "training-s3-bucket-uri",
        "inference-s3-bucket-uri",
        "current-date",
    ],
)

normalization_stats_parameter = args["normalization_stats_parameter"]
source_s3_bucket_uri = args["source_s3_bucket_uri"]
training_s3_bucket_uri = args["training_s3_bucket_uri"]
inference_s3_bucket_uri = args["inference_s3_bucket_uri"]
current_date_arg = args["current_date"]

# Determine current date: use provided date if valid YYYY-MM-DD format, otherwise use UTC now
current_date = None
if current_date_arg and current_date_arg != "default":
    try:
        # Validate format YYYY-MM-DD
        current_date = datetime.strptime(current_date_arg, "%Y-%m-%d")
    except ValueError:
        # Invalid format, fall back to UTC now
        current_date = datetime.utcnow()
else:
    # "default" or empty, use UTC now
    current_date = datetime.utcnow()

previous_date = current_date - timedelta(days=1)

# Construct S3 paths using date partitioning (yyyy/mm/dd)
date_path = previous_date.strftime("%Y/%m/%d")
input_paths = f"{source_s3_bucket_uri}/{date_path}/"
training_output_path = f"{training_s3_bucket_uri}/{date_path}/"
inference_output_path = f"{inference_s3_bucket_uri}/{date_path}/"

# Read existing normalization statistics from SSM
ssm_client = boto3.client("ssm")
response = ssm_client.get_parameter(Name=normalization_stats_parameter)
existing_stats = json.loads(response["Parameter"]["Value"])

# Read dataset from previous day's partition
df = spark.read.option("header", True).option("recursiveFileLookup", "true").csv(input_paths)

default_numeric_features = ["pressure", "temperature"]
default_categorical_features = []
default_metadata = ["vehicle_id", "tire_id"]

# Transform Data
df, additional_metadata = CleanAndFormatDataAndAddMetadata().transform(df)
df, engineered_numeric_features = AddEngineeredNumericFeatures().transform(df)
normalizer = CategorizeAndNormalizeFeatAndMetaData(existing_stats)
df = normalizer._transform(df, default_numeric_features + engineered_numeric_features)

# In both training and inference cols order matters
# inference feature columns should be in same order as inference feature columns
TRAINING_COLUMNS = default_numeric_features + engineered_numeric_features + default_categorical_features
INFERENCE_COLUMNS = default_metadata + additional_metadata + default_numeric_features + engineered_numeric_features

df.select(*TRAINING_COLUMNS).coalesce(1).write.option("header", "False").option(
    "emptyValue", "0.0"
).mode("overwrite").csv(training_output_path)

df.select(*INFERENCE_COLUMNS).coalesce(1).write.option("header", "False").option(
    "emptyValue", "0.0"
).mode("overwrite").csv(inference_output_path)

# Write updated normalization statistics back to SSM
updated_stats_json = json.dumps(normalizer.updated_stats)
ssm_client.put_parameter(
    Name=normalization_stats_parameter,
    Value=updated_stats_json,
    Overwrite=True,
)

spark.stop()
