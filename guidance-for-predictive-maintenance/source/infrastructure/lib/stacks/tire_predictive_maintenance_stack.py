# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
TirePredictiveMaintenanceStack
==============================
Top-level CDK stack for the PM component.

Phase 3b changes (decisions.md f/g):
  * ``stage`` is now read from the ``DEPLOYMENT_STAGE`` env var (or CDK
    context key ``deploymentStage``) and threaded through to all
    constructs that need it.
  * ``ETLConstruct`` now provisions the **governed ETL path**:
    DataZone consumer-project subscription → Lake Formation auto-grant →
    Glue 5.0 job reads tire_health + VTA + service_records → writes
    training-ready dataset to PM training bucket.
    The original self-contained ``raw_data_bucket``-based ETL is retained
    alongside for rollback.
  * ``MLPipelineConstruct`` exposes both the original unsupervised RCF
    baseline AND the new supervised XGBoost option.  Default is RCF for
    backward-compat; set ``ML_MODEL_TYPE=xgboost`` env var to opt in.
"""

# Standard Library
import os
from typing import Any

# AWS Libraries
from aws_cdk import RemovalPolicy, Stack, aws_lambda
from cdk_nag import NagSuppressions
from constructs import Construct

# Predictive Maintenance
from ..common.encrypted_s3 import EncryptedS3Construct
from ..common.lambda_layer_bundling import create_layer_bundling
from ..common.utils import SolutionConfigInputs
from ..constructs.alerts_system import AlertsSystemConstruct
from ..constructs.ml_construct import MLPipelineConstruct
from ..constructs.ml_constructs.ml_training_stepfunction import ModelType, XGBoostModelParameters
from ..constructs.prediction_model import PredictionModelConstruct
from ..constructs.etl_construct import ETLConstruct
from ..constructs.cms_integration import CMSIntegrationConstruct


class TirePredictiveMaintenanceStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, deploy_realtime_endpoint: bool = False, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # cron(minutes hours day-of-month month day-of-week year)
        query_cron_string = "cron(0 * * * ? *)"
        etl_cron_string = "cron(30 * ? * * *)"
        ml_etl_cron_string = "cron(0 2 ? * * *)"
        # Changed from weekly cron(0 3 ? * FRI *) to monthly per decisions.md 2026-08-10.
        # Cost: $11.37/run × 1/month = $11.37/month vs $49.26/month at weekly cadence.
        # Source comment at tire_predictive_maintenance_stack.py already recommends "1 training
        # per year" as data grows — monthly is still conservative for staging.
        ml_training_cron_string = "cron(0 3 1 * ? *)"  # Monthly — 1st of month, 03:00 UTC
        ml_inference_cron_string = "cron(30 2 * * ? *)"

        solution_config_inputs = SolutionConfigInputs(
            solution_name="predictive-maintenance",
            solution_id="SO9676",  # Guidance for Automotive Data Platform on AWS
            solution_version="v1.0.0",
        )

        unique_id = "pm"  # set from deploy config (eg dev/test/prod)

        user_agent_string = solution_config_inputs.get_user_agent_string()

        # ------------------------------------------------------------------
        # Stage resolution — prefer CDK context key, fall back to env var.
        # Valid values: "staging" | "prod".
        # ------------------------------------------------------------------
        stage: str = (
            self.node.try_get_context("deploymentStage")
            or os.environ.get("DEPLOYMENT_STAGE", "prod")
        )

        # ------------------------------------------------------------------
        # ML model type — opt in to XGBoost supervised model via env var.
        # Default: RCF (original unsupervised baseline).
        # ------------------------------------------------------------------
        _ml_model_type_raw = os.environ.get("ML_MODEL_TYPE", "rcf").lower()
        ml_model_type = (
            ModelType.XGBOOST if _ml_model_type_raw == "xgboost" else ModelType.RCF
        )

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

        # ETLConstruct now provisions BOTH the original raw-bucket pipeline
        # AND the new governed pipeline (decisions.md f/g).
        etl_construct = ETLConstruct(
            self,
            "root-etl-stack",
            common_dependency_layer=common_dependency_layer,
            query_cron_string=query_cron_string,
            etl_cron_string=etl_cron_string,
            asset_bucket=asset_bucket,
            s3_log_lifecycle_rules=s3_log_lifecycle_rules,
            stage=stage,
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
            model_type=ml_model_type,
            # XGBoost parameters only used when ml_model_type == XGBOOST.
            xgboost_parameters=XGBoostModelParameters() if ml_model_type == ModelType.XGBOOST else None,
            # deploy_realtime_endpoint=False (default / batch-only posture).
            # The endpoint tail is kept intact behind this flag as a future capability;
            # set to True to deploy the realtime endpoint + MLRealtimeInferenceConstruct.
            # Spec § D1; decisions.md 2026-08-10 — orphan "tpe" endpoint deleted.
            deploy_realtime_endpoint=deploy_realtime_endpoint,
            stage=stage,
        )

        # CMS Integration — daily tire check, blowout risk (gated on flag), SageMaker resources
        CMSIntegrationConstruct(
            self,
            "cms-integration",
            stage=stage,
            deploy_realtime_endpoint=deploy_realtime_endpoint,
        )

        # ---------------------------------------------------------------------------
        # NagSuppressions — CDK-framework custom resources and stack-level findings.
        # CDK custom resources (LogRetention, BucketDeployment, BucketNotifications)
        # are generated by the CDK framework itself; they are not authored by this
        # accelerator and carry managed policies / wildcards inherent to their design.
        # These are standard documented suppressions applied to the whole stack so
        # the paths are resolved after all constructs are created.
        # ---------------------------------------------------------------------------
        NagSuppressions.add_stack_suppressions(
            self,
            suppressions=[
                # AwsSolutions-IAM4 on CDK LogRetention custom resource (#13).
                # The LogRetention Lambda is auto-generated by CDK when log_retention= is
                # specified on a Lambda function — not authored by this accelerator.
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "CDK-framework custom resource Lambda execution roles "
                        "(LogRetention, BucketDeployment, BucketNotifications) use "
                        "AWSLambdaBasicExecutionRole.  These constructs are auto-generated "
                        "by the CDK framework itself and are not authored by this accelerator.  "
                        "The managed policy grants only the minimum required by the Lambda runtime."
                    ),
                    "appliesTo": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                    ],
                },
                # AwsSolutions-IAM5 on CDK LogRetention custom resource (#14).
                # wildcard logs:* on Resource::* is required for LogRetention Lambda to manage
                # retention policies across log groups — not authored by this accelerator.
                # Also covers BucketDeployment S3 wildcards (#50) and step-functions-role
                # logs-delivery Resource::* (#31 partial).
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "CDK-framework custom resource wildcards (LogRetention wildcard logs:* "
                        "on Resource::*, BucketDeployment S3 action wildcards + bucket/* resource "
                        "wildcards) are inherent to these auto-generated CDK constructs.  "
                        "Also covers per-resource documented wildcards with specific rationales "
                        "in the individual construct NagSuppressions (alerts-system, ml-constructs, "
                        "etl, cms-integration)."
                    ),
                    "appliesTo": [
                        "Resource::*",
                        "Action::s3:GetBucket*",
                        "Action::s3:GetObject*",
                        "Action::s3:List*",
                        "Action::s3:Abort*",
                        "Action::s3:DeleteObject*",
                        # CDK BucketDeployment singleton reads from the CDK bootstrap assets bucket.
                        # This ARN pattern is CDK-framework-generated, not authored by this accelerator.
                        "Resource::arn:<AWS::Partition>:s3:::cdk-hnb659fds-assets-<AWS::AccountId>-<AWS::Region>/*",
                    ],
                },
                # AwsSolutions-L1 on CDK BucketDeployment custom resource Lambda (#51).
                # BucketDeployment uses a Lambda pinned to a CDK-determined runtime version —
                # not authored by this accelerator.
                {
                    "id": "AwsSolutions-L1",
                    "reason": (
                        "CDK-framework BucketDeployment custom resource Lambda runtime is managed "
                        "by CDK — not authored by this accelerator.  PM Lambdas authored by this "
                        "accelerator are pinned to python3.13 to match the shared "
                        "common_dependencies layer (see per-function suppressions)."
                    ),
                },
            ],
        )
        # CDK BucketDeployment singleton at stack level — the DefaultPolicy grants read access
        # to the destination asset bucket (encrypted-asset-bucket).  The resource ARN contains
        # a CDK content hash that is determined at synth time.  Suppressing via path-based API
        # because the stack-level suppression cannot match CDK token ARN patterns dynamically.
        NagSuppressions.add_resource_suppressions_by_path(
            self,
            "/tire-predictive-maintenance-stack/Custom::CDKBucketDeployment8693BB64968944B69AAFB0CC9EB8756C/ServiceRole/DefaultPolicy",
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "CDK-framework BucketDeployment custom resource DefaultPolicy grants "
                        "S3 read/write to the CDK bootstrap assets bucket and the destination "
                        "encrypted asset bucket.  The destination bucket ARN uses a CDK content "
                        "hash token (e.g. <encryptedassetbucketencryptedbucket*.Arn>/*) that "
                        "cannot be matched by a static appliesTo string in the stack suppression. "
                        "This construct is not authored by this accelerator."
                    ),
                }
            ],
            apply_to_children=True,
        )

