# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# AWS Libraries
from constructs import Construct

# MMT Predictive Maintenance
from ...common.encrypted_s3 import EncryptedS3Construct, LifecycleConfig


class ETLDataBuckets(Construct):
    def __init__(
        self, scope: Construct, id: str, s3_log_lifecycle_rules: LifecycleConfig
    ):
        super().__init__(scope, id)

        self.raw_data_bucket = EncryptedS3Construct(
            self,
            "raw-data-bucket",
            log_lifecycle_rules=s3_log_lifecycle_rules,
        ).bucket

        self.training_data_bucket = EncryptedS3Construct(
            self, "training-data-bucket", log_lifecycle_rules=s3_log_lifecycle_rules
        ).bucket

        self.inference_data_bucket = EncryptedS3Construct(
            self, "inference-data-bucket", log_lifecycle_rules=s3_log_lifecycle_rules
        ).bucket