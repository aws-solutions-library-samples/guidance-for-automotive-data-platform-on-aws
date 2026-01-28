# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
from typing import Any

# Third Party Libraries
from cdk_monitoring_constructs import MonitoringFacade

# AWS Libraries
from aws_cdk import NestedStack
from constructs import Construct

# MMT Predictive Maintenance
from ..constructs.monitoring_constructs.custom_metrics_monitoring import (
    CustomMetricsMonitoring,
)
from ..constructs.monitoring_constructs.lambda_monitoring import LambdaMonitoring


class ResourceMonitoringStack(NestedStack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        facade = MonitoringFacade(scope=scope, id=f"{construct_id}-monitoring-facade")

        CustomMetricsMonitoring(
            self, f"{construct_id}-custom-metrics-monitoring", monitoring_facade=facade
        )

        LambdaMonitoring(
            self, f"{construct_id}-lambda-monitoring", monitoring_facade=facade
        )
