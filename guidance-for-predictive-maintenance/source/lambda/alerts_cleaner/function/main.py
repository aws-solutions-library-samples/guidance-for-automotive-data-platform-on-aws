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
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    # Third Party Libraries
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table
else:
    S3Client = object
    DynamoDBServiceResource = object
    SQSClient = object
    Table = object

# Environment variables
ALERTS_TABLE_NAME = os.environ["ALERTS_TABLE"]
USER_AGENT_STRING = os.environ.get("USER_AGENT_STRING", None)
POWERTOOLS_METRICS_NAMESPACE = os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "Default")

tracer = Tracer()
logger = Logger()
metrics = Metrics()
default_dimensions = {"Metrics Namespace": POWERTOOLS_METRICS_NAMESPACE}


@lru_cache(maxsize=1)
def get_dynamodb_client() -> DynamoDBServiceResource:
    return boto3.resource("dynamodb", config=Config(user_agent_extra=USER_AGENT_STRING))


@lru_cache(maxsize=1)
def get_alerts_table() -> Table:
    return get_dynamodb_client().Table(ALERTS_TABLE_NAME)


def update_alert_status(
    alert_id: str,
    timestamp: str,
) -> bool:
    """Update the status of an alert in DynamoDB to FAILED only if it exists and status is PENDING.

    Args:
        alert_id: The ID of the alert
        timestamp: The timestamp of the alert

    Returns:
        True if the update was successful or if the condition wasn't met (item doesn't exist or status is not PENDING),
        False only for actual errors that should cause retry
    """

    try:
        get_alerts_table().update_item(
            Key={"alertId": alert_id, "timestamp": timestamp},
            UpdateExpression="SET #status = :new_status",
            ConditionExpression="attribute_exists(alertId) AND #status = :pending_status",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":new_status": "FAILED",
                ":pending_status": "PENDING",
            },
        )
        logger.info(f"Updated alert {alert_id} status from PENDING to FAILED")
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info(
                f"Alert not found or status is not PENDING - considering as successful: alertId={alert_id}, timestamp={timestamp}"
            )
            # Return True for conditional check failures since we don't want to retry these
            return True
        logger.error(f"DynamoDB client error updating alert status: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Error updating alert status: {str(e)}")
        return False


def process_dlq_message(record: Dict[str, Any]) -> bool:
    """Process a single DLQ message and update the corresponding DynamoDB item.

    Args:
        record: The SQS record containing the DLQ message

    Returns:
        True if processing was successful, False otherwise
    """
    message_id = record.get("messageId", "unknown")
    body = record.get("body", "{}")

    logger.info(f"Processing DLQ message {message_id}")

    try:
        message_data = json.loads(body)
    except json.JSONDecodeError:
        logger.warning(f"Could not parse message body as JSON: {body}")
        return False

    if not isinstance(message_data, dict):
        logger.warning(f"Message data is not a dictionary: {message_data}")
        return False

    alert_id = message_data.get("alertId")
    timestamp = message_data.get("timestamp")

    if not alert_id or not timestamp:
        logger.warning(f"Message missing required alertId or timestamp: {message_data}")
        return False

    # Update the alert status to FAILED in DynamoDB
    success = update_alert_status(alert_id, timestamp)

    if not success:
        logger.warning(f"Failed to update alert {alert_id} status to FAILED")
        return False

    logger.info(f"Successfully updated alert {alert_id} status to FAILED")
    return True


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics(default_dimensions=default_dimensions)
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """Lambda handler for processing DLQ messages.

    Args:
        event: The Lambda event containing SQS messages from the DLQ
        context: The Lambda context

    Returns:
        Dict with processing results
    """
    if "Records" not in event:
        logger.info("No records found in event")
        return {"batchItemFailures": []}

    logger.info(f"Processing {len(event['Records'])} messages from DLQ")

    batch_item_failures = []
    processed_count = 0

    for record in event["Records"]:
        receipt_handle = record["receiptHandle"]
        try:
            success = process_dlq_message(record)

            if not success:
                batch_item_failures.append({"itemIdentifier": receipt_handle})
                continue

            processed_count += 1

        except Exception as e:
            logger.exception(f"Error processing DLQ message: {str(e)}")
            batch_item_failures.append({"itemIdentifier": receipt_handle})

    logger.info(f"Successfully processed {processed_count} messages")
    logger.info(f"Failed to process {len(batch_item_failures)} messages")

    metrics.add_metric(
        name="AlertsCleaned", unit=MetricUnit.Count, value=processed_count
    )

    return {"batchItemFailures": batch_item_failures}
