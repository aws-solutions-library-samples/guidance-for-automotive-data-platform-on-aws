# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import base64
import decimal
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict, List, NamedTuple, Optional, Union, cast

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
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient
    from mypy_boto3_sqs.type_defs import DeleteMessageBatchRequestEntryTypeDef

else:
    S3Client = object
    DynamoDBServiceResource = object
    SQSClient = object
    Table = object
    DeleteMessageBatchRequestEntryTypeDef = dict

RELAY_GARAGE_MAX_BATCH_SIZE = 10  # TODO: Set this based on real max
ALERTS_TABLE_NAME = os.environ["ALERTS_TABLE"]
ALERTS_QUEUE_URL = os.environ["ALERTS_QUEUE_URL"]
ALERTS_BUCKET = os.environ["ALERTS_BUCKET"]
ALERTS_BUCKET_PREFIX = os.environ.get("ALERTS_BUCKET_PREFIX", "alerts")
USER_AGENT_STRING = os.environ.get("USER_AGENT_STRING", None)
POWERTOOLS_METRICS_NAMESPACE = os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "Default")


class FailureInfo(NamedTuple):
    code: str
    message: str


class FailureReason(Enum):
    INVALID_ALERT_REF = FailureInfo(
        "INVALID_ALERT_REF", "Alert ref invalid, check AlertId and Timestamp"
    )
    DB_NOT_FOUND = FailureInfo("DB_NOT_FOUND", "Alert entry not found in database")
    PUBLISH_ERROR = FailureInfo("PUBLISH_ERROR", "Failed to publish alert")
    SERVICE_UNAVAILABLE = FailureInfo("SVC_DOWN", "Service unavailable")
    AUTH_FAILURE = FailureInfo("AUTH_FAILURE", "Unable to authorize to API")
    RATE_LIMIT_EXCEEDED = FailureInfo(
        "RATE_LIMIT_EXCEEDED",
        "The API rate limit was exceeded when trying to publish alerts",
    )
    UNKNOWN_ERROR = FailureInfo("UNKNOWN_ERROR", "An unknown error occurred")

    @property
    def code(self) -> str:
        return self.value.code

    @property
    def message(self) -> str:
        return self.value.message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True)
class FailedAlert:
    alert_ref: Dict[str, Any]
    failure_reason: FailureReason


tracer = Tracer()
logger = Logger()
metrics = Metrics()
default_dimensions = {"Metrics Namespace": POWERTOOLS_METRICS_NAMESPACE}


@lru_cache(maxsize=1)
def get_s3_client() -> S3Client:
    return boto3.client("s3", config=Config(user_agent_extra=USER_AGENT_STRING))


@lru_cache(maxsize=1)
def get_dynamodb_client() -> DynamoDBServiceResource:
    return boto3.resource(
        "dynamodb", config=Config(user_agent_extra=os.environ["USER_AGENT_STRING"])
    )


def get_sqs_client() -> SQSClient:
    return boto3.client(
        "sqs", config=Config(user_agent_extra=os.environ["USER_AGENT_STRING"])
    )


@lru_cache(maxsize=1)
def get_alerts_table() -> Table:
    return get_dynamodb_client().Table(ALERTS_TABLE_NAME)


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics(default_dimensions=default_dimensions)
def handler(event: Dict[str, Any], _: LambdaContext) -> Dict[str, Any]:
    if "Records" not in event:
        return {"processed": 0}

    success_receipt_handles: List[str] = []
    processed_alerts: List[Dict[str, Any]] = []
    failed_alerts: List[FailedAlert] = []

    for record in event["Records"]:
        try:
            message_body = record["body"]
            alert_ref = json.loads(message_body)
            receipt_handle = record["receiptHandle"]

            alert = get_alert_from_dynamodb(
                alert_ref["alertId"], alert_ref["timestamp"]
            )
            if not alert:
                logger.error(
                    f"processing failed for {alert_ref}: {FailureReason.DB_NOT_FOUND}"
                )
                failed_alerts.append(
                    FailedAlert(
                        alert_ref=alert_ref, failure_reason=FailureReason.DB_NOT_FOUND
                    )
                )
                continue

            try:
                transformed = transform_alert(alert)
            except Exception as transform_error:
                logger.error(
                    f"Failed to transform alert {alert['alertId']}: {str(transform_error)}"
                )
                failed_alerts.append(
                    FailedAlert(
                        alert_ref=alert_ref, failure_reason=FailureReason.UNKNOWN_ERROR
                    )
                )
                continue

            try:
                log_alert(transformed)
            except Exception as logging_error:
                logger.error(
                    f"Failed to log transformed alert {alert['alertId']}: {str(logging_error)}"
                )

            processed_alerts.append(transformed)

            update_alert_status(
                alert["alertId"],
                alert["timestamp"],
                "PROCESSED",
                {"processedAt": datetime.now(timezone.utc).isoformat()},
            )

            success_receipt_handles.append(receipt_handle)

        except Exception as e:
            logger.exception("Error processing alert")

            if "alertId" in alert_ref and "timestamp" in alert_ref:
                failed_alerts.append(
                    FailedAlert(
                        alert_ref=alert_ref, failure_reason=FailureReason.PUBLISH_ERROR
                    )
                )
                try:
                    alert = get_alert_from_dynamodb(
                        alert_ref["alertId"], alert_ref["timestamp"]
                    )
                    if alert:
                        retry_count = (
                            alert.get("processingData", {}).get("retryCount", 0) + 1
                        )
                        update_alert_status(
                            alert_ref["alertId"],
                            alert_ref["timestamp"],
                            "PENDING",
                            {
                                "error": str(e),
                                "retryCount": retry_count,
                                "lastRetryAttempt": datetime.now(
                                    timezone.utc
                                ).isoformat(),
                            },
                        )
                except Exception as inner_e:
                    logger.error(f"Failed to update retry status: {str(inner_e)}")
            else:
                failed_alerts.append(
                    FailedAlert(
                        alert_ref=alert_ref,
                        failure_reason=FailureReason.INVALID_ALERT_REF,
                    )
                )

    if success_receipt_handles:
        # TODO: replace w/ API call
        write_alerts_to_s3(processed_alerts)
        delete_successful_messages(success_receipt_handles)

    if failed_alerts:
        logger.error(f"The following alerts failed to process:\n {failed_alerts}")
        raise Exception(
            f"Failed to process {len(failed_alerts)} alerts. They will be retried."
        )

    metrics.add_metric(
        name="AlertsProcessed",
        unit=MetricUnit.Count,
        value=len(success_receipt_handles),
    )
    return {"processed": len(success_receipt_handles)}


def get_alert_from_dynamodb(alert_id: str, timestamp: str) -> Optional[Dict[str, Any]]:
    try:
        response = get_alerts_table().get_item(
            Key={"alertId": alert_id, "timestamp": timestamp}
        )
        return cast(Optional[Dict[str, Any]], response.get("Item"))
    except ClientError as e:
        logger.error(f"Error retrieving alert from DynamoDB: {str(e)}")
        return None


def update_alert_status(
    alert_id: str,
    timestamp: str,
    status: str,
    additional_data: Optional[Dict[str, Any]] = None,
) -> None:
    if additional_data is None:
        additional_data = {}

    try:
        get_alerts_table().update_item(
            Key={"alertId": alert_id, "timestamp": timestamp},
            UpdateExpression="SET #status = :status, processingData = :data",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={":status": status, ":data": additional_data},
        )
    except ClientError as e:
        logger.error(f"Error updating alert status: {str(e)}")


def delete_successful_messages(receipt_handles: List[str]) -> None:
    for i in range(0, len(receipt_handles), 10):
        batch = receipt_handles[i : i + 10]
        entries: List[DeleteMessageBatchRequestEntryTypeDef] = [
            {
                "Id": str(idx),
                "ReceiptHandle": handle,
            }
            for idx, handle in enumerate(batch)
        ]

        try:
            get_sqs_client().delete_message_batch(
                QueueUrl=ALERTS_QUEUE_URL,
                Entries=entries,
            )
        except Exception as e:
            logger.error(f"Error deleting messages: {str(e)}")


def log_alert(alert: Dict[str, Any]) -> None:
    logger.info(
        f"Alert event payload:\n{json.dumps(alert, indent=2, default=_json_serializer)}"
    )


def write_alerts_to_s3(alerts: List[Dict[str, Any]]) -> None:

    now = datetime.utcnow()
    key = f"{ALERTS_BUCKET_PREFIX}/{now:%Y/%m/%d}/alerts-{uuid.uuid4()}.json"

    try:
        get_s3_client().put_object(
            Bucket=ALERTS_BUCKET,
            Key=key,
            Body=json.dumps(alerts, indent=2, default=_json_serializer),
            ContentType="application/json",
        )
        logger.info(f"Wrote {len(alerts)} alerts to s3://{ALERTS_BUCKET}/{key}")
    except Exception as e:
        logger.exception(f"Failed to write alerts to S3: {str(e)}")


def transform_alert(alert: Dict[str, Any]) -> Dict[str, Any]:
    msg = alert.get("message", {})

    payload = {
        "eventId": alert["alertId"],
        "vehicleId": alert["vehicle_id"],
        "tireId": alert["tire_id"],
        "firstTimestamp": alert["first_timestamp"],
        "lastTimestamp": alert["last_timestamp"],
    }

    if "triggerRule" in msg:
        payload["triggerRule"] = msg["triggerRule"]

    return payload


# DynamoDB client type to json safe serializer
def _json_serializer(obj: Any) -> Union[float, List[Any], str]:
    result: Union[float, List[Any], str]
    if isinstance(obj, decimal.Decimal):
        result = float(obj)
    elif isinstance(obj, (set, frozenset)):
        result = list(obj)
    elif isinstance(obj, bytes):
        result = base64.b64encode(obj).decode("utf-8")
    else:
        raise TypeError(f"Type {type(obj)} not serializable")
    return result
