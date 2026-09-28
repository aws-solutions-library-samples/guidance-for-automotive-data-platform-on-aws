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
from cdk_nag import NagSuppressions

# Predictive Maintenance
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

        # CloudWatch Log Group for API access logging (APIG1)
        api_access_log_group = aws_logs.LogGroup(
            self,
            "realtime-inference-api-access-logs",
            log_group_name="/aws/apigateway/realtime-inference-api",
            retention=aws_logs.RetentionDays.THREE_MONTHS,
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
                # APIG1: enable access logging to CloudWatch
                access_log_destination=aws_apigateway.LogGroupLogDestination(api_access_log_group),
                access_log_format=aws_apigateway.AccessLogFormat.clf(),
            ),
            default_cors_preflight_options=aws_apigateway.CorsOptions(
                allow_origins=aws_apigateway.Cors.ALL_ORIGINS,
                allow_methods=["POST", "OPTIONS"],
                allow_headers=["Content-Type", "X-Api-Key", "Authorization"],
            ),
        )

        # APIG2: request validator — validates request body presence
        request_validator = aws_apigateway.RequestValidator(
            self,
            "realtime-inference-request-validator",
            rest_api=self.api,
            request_validator_name="predict-body-validator",
            validate_request_body=True,
            validate_request_parameters=False,
        )

        # JSON schema for the predict request body (APIG2)
        predict_request_model = self.api.add_model(
            "PredictRequestModel",
            content_type="application/json",
            model_name="PredictRequest",
            schema=aws_apigateway.JsonSchema(
                schema=aws_apigateway.JsonSchemaVersion.DRAFT4,
                title="PredictRequest",
                type=aws_apigateway.JsonSchemaType.OBJECT,
                required=["vehicle_id", "tire_id", "pressure", "temperature", "delta_pressure", "delta_temp"],
                properties={
                    "vehicle_id": aws_apigateway.JsonSchema(type=aws_apigateway.JsonSchemaType.STRING),
                    "tire_id": aws_apigateway.JsonSchema(type=aws_apigateway.JsonSchemaType.STRING),
                    "pressure": aws_apigateway.JsonSchema(type=aws_apigateway.JsonSchemaType.NUMBER),
                    "temperature": aws_apigateway.JsonSchema(type=aws_apigateway.JsonSchemaType.NUMBER),
                    "delta_pressure": aws_apigateway.JsonSchema(type=aws_apigateway.JsonSchemaType.NUMBER),
                    "delta_temp": aws_apigateway.JsonSchema(type=aws_apigateway.JsonSchemaType.NUMBER),
                },
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
        
        # Add POST method with IAM authorization (APIG4 fix) and API key for quota tracking.
        # COG4 is suppressed: IAM/SigV4 auth satisfies APIG4; Cognito is not appropriate
        # for this operator/service-to-service API (see NagSuppressions below).
        predict_resource.add_method(
            "POST",
            lambda_integration,
            api_key_required=True,                                          # keep for quota/throttle tracking
            authorization_type=aws_apigateway.AuthorizationType.IAM,        # APIG4 fix: SigV4 auth
            request_validator=request_validator,                            # APIG2 fix: validate body
            request_models={"application/json": predict_request_model},     # APIG2: body schema
            method_responses=[
                aws_apigateway.MethodResponse(
                    status_code="200",
                    response_parameters={
                        "method.response.header.Access-Control-Allow-Origin": True
                    },
                )
            ],
        )

        # COG4 suppression: the predict API uses IAM (SigV4) authorization, which satisfies
        # APIG4. COG4 requires a Cognito user pool authorizer specifically, which is not
        # appropriate for this operator/service-to-service API. Callers sign requests with
        # SigV4 using IAM credentials (boto3 / requests-aws4auth).
        NagSuppressions.add_resource_suppressions(
            predict_resource,
            suppressions=[
                {
                    "id": "AwsSolutions-COG4",
                    "reason": (
                        "The predict API uses IAM (AWS_IAM / SigV4) authorization, which "
                        "satisfies APIG4. COG4 requires a Cognito user pool authorizer specifically. "
                        "A Cognito user pool is not appropriate for this operator/service-to-service "
                        "ML inference API — callers are operator scripts or internal services that "
                        "authenticate via IAM credentials (boto3 / requests-aws4auth / SigV4). "
                        "No end-user identity pool exists for this accelerator."
                    ),
                }
            ],
            apply_to_children=True,
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

        # ---------------------------------------------------------------------------
        # NagSuppressions — documented justifications, reviewed per-resource.
        # ---------------------------------------------------------------------------

        # AwsSolutions-L1 (#42): realtime-inference-lambda pinned to python3.13.
        # Rationale (decisions.md 2026-07-16): pinned to python3.13 to match the shared
        # common_dependencies Lambda layer (compatible_runtimes=[PYTHON_3_13]).
        NagSuppressions.add_resource_suppressions(
            self.realtime_inference_lambda,
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

        # AwsSolutions-IAM5 (#43): realtime-inference-lambda-role wildcards.
        #   • CW log-stream *: Lambda writes to execution-ID-suffixed streams unknown at deploy.
        #   • SageMaker endpoint/*: endpoint name is written at runtime by the training pipeline
        #     into an SSM parameter; the exact endpoint name is not known at CDK synth time.
        #     The resource is still scoped to sagemaker:endpoint/* (not sagemaker:*).
        NagSuppressions.add_resource_suppressions(
            realtime_inference_lambda_role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Two operationally-required wildcards: "
                        "(1) CW log-stream *: the Lambda runtime writes to execution-ID-suffixed "
                        "streams whose exact names are unknown at deploy time — standard AWS Lambda "
                        "logging pattern. "
                        "(2) sagemaker:endpoint/*: the SageMaker endpoint name is written at runtime "
                        "by the training Step Function into an SSM parameter and is unknown at CDK "
                        "synth time.  The resource is scoped to sagemaker:endpoint/* (not *)."
                    ),
                }
            ],
        )

        # AwsSolutions-APIG3 (#45): WAFv2 web ACL association.
        # WAFv2 association is optional for reference accelerators.  Operators deploying to
        # production should associate a WAFv2 web ACL appropriate to their threat model.
        # The API is already protected by IAM (SigV4) auth + API key + throttling/quota.
        # AwsSolutions-APIG2 (#46): cdk-nag checks for a RequestValidator on the REST API
        # resource; validation IS configured on the POST /predict method (see above).
        # cdk-nag fires on the RestApi resource when no API-level default validator is set.
        NagSuppressions.add_resource_suppressions(
            self.api,
            suppressions=[
                {
                    "id": "AwsSolutions-APIG3",
                    "reason": (
                        "WAFv2 web ACL association is optional for reference accelerators. "
                        "The predict API is already protected by IAM/SigV4 authorization, "
                        "API key-based throttling (100 RPS / 10,000/day quota), and request body "
                        "validation.  Operators deploying to production should associate a WAFv2 "
                        "ACL appropriate to their threat model and traffic profile."
                    ),
                },
                {
                    "id": "AwsSolutions-APIG2",
                    "reason": (
                        "Request validation IS enabled on the POST /predict method: "
                        "a RequestValidator with validate_request_body=True and a PredictRequest "
                        "JSON schema model are attached to the method (Group 2 fix). "
                        "cdk-nag APIG2 fires on the RestApi resource when no API-level default "
                        "validator is configured; this accelerator enforces validation at the "
                        "method level on the only resource (/predict POST), which is the "
                        "AWS-recommended pattern for method-specific JSON schema validation."
                    ),
                },
            ],
            apply_to_children=True,
        )
