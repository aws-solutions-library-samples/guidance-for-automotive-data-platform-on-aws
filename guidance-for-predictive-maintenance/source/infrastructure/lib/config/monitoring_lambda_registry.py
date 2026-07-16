# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
from dataclasses import dataclass
from typing import List

# AWS Libraries
from aws_cdk.aws_lambda import Function


@dataclass(frozen=True)
class MonitoringLambdaFunction:
    """
    Associates a Lambda function with its identifier for monitoring purposes.

    This immutable dataclass represents a Lambda function that should be monitored,
    pairing the CDK Function construct with a unique identifier. The identifier is used
    to look up specific monitoring configurations from the LambdaAlarmConfigs class.

    The frozen=True decorator ensures that instances of this class are immutable,
    preventing accidental modification after creation.

    Attributes:
        lambda_identifier: A unique identifier for the Lambda function. This should
            match the identifier used in LambdaAlarmConfigs if specific alarm
            thresholds are defined for this function. Typically, this is a logical
            name that describes the function's purpose (e.g., "data-processor",
            "event-handler").

        lambda_function: The CDK Lambda Function construct representing the actual
            Lambda function to be monitored. This is the CDK resource that will have
            monitoring applied to it.

    Example:
        # Create a MonitoringLambdaFunction instance
        monitored_lambda = MonitoringLambdaFunction(
            lambda_identifier="data-processor",
            lambda_function=data_processor_lambda
        )
    """

    lambda_identifier: str
    lambda_function: Function


class MonitoringLambdaRegistry:
    """
    Registry for Lambda functions that require monitoring.
    """

    _LAMBDA_FUNCTIONS: List[MonitoringLambdaFunction] = []

    @classmethod
    def get_lambda_functions(cls) -> tuple[MonitoringLambdaFunction, ...]:
        """
        Returns a tuple of all registered Lambda functions.

        Returns a tuple (immutable) rather than a list to prevent modification.

        Returns:
            Tuple[MonitoringLambdaFunction]: A tuple containing all registered Lambda functions.
        """
        return tuple(cls._LAMBDA_FUNCTIONS)

    @classmethod
    def register_lambda(cls, lambda_identifier: str, lambda_function: Function) -> None:
        """
        Registers a Lambda function for monitoring.

        This method adds a CDK Lambda function construct to the registry of functions that should be
        monitored. If a function with the same lambda_identifier already exists in the registry,
        it will raise a ValueError to prevent duplicate registrations.

        The registered Lambda functions can later be retrieved as a complete collection
        for setting up monitoring dashboards, alarms, and other observability resources.

        Args:
            lambda_identifier: A unique identifier for the Lambda function. This should
                match the identifier used in LambdaAlarmConfigs if specific alarm
                thresholds are defined for this function.

            lambda_function: The CDK Lambda Function construct representing the Lambda
                function to be monitored.

        Returns:
            None

        Raises:
            ValueError: If a Lambda function with the same identifier is already registered.

        Example:
            # Register a Lambda function
            MonitoringLambdaRegistry.register_lambda(
                lambda_identifier="data-processor",
                lambda_function=data_processor_lambda
            )
        """
        # Check if a function with this identifier already exists
        for existing in cls._LAMBDA_FUNCTIONS:
            if existing.lambda_identifier == lambda_identifier:
                raise ValueError(
                    f"Lambda function with identifier '{lambda_identifier}' is already registered. "
                    "Each Lambda function must have a unique identifier."
                )

        # If no existing entry was found, append the new one
        cls._LAMBDA_FUNCTIONS.append(
            MonitoringLambdaFunction(
                lambda_identifier=lambda_identifier,
                lambda_function=lambda_function,
            )
        )
