# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import json
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict

# AWS Libraries
import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

if TYPE_CHECKING:
    # Third Party Libraries
    from mypy_boto3_sagemaker_runtime import SageMakerRuntimeClient
    from mypy_boto3_ssm.client import SSMClient
else:
    SageMakerRuntimeClient = object
    SSMClient = object

tracer = Tracer()
logger = Logger()


class ThresholdNotAvailableError(Exception):
    """Raised when anomaly threshold is not yet available in SSM"""
    pass


@lru_cache(maxsize=128)
def get_sagemaker_runtime_client() -> SageMakerRuntimeClient:
    return boto3.client("sagemaker-runtime")


@lru_cache(maxsize=128)
def get_ssm_client() -> SSMClient:
    return boto3.client("ssm")


def get_normalization_stats() -> Dict[str, Dict[str, float]]:
    """Retrieve normalization statistics from SSM Parameter Store."""
    normalization_stats_parameter = os.environ["NORMALIZATION_STATS_PARAMETER"]
    response = get_ssm_client().get_parameter(Name=normalization_stats_parameter)
    return json.loads(response["Parameter"]["Value"])


def get_endpoint_name() -> str:
    """Retrieve the model endpoint name from SSM Parameter Store."""
    model_endpoint_parameter = os.environ["MODEL_ENDPOINT_PARAMETER"]
    response = get_ssm_client().get_parameter(Name=model_endpoint_parameter)
    return response["Parameter"]["Value"]


def get_anomaly_threshold() -> float:
    """Retrieve anomaly threshold from SSM Parameter Store."""
    anomaly_threshold_parameter = os.environ["ANOMALY_THRESHOLD_PARAMETER"]
    response = get_ssm_client().get_parameter(Name=anomaly_threshold_parameter)
    threshold_data = json.loads(response["Parameter"]["Value"])
    
    threshold = threshold_data.get("threshold")
    if threshold is None:
        raise ThresholdNotAvailableError(
            "Anomaly threshold not yet available. Please run batch inference first to establish baseline."
        )
    
    return float(threshold)


def normalize_features(
    pressure: float,
    temperature: float,
    delta_pressure: float,
    delta_temp: float,
    stats: Dict[str, Dict[str, float]],
) -> list[float]:
    """
    Normalize input features using stored statistics.
    
    Returns normalized features in order: [pressure, temperature, delta_pressure, delta_temp]
    """
    normalized = []
    
    features = {
        "pressure": pressure,
        "temperature": temperature,
        "delta_pressure": delta_pressure,
        "delta_temp": delta_temp,
    }
    
    for feature_name in ["pressure", "temperature", "delta_pressure", "delta_temp"]:
        value = features[feature_name]
        mean = stats.get(feature_name, {}).get("mean", 0.0)
        std = stats.get(feature_name, {}).get("std", 1.0)
        
        # Handle None values from SSM (first run case)
        if mean is None:
            mean = 0.0
        if std is None or std == 0:
            std = 1.0
        
        # Z-score normalization
        normalized_value = (value - mean) / std
        normalized.append(normalized_value)
    
    return normalized


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Lambda function for real-time tire prediction inference.
    
    Handles both direct invocation and API Gateway events.
    
    Expected input (API Gateway body):
    {
        "vehicle_id": "ABC123",
        "tire_id": "FL",
        "pressure": 32.5,
        "temperature": 75.0,
        "delta_pressure": -0.5,
        "delta_temp": 2.0
    }
    
    Returns (API Gateway format):
    {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": "{\"anomaly_score\": 0.75, \"prediction\": true, \"vehicle_id\": \"ABC123\", \"tire_id\": \"FL\"}"
    }
    """
    
    # Handle API Gateway event format
    if "body" in event:
        # API Gateway event
        try:
            if isinstance(event["body"], str):
                body = json.loads(event["body"])
            else:
                body = event["body"]
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Invalid JSON in request body: {e}")
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*"
                },
                "body": json.dumps({
                    "error": "Invalid JSON in request body"
                }),
            }
    else:
        # Direct invocation
        body = event
    
    # Extract input features
    vehicle_id = body.get("vehicle_id")
    tire_id = body.get("tire_id")
    pressure = body.get("pressure")
    temperature = body.get("temperature")
    delta_pressure = body.get("delta_pressure")
    delta_temp = body.get("delta_temp")
    
    # Validate required fields
    if None in [vehicle_id, tire_id, pressure, temperature, delta_pressure, delta_temp]:
        error_response = {
            "error": "Missing required fields: vehicle_id, tire_id, pressure, temperature, delta_pressure, delta_temp"
        }
        
        if "body" in event:
            # API Gateway response
            return {
                "statusCode": 400,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*"
                },
                "body": json.dumps(error_response),
            }
        else:
            # Direct invocation response
            return {
                "statusCode": 400,
                "body": json.dumps(error_response),
            }
    
    # Get normalization statistics, endpoint name, and anomaly threshold
    try:
        stats = get_normalization_stats()
        endpoint_name = get_endpoint_name()
        anomaly_threshold = get_anomaly_threshold()
    except ThresholdNotAvailableError as e:
        logger.error(str(e))
        error_response = {
            "error": "Service Unavailable",
            "message": str(e)
        }
        
        if "body" in event:
            # API Gateway response
            return {
                "statusCode": 503,
                "headers": {
                    "Content-Type": "application/json",
                    "Access-Control-Allow-Origin": "*"
                },
                "body": json.dumps(error_response),
            }
        else:
            # Direct invocation response
            return {
                "statusCode": 503,
                "body": json.dumps(error_response),
            }
    
    logger.info(f"Using endpoint: {endpoint_name}, threshold: {anomaly_threshold}")
    
    # Normalize features
    normalized_features = normalize_features(
        pressure=float(pressure),
        temperature=float(temperature),
        delta_pressure=float(delta_pressure),
        delta_temp=float(delta_temp),
        stats=stats,
    )
    
    # Prepare payload for SageMaker endpoint (CSV format)
    payload = ",".join(str(f) for f in normalized_features)
    
    logger.info(f"Invoking endpoint with normalized features: {payload}")
    
    # Invoke SageMaker endpoint
    response = get_sagemaker_runtime_client().invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="text/csv",
        Body=payload,
    )
    
    # Parse prediction score from response
    result = json.loads(response["Body"].read().decode())
    anomaly_score = float(result["scores"][0]["score"])
    
    # Determine prediction based on dynamic threshold
    prediction = anomaly_score > anomaly_threshold
    
    logger.info(f"Anomaly score: {anomaly_score}, Threshold: {anomaly_threshold}, Prediction: {prediction}")
    
    success_response = {
        "anomaly_score": anomaly_score,
        "prediction": prediction,
        "vehicle_id": vehicle_id,
        "tire_id": tire_id,
    }
    
    if "body" in event:
        # API Gateway response
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(success_response),
        }
    else:
        # Direct invocation response
        return {
            "statusCode": 200,
            "body": json.dumps(success_response),
        }
