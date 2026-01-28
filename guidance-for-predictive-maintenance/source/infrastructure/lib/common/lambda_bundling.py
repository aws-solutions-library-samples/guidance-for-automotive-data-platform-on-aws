# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import logging
from typing import List, Optional

# AWS Libraries
from aws_cdk import BundlingOptions, aws_lambda

logger = logging.getLogger(__name__)


def create_poetry_bundling(
    asset_path: str,
    exclude_patterns: Optional[List[str]] = None,
    runtime: Optional[str] = None,
) -> aws_lambda.Code:
    """
    Create a Lambda code asset with Poetry-based bundling.

    Args:
        asset_path: Path to the Lambda code directory
        exclude_patterns: List of patterns to exclude from bundling

    Returns:
        Lambda code asset
    """
    exclude_patterns = exclude_patterns or [
        ".venv*",
        "dist",
        "__pycache__*",
        "*.pyc",
        ".pytest_cache*",
        "requirements.txt",
    ]

    # Define the bundling commands for Docker
    bundling_commands = [
        "bash",
        "-c",
        "pip install poetry && "
        "cp -r /asset-input/* /asset-output/ && "
        "cd /asset-output && "
        "poetry build && "
        "poetry install --only main && "
        "poetry run pip install -t /asset-output dist/*.whl",
    ]

    if runtime is None:
        bundling_image = aws_lambda.Runtime.PYTHON_3_13.bundling_image
    else:
        bundling_image = aws_lambda.Runtime(
            runtime, aws_lambda.RuntimeFamily.PYTHON
        ).bundling_image

    return aws_lambda.Code.from_asset(
        asset_path,
        exclude=exclude_patterns,
        bundling=BundlingOptions(
            image=bundling_image,
            command=bundling_commands,
            user="root",
            network="host",
            security_opt="no-new-privileges:true",
        ),
    )
