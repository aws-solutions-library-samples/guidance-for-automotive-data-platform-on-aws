# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
from dataclasses import dataclass
from typing import Dict, List, Optional

# Third Party Libraries
from cdk_monitoring_constructs import (
    ErrorRateThreshold,
    LatencyTimeoutPercentageThreshold,
    MinUsageCountThreshold,
)

# AWS Libraries
from aws_cdk import Duration

# MMT Predictive Maintenance
from ..constructs.alerts_system import AlertsSystemConstruct


@dataclass(frozen=True)
class LambdaAlarmThresholds:
    """
    Configuration class for Lambda function monitoring thresholds.

    This class holds the thresholds for different types of alarms
    that can be applied to Lambda functions. Each threshold type is a dictionary
    mapping severity levels (e.g., "Warning", "Critical", "Sev2", "Sev3") to specific threshold
    configurations.
    """

    # Dictionary mapping severity levels to alarm thresholds
    fault_rate_threshold: Optional[Dict[str, ErrorRateThreshold]] = None
    min_invocations_count_threshold: Optional[Dict[str, MinUsageCountThreshold]] = None
    latency_p99_threshold: Optional[Dict[str, LatencyTimeoutPercentageThreshold]] = None


@dataclass(frozen=True)
class LambdaAlarmConfig:
    """
    Configuration class that associates a Lambda function identifier with its monitoring thresholds.
    """

    lambda_identifier: str
    lambda_alarm_thresholds: LambdaAlarmThresholds


class LambdaAlarmConfigs:
    # Static configuration map of Lambda alarm thresholds
    # Key: Lambda function identifier (name)
    # Value: LambdaThresholdConfig with alarm settings
    _ALARM_CONFIGS: List[LambdaAlarmConfig] = [
        # alerts-processor Lambda
        LambdaAlarmConfig(
            lambda_identifier=AlertsSystemConstruct.alerts_processor_lambda_name,
            lambda_alarm_thresholds=LambdaAlarmThresholds(
                fault_rate_threshold={
                    "Warning": ErrorRateThreshold(
                        max_error_rate=5,
                        evaluation_periods=3,
                        period=Duration.minutes(1),
                        datapoints_to_alarm=3,
                    ),
                },
                min_invocations_count_threshold={
                    "Warning": MinUsageCountThreshold(
                        min_count=1,
                        evaluation_periods=1,
                        period=Duration.days(1),
                        datapoints_to_alarm=1,
                    ),
                },
                latency_p99_threshold={
                    "Warning": LatencyTimeoutPercentageThreshold(
                        max_latency_percentage_of_timeout=99,
                        evaluation_periods=3,
                        period=Duration.minutes(1),
                        datapoints_to_alarm=3,
                    ),
                },
            ),
        ),
        # alerts-transformer Lambda
        LambdaAlarmConfig(
            lambda_identifier=AlertsSystemConstruct.alerts_transformer_lambda_name,
            lambda_alarm_thresholds=LambdaAlarmThresholds(
                fault_rate_threshold={
                    "Warning": ErrorRateThreshold(
                        max_error_rate=5,
                        evaluation_periods=3,
                        period=Duration.minutes(5),
                        datapoints_to_alarm=3,
                    ),
                },
                min_invocations_count_threshold={
                    "Warning": MinUsageCountThreshold(
                        min_count=1,
                        evaluation_periods=1,
                        period=Duration.days(1),
                        datapoints_to_alarm=1,
                    ),
                },
                latency_p99_threshold={
                    "Warning": LatencyTimeoutPercentageThreshold(
                        max_latency_percentage_of_timeout=99,
                        evaluation_periods=3,
                        period=Duration.minutes(5),
                        datapoints_to_alarm=3,
                    ),
                },
            ),
        ),
    ]

    @classmethod
    def get_lambda_alarm_thresholds(
        cls, lambda_identifier: str
    ) -> LambdaAlarmThresholds:
        """
        Retrieves the alarm thresholds for a specific Lambda function.

        This method searches through the ALARM_CONFIGS list for a LambdaAlarmConfig
        with a matching lambda_identifier and returns its thresholds.

        Args:
            lambda_identifier: The identifier (e.g. name) of the Lambda function

        Returns:
            LambdaAlarmThresholds: The thresholds for the Lambda function.
                If no configuration exists, returns an empty LambdaThresholdConfig.
        """
        for config in cls._ALARM_CONFIGS:
            if config.lambda_identifier == lambda_identifier:
                return config.lambda_alarm_thresholds

        # If no match is found, return an empty LambdaThresholdConfig
        return LambdaAlarmThresholds()
