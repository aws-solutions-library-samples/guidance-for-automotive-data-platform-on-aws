# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# AWS Libraries
from aws_cdk import aws_lambda, aws_s3, aws_s3_notifications
from constructs import Construct

# MMT Predictive Maintenance
from ..common.encrypted_s3 import EncryptedS3Construct, LifecycleConfig


class PredictionModelConstruct(Construct):
    def __init__(
        self,
        scope: Construct,
        id: str,
        s3_log_lifecycle_rules: LifecycleConfig,
        alerts_transformer_function: aws_lambda.Function,
    ):
        super().__init__(scope, id)

        self.prediction_bucket_construct = EncryptedS3Construct(
            self,
            "prediction-bucket-construct",
            log_lifecycle_rules=s3_log_lifecycle_rules,
        )

        # Configure notifications to alert transformer Lambda
        self.prediction_bucket_construct.bucket.grant_read(
            alerts_transformer_function
        )
        self.prediction_bucket_construct.bucket.add_event_notification(
            aws_s3.EventType.OBJECT_CREATED,
            aws_s3_notifications.LambdaDestination(alerts_transformer_function),
        )
