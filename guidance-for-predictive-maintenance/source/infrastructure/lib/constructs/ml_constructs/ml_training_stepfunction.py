# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
MLTrainingConstruct
===================
SageMaker training pipeline with Step Functions supporting TWO model options:

1. **Unsupervised (RCF)** — Amazon Random Cut Forest, the original baseline.
   Trains on pressure/tread/temperature feature vectors without labels.
   Suitable for anomaly scoring when ground-truth labels are unavailable.

2. **Supervised (XGBoost)** — Amazon XGBoost, NEW in Phase 3b.
   Trains on the ``wear_category`` / ``needs_replacement`` labels now present
   in the ``tire_health`` governed data product written by the Governed ETL job.
   Outputs a classification model (wear_category: ok/monitor/replace).

The ``model_type`` parameter (``"rcf"`` | ``"xgboost"``) selects which
algorithm is used.  Both options share the same Step Functions skeleton
(Train → Create Model → Create Endpoint); only the algorithm image URL and
hyperparameters differ.

XGBoost image
-------------
Uses the SageMaker-managed XGBoost container via
``aws_stepfunctions_tasks.DockerImage.from_registry``.  The account/region
are the SageMaker built-in algorithm container registries, resolved via
the regional ECR account lookup pattern.  We use the public ECR alias
``763104351884.dkr.ecr.<region>.amazonaws.com/xgboost:1.7-1`` which is the
stable XGBoost 1.7 image available in all commercial regions.

Training data format
--------------------
* RCF: ``text/csv;label_size=0`` (label column absent or zero columns at start)
* XGBoost: ``text/csv`` with the label in column 0 (SageMaker XGBoost convention)

The Governed ETL job (``governed_etl_job.py``) writes two Parquet layouts:
  ``training/rcf/``      — unlabeled feature vectors (10 features)
  ``training/xgboost/``  — label (wear_category ordinal 0/1/2) + 10 features

The ``training_data_prefix`` in ``ModelTrainingConfig`` selects which layout
to use.
"""

# Standard Library
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

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
from cdk_nag import NagSuppressions
from constructs import Construct

# Predictive Maintenance
from ...common.encrypted_s3 import EncryptedS3Construct, LifecycleConfig
from ...common.lambda_bundling import create_poetry_bundling


class ModelType(str, Enum):
    """Supported SageMaker algorithm options for PM training."""

    RCF = "rcf"           # unsupervised anomaly detection (original baseline)
    XGBOOST = "xgboost"   # supervised wear classification (Phase 3b, NEW)


@dataclass
class ModelTrainingConfig:
    """Configuration for SageMaker training job."""

    training_data_prefix: str  # S3 key prefix under training_data_bucket
    instance_type: str         # e.g. "m5.12xlarge"
    instance_volume_size_in_gib: int  # e.g. 400
    max_training_time_in_seconds: int  # e.g. 3600
    model_type: ModelType = ModelType.RCF  # which algorithm to train


@dataclass
class ModelParameters:
    """RCF hyperparameters (used when model_type == ModelType.RCF)."""

    feature_dimension: str     # e.g. "10"
    num_samples_per_tree: str  # e.g. "256"
    num_trees: str             # e.g. "100"


@dataclass
class XGBoostModelParameters:
    """XGBoost hyperparameters (used when model_type == ModelType.XGBOOST).

    Target: wear_category ordinal classification (0=ok, 1=monitor, 2=replace).
    """

    num_round: str = "100"          # boosting rounds
    max_depth: str = "6"            # tree depth
    eta: str = "0.3"                # learning rate
    objective: str = "multi:softmax"  # multi-class classification
    num_class: str = "3"            # ok / monitor / replace
    eval_metric: str = "merror"     # multi-class error rate
    subsample: str = "0.8"          # row subsample
    colsample_bytree: str = "0.8"   # column subsample
    min_child_weight: str = "1"     # min leaf weight
    gamma: str = "0"                # min loss reduction for split


# ---------------------------------------------------------------------------
# SageMaker built-in algorithm container registry — XGBoost 1.7
# Regional ECR URI pattern (public ECR framework container).
# Account 763104351884 is the AWS Deep Learning Containers account across
# all commercial regions.
# Source: https://github.com/aws/sagemaker-python-sdk/blob/master/src/sagemaker/image_uri_config/xgboost.json
# ---------------------------------------------------------------------------
_XGBOOST_IMAGE_ACCOUNT = "763104351884"
_XGBOOST_IMAGE_TAG = "1.7-1"  # stable XGBoost 1.7, available in all commercial regions


class MLTrainingConstruct(Construct):
    """
    A construct that creates an ML training pipeline with Step Functions:
    1. SageMaker Training Job (RCF or XGBoost depending on model_type)
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
        xgboost_parameters: Optional[XGBoostModelParameters] = None,
    ):
        """Construct an ML training pipeline.

        Parameters
        ----------
        training_config.model_type
            ``ModelType.RCF`` (default — unsupervised, original baseline) or
            ``ModelType.XGBOOST`` (supervised, Phase 3b addition).
        xgboost_parameters
            Required when ``training_config.model_type == ModelType.XGBOOST``.
            Ignored for RCF.
        """
        super().__init__(scope, id)

        stack = Stack.of(self)
        model_type = training_config.model_type

        # ------------------------------------------------------------------
        # Select algorithm image URL based on model_type.
        # RCF: ECR image in us-east-1 (fixed per original implementation).
        # XGBoost: regional DLC ECR image (resolved at synth time from stack
        # region so the correct regional endpoint is used).
        # ------------------------------------------------------------------
        if model_type == ModelType.XGBOOST:
            # XGBoost DLC image — regional; account 763104351884 is the AWS
            # Deep Learning Containers account in all commercial partitions.
            training_image_url = (
                f"{_XGBOOST_IMAGE_ACCOUNT}.dkr.ecr."
                f"{stack.region}.amazonaws.com/xgboost:{_XGBOOST_IMAGE_TAG}"
            )
            content_type = "text/csv"  # XGBoost: label col 0 + features
            _xgb_params = xgboost_parameters or XGBoostModelParameters()
            hyperparameters: dict[str, str] = {
                "num_round": _xgb_params.num_round,
                "max_depth": _xgb_params.max_depth,
                "eta": _xgb_params.eta,
                "objective": _xgb_params.objective,
                "num_class": _xgb_params.num_class,
                "eval_metric": _xgb_params.eval_metric,
                "subsample": _xgb_params.subsample,
                "colsample_bytree": _xgb_params.colsample_bytree,
                "min_child_weight": _xgb_params.min_child_weight,
                "gamma": _xgb_params.gamma,
            }
        else:
            # RCF — original baseline (unsupervised anomaly detection).
            training_image_url = self.TRAINING_IMAGE_URL
            content_type = "text/csv;label_size=0"
            hyperparameters = {
                "feature_dim": model_parameters.feature_dimension,
                "num_samples_per_tree": model_parameters.num_samples_per_tree,
                "num_trees": model_parameters.num_trees,
            }

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
                        # GetAuthorizationToken is account-level and cannot be
                        # scoped to a specific repository ARN — must use resources=["*"].
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=["ecr:GetAuthorizationToken"],
                            resources=["*"],
                        ),
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "ecr:GetDownloadUrlForLayer",
                                "ecr:BatchGetImage",
                                "ecr:BatchCheckLayerAvailability",
                            ],
                            # For RCF: scope to the specific ECR repo in us-east-1.
                            # For XGBoost: scope to the regional DLC ECR repo
                            # (account 763104351884 in the stack's own region).
                            resources=[
                                Stack.of(self).format_arn(
                                    service="ecr",
                                    resource="repository",
                                    resource_name=(
                                        "xgboost"
                                        if model_type == ModelType.XGBOOST
                                        else "randomcutforest"
                                    ),
                                    account=(
                                        _XGBOOST_IMAGE_ACCOUNT
                                        if model_type == ModelType.XGBOOST
                                        else self.TRAINING_IMAGE_ACCOUNT
                                    ),
                                    region=(
                                        stack.region
                                        if model_type == ModelType.XGBOOST
                                        else self.TRAINING_IMAGE_REGION
                                    ),
                                    arn_format=ArnFormat.SLASH_RESOURCE_NAME,
                                )
                            ],
                        ),
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
                    training_image_url  # dynamic: RCF or XGBoost
                ),
                training_input_mode=aws_stepfunctions_tasks.InputMode.FILE,
            ),
            input_data_config=[
                aws_stepfunctions_tasks.Channel(
                    channel_name="train",
                    content_type=content_type,  # dynamic: RCF vs XGBoost format
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
            hyperparameters=hyperparameters,  # dynamic: RCF or XGBoost params
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

        # Define SageMaker create model task.
        # Use the same dynamic image URL for the inference container so that
        # the model registered in the SageMaker model registry matches the
        # training image.
        create_model = aws_stepfunctions_tasks.SageMakerCreateModel(
            self,
            "CreateModel",
            model_name=aws_stepfunctions.JsonPath.format(
                "{}-model", aws_stepfunctions.JsonPath.string_at("$.TrainingJobName")
            ),
            primary_container=aws_stepfunctions_tasks.ContainerDefinition(
                image=aws_stepfunctions_tasks.DockerImage.from_registry(
                    training_image_url  # dynamic: must match training image
                ),
                model_s3_location=aws_stepfunctions_tasks.S3Location.from_json_expression(
                    "$.ModelArtifacts.S3ModelArtifacts"
                ),
                environment_variables=aws_stepfunctions.TaskInput.from_object(
                    {
                        "SAGEMAKER_CONTAINER_LOG_LEVEL": "20",
                        "SAGEMAKER_REGION": Stack.of(self).region,
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
            iam_resources=[self.model_name_ssm_parameter.parameter_arn],
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
            # AmazonSageMakerFullAccess + AmazonS3ReadOnlyAccess managed policies removed (IAM4 fix, #30).
            # The inline "sagemaker-policy" below already grants all required SageMaker actions
            # (CreateModel, CreateTrainingJob, CreateEndpoint, CreateEndpointConfig, UpdateEndpoint,
            # DescribeEndpoint) scoped to specific resource ARNs. The CDK-generated DefaultPolicy
            # (from S3Location.from_bucket() on training_data_bucket) covers the S3 read access
            # that Step Functions tasks need to pass bucket locations to SageMaker — AmazonS3ReadOnlyAccess
            # was therefore redundant. AmazonSageMakerFullAccess was also redundant given the scoped
            # inline policy.
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
                                # AddTags required when Create* calls carry tags (runtime
                                # AccessDeniedException otherwise)
                                "sagemaker:AddTags",
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
                # SF1: allow Step Functions to deliver execution logs to CloudWatch
                "logs-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogDelivery",
                                "logs:GetLogDelivery",
                                "logs:UpdateLogDelivery",
                                "logs:DeleteLogDelivery",
                                "logs:ListLogDeliveries",
                                "logs:PutLogEvents",
                                "logs:PutResourcePolicy",
                                "logs:DescribeResourcePolicies",
                                "logs:DescribeLogGroups",
                            ],
                            resources=["*"],
                        )
                    ]
                ),
            },
        )

        # CloudWatch Log Group for Step Function execution logs (SF1)
        training_sf_log_group = aws_logs.LogGroup(
            self,
            "training-sf-logs",
            log_group_name="/aws/states/RCFTrainingPipeline",
            retention=aws_logs.RetentionDays.THREE_MONTHS,
        )

        # Create the state machine
        self.training_step_function = aws_stepfunctions.StateMachine(
            self,
            "RCFTrainingPipeline",
            definition_body=aws_stepfunctions.DefinitionBody.from_chainable(definition),
            role=stepfunctions_role,
            timeout=Duration.hours(1),
            # SF1: log ALL events to CloudWatch Logs
            logs=aws_stepfunctions.LogOptions(
                destination=training_sf_log_group,
                level=aws_stepfunctions.LogLevel.ALL,
                include_execution_data=True,
            ),
            # SF2: enable X-Ray tracing
            tracing_enabled=True,
        )

        # turn on this rule to run it at a scheduled time
        # aws_events.Rule(
        #     self,
        #     "ml-training-scheduled-run-rule",
        #     schedule=aws_events.Schedule.expression(ml_training_cron_string),
        #     targets=[aws_events_targets.SfnStateMachine(self.training_step_function)],
        # )

        # ---------------------------------------------------------------------------
        # NagSuppressions — documented justifications, reviewed per-resource.
        # ---------------------------------------------------------------------------

        # AwsSolutions-L1 (#26): ml-etl-cleaner-lambda pinned to python3.13.
        NagSuppressions.add_resource_suppressions(
            ml_etl_cleaner_lambda,
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

        # AwsSolutions-IAM5 (#27): ml-etl-cleaner-lambda-role wildcards.
        #   • S3 training-bucket/*: PutObject for ETL cleaner output requires the /* suffix;
        #     bucket ARN is already scoped to the specific training bucket.
        #   • CW log-stream *: Lambda writes to execution-ID-suffixed streams unknown at deploy.
        NagSuppressions.add_resource_suppressions(
            ml_etl_cleaner_lambda_role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Two operationally-required wildcards: "
                        "(1) S3 training-bucket/*: object-level PutObject requires the /* suffix; "
                        "bucket ARN is already scoped to the specific CDK-provisioned training bucket. "
                        "(2) CW log-stream *: Lambda writes to execution-ID-suffixed streams whose "
                        "exact names are unknown at deploy time — standard AWS Lambda logging pattern."
                    ),

                }
            ],
        )

        # AwsSolutions-IAM5 (#28): sagemaker-role inline policy wildcards.
        #   • S3 bucket/*: object-level SageMaker training/inference I/O requires /* suffix;
        #     bucket ARNs are already scoped to specific CDK-provisioned buckets.
        #   • /aws/sagemaker/*: SageMaker container logs use a log-group name that includes
        #     the training job name, which is unknown at deploy time.
        #   • ECR Resource::*: ecr:GetAuthorizationToken is an account-level action; AWS
        #     documentation explicitly states it cannot be scoped to a specific repository ARN.
        NagSuppressions.add_resource_suppressions(
            sagemaker_role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Operationally-required wildcards on the SageMaker execution role: "
                        "(1) S3 bucket/*: SageMaker training I/O reads/writes require the /* object "
                        "suffix; bucket ARNs are already scoped to specific CDK-provisioned buckets. "
                        "(2) CW logs /aws/sagemaker/*: SageMaker container log groups include the "
                        "training job name, which is a runtime UUID unknown at deploy time. "
                        "(3) ecr:GetAuthorizationToken Resource::*: per AWS documentation, "
                        "GetAuthorizationToken is an account-level IAM action that cannot be scoped "
                        "to a specific ECR repository ARN."
                    ),
                }
            ],
            apply_to_children=True,
        )

        # AwsSolutions-IAM5 (#29): sagemaker-role/DefaultPolicy CDK-grant wildcards.
        # CDK's S3Location.from_bucket() adds s3:GetBucket*, s3:GetObject*, s3:List*,
        # s3:Abort*, s3:DeleteObject* action wildcards plus bucket/* resource wildcards.
        # These are inherent to the CDK SageMaker training task L2 construct's grant pattern;
        # resource scope is already bounded to specific bucket ARNs.
        # ECR Resource::* covers the GetAuthorizationToken account-level action (see #28 above).
        NagSuppressions.add_resource_suppressions(
            sagemaker_role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "CDK-grant-generated action wildcards in DefaultPolicy from "
                        "S3Location.from_bucket() (s3:GetBucket*, s3:GetObject*, s3:List*, "
                        "s3:Abort*, s3:DeleteObject*) and resource wildcards (bucket/*, prefix/*). "
                        "These are inherent to the CDK SageMaker training task L2 construct grant "
                        "pattern; resource scope is already bounded to specific CDK-provisioned "
                        "bucket ARNs.  Also covers ecr:GetAuthorizationToken Resource::* which is "
                        "an account-level action that AWS does not allow scoping to a repo ARN."
                    ),
                    "appliesTo": [
                        "Action::s3:GetBucket*",
                        "Action::s3:GetObject*",
                        "Action::s3:List*",
                        "Action::s3:Abort*",
                        "Action::s3:DeleteObject*",
                        "Resource::*",
                    ],
                }
            ],
            apply_to_children=True,
        )

        # AwsSolutions-IAM5 (#31): step-functions-role inline policy wildcards.
        # The SageMaker sagemaker-policy actions use resource_name="*" because SageMaker
        # training-job, model, endpoint, and endpoint-config names are UUID-suffixed at
        # runtime (generated by the State Machine execution) and are unknown at deploy time.
        # The resource type is already scoped (training-job/*, model/*, endpoint/*, etc.).
        NagSuppressions.add_resource_suppressions(
            stepfunctions_role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "SageMaker resource name wildcards (training-job/*, model/*, endpoint/*, "
                        "endpoint-config/*) in the step-functions-role inline policy: SageMaker "
                        "job/model/endpoint names are UUID-suffixed at runtime by the Step Functions "
                        "execution and are unknown at CDK synth time.  Resource type is already "
                        "scoped (not sagemaker:*) — only the resource-name suffix is wildcarded. "
                        "Also: logs:* on Resource::* is required for SF CloudWatch log delivery "
                        "per AWS Step Functions documentation (account-level log-delivery actions "
                        "cannot be scoped to a specific log group ARN)."
                    ),
                    "appliesTo": [
                        "Resource::*",
                        "Resource::arn:<AWS::Partition>:sagemaker:<AWS::Region>:<AWS::AccountId>:training-job/*",
                        "Resource::arn:<AWS::Partition>:sagemaker:<AWS::Region>:<AWS::AccountId>:model/*",
                        "Resource::arn:<AWS::Partition>:sagemaker:<AWS::Region>:<AWS::AccountId>:endpoint/*",
                        "Resource::arn:<AWS::Partition>:sagemaker:<AWS::Region>:<AWS::AccountId>:endpoint-config/*",
                    ],
                }
            ],
            apply_to_children=True,
        )

        # AwsSolutions-IAM5 (#32): step-functions-role/DefaultPolicy CDK-grant wildcards.
        # Lambda ARN :* wildcard is added by CDK's LambdaInvoke task when it grants
        # lambda:InvokeFunction on the Lambda function ARN — the :* suffix covers all
        # qualified versions/aliases, which is the CDK L2 grant pattern.
        # SageMaker training-job/model/endpoint-config/* wildcards are runtime-generated UUIDs.
        # ECR Resource::* covers ecr:GetAuthorizationToken (account-level, cannot be scoped).
        NagSuppressions.add_resource_suppressions(
            stepfunctions_role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "CDK-grant-generated wildcards in step-functions-role DefaultPolicy: "
                        "(1) Lambda ARN :* suffix is generated by CDK LambdaInvoke task grant — "
                        "covers all Lambda qualified versions/aliases (CDK L2 pattern). "
                        "(2) SageMaker training-job/*, model/*, endpoint-config/* resource "
                        "wildcards — names are runtime-generated UUIDs unknown at deploy time. "
                        "(3) ECR Resource::* for ecr:GetAuthorizationToken — account-level action "
                        "that AWS does not allow scoping to a specific repository ARN."
                    ),
                }
            ],
            apply_to_children=True,
        )
