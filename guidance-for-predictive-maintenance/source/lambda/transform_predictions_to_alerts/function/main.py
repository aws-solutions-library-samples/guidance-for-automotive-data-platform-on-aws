# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import csv
import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from io import StringIO
from typing import TYPE_CHECKING, Any, Dict, List

# AWS Libraries
import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.config import Config

if TYPE_CHECKING:
    # Third Party Libraries
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient
    from mypy_boto3_sqs.type_defs import SendMessageBatchRequestEntryTypeDef
    from mypy_boto3_ssm import SSMClient
else:
    S3Client = object
    DynamoDBServiceResource = object
    SQSClient = object
    SSMClient = object
    Table = object

# Environment variables
ALERTS_TABLE_NAME = os.environ["ALERTS_TABLE"]
ALERTS_QUEUE_URL = os.environ["ALERTS_QUEUE_URL"]
ANOMALY_THRESHOLD_PARAMETER = os.environ.get("ANOMALY_THRESHOLD_PARAMETER")
USER_AGENT_STRING = os.environ.get("USER_AGENT_STRING", None)
POWERTOOLS_METRICS_NAMESPACE = os.environ.get("POWERTOOLS_METRICS_NAMESPACE", "Default")

tracer = Tracer()
logger = Logger()
metrics = Metrics()
default_dimensions = {"Metrics Namespace": POWERTOOLS_METRICS_NAMESPACE}


@lru_cache(maxsize=1)
def get_s3_client() -> S3Client:
    return boto3.client("s3", config=Config(user_agent_extra=USER_AGENT_STRING))


@lru_cache(maxsize=1)
def get_dynamodb_client() -> DynamoDBServiceResource:
    return boto3.resource("dynamodb", config=Config(user_agent_extra=USER_AGENT_STRING))


@lru_cache(maxsize=1)
def get_sqs_client() -> SQSClient:
    return boto3.client("sqs", config=Config(user_agent_extra=USER_AGENT_STRING))


@lru_cache(maxsize=1)
def get_ssm_client() -> SSMClient:
    return boto3.client("ssm", config=Config(user_agent_extra=USER_AGENT_STRING))


@lru_cache(maxsize=1)
def get_alerts_table() -> Table:
    return get_dynamodb_client().Table(ALERTS_TABLE_NAME)


def extract_s3_info_from_event(s3_record: Dict[str, Any]) -> tuple[str, str]:
    """Extract bucket name and object key from S3 event record"""
    bucket_name = s3_record["s3"]["bucket"]["name"]
    object_key = s3_record["s3"]["object"]["key"]
    return bucket_name, object_key


def read_csv_from_s3(
    s3_client: S3Client, bucket_name: str, csv_file_key: str
) -> List[Dict[str, Any]]:
    """Read CSV file from S3 and return list of dictionaries with headers"""
    csv_obj = s3_client.get_object(Bucket=bucket_name, Key=csv_file_key)
    csv_content = csv_obj["Body"].read().decode("utf-8")

    headers = [
        "vehicle_id",
        "tire_id",
        "first_timestamp",
        "last_timestamp",
        "anomaly_score",
    ]

    reader = csv.reader(StringIO(csv_content))
    data = []

    for row in reader:
        if len(row) == len(headers):
            record: Dict[str, Any] = dict(zip(headers, row))
            # Convert numeric fields
            try:
                record["anomaly_score"] = (
                    float(record["anomaly_score"]) if record["anomaly_score"] else 0.0
                )
            except (ValueError, TypeError):
                record["anomaly_score"] = 0.0
            data.append(record)

    return data


def calculate_percentile(values: List[float], percentile: float) -> float:
    """Calculate percentile of a list of values"""
    sorted_values = sorted([v for v in values if v is not None])
    if not sorted_values:
        return 0.0
    index = int(len(sorted_values) * percentile / 100)
    return sorted_values[min(index, len(sorted_values) - 1)]


def filter_anomalies(data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter data to keep only anomalies based on 99th percentile and update SSM parameter"""
    anomaly_scores = [record["anomaly_score"] for record in data]
    anomaly_threshold = calculate_percentile(anomaly_scores, 99.0)

    logger.info(f"Anomaly threshold (99th percentile): {anomaly_threshold}")

    # Update SSM parameter with new threshold
    if ANOMALY_THRESHOLD_PARAMETER:
        try:
            threshold_data = {
                "threshold": anomaly_threshold,
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            get_ssm_client().put_parameter(
                Name=ANOMALY_THRESHOLD_PARAMETER,
                Value=json.dumps(threshold_data),
                Overwrite=True
            )
            logger.info(f"Updated anomaly threshold in SSM: {anomaly_threshold}")
        except Exception as e:
            logger.error(f"Failed to update SSM parameter: {str(e)}")
            # Don't fail the entire process if SSM update fails

    filtered = [
        record for record in data if record["anomaly_score"] >= anomaly_threshold
    ]
    logger.info(f"Filtered {len(filtered)} anomalies from {len(data)} total records")

    return filtered


@tracer.capture_method
def process_tire_alerts(tire_alerts: List[Dict[str, Any]]) -> None:
    """
    Transform tire alerts into simplified format and persist to DynamoDB and SQS.

    Args:
        tire_alerts: List of filtered anomaly records from ML predictions

    Returns:
        None

    Raises:
        Exception: If DynamoDB batch write fails
    """
    logger.info(f"Processing {len(tire_alerts)} tire alerts")

    transformed_alerts = []

    for alert in tire_alerts:
        logger.info(
            f"Processing alert: Vehicle {alert['vehicle_id']} - Tire: {alert['tire_id']} - Score: {alert['anomaly_score']}"
        )

        # Create event ID as composite key
        alert_id = f"{alert['vehicle_id']}-{alert['tire_id']}-{alert['last_timestamp']}"

        # Create simplified DynamoDB item
        ddb_item = {
            "alertId": alert_id,
            "timestamp": alert["last_timestamp"],
            "vehicleId": alert["vehicle_id"],
            "tireId": alert["tire_id"],
            "firstTimestamp": alert["first_timestamp"],
            "lastTimestamp": alert["last_timestamp"],
        }

        transformed_alerts.append(ddb_item)

    if transformed_alerts:
        batch_write_to_dynamodb(transformed_alerts)
        send_alerts_to_sqs(transformed_alerts)


@tracer.capture_method
def batch_write_to_dynamodb(items: List[Dict[str, Any]]) -> None:
    """
    Batch write alert items to DynamoDB

    Args:
        items: List of DynamoDB items to write

    Returns:
        None

    Raises:
        Exception: If batch write operation fails
    """
    table = get_alerts_table()

    try:
        with table.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=item)

        logger.info(
            f"Successfully wrote {len(items)} items to DynamoDB table {ALERTS_TABLE_NAME}"
        )
        metrics.add_metric(
            name="AlertsWrittenToDynamoDB", unit="Count", value=len(items)
        )

    except Exception as e:
        logger.error(f"Error writing batch to DynamoDB: {str(e)}")
        raise


@tracer.capture_method
def send_alerts_to_sqs(items: List[Dict[str, Any]]) -> None:
    """
    Send alert notifications to SQS queue for downstream processing.

    Args:
        items: List of DynamoDB items containing alertId, vehicleId, tireId and timestamps

    Returns:
        None
    """
    sqs_client = get_sqs_client()
    total_sent = 0
    total_failed = 0

    try:
        sqs_entries: List[SendMessageBatchRequestEntryTypeDef] = []
        for item in items:
            message_body = {
                "alertId": item["alertId"],
                "timestamp": item["lastTimestamp"],
                "vehicleId": item["vehicleId"],
                "tireId": item["tireId"],
                "firstTimestamp": item["firstTimestamp"],
                "lastTimestamp": item["lastTimestamp"],
            }

            sqs_entries.append(
                {"Id": item["alertId"], "MessageBody": json.dumps(message_body)}
            )

        # Send messages in batches (SQS supports up to 10 messages per batch)
        batch_size = 10
        for i in range(0, len(sqs_entries), batch_size):
            batch = sqs_entries[i : i + batch_size]

            try:
                response = sqs_client.send_message_batch(
                    QueueUrl=ALERTS_QUEUE_URL, Entries=batch
                )

                if "Failed" in response and response["Failed"]:
                    failed_count = len(response["Failed"])
                    total_failed += failed_count
                    logger.error(
                        f"Failed to send {failed_count} messages to SQS: {response['Failed']}"
                    )

                successful_count = len(response.get("Successful", []))
                total_sent += successful_count
                logger.info(
                    f"Successfully sent {successful_count} messages to SQS queue"
                )

            except Exception as batch_error:
                logger.error(f"Error sending batch to SQS: {str(batch_error)}")
                total_failed += len(batch)

        metrics.add_metric(
            name="TransformedAlertsSentToSQS", unit="Count", value=total_sent
        )
        if total_failed > 0:
            metrics.add_metric(
                name="TransformedAlertsFailedToSendToSQS",
                unit="Count",
                value=total_failed,
            )

    except Exception as e:
        logger.error(f"Error in send_alerts_to_sqs: {str(e)}")


@tracer.capture_method
def process_s3_record(s3_record: Dict[str, Any]) -> bool:
    """
    Process a single S3 event record.
    
    Args:
        s3_record: S3 event record containing bucket and object information
        
    Returns:
        True if processing was successful, False otherwise
    """
    try:
        # Extract S3 information
        bucket_name, csv_file_key = extract_s3_info_from_event(s3_record)
        logger.info(f"Processing file: s3://{bucket_name}/{csv_file_key}")
        
        # Only process .csv.out files
        if not csv_file_key.endswith(".csv.out"):
            logger.info(f"Skipping non-CSV file: {csv_file_key}")
            return False

        # Read CSV file
        data = read_csv_from_s3(get_s3_client(), bucket_name, csv_file_key)
        logger.info(f"Read {len(data)} records from CSV")

        # Filter anomalies
        anomaly_data = filter_anomalies(data)

        metrics.add_metric(name="MLPredictionsProcessed", unit="Count", value=len(data))
        metrics.add_metric(
            name="AnomaliesDetected", unit="Count", value=len(anomaly_data)
        )

        # Process and send alerts
        if anomaly_data:
            process_tire_alerts(anomaly_data)
            logger.info(f"Successfully processed {len(anomaly_data)} anomaly alerts")
        else:
            logger.info("No anomalies detected above threshold")
            
        return True

    except Exception as e:
        logger.error(f"Error processing S3 record: {str(e)}")
        metrics.add_metric(name="ProcessingErrors", unit="Count", value=1)
        return False


@tracer.capture_lambda_handler
@logger.inject_lambda_context
@metrics.log_metrics(default_dimensions=default_dimensions)
def handler(event: Dict[str, Any], context: LambdaContext) -> None:
    """
    Lambda handler that processes S3 event notifications from ML batch transform outputs.

    This function:
    1. Processes S3 ObjectCreated events for CSV files
    2. Parses tire prediction data from CSV files
    3. Filters anomalies based on 99th percentile threshold
    4. Updates anomaly threshold in SSM Parameter Store
    5. Transforms alerts into standardized format
    6. Batch writes alert records to DynamoDB (ALERTS_TABLE)
    7. Sends alert notifications to SQS (ALERTS_QUEUE_URL)

    Args:
        event: S3 event notification containing Records array with S3 object details
        context: AWS Lambda context object

    Returns:
        None

    Raises:
        Exception: If critical processing fails
    """
    logger.info(f"Event received: {json.dumps(event, indent=2)}")

    if "Records" not in event:
        logger.info("No records found in the event")
        return

    csv_files_processed = 0
    for s3_record in event["Records"]:
        success = process_s3_record(s3_record)
        if success:
            csv_files_processed += 1

    metrics.add_metric(name="AlertCSVsProcessed", unit="Count", value=csv_files_processed)
    logger.info(f"Processing complete. Processed {csv_files_processed} CSV files")
    return
