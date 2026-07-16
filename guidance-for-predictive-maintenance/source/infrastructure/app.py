#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# AWS Libraries
import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from lib.stacks.resource_monitoring_stack import ResourceMonitoringStack
from lib.stacks.tire_predictive_maintenance_stack import TirePredictiveMaintenanceStack

app = cdk.App()

tire_predictive_maintenance_stack = TirePredictiveMaintenanceStack(
    app, "tire-predictive-maintenance-stack",
    description="Guidance for Automotive Data Platform on AWS (SO9676) - Predictive Maintenance"
)
ResourceMonitoringStack(tire_predictive_maintenance_stack, "resource-monitoring-stack")

# Wire AwsSolutionsChecks stack-wide — every finding must be either fixed or
# documented-suppressed.  Replaces the prior construct-scoped Aspects in etl_construct.py
# (which only covered the Group-6 governed constructs) with a stack-wide check that
# covers all PM constructs.  All pre-existing findings have been addressed in
# Groups 2/3 (genuine fixes) and Group 4 (documented NagSuppressions).
cdk.Aspects.of(app).add(AwsSolutionsChecks())

app.synth()
