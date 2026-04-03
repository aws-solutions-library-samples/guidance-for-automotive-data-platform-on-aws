# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import os
from typing import Any

# AWS Libraries
from aws_cdk import RemovalPolicy, Stack, aws_lambda
from constructs import Construct

# MMT Predictive Maintenance
from ..common.encrypted_s3 import EncryptedS3Construct
from ..common.lambda_layer_bundling import create_layer_bundling
from ..common.utils import SolutionConfigInputs
from ..constructs.alerts_system import AlertsSystemConstruct
from ..constructs.ml_construct import MLPipelineConstruct
from ..constructs.prediction_model import PredictionModelConstruct
from ..constructs.etl_construct import ETLConstruct
from ..constructs.cms_integration import CMSIntegrationConstruct


class TirePredictiveMaintenanceStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # cron(minutes hours day-of-month month day-of-week year)
        query_cron_string = "cron(0 * * * ? *)"
        etl_cron_string = "cron(30 * ? * * *)"
        ml_etl_cron_string = "cron(0 2 ? * * *)"
        ml_training_cron_string = "cron(0 3 ? * FRI *)"  # NOTE: WEEKLY RETRAINING, needs to change as the data size grows. Recommendation of 1 training per year.
        ml_inference_cron_string = "cron(30 2 * * ? *)"

        solution_config_inputs = SolutionConfigInputs(
            solution_name="mmt-predictive-maintenance",
            solution_id="SO9676",  # Guidance for Automotive Data Platform on AWS
            solution_version="v1.0.0",
        )

        unique_id = "mmt"  # todo set this from deploy config (eg dev/test/prod)

        user_agent_string = solution_config_inputs.get_user_agent_string()

        s3_log_lifecycle_rules = (
            EncryptedS3Construct.create_log_lifecycle_cfn_parameters(self)
        )

        asset_bucket = EncryptedS3Construct(
            self, "encrypted-asset-bucket", log_lifecycle_rules=s3_log_lifecycle_rules
        ).bucket

        common_dependency_layer = aws_lambda.LayerVersion(
            self,
            "common-lambda-dependency-layer",
            code=create_layer_bundling(
                asset_path=f"{os.getcwd()}/../lambda/layers/common_dependencies"
            ),
            compatible_runtimes=[aws_lambda.Runtime.PYTHON_3_13],
            description="Layer containing Custom Resource packages",
            license="Apache-2.0",
            removal_policy=RemovalPolicy.DESTROY,
        )

        alerts_system_construct = AlertsSystemConstruct(
            self,
            "alerts-system-construct",
            unique_id=unique_id,
            common_dependency_layer=common_dependency_layer,
            s3_log_lifecycle_rules=s3_log_lifecycle_rules,
            user_agent_string=user_agent_string,
        )

        etl_construct = ETLConstruct(
            self,
            "root-etl-stack",
            common_dependency_layer=common_dependency_layer,
            query_cron_string=query_cron_string,
            etl_cron_string=etl_cron_string,
            asset_bucket=asset_bucket,
            s3_log_lifecycle_rules=s3_log_lifecycle_rules,
        )

        prediction_model_construct = PredictionModelConstruct(
            self,
            "prediction-model-construct",
            s3_log_lifecycle_rules=s3_log_lifecycle_rules,
            alerts_transformer_function=alerts_system_construct.alerts_transformer_function,
        )

        MLPipelineConstruct(
            self,
            "ml-based-slow-leak-detection-construct",
            ml_etl_cron_string=ml_etl_cron_string,
            ml_training_cron_string=ml_training_cron_string,
            ml_inference_cron_string=ml_inference_cron_string,
            common_dependency_layer=common_dependency_layer,
            asset_bucket=asset_bucket,
            etl_construct=etl_construct,
            prediction_bucket=prediction_model_construct.prediction_bucket_construct.bucket,
            s3_log_lifecycle_rules=s3_log_lifecycle_rules,
            anomaly_threshold_ssm_parameter=alerts_system_construct.anomaly_threshold_ssm_parameter,
        )

        # CMS Integration — daily tire check, blowout risk, SageMaker resources
        CMSIntegrationConstruct(
            self,
            "cms-integration",
            stage=os.environ.get("DEPLOYMENT_STAGE", "prod"),
        )
