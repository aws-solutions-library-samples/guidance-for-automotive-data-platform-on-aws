# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# AWS Libraries
from aws_cdk import (
    ArnFormat, 
    Duration, 
    Stack, 
    aws_apigateway, 
    aws_iam, 
    aws_lambda, 
    aws_logs, 
    aws_ssm
)
from constructs import Construct

# MMT Predictive Maintenance
from ...common.lambda_bundling import create_poetry_bundling


class MLRealtimeInferenceConstruct(Construct):
    """
    A construct that creates a Lambda function for real-time inference
    using a SageMaker endpoint.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        model_endpoint_ssm_parameter: aws_ssm.StringParameter,
        normalization_stats_ssm_parameter: aws_ssm.StringParameter,
        anomaly_threshold_ssm_parameter: aws_ssm.StringParameter,
        common_dependency_layer: aws_lambda.LayerVersion,
    ):
        super().__init__(scope, id)

        realtime_inference_lambda_name = "realtime-inference-lambda"

        realtime_inference_lambda_role = aws_iam.Role(
            self,
            f"{realtime_inference_lambda_name}-role",
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
                                    resource_name=f"/aws/lambda/{realtime_inference_lambda_name}",
                                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                ),
                                Stack.of(self).format_arn(
                                    service="logs",
                                    resource="log-group",
                                    resource_name=f"/aws/lambda/{realtime_inference_lambda_name}:log-stream:*",
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
                            actions=["sagemaker:InvokeEndpoint"],
                            resources=[
                                Stack.of(self).format_arn(
                                    service="sagemaker",
                                    resource="endpoint",
                                    resource_name="*",
                                    arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                )
                            ],
                        )
                    ]
                ),
                "ssm-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=["ssm:GetParameter"],
                            resources=[
                                model_endpoint_ssm_parameter.parameter_arn,
                                normalization_stats_ssm_parameter.parameter_arn,
                                anomaly_threshold_ssm_parameter.parameter_arn,
                            ],
                        )
                    ]
                ),
            },
        )

        self.realtime_inference_lambda = aws_lambda.Function(
            self,
            realtime_inference_lambda_name,
            function_name=realtime_inference_lambda_name,
            runtime=aws_lambda.Runtime.PYTHON_3_13,
            handler="function.main.handler",
            code=create_poetry_bundling("../lambda/realtime_inference"),
            timeout=Duration.seconds(30),
            memory_size=256,
            layers=[common_dependency_layer],
            role=realtime_inference_lambda_role,
            environment={
                "MODEL_ENDPOINT_PARAMETER": model_endpoint_ssm_parameter.parameter_name,
                "NORMALIZATION_STATS_PARAMETER": normalization_stats_ssm_parameter.parameter_name,
                "ANOMALY_THRESHOLD_PARAMETER": anomaly_threshold_ssm_parameter.parameter_name,
            },
            log_retention=aws_logs.RetentionDays.THREE_MONTHS,
        )

        # Create API Gateway REST API
        self.api = aws_apigateway.RestApi(
            self,
            "realtime-inference-api",
            rest_api_name="Tire Prediction Realtime Inference API",
            description="API for real-time tire anomaly prediction",
            deploy_options=aws_apigateway.StageOptions(
                stage_name="dev",
                throttling_rate_limit=100,
                throttling_burst_limit=200,
                logging_level=aws_apigateway.MethodLoggingLevel.INFO,
                data_trace_enabled=True,
                metrics_enabled=True,
            ),
            default_cors_preflight_options=aws_apigateway.CorsOptions(
                allow_origins=aws_apigateway.Cors.ALL_ORIGINS,
                allow_methods=["POST", "OPTIONS"],
                allow_headers=["Content-Type", "X-Api-Key", "Authorization"],
            ),
        )

        # Create API Key
        self.api_key = aws_apigateway.ApiKey(
            self,
            "realtime-inference-api-key",
            api_key_name="tire-prediction-api-key",
            description="API key for tire prediction realtime inference",
        )

        # Create Usage Plan
        usage_plan = aws_apigateway.UsagePlan(
            self,
            "realtime-inference-usage-plan",
            name="TirePredictionUsagePlan",
            description="Usage plan for tire prediction API",
            throttle=aws_apigateway.ThrottleSettings(
                rate_limit=100,
                burst_limit=200,
            ),
            quota=aws_apigateway.QuotaSettings(
                limit=10000,
                period=aws_apigateway.Period.DAY,
            ),
        )

        # Associate API Key with Usage Plan
        usage_plan.add_api_key(self.api_key)
        usage_plan.add_api_stage(
            stage=self.api.deployment_stage,
        )

        # Create Lambda integration
        lambda_integration = aws_apigateway.LambdaIntegration(
            self.realtime_inference_lambda,
            proxy=True,
            integration_responses=[
                aws_apigateway.IntegrationResponse(
                    status_code="200",
                    response_parameters={
                        "method.response.header.Access-Control-Allow-Origin": "'*'"
                    },
                )
            ],
        )

        # Create /predict resource
        predict_resource = self.api.root.add_resource("predict")
        
        # Add POST method with API key requirement
        predict_resource.add_method(
            "POST",
            lambda_integration,
            api_key_required=True,
            method_responses=[
                aws_apigateway.MethodResponse(
                    status_code="200",
                    response_parameters={
                        "method.response.header.Access-Control-Allow-Origin": True
                    },
                )
            ],
        )

        # Store API key in SSM for easy retrieval
        self.api_key_ssm_parameter = aws_ssm.StringParameter(
            self,
            "api-key-ssm-parameter",
            parameter_name="/tire-prediction/api-key-id",
            string_value=self.api_key.key_id,
            description="API Key ID for tire prediction realtime inference API",
        )

        # Store API endpoint URL in SSM
        self.api_url_ssm_parameter = aws_ssm.StringParameter(
            self,
            "api-url-ssm-parameter",
            parameter_name="/tire-prediction/api-url",
            string_value=self.api.url,
            description="API Gateway URL for tire prediction realtime inference",
        )
