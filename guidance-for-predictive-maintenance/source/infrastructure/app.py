#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# AWS Libraries
import aws_cdk as cdk

from lib.stacks.resource_monitoring_stack import ResourceMonitoringStack
from lib.stacks.tire_predictive_maintenance_stack import TirePredictiveMaintenanceStack

app = cdk.App()

tire_predictive_maintenance_stack = TirePredictiveMaintenanceStack(
    app, "tire-predictive-maintenance-stack"
)
ResourceMonitoringStack(tire_predictive_maintenance_stack, "resource-monitoring-stack")

app.synth()
