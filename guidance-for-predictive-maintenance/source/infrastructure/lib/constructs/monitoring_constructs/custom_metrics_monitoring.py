# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Third Party Libraries
from cdk_monitoring_constructs import CustomMetricGroup, MonitoringFacade

# AWS Libraries
from aws_cdk import Duration
from aws_cdk.aws_cloudwatch import Metric
from constructs import Construct

# MMT Predictive Maintenance
from ...constructs.alerts_system import AlertsSystemConstruct


class CustomMetricsMonitoring(Construct):
    """
    Construct for monitoring custom metrics.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        monitoring_facade: MonitoringFacade,
    ) -> None:
        """
        Initialize the CustomMetricsMonitoring construct.

        Args:
            scope: The scope in which to define this construct
            construct_id: The ID of this construct
            monitoring_facade: The monitoring facade to use for setting up metrics
        """
        super().__init__(scope, construct_id)

        custom_metrics_facade = monitoring_facade.add_large_header("Custom Metrics")
        custom_metrics_facade.monitor_custom(
            metric_groups=[
                CustomMetricGroup(
                    title="Alerts Metrics",
                    metrics=[
                        Metric(
                            namespace=AlertsSystemConstruct.cloud_watch_custom_namespace,
                            metric_name="AlertsCleaned",
                            dimensions_map={
                                "Metrics Namespace": AlertsSystemConstruct.cloud_watch_custom_namespace
                            },
                            statistic="Sum",
                            period=Duration.hours(24),
                        ),
                        Metric(
                            namespace=AlertsSystemConstruct.cloud_watch_custom_namespace,
                            metric_name="AlertsProcessed",
                            dimensions_map={
                                "Metrics Namespace": AlertsSystemConstruct.cloud_watch_custom_namespace
                            },
                            statistic="Sum",
                            period=Duration.hours(24),
                        ),
                        Metric(
                            namespace=AlertsSystemConstruct.cloud_watch_custom_namespace,
                            metric_name="AlertCSVsProcessed",
                            dimensions_map={
                                "Metrics Namespace": AlertsSystemConstruct.cloud_watch_custom_namespace
                            },
                            statistic="Sum",
                            period=Duration.hours(24),
                        ),
                        Metric(
                            namespace=AlertsSystemConstruct.cloud_watch_custom_namespace,
                            metric_name="TransformedAlertsSentToSQS",
                            dimensions_map={
                                "Metrics Namespace": AlertsSystemConstruct.cloud_watch_custom_namespace
                            },
                            statistic="Sum",
                            period=Duration.hours(24),
                        ),
                        Metric(
                            namespace=AlertsSystemConstruct.cloud_watch_custom_namespace,
                            metric_name="TransformedAlertsFailedToSendToSQS",
                            dimensions_map={
                                "Metrics Namespace": AlertsSystemConstruct.cloud_watch_custom_namespace
                            },
                            statistic="Sum",
                            period=Duration.hours(24),
                        ),
                    ],
                )
            ],
            alarm_friendly_name="Various Custom Metrics",
        )
