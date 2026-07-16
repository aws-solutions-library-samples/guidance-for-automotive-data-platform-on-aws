# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
ETLConstruct
============
Aggregates the PM ETL layer:

  * ETL data buckets (raw / training / inference).
  * Normalization stats SSM parameter.
  * Original self-contained ETL pipeline (reads from ``raw_data_bucket``).
  * NEW: Governed ETL pipeline (reads via Lake Formation / DataZone
    subscription) — wired when ``stage`` is supplied.

When ``stage`` is set, the construct also provisions:
  * ``GovernedDataAccessConstruct`` — IAM role + DataZone subscription
    permissions (LF-governed read path, no direct s3:GetObject on lake).
  * ``GovernedGlueEtlConstruct`` — Glue 5.0 job that joins tire_health +
    VTA + service_records via LF and writes to ``training_data_bucket``.
"""

# Standard Library
import os

# AWS Libraries
from aws_cdk import aws_lambda, aws_s3
from constructs import Construct

# Predictive Maintenance
from ..common.encrypted_s3 import LifecycleConfig
from .etl_constructs.etl_data_buckets import ETLDataBuckets
from .etl_constructs.etl_glue_jobs import ETLPipeline
from .etl_constructs.governed_glue_etl import GovernedGlueEtlConstruct
from .etl_constructs.normalization_stats import NormalizationStats
from .governed_data_access import GovernedDataAccessConstruct


class ETLConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        id: str,
        common_dependency_layer: aws_lambda.LayerVersion,
        asset_bucket: aws_s3.Bucket,
        query_cron_string: str,
        etl_cron_string: str,
        s3_log_lifecycle_rules: LifecycleConfig,
        stage: str = "prod",  # deployment stage; used for governed ETL
    ):
        super().__init__(scope, id)

        self.etl_data_buckets = ETLDataBuckets(
            self, "etl-data-buckets", s3_log_lifecycle_rules=s3_log_lifecycle_rules
        )

        # Create normalization stats SSM parameter
        self.normalization_stats = NormalizationStats(self, "normalization-stats")

        # ------------------------------------------------------------------
        # Original self-contained ETL pipeline (raw_data_bucket → training).
        # Retained for backward-compatibility and rollback.
        # ------------------------------------------------------------------
        self.etl_pipeline = ETLPipeline(
            self,
            "etl-glue-jobs",
            asset_bucket=asset_bucket,
            etl_glue_scripts_location=f"{os.getcwd()}/../assets/etl_scripts/",
            etl_data_buckets=self.etl_data_buckets,
            normalization_stats=self.normalization_stats,
        )

        # ------------------------------------------------------------------
        # Governed ETL pipeline (LF-governed → training).
        # Reads tire_health + VTA + service_records via DataZone subscription
        # → Lake Formation auto-grant → Glue Catalog.
        # No direct s3:GetObject on the lake bucket.
        # ------------------------------------------------------------------
        self.governed_access = GovernedDataAccessConstruct(
            self,
            "governed-data-access",
            stage=stage,
            training_data_bucket=self.etl_data_buckets.training_data_bucket,
            inference_data_bucket=self.etl_data_buckets.inference_data_bucket,
        )

        self.governed_etl = GovernedGlueEtlConstruct(
            self,
            "governed-glue-etl",
            stage=stage,
            glue_etl_role=self.governed_access.glue_etl_role,
            asset_bucket=asset_bucket,
            training_data_bucket=self.etl_data_buckets.training_data_bucket,
            normalization_stats_ssm_parameter=self.normalization_stats.stats_ssm_parameter,
            pm_workgroup_name=self.governed_access.pm_workgroup_name,
            etl_scripts_path=f"{os.getcwd()}/../assets/etl_scripts/",
        )
