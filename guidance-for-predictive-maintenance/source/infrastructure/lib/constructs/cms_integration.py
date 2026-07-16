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
    def __init__(self, scope: Construct, id: str, *, stage: str = "prod", **kwargs):
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

        # SageMaker execution role — scoped inline policies (no *FullAccess managed policies).
        # Actions derived from what the SageMaker training + inference endpoint pipeline
        # actually calls:
        #   • S3: read training data + write model artifacts to training_bucket
        #   • SageMaker: training job, model registry, endpoint lifecycle, batch transform
        #   • CloudWatch Logs: SageMaker container logs (required by SageMaker runtime)
        #   • ECR: pull training container image
        #   • SSM: read model config parameters (anomaly threshold, normalization stats)
        # Pattern modeled on ml_training_stepfunction.py's sagemaker_role inline policies.
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
                        # Training job lifecycle + model/endpoint management.
                        # sagemaker:AddTags is required when CreateTrainingJob/CreateModel/
                        # CreateEndpoint/CreateEndpointConfig are called with tags (runtime
                        # AccessDeniedException otherwise).
                        iam.PolicyStatement(
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "sagemaker:CreateTrainingJob",
                                "sagemaker:DescribeTrainingJob",
                                "sagemaker:StopTrainingJob",
                                "sagemaker:CreateModel",
                                "sagemaker:DescribeModel",
                                "sagemaker:DeleteModel",
                                "sagemaker:CreateEndpointConfig",
                                "sagemaker:DescribeEndpointConfig",
                                "sagemaker:DeleteEndpointConfig",
                                "sagemaker:CreateEndpoint",
                                "sagemaker:DescribeEndpoint",
                                "sagemaker:UpdateEndpoint",
                                "sagemaker:DeleteEndpoint",
                                "sagemaker:InvokeEndpoint",
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
                                    resource="endpoint",
                                    resource_name="*",
                                    arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                ),
                                Stack.of(self).format_arn(
                                    service="sagemaker",
                                    account=Stack.of(self).account,
                                    region=Stack.of(self).region,
                                    resource="endpoint-config",
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
        prediction_role = iam.Role(
            self, "PredictionLambdaRole",
            role_name="cms-tire-prediction-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            inline_policies={
                "PredictionAccess": iam.PolicyDocument(statements=[
                    iam.PolicyStatement(
                        actions=["dynamodb:Scan", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:BatchWriteItem", "dynamodb:GetItem"],
                        resources=[f"arn:aws:dynamodb:{region}:{account}:table/cms-{stage}-*"],
                    ),
                    iam.PolicyStatement(
                        actions=["ssm:GetParameter"],
                        resources=[f"arn:aws:ssm:{region}:{account}:parameter/tire-prediction/*"],
                    ),
                    iam.PolicyStatement(
                        actions=["sagemaker:InvokeEndpoint"],
                        resources=[f"arn:aws:sagemaker:{region}:{account}:endpoint/tire-anomaly-*"],
                    ),
                ]),
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
                "DEPLOYMENT_STAGE": stage,
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

        # Real-time blowout risk Lambda
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
                "DEPLOYMENT_STAGE": stage,
            },
        )

        # Outputs
        CfnOutput(self, "DailyTireCheckArn", value=self.daily_tire_check.function_arn)
        CfnOutput(self, "BlowoutRiskArn", value=self.blowout_risk.function_arn)
        CfnOutput(self, "TrainingBucketName", value=self.training_bucket.bucket_name)
        CfnOutput(self, "SageMakerRoleArn", value=self.sagemaker_role.role_arn)

        # ---------------------------------------------------------------------------
        # NagSuppressions — documented justifications, reviewed per-resource.
        # ---------------------------------------------------------------------------

        # AwsSolutions-L1 (#24, #25): DailyTireCheck and BlowoutRisk Lambdas pinned to python3.13.
        for fn in (self.daily_tire_check, self.blowout_risk):
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
        #   • DDB table/cms-{stage}-*: the DynamoDB table name includes a deploy-time stage
        #     prefix (e.g., cms-prod-alerts); the exact table name is resolved from the
        #     CMS stack at runtime via an SSM parameter or environment variable — not known
        #     at CDK synth time.  The resource is scoped to a specific DDB table path pattern.
        #   • SSM parameter/tire-prediction/*: multiple SSM parameters share this prefix
        #     (api-key-id, api-url, model name, normalization stats); scoping to the shared
        #     prefix covers all required parameters without over-granting.
        #   • SageMaker endpoint/tire-anomaly-*: SageMaker endpoints use the tire-anomaly-*
        #     naming convention set by the training pipeline; exact endpoint name is unknown
        #     at deploy time but follows this documented prefix.
        NagSuppressions.add_resource_suppressions(
            prediction_role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Stage-parameterized and runtime-determined resource name wildcards: "
                        "(1) DDB table/cms-{stage}-*: table name includes a deploy-time stage "
                        "prefix resolved from CMS stack at runtime — not known at CDK synth time. "
                        "(2) SSM parameter/tire-prediction/*: multiple required SSM parameters "
                        "share this prefix; scoping to the prefix is the correct pattern. "
                        "(3) SageMaker endpoint/tire-anomaly-*: endpoint name follows the "
                        "tire-anomaly- prefix convention set by the training pipeline; exact "
                        "name is a runtime UUID unknown at deploy time."
                    ),
                }
            ],
            apply_to_children=True,
        )

        # AwsSolutions-IAM5 on SageMakerRole (#28 partial — ECR and CW logs wildcards).
        #   • ECR GetAuthorizationToken Resource::*: per AWS documentation, this is an
        #     account-level IAM action that cannot be scoped to a specific ECR repository ARN.
        #   • CW logs /aws/sagemaker/*: SageMaker container log groups include the training
        #     job name (a runtime UUID), making the full ARN unknown at deploy time.
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
                        "in the AWS SageMaker IAM documentation."
                    ),
                }
            ],
            apply_to_children=True,
        )
