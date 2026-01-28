# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
from dataclasses import dataclass

# AWS Libraries
from aws_cdk import (
    ArnFormat,
    Duration,
    Size,
    Stack,
    aws_ec2,
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
from ...common.encrypted_s3 import EncryptedS3Construct, LifecycleConfig
from ...common.lambda_bundling import create_poetry_bundling


@dataclass
class ModelTrainingConfig:
    """
    Data model representing configuration for SageMaker training job.
    """

    training_data_prefix: str  # "" empty string
    instance_type: str  # m5.12xlarge
    instance_volume_size_in_gib: int  # 400
    max_training_time_in_seconds: int  # 3600

@dataclass
class ModelParameters:
    feature_dimension: str  # 10
    num_samples_per_tree: str  # 256
    num_trees: str  # 100

class MLTrainingConstruct(Construct):
    """
    A construct that creates an ML training pipeline with Step Functions:
    1. SageMaker Training Job
    2. SageMaker Model
    3. SageMaker Endpoint
    """

    TRAINING_IMAGE_ACCOUNT = "382416733822"
    TRAINING_IMAGE_REGION = "us-east-1"
    TRAINING_IMAGE_URL = f"{TRAINING_IMAGE_ACCOUNT}.dkr.ecr.{TRAINING_IMAGE_REGION}.amazonaws.com/randomcutforest:1"

    def __init__(
        self,
        scope: Construct,
        id: str,
        ml_training_cron_string: str,
        s3_log_lifecycle_rules: LifecycleConfig,
        inference_data_bucket: aws_s3.Bucket,
        training_data_bucket: aws_s3.Bucket,
        prediction_bucket: aws_s3.Bucket,
        training_config: ModelTrainingConfig,
        model_parameters: ModelParameters,
        common_dependency_layer: aws_lambda.LayerVersion,
    ):
        super().__init__(scope, id)

        self.model_bucket = EncryptedS3Construct(
            self, "model-bucket", log_lifecycle_rules=s3_log_lifecycle_rules
        ).bucket

        ml_etl_cleaner_lambda_name = "ml-etl-cleaner-lambda"

        ml_etl_cleaner_lambda_role = aws_iam.Role(
            self,
            f"{ml_etl_cleaner_lambda_name}-role",
            assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
            inline_policies={
                "s3-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=["s3:PutObject", "s3:ListBucket"],
                            resources=[
                                training_data_bucket.bucket_arn,
                                f"{training_data_bucket.bucket_arn}/*",
                            ],
                        ),
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
                                    resource_name=f"/aws/lambda/{ml_etl_cleaner_lambda_name}",
                                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                ),
                                Stack.of(self).format_arn(
                                    service="logs",
                                    resource="log-group",
                                    resource_name=f"/aws/lambda/{ml_etl_cleaner_lambda_name}:log-stream:*",
                                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                ),
                            ],
                        )
                    ]
                ),
            },
        )

        # Create the Lambda function for batch transform
        ml_etl_cleaner_lambda = aws_lambda.Function(
            self,
            ml_etl_cleaner_lambda_name,
            function_name=ml_etl_cleaner_lambda_name,
            runtime=aws_lambda.Runtime.PYTHON_3_13,
            handler="function.main.handler",
            code=create_poetry_bundling("../lambda/ml_etl_cleaner"),
            timeout=Duration.minutes(1),
            memory_size=256,
            layers=[common_dependency_layer],
            role=ml_etl_cleaner_lambda_role,
            environment={"TRAINING_BUCKET_NAME": training_data_bucket.bucket_name},
            log_retention=aws_logs.RetentionDays.THREE_MONTHS,
        )

        sagemaker_role = aws_iam.Role(
            self,
            "sagemaker-role",
            assumed_by=aws_iam.ServicePrincipal("sagemaker.amazonaws.com"),
            inline_policies={
                "s3-write-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "s3:PutObject",
                                "s3:ListBucket",
                            ],
                            resources=[
                                self.model_bucket.bucket_arn,
                                f"{self.model_bucket.bucket_arn}/*",
                                prediction_bucket.bucket_arn,
                                f"{prediction_bucket.bucket_arn}/*"
                            ],
                        )
                    ]
                ),
                "s3-read-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "s3:GetObject",
                                "s3:ListBucket",
                                "s3:GetObjectVersion",
                            ],
                            resources=[
                                self.model_bucket.bucket_arn,
                                f"{self.model_bucket.bucket_arn}/*",
                                training_data_bucket.bucket_arn,
                                f"{training_data_bucket.bucket_arn}/*",
                                inference_data_bucket.bucket_arn,
                                f"{inference_data_bucket.bucket_arn}/*",
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
                                "logs:DescribeLogStreams",
                                "logs:PutLogEvents",
                            ],
                            resources=[
                                Stack.of(self).format_arn(
                                    service="logs",
                                    resource="log-group",
                                    resource_name="/aws/sagemaker/*",
                                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                )
                            ],
                        )
                    ]
                ),
                "ecr-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "ecr:GetAuthorizationToken",
                                "ecr:GetDownloadUrlForLayer",
                                "ecr:BatchGetImage",
                                "ecr:BatchCheckLayerAvailability",
                            ],
                            resources=[
                                Stack.of(self).format_arn(
                                    service="ecr",
                                    resource="repository",
                                    resource_name="randomcutforest",
                                    account=self.TRAINING_IMAGE_ACCOUNT,
                                    region=self.TRAINING_IMAGE_REGION,
                                    arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                )
                            ],
                        )
                    ]
                ),
            },
        )

        self.model_name_ssm_parameter = aws_ssm.StringParameter(
            self,
            "model-name-ssm-parameter",
            parameter_name="/tire-maintenance/model-name",
            string_value="default-model-name",  # Default value until updated by ML pipeline
            description="Name of the latest trained model for slow leak prediction",
        )

        # Fixed endpoint name for in-place updates
        endpoint_name = "tpe"

        self.model_endpoint_ssm_parameter = aws_ssm.StringParameter(
            self,
            "model-endpoint-ssm-parameter",
            parameter_name="/tire-maintenance/model-endpoint",
            string_value=endpoint_name,
            description="Name of the model endpoint for real-time inference",
        )

        invoke_ml_etl_cleaner_lambda = aws_stepfunctions_tasks.LambdaInvoke(
            self,
            f"{ml_etl_cleaner_lambda_name}-invoke",
            lambda_function=ml_etl_cleaner_lambda,
        )

        model_base_name = "tpm" # tpm = tire prediction model
        # Generate unique ID for job names
        generate_uuid = aws_stepfunctions.Pass(
            self,
            "generate-uuid",
            parameters={"uuid.$": "States.UUID()", "base_name": model_base_name},
            result_path="$.ids",
        )

        # Define SageMaker training job task with .sync()
        training_job = aws_stepfunctions_tasks.SageMakerCreateTrainingJob(
            self,
            "train-model",
            training_job_name=aws_stepfunctions.JsonPath.format(
                "{}-{}",
                aws_stepfunctions.JsonPath.string_at("$.ids.base_name"),
                aws_stepfunctions.JsonPath.string_at("$.ids.uuid"),
            ),
            algorithm_specification=aws_stepfunctions_tasks.AlgorithmSpecification(
                training_image=aws_stepfunctions_tasks.DockerImage.from_registry(
                    self.TRAINING_IMAGE_URL
                ),
                training_input_mode=aws_stepfunctions_tasks.InputMode.FILE,
            ),
            input_data_config=[
                aws_stepfunctions_tasks.Channel(
                    channel_name="train",
                    content_type="text/csv;label_size=0",
                    data_source=aws_stepfunctions_tasks.DataSource(
                        s3_data_source=aws_stepfunctions_tasks.S3DataSource(
                            s3_location=aws_stepfunctions_tasks.S3Location.from_bucket(
                                bucket=training_data_bucket,
                                key_prefix=training_config.training_data_prefix,
                            ),
                            s3_data_type=aws_stepfunctions_tasks.S3DataType.S3_PREFIX,
                        )
                    ),
                )
            ],
            output_data_config=aws_stepfunctions_tasks.OutputDataConfig(
                s3_output_location=aws_stepfunctions_tasks.S3Location.from_bucket(
                    bucket=self.model_bucket, key_prefix="tire_prediction_model"
                )
            ),
            resource_config=aws_stepfunctions_tasks.ResourceConfig(
                instance_count=4,
                instance_type=aws_ec2.InstanceType(training_config.instance_type),
                volume_size=Size.gibibytes(
                    training_config.instance_volume_size_in_gib
                ),
            ),
            stopping_condition=aws_stepfunctions_tasks.StoppingCondition(
                max_runtime=Duration.seconds(
                    training_config.max_training_time_in_seconds
                )
            ),
            hyperparameters={
                "feature_dim": model_parameters.feature_dimension,
                "num_samples_per_tree": model_parameters.num_samples_per_tree,
                "num_trees": model_parameters.num_trees,
            },
            role=sagemaker_role,
            integration_pattern=aws_stepfunctions.IntegrationPattern.RUN_JOB,
        )

        # Save training info
        save_training_info = aws_stepfunctions.Pass(
            self,
            "SaveTrainingInfo",
            parameters={
                "TrainingJobName.$": "$.TrainingJobName",
                "ModelArtifacts.$": "$.ModelArtifacts",
            },
        )

        # Define SageMaker create model task
        create_model = aws_stepfunctions_tasks.SageMakerCreateModel(
            self,
            "CreateModel",
            model_name=aws_stepfunctions.JsonPath.format(
                "{}-model", aws_stepfunctions.JsonPath.string_at("$.TrainingJobName")
            ),
            primary_container=aws_stepfunctions_tasks.ContainerDefinition(
                image=aws_stepfunctions_tasks.DockerImage.from_registry(
                    "382416733822.dkr.ecr.us-east-1.amazonaws.com/randomcutforest:1"
                ),
                model_s3_location=aws_stepfunctions_tasks.S3Location.from_json_expression(
                    "$.ModelArtifacts.S3ModelArtifacts"
                ),
                environment_variables=aws_stepfunctions.TaskInput.from_object(
                    {
                        "SAGEMAKER_CONTAINER_LOG_LEVEL": "20",
                        "SAGEMAKER_REGION": "us-east-1",
                    }
                ),
            ),
            role=sagemaker_role,
            result_path="$.ModelOutput",
        )

        # Save model info
        save_model_info = aws_stepfunctions.Pass(
            self,
            "SaveModelInfo",
            parameters={
                "TrainingJobName.$": "$.TrainingJobName",
                "ModelArtifacts.$": "$.ModelArtifacts",
                "ModelOutput.$": "$.ModelOutput",
            },
        )

        # Update SSM parameter with model name
        update_ssm_parameter_model_name = aws_stepfunctions_tasks.CallAwsService(
            self,
            "UpdateModelNameParameter",
            service="ssm",
            action="putParameter",
            parameters={
                "Name": self.model_name_ssm_parameter.parameter_name,
                "Value.$": "States.Format('{}-model', $.TrainingJobName)",
                "Overwrite": True,
            },
            iam_resources=["*"],
            result_path="$.SSMParameterUpdate",
        )

        # Check if endpoint exists
        # Define success state
        success = aws_stepfunctions.Succeed(self, "TrainingSucceeded")

        # Create new endpoint (for first run when endpoint doesn't exist)
        create_endpoint = aws_stepfunctions_tasks.SageMakerCreateEndpoint(
            self,
            "CreateEndpoint",
            endpoint_name=endpoint_name,
            endpoint_config_name=aws_stepfunctions.JsonPath.format(
                "{}-config", aws_stepfunctions.JsonPath.string_at("$.TrainingJobName")
            ),
            result_path="$.EndpointOutput",
        ).next(success)

        # Try to update endpoint first (for subsequent runs)
        # If endpoint doesn't exist, catch the error and create it instead
        update_endpoint = aws_stepfunctions_tasks.SageMakerUpdateEndpoint(
            self,
            "UpdateEndpoint",
            endpoint_name=endpoint_name,
            endpoint_config_name=aws_stepfunctions.JsonPath.format(
                "{}-config", aws_stepfunctions.JsonPath.string_at("$.TrainingJobName")
            ),
            result_path="$.EndpointOutput",
        ).add_catch(
            create_endpoint,
            errors=["States.TaskFailed"],
            result_path="$.updateError"
        ).next(success)

        # Create new endpoint configuration for the updated model
        create_endpoint_config = aws_stepfunctions_tasks.SageMakerCreateEndpointConfig(
            self,
            "CreateEndpointConfig",
            endpoint_config_name=aws_stepfunctions.JsonPath.format(
                "{}-config", aws_stepfunctions.JsonPath.string_at("$.TrainingJobName")
            ),
            production_variants=[
                aws_stepfunctions_tasks.ProductionVariant(
                    variant_name="AllTraffic",
                    model_name=aws_stepfunctions.JsonPath.format(
                        "{}-model", aws_stepfunctions.JsonPath.string_at("$.TrainingJobName")
                    ),
                    instance_type=aws_ec2.InstanceType("m5.xlarge"),
                    initial_instance_count=1,
                )
            ],
            result_path="$.EndpointConfigOutput",
        )

        # Define the workflow
        definition = (
            aws_stepfunctions.Pass(self, "InitializeVariables")
            .next(invoke_ml_etl_cleaner_lambda)
            .next(generate_uuid)
            .next(
                training_job
                .next(save_training_info)
                .next(
                    create_model
                    .next(save_model_info)
                    .next(update_ssm_parameter_model_name)
                    .next(
                        create_endpoint_config
                        .next(update_endpoint)
                    )
                )
            )
        )

        stepfunctions_role = aws_iam.Role(
            self,
            "step-functions-role",
            assumed_by=aws_iam.ServicePrincipal("states.amazonaws.com"),
            managed_policies=[
                aws_iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonSageMakerFullAccess"
                ),
                aws_iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AmazonS3ReadOnlyAccess"
                ),
            ],
            inline_policies={
                "ssm-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=["ssm:PutParameter"],
                            resources=[
                                self.model_name_ssm_parameter.parameter_arn,
                                self.model_endpoint_ssm_parameter.parameter_arn,
                            ],
                        )
                    ]
                ),
                "sagemaker-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "sagemaker:CreateModel",
                                "sagemaker:CreateTrainingJob",
                                "sagemaker:CreateEndpoint",
                                "sagemaker:CreateEndpointConfig",
                                "sagemaker:UpdateEndpoint",
                                "sagemaker:DescribeEndpoint",
                            ],
                            resources=[
                                Stack.of(self).format_arn(
                                    service="sagemaker",
                                    account=Stack.of(self).account,
                                    region=Stack.of(self).region,
                                    resource="training-job",
                                    resource_name="*",
                                ),
                                Stack.of(self).format_arn(
                                    service="sagemaker",
                                    account=Stack.of(self).account,
                                    region=Stack.of(self).region,
                                    resource="model",
                                    resource_name="*",
                                ),
                                Stack.of(self).format_arn(
                                    service="sagemaker",
                                    account=Stack.of(self).account,
                                    region=Stack.of(self).region,
                                    resource="endpoint",
                                    resource_name="*",
                                ),
                                Stack.of(self).format_arn(
                                    service="sagemaker",
                                    account=Stack.of(self).account,
                                    region=Stack.of(self).region,
                                    resource="endpoint-config",
                                    resource_name="*",
                                ),
                            ],
                        )
                    ]
                ),
                "iam-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=["iam:PassRole"],
                            resources=[sagemaker_role.role_arn],
                        )
                    ]
                ),
            },
        )

        # Create the state machine
        self.training_step_function = aws_stepfunctions.StateMachine(
            self,
            "RCFTrainingPipeline",
            definition_body=aws_stepfunctions.DefinitionBody.from_chainable(definition),
            role=stepfunctions_role,
            timeout=Duration.hours(1),
        )

        # turn on this rule to run it at a scheduled time
        # aws_events.Rule(
        #     self,
        #     "ml-training-scheduled-run-rule",
        #     schedule=aws_events.Schedule.expression(ml_training_cron_string),
        #     targets=[aws_events_targets.SfnStateMachine(self.training_step_function)],
        # )
