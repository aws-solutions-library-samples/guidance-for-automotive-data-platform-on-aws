# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import os

# AWS Libraries
from aws_cdk import aws_lambda, aws_s3
from constructs import Construct

# MMT Predictive Maintenance
from ..common.encrypted_s3 import LifecycleConfig
from .etl_constructs.etl_data_buckets import ETLDataBuckets
from .etl_constructs.etl_glue_jobs import ETLPipeline
from .etl_constructs.normalization_stats import NormalizationStats


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
    ):
        super().__init__(scope, id)

        self.etl_data_buckets = ETLDataBuckets(
            self, "etl-data-buckets", s3_log_lifecycle_rules=s3_log_lifecycle_rules
        )

        # Create normalization stats SSM parameter
        self.normalization_stats = NormalizationStats(self, "normalization-stats")

        self.etl_pipeline = ETLPipeline(
            self,
            "etl-glue-jobs",
            asset_bucket=asset_bucket,
            etl_glue_scripts_location=f"{os.getcwd()}/../assets/etl_scripts/",
            etl_data_buckets=self.etl_data_buckets,
            normalization_stats=self.normalization_stats,
        )
