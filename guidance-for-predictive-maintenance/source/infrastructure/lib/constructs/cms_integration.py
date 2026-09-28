# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
CMS Integration Construct — resources for connecting the tire prediction model
to the Connected Mobility Guidance telemetry pipeline.

Creates:
- Daily tire check Lambda (slow leak trend detection)
- Real-time blowout risk Lambda (SageMaker inference)
- EventBridge schedule for daily check
- IAM roles with least-privilege permissions
- S3 bucket for training artifacts
- SSM parameters for model config
"""

import os
from constructs import Construct
from aws_cdk import (
    ArnFormat,
    Duration,
    RemovalPolicy,
    Stack,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_events as events,
    aws_events_targets as targets,
    aws_s3 as s3,
    aws_ssm as ssm,
    CfnOutput,
)
from cdk_nag import NagSuppressions


class CMSIntegrationConstruct(Construct):
    def __init__(self, scope: Construct, id: str, *, stage: str = "prod", deploy_realtime_endpoint: bool = False, **kwargs):
        super().__init__(scope, id, **kwargs)

        region = os.environ.get("CDK_DEFAULT_REGION", "us-east-2")
        account = os.environ.get("CDK_DEFAULT_ACCOUNT", "")

        # S3 bucket for training artifacts
        self.training_bucket = s3.Bucket(
            self, "TrainingBucket",
            bucket_name=f"cms-tire-prediction-{account}-{region}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            # S1: server access logging — logs delivered to the same bucket with a prefix
            server_access_logs_prefix="server-access-logs/",
            # S10: enforce SSL-only access
            enforce_ssl=True,
        )

        # SageMaker execution role — only created when deploy_realtime_endpoint=True.
        #
        # Security review cycle 1 (Warning 4): no code path in this repository passes
        # cms-sagemaker-execution-role to a SageMaker API call.  Training uses a separate
        # role defined in ml_training_stepfunction.py.  The role had standing
        # CreateEndpoint/UpdateEndpoint/DeleteEndpoint/InvokeEndpoint on endpoint/*,
        # which is the same shape that produced the orphan "tpe" endpoint deleted
        # 2026-08-10 after 8 months of idle cost.  Gate the entire role on the flag so
        # it cannot be iam:PassRole'd to create an endpoint in batch-only mode.
        #
        # When the flag IS on, endpoint-lifecycle actions are scoped to the derived
        # endpoint name prefix (tpe-{stage}-*) rather than endpoint/*, matching the
        # naming convention from ml_training_stepfunction.py:432.
        # Pattern modeled on ml_training_stepfunction.py's sagemaker_role inline policies.
        self.sagemaker_role = None
        if deploy_realtime_endpoint:
            self.sagemaker_role = iam.Role(
                self, "SageMakerRole",
                role_name="cms-sagemaker-execution-role",
                assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
                inline_policies={
                    "s3-policy": iam.PolicyDocument(
                        statements=[
                            # Read training input data and write model artifacts
                            iam.PolicyStatement(
                                effect=iam.Effect.ALLOW,
                                actions=["s3:GetObject", "s3:ListBucket", "s3:GetObjectVersion"],
                                resources=[
                                    self.training_bucket.bucket_arn,
                                    f"{self.training_bucket.bucket_arn}/*",
                                ],
                            ),
                            iam.PolicyStatement(
                                effect=iam.Effect.ALLOW,
                                actions=["s3:PutObject", "s3:ListBucket"],
                                resources=[
                                    self.training_bucket.bucket_arn,
                                    f"{self.training_bucket.bucket_arn}/*",
                                ],
                            ),
                        ]
                    ),
                    "sagemaker-policy": iam.PolicyDocument(
                        statements=[
                            # Training job lifecycle — batch path, not endpoint-specific.
                            # sagemaker:AddTags is required when CreateTrainingJob/CreateModel
                            # are called with tags (runtime AccessDeniedException otherwise).
                            iam.PolicyStatement(
                                effect=iam.Effect.ALLOW,
                                actions=[
                                    "sagemaker:CreateTrainingJob",
                                    "sagemaker:DescribeTrainingJob",
                                    "sagemaker:StopTrainingJob",
                                    "sagemaker:CreateModel",
                                    "sagemaker:DescribeModel",
                                    "sagemaker:DeleteModel",
                                    "sagemaker:CreateTransformJob",
                                    "sagemaker:DescribeTransformJob",
                                    "sagemaker:StopTransformJob",
                                    "sagemaker:AddTags",
                                ],
                                resources=[
                                    Stack.of(self).format_arn(
                                        service="sagemaker",
                                        account=Stack.of(self).account,
                                        region=Stack.of(self).region,
                                        resource="training-job",
                                        resource_name="*",
                                        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                    ),
                                    Stack.of(self).format_arn(
                                        service="sagemaker",
                                        account=Stack.of(self).account,
                                        region=Stack.of(self).region,
                                        resource="model",
                                        resource_name="*",
                                        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                    ),
                                    Stack.of(self).format_arn(
                                        service="sagemaker",
                                        account=Stack.of(self).account,
                                        region=Stack.of(self).region,
                                        resource="transform-job",
                                        resource_name="*",
                                        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                    ),
                                ],
                            ),
                            # Endpoint lifecycle — gated on deploy_realtime_endpoint=True.
                            # Scoped to tpe-{stage}-* (the derived name from
                            # ml_training_stepfunction.py:432) rather than endpoint/*,
                            # so this role cannot create/manage unrelated endpoints.
                            iam.PolicyStatement(
                                effect=iam.Effect.ALLOW,
                                actions=[
                                    "sagemaker:CreateEndpointConfig",
                                    "sagemaker:DescribeEndpointConfig",
                                    "sagemaker:DeleteEndpointConfig",
                                    "sagemaker:CreateEndpoint",
                                    "sagemaker:DescribeEndpoint",
                                    "sagemaker:UpdateEndpoint",
                                    "sagemaker:DeleteEndpoint",
                                    "sagemaker:InvokeEndpoint",
                                ],
                                resources=[
                                    Stack.of(self).format_arn(
                                        service="sagemaker",
                                        account=Stack.of(self).account,
                                        region=Stack.of(self).region,
                                        resource="endpoint",
                                        resource_name=f"tpe-{stage}-*",
                                        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                    ),
                                    Stack.of(self).format_arn(
                                        service="sagemaker",
                                        account=Stack.of(self).account,
                                        region=Stack.of(self).region,
                                        resource="endpoint-config",
                                        resource_name=f"tpe-{stage}-*",
                                        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                    ),
                                ],
                            ),
                        ]
                    ),
                    "logs-policy": iam.PolicyDocument(
                        statements=[
                            # SageMaker container training logs — required by SageMaker runtime
                            iam.PolicyStatement(
                                effect=iam.Effect.ALLOW,
                                actions=[
                                    "logs:CreateLogGroup",
                                    "logs:CreateLogStream",
                                    "logs:DescribeLogStreams",
                                    "logs:PutLogEvents",
                                ],
                                resources=[
                                    Stack.of(self).format_arn(
                                        service="logs",
                                        resource="log-group",
                                        resource_name="/aws/sagemaker/*",
                                        arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                    ),
                                ],
                            ),
                        ]
                    ),
                    "ecr-policy": iam.PolicyDocument(
                        statements=[
                            # Pull training container image from ECR
                            # GetAuthorizationToken is account-level (cannot be further scoped)
                            iam.PolicyStatement(
                                effect=iam.Effect.ALLOW,
                                actions=["ecr:GetAuthorizationToken"],
                                resources=["*"],
                            ),
                            iam.PolicyStatement(
                                effect=iam.Effect.ALLOW,
                                actions=[
                                    "ecr:GetDownloadUrlForLayer",
                                    "ecr:BatchGetImage",
                                    "ecr:BatchCheckLayerAvailability",
                                ],
                                # Scoped to the RCF training image repo in us-east-1
                                # (account 382416733822 per ml_training_stepfunction.py constants)
                                resources=[
                                    f"arn:aws:ecr:us-east-1:382416733822:repository/randomcutforest",
                                ],
                            ),
                        ]
                    ),
                    "ssm-policy": iam.PolicyDocument(
                        statements=[
                            # Read model config: normalization stats, anomaly threshold, endpoint name
                            iam.PolicyStatement(
                                effect=iam.Effect.ALLOW,
                                actions=["ssm:GetParameter"],
                                resources=[
                                    Stack.of(self).format_arn(
                                        service="ssm",
                                        resource="parameter",
                                        resource_name="tire-prediction/*",
                                        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                    ),
                                    Stack.of(self).format_arn(
                                        service="ssm",
                                        resource="parameter",
                                        resource_name="tire-maintenance/*",
                                        arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                    ),
                                ],
                            ),
                        ]
                    ),
                },
            )

        # Lambda execution role for prediction Lambdas.
        # AWSLambdaBasicExecutionRole managed policy removed (IAM4); CloudWatch Logs
        # actions are explicitly granted below in the inline policy instead.
        #
        # DynamoDB grants require a region at synth time.  The CMS tables live in
        # a different region from the ADP account; that region is STAGE-DEPENDENT:
        #   staging → us-west-2  (verified live 2026-08-10: cms-staging-storage-* tables)
        #   prod    → us-east-1  (verified live 2026-08-10: cms-prod-storage-* tables;
        #                         list-tables in us-west-2 returns no cms-prod-storage rows)
        #
        # A wrong region here produces DynamoDB IAM grants that match nothing, which
        # manifests as a Lambda that silently finds no tables and writes no alerts —
        # indistinguishable from the never-deployed state this spec exists to fix.
        #
        # CDK_DEFAULT_REGION is NOT used here (spec § D2 + 2026-06-03 context-isolation
        # precedent: ambient deploy-affecting region resolution is rejected).
        _CMS_TABLE_REGION_BY_STAGE = {
            "staging": "us-west-2",
            "prod": "us-east-1",
        }
        if stage not in _CMS_TABLE_REGION_BY_STAGE:
            raise ValueError(
                f"CMSIntegrationConstruct: unknown stage {stage!r}. "
                f"Valid stages are: {sorted(_CMS_TABLE_REGION_BY_STAGE)}. "
                "Add a verified CMS table region for this stage before deploying."
            )
        cms_table_region = _CMS_TABLE_REGION_BY_STAGE[stage]

        # Explicit ARNs for the three CMS DynamoDB tables this Lambda reads/writes.
        # Names are fully deterministic from the stage parameter, known at CDK synth time.
        # Verified live 2026-08-10: cms-{stage}-storage-{telemetry,vehicles,maintenance-alerts}.
        _telemetry_table_arn = f"arn:aws:dynamodb:{cms_table_region}:{account}:table/cms-{stage}-storage-telemetry"
        _vehicles_table_arn = f"arn:aws:dynamodb:{cms_table_region}:{account}:table/cms-{stage}-storage-vehicles"
        _alerts_table_arn = f"arn:aws:dynamodb:{cms_table_region}:{account}:table/cms-{stage}-storage-maintenance-alerts"

        # Specific ARN for the model-name SSM parameter the Lambda actually reads.
        # Parameter is provisioned by MLTrainingConstruct at /tire-maintenance/model-name.
        # Using Stack.of(self).format_arn() following the correct precedent at
        # ml_inference_stepfunction.py:58-59 (scope to specific parameter, no wildcard).
        _model_name_parameter_arn = Stack.of(self).format_arn(
            service="ssm",
            resource="parameter",
            resource_name="tire-maintenance/model-name",
            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
        )

        # Inline policy statements for PredictionLambdaRole.
        # Split DynamoDB read from write: telemetry and vehicles are read-only;
        # only maintenance-alerts needs PutItem/BatchWriteItem.
        _prediction_access_statements = [
            # Read-only on telemetry: Lambda queries by vehicleId (main.py:110-115)
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["dynamodb:Query", "dynamodb:GetItem"],
                resources=[_telemetry_table_arn],
            ),
            # Read-only on vehicles: Lambda scans for enrolled vehicles (main.py:99)
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["dynamodb:Scan", "dynamodb:GetItem"],
                resources=[_vehicles_table_arn],
            ),
            # Write (and read for idempotency) on maintenance-alerts only
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["dynamodb:PutItem", "dynamodb:BatchWriteItem", "dynamodb:GetItem"],
                resources=[_alerts_table_arn],
            ),
            # SSM: scoped to the specific parameter ARN the Lambda reads.
            # The Lambda reads exactly one parameter: /tire-maintenance/model-name.
            # The grant deliberately does NOT cover /tire-prediction/* — that namespace
            # is read by realtime_blowout_risk, which is not deployed in batch-only mode.
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["ssm:GetParameter"],
                resources=[_model_name_parameter_arn],
            ),
        ]

        # sagemaker:InvokeEndpoint is only needed by the realtime blowout-risk Lambda.
        # In batch-only mode (deploy_realtime_endpoint=False) daily_tire_check holds this
        # role and invokes no endpoint. Gate the grant to prevent a standing permission
        # with no consumer — the exact pattern that let orphan endpoints run unnoticed.
        if deploy_realtime_endpoint:
            _prediction_access_statements.append(
                iam.PolicyStatement(
                    effect=iam.Effect.ALLOW,
                    actions=["sagemaker:InvokeEndpoint"],
                    resources=[f"arn:aws:sagemaker:{region}:{account}:endpoint/tire-anomaly-*"],
                )
            )

        prediction_role = iam.Role(
            self, "PredictionLambdaRole",
            role_name="cms-tire-prediction-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            inline_policies={
                "PredictionAccess": iam.PolicyDocument(statements=_prediction_access_statements),
                # Explicit CW Logs grant replacing AWSLambdaBasicExecutionRole (IAM4 fix).
                # Scoped to the two Lambda function log groups provisioned by this construct.
                "LogsAccess": iam.PolicyDocument(statements=[
                    iam.PolicyStatement(
                        effect=iam.Effect.ALLOW,
                        actions=[
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents",
                        ],
                        resources=[
                            f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/cms-{stage}-daily-tire-check:*",
                            f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/cms-{stage}-daily-tire-check",
                            f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/cms-{stage}-blowout-risk:*",
                            f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/cms-{stage}-blowout-risk",
                        ],
                    ),
                ]),
            },
        )

        # Daily tire check Lambda
        self.daily_tire_check = lambda_.Function(
            self, "DailyTireCheck",
            function_name=f"cms-{stage}-daily-tire-check",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="main.handler",
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "../../../lambda/daily_tire_check")
            ),
            role=prediction_role,
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                # Required: CMS table region and stage (§ D2).
                # The Lambda's own region (AWS_REGION) comes from the runtime; these
                # tell it where the CMS DynamoDB tables live, which is a different
                # region (us-west-2) from where this Lambda runs (us-east-1 for ADP).
                "CMS_TABLE_REGION": cms_table_region,
                "CMS_STAGE": stage,
            },
        )

        # EventBridge schedule — daily at 10 AM UTC
        events.Rule(
            self, "DailyTireCheckSchedule",
            rule_name=f"cms-{stage}-daily-tire-check-schedule",
            schedule=events.Schedule.cron(hour="10", minute="0"),
            targets=[targets.LambdaFunction(self.daily_tire_check)],
            description="Daily tire health check — slow leak detection",
        )

        # Real-time blowout risk Lambda — only deployed when deploy_realtime_endpoint=True.
        # This Lambda calls sagemaker:InvokeEndpoint on the model endpoint SSM parameter.
        # With deploy_realtime_endpoint=False that parameter has no writer, so this Lambda
        # must not deploy when no endpoint exists.
        # Spec § D1; decisions.md 2026-08-10.
        self.blowout_risk = None
        if deploy_realtime_endpoint:
            self.blowout_risk = lambda_.Function(
                self, "BlowoutRisk",
                function_name=f"cms-{stage}-blowout-risk",
                runtime=lambda_.Runtime.PYTHON_3_13,
                handler="main.handler",
                code=lambda_.Code.from_asset(
                    os.path.join(os.path.dirname(__file__), "../../../lambda/realtime_blowout_risk")
                ),
                role=prediction_role,
                timeout=Duration.seconds(30),
                memory_size=256,
                environment={
                    # Required: CMS table region and stage (§ D2).
                    "CMS_TABLE_REGION": cms_table_region,
                    "CMS_STAGE": stage,
                },
            )

        # Outputs
        CfnOutput(self, "DailyTireCheckArn", value=self.daily_tire_check.function_arn)
        if self.blowout_risk is not None:
            CfnOutput(self, "BlowoutRiskArn", value=self.blowout_risk.function_arn)
        CfnOutput(self, "TrainingBucketName", value=self.training_bucket.bucket_name)
        if self.sagemaker_role is not None:
            CfnOutput(self, "SageMakerRoleArn", value=self.sagemaker_role.role_arn)

        # ---------------------------------------------------------------------------
        # NagSuppressions — documented justifications, reviewed per-resource.
        # ---------------------------------------------------------------------------

        # AwsSolutions-L1 (#24, #25): DailyTireCheck and BlowoutRisk Lambdas pinned to python3.13.
        lambda_fns_to_suppress = [self.daily_tire_check]
        if self.blowout_risk is not None:
            lambda_fns_to_suppress.append(self.blowout_risk)
        for fn in lambda_fns_to_suppress:
            NagSuppressions.add_resource_suppressions(
                fn,
                suppressions=[
                    {
                        "id": "AwsSolutions-L1",
                        "reason": (
                            "PM Lambdas are pinned to python3.13 to match the shared "
                            "common_dependencies Lambda layer (built with SAM build-python3.13, "
                            "compatible_runtimes=[PYTHON_3_13]).  Bumping the runtime requires a "
                            "coordinated layer rebuild and dependency-compatibility validation — "
                            "tracked as a follow-up, not done piecemeal."
                        ),
                    }
                ],
            )

        # AwsSolutions-IAM5 (#23): PredictionLambdaRole inline policy wildcards.
        #
        # Remaining wildcard after security-review cycle 1 narrowing:
        #   • SageMaker endpoint/tire-anomaly-* (only present when deploy_realtime_endpoint=True):
        #     endpoint name follows the tire-anomaly-* naming convention set by the training
        #     pipeline; the exact endpoint name includes a runtime UUID suffix unknown at
        #     deploy time.  Scoped to this prefix, not endpoint/*.
        #
        # Previously-false rationales corrected (security review cycle 1):
        #   • "DDB table name not known at synth time" — removed; the three table ARNs are now
        #     explicitly named (cms-{stage}-storage-{telemetry,vehicles,maintenance-alerts}),
        #     because the names ARE fully deterministic from the stage parameter at CDK synth time.
        #   • "multiple SSM parameters share /tire-prediction/*" — removed; the Lambda reads
        #     exactly one parameter (/tire-maintenance/model-name), now granted by specific ARN.
        NagSuppressions.add_resource_suppressions(
            prediction_role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "One remaining wildcard on PredictionLambdaRole: "
                        "SageMaker endpoint/tire-anomaly-* (only present when "
                        "deploy_realtime_endpoint=True): endpoint name follows the tire-anomaly-* "
                        "naming convention set by the training pipeline; exact name includes a "
                        "runtime UUID suffix unknown at deploy time.  All DynamoDB grants now use "
                        "explicit table ARNs (cms-{stage}-storage-{telemetry,vehicles,"
                        "maintenance-alerts}); SSM grant uses the specific parameter ARN for "
                        "/tire-maintenance/model-name — no prefix wildcards remain on either."
                    ),
                }
            ],
            apply_to_children=True,
        )

        # AwsSolutions-IAM5 on SageMakerRole (#28 partial — ECR and CW logs wildcards).
        # Only applied when deploy_realtime_endpoint=True (role is not created otherwise).
        #   • ECR GetAuthorizationToken Resource::*: per AWS documentation, this is an
        #     account-level IAM action that cannot be scoped to a specific ECR repository ARN.
        #   • CW logs /aws/sagemaker/*: SageMaker container log groups include the training
        #     job name (a runtime UUID), making the full ARN unknown at deploy time.
        if self.sagemaker_role is not None:
            NagSuppressions.add_resource_suppressions(
                self.sagemaker_role,
                suppressions=[
                    {
                        "id": "AwsSolutions-IAM5",
                        "reason": (
                            "Two operationally-required wildcards on the SageMaker execution role: "
                            "(1) ecr:GetAuthorizationToken Resource::*: per AWS documentation, this is "
                            "an account-level action that cannot be scoped to a specific ECR repo ARN. "
                            "(2) CW logs /aws/sagemaker/*: SageMaker container log groups include the "
                            "training job name (a runtime UUID) — log group ARN is unknown at deploy time. "
                            "Both wildcards are documented-standard patterns for SageMaker execution roles "
                            "in the AWS SageMaker IAM documentation.  "
                            "Endpoint-lifecycle actions are scoped to tpe-{stage}-* (not endpoint/*) — "
                            "this role is only created when deploy_realtime_endpoint=True."
                        ),
                    }
                ],
                apply_to_children=True,
            )
