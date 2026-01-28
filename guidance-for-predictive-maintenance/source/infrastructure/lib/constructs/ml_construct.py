# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# AWS Libraries
from aws_cdk import aws_lambda, aws_s3, aws_ssm
from constructs import Construct

# MMT Predictive Maintenance
from ..common.encrypted_s3 import LifecycleConfig
from .etl_construct import ETLConstruct
from .ml_constructs.ml_inference_stepfunction import MLInferenceConstruct
from .ml_constructs.ml_realtime_inference import MLRealtimeInferenceConstruct
from .ml_constructs.ml_training_stepfunction import (
    MLTrainingConstruct,
    ModelTrainingConfig,
    ModelParameters
)


class MLPipelineConstruct(Construct):

    def __init__(
        self,
        scope: Construct,
        id: str,
        ml_etl_cron_string: str,
        ml_training_cron_string: str,
        ml_inference_cron_string: str,
        asset_bucket: aws_s3.Bucket,
        prediction_bucket: aws_s3.Bucket,
        etl_construct: ETLConstruct,
        common_dependency_layer: aws_lambda.LayerVersion,
        s3_log_lifecycle_rules: LifecycleConfig,
        anomaly_threshold_ssm_parameter: aws_ssm.StringParameter,
    ):
        super().__init__(scope, id)

        ml_training_construct = MLTrainingConstruct(
            self,
            "ml-training-construct",
            inference_data_bucket=etl_construct.etl_data_buckets.inference_data_bucket,
            training_data_bucket=etl_construct.etl_data_buckets.training_data_bucket,
            prediction_bucket=prediction_bucket,
            s3_log_lifecycle_rules=s3_log_lifecycle_rules,
            ml_training_cron_string=ml_training_cron_string,
            training_config=ModelTrainingConfig(
                training_data_prefix="",
                instance_type="m5.12xlarge",
                instance_volume_size_in_gib=400,
                max_training_time_in_seconds=3600,
            ),
            model_parameters=ModelParameters(
                feature_dimension="4",
                num_samples_per_tree="256",
                num_trees="100",
            ),
            common_dependency_layer=common_dependency_layer,
        )

        MLInferenceConstruct(
            self,
            "ml-inference-construct",
            common_dependency_layer=common_dependency_layer,
            prediction_bucket=prediction_bucket,
            inference_data_bucket=etl_construct.etl_data_buckets.inference_data_bucket,
            model_name_ssm_parameter=ml_training_construct.model_name_ssm_parameter,
            s3_log_lifecycle_rules=s3_log_lifecycle_rules,
            ml_inference_cron_string=ml_inference_cron_string,
        )

        MLRealtimeInferenceConstruct(
            self,
            "ml-realtime-inference-construct",
            model_endpoint_ssm_parameter=ml_training_construct.model_endpoint_ssm_parameter,
            normalization_stats_ssm_parameter=etl_construct.normalization_stats.stats_ssm_parameter,
            anomaly_threshold_ssm_parameter=anomaly_threshold_ssm_parameter,
            common_dependency_layer=common_dependency_layer,
        )
