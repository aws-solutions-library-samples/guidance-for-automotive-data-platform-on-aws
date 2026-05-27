# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import logging
from typing import Any, Dict, List, Optional, cast

# AWS Libraries
from aws_cdk import BundlingOptions, DockerImage, aws_lambda

logger = logging.getLogger(__name__)


def create_layer_bundling(
    asset_path: str,
    exclude_patterns: Optional[List[str]] = None,
    runtime: aws_lambda.Runtime = aws_lambda.Runtime.PYTHON_3_13,
    bundling_options: Optional[Dict[str, Any]] = None,
) -> aws_lambda.Code:
    """
    Create a Lambda layer asset with Poetry-based bundling.

    This function creates a Lambda layer with proper Python package structure
    where dependencies are installed in the 'python' directory as required by Lambda layers.

    Args:
        asset_path: Path to the Lambda layer code directory containing pyproject.toml
        exclude_patterns: List of patterns to exclude from bundling
        runtime: Lambda runtime to use for bundling
        bundling_options: Additional bundling options to override defaults

    Returns:
        Lambda code asset for the layer
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
    # For Lambda layers, Python packages must be in the 'python' directory
    bundling_commands = [
        "bash",
        "-c",
        # Create the python directory structure required for Lambda layers
        "mkdir -p /asset-output/python && "
        "pip install poetry && "
        "cp -r /asset-input/* /asset-output/ && "
        "cd /asset-output && "
        # Build the package with poetry
        "poetry build && "
        # Install the dependencies into the python directory
        "pip install --target /asset-output/python dist/*.whl && "
        # Clean up build artifacts not needed in the layer
        "rm -rf dist .venv* __pycache__* *.pyc .pytest_cache* && "
        # Keep only the python directory at the root level
        "find . -maxdepth 1 -not -name python -not -name . -exec rm -rf {} \\;",
    ]

    # Default bundling options
    default_options = {
        "image": runtime.bundling_image,
        "command": bundling_commands,
        "user": "root",
        "network": "host",
        "security_opt": "no-new-privileges:true",
    }

    # Override defaults with any provided options
    if bundling_options:
        default_options.update(bundling_options)

    image = cast(DockerImage, default_options["image"])
    command = cast(List[str], default_options["command"])
    user = cast(Optional[str], default_options.get("user"))
    network = cast(Optional[str], default_options.get("network"))
    security_opt = cast(Optional[str], default_options.get("security_opt"))

    # Use CDK's built-in bundling mechanism
    return aws_lambda.Code.from_asset(
        asset_path,
        exclude=exclude_patterns,
        bundling=BundlingOptions(
            image=image,
            command=command,
            user=user,
            network=network,
            security_opt=security_opt,
        ),
    )
