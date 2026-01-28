# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# AWS Libraries
from aws_cdk import (
    ArnFormat,
    Duration,
    Stack,
    aws_events,
    aws_events_targets,
    aws_iam,
    aws_lambda,
    aws_logs,
    aws_s3,
    aws_ssm,
    aws_stepfunctions,
    aws_stepfunctions_tasks,
)
from constructs import Construct

# MMT Predictive Maintenance
from ...common.encrypted_s3 import LifecycleConfig
from ...common.lambda_bundling import create_poetry_bundling


class MLInferenceConstruct(Construct):
    """
    A construct that creates a Step Function workflow for batch inference and alerting.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        ml_inference_cron_string: str,
        common_dependency_layer: aws_lambda.LayerVersion,
        prediction_bucket: aws_s3.Bucket,
        inference_data_bucket: aws_s3.Bucket,
        model_name_ssm_parameter: aws_ssm.StringParameter,
        s3_log_lifecycle_rules: LifecycleConfig,
    ):
        super().__init__(scope, id)

        start_batch_transform_lambda_name = "start-batch-transform-lambda"
        inference_job_status_lambda_name = "inference-job-status-lambda"

        start_batch_transform_lambda_role = aws_iam.Role(
            self,
            f"{start_batch_transform_lambda_name}-role",
            assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
            inline_policies={
                "ssm-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=["ssm:GetParameter"],
                            resources=[model_name_ssm_parameter.parameter_arn],
                        )
                    ]
                ),
                "sagemaker-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=["sagemaker:CreateTransformJob"],
                            resources=[
                                Stack.of(self).format_arn(
                                    service="sagemaker",
                                    resource="transform-job",
                                    resource_name="*",
                                    arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                )
                            ],
                        )
                    ]
                ),
                "logs-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                            ],
                            resources=[
                                Stack.of(self).format_arn(
                                    service="logs",
                                    resource="log-group",
                                    resource_name=f"/aws/lambda/{start_batch_transform_lambda_name}",
                                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                ),
                                Stack.of(self).format_arn(
                                    service="logs",
                                    resource="log-group",
                                    resource_name=f"/aws/lambda/{start_batch_transform_lambda_name}:log-stream:*",
                                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                ),
                            ],
                        )
                    ]
                ),
            },
        )

        # Create the Lambda function for batch transform
        start_batch_transform_lambda = aws_lambda.Function(
            self,
            start_batch_transform_lambda_name,
            function_name=start_batch_transform_lambda_name,
            runtime=aws_lambda.Runtime.PYTHON_3_13,
            handler="function.main.handler",
            code=create_poetry_bundling("../lambda/start_batch_transform"),
            timeout=Duration.minutes(1),
            memory_size=256,
            layers=[common_dependency_layer],
            role=start_batch_transform_lambda_role,
            environment={
                "PREDICTIONS_BUCKET": prediction_bucket.s3_url_for_object(),
                "INFERENCE_DATA_BUCKET": inference_data_bucket.s3_url_for_object(),
            },
            log_retention=aws_logs.RetentionDays.THREE_MONTHS,
        )

        # Create a role for the job status checker Lambda
        inference_job_status_lambda_role = aws_iam.Role(
            self,
            f"{inference_job_status_lambda_name}-role",
            assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
            inline_policies={
                "logs-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                            ],
                            resources=[
                                Stack.of(self).format_arn(
                                    service="logs",
                                    resource="log-group",
                                    resource_name=f"/aws/lambda/{inference_job_status_lambda_name}",
                                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                ),
                                Stack.of(self).format_arn(
                                    service="logs",
                                    resource="log-group",
                                    resource_name=f"/aws/lambda/{inference_job_status_lambda_name}:log-stream:*",
                                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                ),
                            ],
                        )
                    ]
                ),
                "sagemaker-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=["sagemaker:DescribeTransformJob"],
                            resources=[
                                Stack.of(self).format_arn(
                                    service="sagemaker",
                                    resource="transform-job",
                                    resource_name="*",
                                    arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                ),
                            ],
                        )
                    ]
                ),
            },
        )

        # Create the Lambda function for checking job status
        inference_job_status_lambda = aws_lambda.Function(
            self,
            inference_job_status_lambda_name,
            function_name=inference_job_status_lambda_name,
            runtime=aws_lambda.Runtime.PYTHON_3_13,
            handler="function.main.handler",
            code=create_poetry_bundling("../lambda/inference_job_status"),
            timeout=Duration.minutes(5),
            memory_size=256,
            layers=[common_dependency_layer],
            role=inference_job_status_lambda_role,
            log_retention=aws_logs.RetentionDays.THREE_MONTHS,
        )

        # Task to start batch transform job
        start_batch_transform = aws_stepfunctions_tasks.LambdaInvoke(
            self,
            f"{start_batch_transform_lambda_name}-invoke",
            lambda_function=start_batch_transform_lambda,
            result_path="$.BatchTransformResult",
        )

        # Task to check job status
        check_job_status = aws_stepfunctions_tasks.LambdaInvoke(
            self,
            f"{inference_job_status_lambda_name}-invoke",
            lambda_function=inference_job_status_lambda,
            payload=aws_stepfunctions.TaskInput.from_object(
                {"job_name.$": "$.BatchTransformResult.Payload.job_name"}
            ),
            result_path="$.JobStatus",
        )

        # Define a wait state
        wait_for_job = aws_stepfunctions.Wait(
            self,
            "wait-for-job",
            time=aws_stepfunctions.WaitTime.duration(Duration.seconds(30)),
        )

        # Define a choice state to check if job is complete
        is_job_complete = aws_stepfunctions.Choice(self, "is-job-complete")

        # Define condition for job completion
        job_complete = aws_stepfunctions.Condition.string_equals(
            "$.JobStatus.Payload.status", "Completed"
        )
        job_failed = aws_stepfunctions.Condition.string_equals(
            "$.JobStatus.Payload.status", "Failed"
        )

        failure = aws_stepfunctions.Fail(
            self,
            "inference-failed",
            cause="batch transform job failed",
            error="InferencePipelineFailed",
        )

        success = aws_stepfunctions.Succeed(
            self,
            "inference-succeed",
        )

        # Define the workflow
        definition = start_batch_transform.next(check_job_status).next(
            is_job_complete.when(job_complete, success)
            .when(job_failed, failure)
            .otherwise(wait_for_job.next(check_job_status))
        )

        # Create the state machine
        self.inference_state_machine = aws_stepfunctions.StateMachine(
            self,
            "inference-state-machine",
            definition_body=aws_stepfunctions.DefinitionBody.from_chainable(definition),
            timeout=Duration.hours(2),
        )

        # turn on this rule to run it at a scheduled time
        # aws_events.Rule(
        #     self,
        #     "ml-inference-scheduled-run-rule",
        #     schedule=aws_events.Schedule.expression(ml_inference_cron_string),
        #     targets=[aws_events_targets.SfnStateMachine(self.inference_state_machine)],
        # )
