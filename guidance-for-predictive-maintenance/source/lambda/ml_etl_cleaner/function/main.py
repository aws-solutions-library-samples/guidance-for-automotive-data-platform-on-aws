# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
ETL Cleaner Lambda Function

This Lambda function cleans up temporary folders and zero-byte objects created by Glue jobs
in the training bucket. It reads the TRAINING_BUCKET_NAME environment variable and deletes:
1. All objects with 0 byte size
2. All temporary objects (regardless of size) that match common Glue job patterns
"""

# Standard Library
import json
import os
from typing import TYPE_CHECKING, Any, Dict, List

# AWS Libraries
import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

if TYPE_CHECKING:
    # Third Party Libraries
    from mypy_boto3_s3 import S3Client

else:
    S3Client = object

# Initialize AWS Lambda Powertools
tracer = Tracer()
logger = Logger()

# Common temporary folder patterns created by Glue jobs
TEMP_FOLDER_PATTERNS = [
    "_temporary/",
    ".temp/",
    "_temp/",
    "temp/",
    "_spark_metadata/",
    "_SUCCESS",
    ".sparkStaging",
    "_committed_",
    "_started_",
]


@tracer.capture_method
def get_s3_client() -> S3Client:
    """Get S3 client with custom user agent."""
    return boto3.client("s3")


@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=True)
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Lambda handler that cleans up temporary folders and zero-byte objects created by Glue jobs.

    This function:
    1. Lists all objects in the training bucket
    2. Identifies objects to delete based on:
       - Zero byte size (empty files)
       - Temporary folder patterns (Glue job artifacts)
    3. Deletes identified objects
    4. Logs cleanup statistics

    Args:
        event: Lambda event (can be empty or contain specific cleanup parameters)
        context: AWS Lambda context object

    Returns:
        Dict containing cleanup statistics and status
    """
    logger.info(f"Event received: {json.dumps(event, indent=2)}. Context: {context}")

    s3_client = get_s3_client()

    try:
        # Get cleanup parameters from event or use defaults
        dry_run = event.get("dry_run", False)
        prefix_filter = event.get("prefix_filter", "")

        cleanup_stats = cleanup_objects(
            s3_client,
            os.environ["TRAINING_BUCKET_NAME"],
            dry_run=dry_run,
            prefix_filter=prefix_filter,
        )

        logger.info(f"Cleanup complete: {cleanup_stats}")

        return {"statusCode": 200, "body": json.dumps(cleanup_stats)}

    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
        return {"statusCode": 500, "body": f"Error during cleanup: {str(e)}"}


@tracer.capture_method
def cleanup_objects(
    s3_client: S3Client,
    bucket_name: str,
    dry_run: bool = False,
    prefix_filter: str = "",
) -> Dict[str, int]:
    """
    Clean up zero-byte objects and temporary objects in the specified S3 bucket.

    Args:
        s3_client: Boto3 S3 client
        bucket_name: Name of the S3 bucket to clean
        dry_run: If True, only log what would bev deleted without actually deleting
        prefix_filter: Optional prefix to filter objects (e.g., "glue-jobs/")

    Returns:
        Dict with cleanup statistics
    """
    logger.info(f"Starting cleanup of bucket: {bucket_name}")
    if dry_run:
        logger.info("DRY RUN MODE - No objects will be deleted")

    zero_byte_objects = []
    temp_objects = []
    zero_byte_objects_deleted = 0
    temp_objects_deleted = 0

    try:
        # List all objects in the bucket
        paginator = s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=bucket_name, Prefix=prefix_filter)

        for page in page_iterator:
            if "Contents" not in page:
                continue

            for obj in page["Contents"]:
                key = obj["Key"]
                size = obj["Size"]

                # Check for zero-byte objects
                if size == 0:
                    zero_byte_objects.append(key)
                    logger.debug(f"Found zero-byte object: {key}")

                # Check if the object matches temporary folder patterns
                elif is_temporary_object(key):
                    temp_objects.append(key)
                    logger.debug(f"Found temporary object: {key} (size: {size} bytes)")

        logger.info(f"Found {len(zero_byte_objects)} zero-byte objects to delete")
        logger.info(f"Found {len(temp_objects)} temporary objects to delete")

        # Delete zero-byte objects in batches
        if zero_byte_objects and not dry_run:
            zero_byte_objects_deleted = delete_objects_in_batches(
                s3_client, bucket_name, zero_byte_objects
            )
        elif zero_byte_objects and dry_run:
            zero_byte_objects_deleted = len(zero_byte_objects)
            logger.info(
                f"DRY RUN: Would delete {zero_byte_objects_deleted} zero-byte objects"
            )

        # Delete temporary objects in batches
        if temp_objects and not dry_run:
            temp_objects_deleted = delete_objects_in_batches(
                s3_client, bucket_name, temp_objects
            )
        elif temp_objects and dry_run:
            temp_objects_deleted = len(temp_objects)
            logger.info(
                f"DRY RUN: Would delete {temp_objects_deleted} temporary objects"
            )

    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
        raise

    total_objects_deleted = zero_byte_objects_deleted + temp_objects_deleted

    return {
        "zero_byte_objects_deleted": zero_byte_objects_deleted,
        "temp_objects_deleted": temp_objects_deleted,
        "total_objects_deleted": total_objects_deleted,
        "dry_run": dry_run,
    }


def is_temporary_object(key: str) -> bool:
    """
    Check if an S3 object key represents a temporary file or folder created by Glue jobs.

    Args:
        key: S3 object key

    Returns:
        True if the object is temporary, False otherwise
    """
    # Check for common temporary patterns
    for pattern in TEMP_FOLDER_PATTERNS:
        if pattern in key:
            return True

    # Check for Spark/Glue specific patterns
    if (
        key.startswith("_")  # pylint: disable=too-many-boolean-expressions
        or key.endswith("_$folder$")
        or "/_temporary/" in key
        or "/.sparkStaging/" in key
        or key.endswith(".crc")
        or key.endswith(".tmp")  # Hadoop checksum files
        or "/part-" in key  # Temporary files
        and key.endswith(".tmp")
    ):  # Spark part files that are temporary
        return True

    return False


@tracer.capture_method
def delete_objects_in_batches(
    s3_client: S3Client, bucket_name: str, object_keys: List[str]
) -> int:
    """
    Delete S3 objects in batches of 1000 (S3 delete limit).

    Args:
        s3_client: Boto3 S3 client
        bucket_name: Name of the S3 bucket
        object_keys: List of object keys to delete

    Returns:
        Number of objects successfully deleted
    """
    deleted_count = 0
    batch_size = 1000

    for i in range(0, len(object_keys), batch_size):
        batch = object_keys[i : i + batch_size]

        # Prepare delete request
        delete_request = {"Objects": [{"Key": key} for key in batch], "Quiet": True}

        try:
            response = s3_client.delete_objects(
                Bucket=bucket_name, Delete=delete_request  # type: ignore[arg-type]
            )

            # Count successful deletions
            if "Deleted" in response:
                deleted_count += len(response["Deleted"])

            # Log any errors
            if "Errors" in response:
                for error in response["Errors"]:
                    logger.error(f"Failed to delete {error['Key']}: {error['Message']}")

            logger.info(f"Deleted batch of {len(batch)} objects")

        except Exception as e:
            logger.error(f"Error deleting batch: {str(e)}")
            # Continue with next batch even if one fails
            continue

    return deleted_count


def count_unique_folders(object_keys: List[str]) -> int:
    """
    Count the number of unique folder paths from a list of object keys.

    Args:
        object_keys: List of S3 object keys

    Returns:
        Number of unique folder paths
    """
    folders = set()

    for key in object_keys:
        # Extract folder path (everything before the last '/')
        if "/" in key:
            folder_path = "/".join(key.split("/")[:-1])
            folders.add(folder_path)

    return len(folders)
