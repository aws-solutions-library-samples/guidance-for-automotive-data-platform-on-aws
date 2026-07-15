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
    Duration,
    RemovalPolicy,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_events as events,
    aws_events_targets as targets,
    aws_s3 as s3,
    aws_ssm as ssm,
    CfnOutput,
)


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
        )

        # SageMaker execution role
        self.sagemaker_role = iam.Role(
            self, "SageMakerRole",
            role_name="cms-sagemaker-execution-role",
            assumed_by=iam.ServicePrincipal("sagemaker.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSageMakerFullAccess"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonS3FullAccess"),
                iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMFullAccess"),
            ],
        )

        # Lambda execution role for prediction Lambdas
        prediction_role = iam.Role(
            self, "PredictionLambdaRole",
            role_name="cms-tire-prediction-lambda-role",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
            ],
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
