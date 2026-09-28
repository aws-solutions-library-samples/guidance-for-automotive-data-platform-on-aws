# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict

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
def get_sagemaker_client() -> SageMakerClient:
    return boto3.client("sagemaker")


COMPLETED_STATUS = "Completed"


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Lambda function to check the status of a SageMaker transform job.
    """
    job_name = event.get("job_name")

    if not job_name:
        return {
            "statusCode": 400,
            "status": "Failed",
            "message": "Missing job_name parameter",
        }

    # Get transform job status
    try:
        response = get_sagemaker_client().describe_transform_job(
            TransformJobName=job_name
        )

        status = response["TransformJobStatus"]

        if status == COMPLETED_STATUS:
            return {
                "statusCode": 200,
                "status": status,
                "job_name": job_name,
                "output_path": response["TransformOutput"]["S3OutputPath"],
            }
        return {"statusCode": 200, "status": status, "job_name": job_name}
    except Exception as e:
        return {"statusCode": 500, "status": "Failed", "message": str(e)}
