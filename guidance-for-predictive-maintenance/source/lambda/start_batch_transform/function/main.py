# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict
from uuid import uuid4
from zoneinfo import ZoneInfo

# AWS Libraries
import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

if TYPE_CHECKING:
    # Third Party Libraries
    from mypy_boto3_sagemaker import SageMakerClient
    from mypy_boto3_ssm.client import SSMClient

else:
    SSMClient = object
    SageMakerClient = object

tracer = Tracer()
logger = Logger()


@lru_cache(maxsize=128)
def get_ssm_client() -> SSMClient:
    return boto3.client("ssm")


@lru_cache(maxsize=128)
def get_sagemaker_client() -> SageMakerClient:
    return boto3.client("sagemaker")


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Lambda function to start a SageMaker batch transform job.
    """
    # Get model name from SSM Parameter Store
    model_name_param = get_ssm_client().get_parameter(
        Name="/tire-maintenance/model-name"
    )
    model_name = model_name_param["Parameter"]["Value"]

    time_zone = ZoneInfo("UTC")
    try:
        #### YYYY-MM-DD iso format
        date = event["DATE"]
        current_time = datetime.fromisoformat(date)
    except KeyError:
        current_time = datetime.now(time_zone)
    previous_date = current_time - timedelta(days=1)

    input_path = (
        f"{os.environ['INFERENCE_DATA_BUCKET']}/{previous_date.strftime('%Y/%m/%d')}"
    )

    raw_predictions_bucket = os.environ["PREDICTIONS_BUCKET"]
    date_prefix = current_time.strftime("%Y/%m/%d")
    output_path = f"{raw_predictions_bucket}/{date_prefix}/"

    # Start batch transform job
    job_name = f"model-batch-{current_time.strftime('%Y-%m-%d')}-{uuid4()}"
    get_sagemaker_client().create_transform_job(
        TransformJobName=job_name,
        ModelName=model_name,
        TransformInput={
            "DataSource": {
                "S3DataSource": {"S3DataType": "S3Prefix", "S3Uri": str(input_path)}
            },
            "ContentType": "text/csv",
            "SplitType": "Line",
        },
        TransformOutput={
            "S3OutputPath": output_path,
            "Accept": "text/csv",
            "AssembleWith": "Line",
        },
        TransformResources={"InstanceType": "ml.m5.12xlarge", "InstanceCount": 1},
        DataProcessing={
            "InputFilter": "$[4:7]",  # NOTE: First 12 columns are metadata
            "OutputFilter": "$[0,1,2,3,-1]",  # NOTE: take metadata and anomaly score as output
            "JoinSource": "Input",
        },
    )

    return {"statusCode": 200, "job_name": job_name, "output_path": output_path}
