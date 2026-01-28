# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

# AWS Libraries
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

tracer = Tracer()
logger = Logger()


def generate_date_patterns(date_str: str, days_back: int) -> List[str]:
    """
    Generate S3 path patterns for the given date and n days back

    Args:
        date_str: Date string in format 'yyyy-mm-dd'
        days_back: Number of days to look back

    Returns:
        List of S3 path patterns for each day
    """
    try:
        # Parse the input date
        current_date = datetime.strptime(date_str, "%Y-%m-%d")

        # Generate patterns for each day
        patterns = []
        for i in range(days_back + 1):  # Include the current day
            # timedelta automatically handles month/year transitions
            target_date = current_date - timedelta(days=i)
            year = target_date.year
            month = target_date.month
            day = target_date.day

            # Format as yyyy/mm/dd
            pattern = f"{year}/{month:02d}/{day:02d}"
            patterns.append(pattern)

        return patterns
    except ValueError as e:
        logger.error(f"Invalid date format: {date_str}. Expected format: yyyy-mm-dd")
        raise ValueError(
            f"Invalid date format: {date_str}. Expected format: yyyy-mm-dd"
        ) from e


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Process date input and return a comma-separated string of date patterns for n days back.

    Args:
        event: The Lambda event object containing:
            - date: Date string in format 'yyyy-mm-dd'
            - days_back: Number of days to look back
        context: The Lambda context

    Returns:
        Dict containing the comma-separated date patterns

    Example:
        Input:
        {
            "date": "2024-05-15",
            "days_back": 2
        }

        Output:
        {
            "statusCode": 200,
            "date_patterns": "2024/05/15,2024/05/14,2024/05/13"
        }
    """
    logger.info(
        "Processing date input for date pattern generation", extra={"event": event}
    )

    # Extract input values from event
    date_str = event.get("date")
    if not date_str:
        date_str = str(date.today())
    days_back = int(event.get("days_back", 10))

    # Validate required inputs
    if not date_str:
        error_msg = "Missing required parameter: 'date' (format: yyyy-mm-dd)"
        logger.error(error_msg)
        return {"statusCode": 400, "error": error_msg}

    try:
        # Generate date patterns for the specified range
        date_patterns = generate_date_patterns(date_str, days_back)

        # Join the patterns with commas
        date_patterns_csv = "&".join(date_patterns)

        # Return the comma-separated date patterns
        return {"statusCode": 200, "date_patterns": date_patterns_csv}
    except ValueError as e:
        return {"statusCode": 400, "error": str(e)}
