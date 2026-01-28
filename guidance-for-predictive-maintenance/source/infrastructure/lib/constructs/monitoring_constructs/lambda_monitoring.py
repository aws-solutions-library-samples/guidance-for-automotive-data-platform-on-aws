# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Third Party Libraries
from cdk_monitoring_constructs import MonitoringFacade

# AWS Libraries
from constructs import Construct

# MMT Predictive Maintenance
from ...config.lambda_alarm_configs import LambdaAlarmConfigs
from ...config.monitoring_lambda_registry import MonitoringLambdaRegistry


class LambdaMonitoring(Construct):
    """
    Construct for monitoring Lambda functions.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        monitoring_facade: MonitoringFacade,
    ) -> None:
        """
        Initialize the LambdaMonitoring construct.

        Args:
            scope: The scope in which to define this construct
            construct_id: The ID of this construct
            monitoring_facade: The monitoring facade to use for setting up metrics
        """
        super().__init__(scope, construct_id)

        compute_facade = monitoring_facade.add_large_header("Compute")
        # See https://constructs.dev/packages/cdk-monitoring-constructs/v/9.12.0/api/LambdaFunctionMonitoringOptions?lang=python
        # for Lambda Function monitoring options
        for monitoring_lambda in MonitoringLambdaRegistry.get_lambda_functions():
            lambda_function = monitoring_lambda.lambda_function
            lambda_identifier = monitoring_lambda.lambda_identifier
            compute_facade.monitor_lambda_function(
                lambda_function=lambda_function,
                add_fault_rate_alarm=LambdaAlarmConfigs.get_lambda_alarm_thresholds(
                    lambda_identifier
                ).fault_rate_threshold,
                add_min_invocations_count_alarm=LambdaAlarmConfigs.get_lambda_alarm_thresholds(
                    lambda_identifier
                ).min_invocations_count_threshold,
                add_latency_p99_alarm=LambdaAlarmConfigs.get_lambda_alarm_thresholds(
                    lambda_identifier
                ).latency_p99_threshold,
            )
