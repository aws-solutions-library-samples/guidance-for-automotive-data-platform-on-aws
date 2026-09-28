# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import json

# AWS Libraries
from aws_cdk import aws_ssm
from constructs import Construct


class NormalizationStats(Construct):
    def __init__(
        self,
        scope: Construct,
        id: str,
    ):
        super().__init__(scope, id)

        # Initialize normalization statistics with null values
        initial_stats = {
            "pressure": {"mean": None, "std": None, "count": 0},
            "temperature": {"mean": None, "std": None, "count": 0},
            "delta_pressure": {"mean": None, "std": None, "count": 0},
            "delta_temp": {"mean": None, "std": None, "count": 0},
        }

        # Create SSM Parameter to store normalization statistics
        self.stats_ssm_parameter = aws_ssm.StringParameter(
            self,
            "normalization-stats-parameter",
            parameter_name="/etl/normalization-stats",
            string_value=json.dumps(initial_stats),
            description="Normalization statistics (mean and std) for ETL features",
            tier=aws_ssm.ParameterTier.STANDARD,
        )
