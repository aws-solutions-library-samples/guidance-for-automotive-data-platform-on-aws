# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Standard Library
import os

# AWS Libraries
from aws_cdk import (
    ArnFormat,
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb,
    aws_iam,
    aws_lambda,
    aws_lambda_event_sources,
    aws_logs,
    aws_sqs,
    aws_ssm,
)
from cdk_nag import NagSuppressions
from constructs import Construct

# Predictive Maintenance
from ..common.encrypted_s3 import EncryptedS3Construct, LifecycleConfig
from ..common.lambda_bundling import create_poetry_bundling
from ..config.monitoring_lambda_registry import MonitoringLambdaRegistry



class AlertsSystemConstruct(Construct):
    cloud_watch_custom_namespace = "Alerts Metrics"
    alerts_processor_lambda_name = "alerts-processor"
    alerts_transformer_lambda_name = "alerts-transformer"
    alerts_cleaner_lambda_name = "alerts-cleaner"

    def __init__(
        self,
        scope: Construct,
        id: str,
        unique_id: str,
        common_dependency_layer: aws_lambda.LayerVersion,
        s3_log_lifecycle_rules: LifecycleConfig,
        user_agent_string: str,
    ) -> None:
        super().__init__(scope, id)
        
        # Create SSM parameter for anomaly threshold
        self.anomaly_threshold_ssm_parameter = aws_ssm.StringParameter(
            self,
            "anomaly-threshold-ssm-parameter",
            parameter_name="/tire-maintenance/anomaly-threshold",
            string_value='{"threshold": null, "last_updated": null}',
            description="Anomaly detection threshold and last update timestamp",
        )

        table_name = f"{unique_id}-alerts"
        unique_alerts_processor_lambda_name = (
            f"{unique_id}-{self.alerts_processor_lambda_name}"
        )
        unique_alerts_transformer_lambda_name = (
            f"{unique_id}-{self.alerts_transformer_lambda_name}"
        )
        unique_alerts_cleaner_lambda_name = (
            f"{unique_id}-{self.alerts_cleaner_lambda_name}"
        )
        sqs_queue_name = f"{unique_id}-alerts-processing"
        sqs_dlq_name = f"{sqs_queue_name}-dlq"

        # Temporary bucket to store generated alerts until API is available
        self.alerts_bucket_construct = EncryptedS3Construct(
            self,
            "alerts-bucket-construct",
            log_lifecycle_rules=s3_log_lifecycle_rules,
        )

        self.error_data_bucket = EncryptedS3Construct(
            self,
            "error-bucket-construct",
            log_lifecycle_rules=s3_log_lifecycle_rules,
        )

        self.alerts_table = aws_dynamodb.Table(
            self,
            "alerts-table",
            table_name=table_name,
            partition_key=aws_dynamodb.Attribute(
                name="alertId",
                type=aws_dynamodb.AttributeType.STRING,
            ),
            sort_key=aws_dynamodb.Attribute(
                name="timestamp",
                type=aws_dynamodb.AttributeType.STRING,
            ),
            billing_mode=aws_dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            # DDB3: enable Point-in-Time Recovery for operational data protection
            point_in_time_recovery=True,
        )

        self.alerts_table.add_global_secondary_index(
            index_name="alerts-by-time",
            partition_key=aws_dynamodb.Attribute(
                name="alert_partition_key",
                type=aws_dynamodb.AttributeType.STRING,
            ),
            sort_key=aws_dynamodb.Attribute(
                name="timestamp",
                type=aws_dynamodb.AttributeType.STRING,
            ),
            projection_type=aws_dynamodb.ProjectionType.ALL,
        )

        self.alerts_table.add_global_secondary_index(
            index_name="alerts-by-status",
            partition_key=aws_dynamodb.Attribute(
                name="status",
                type=aws_dynamodb.AttributeType.STRING,
            ),
            sort_key=aws_dynamodb.Attribute(
                name="timestamp",
                type=aws_dynamodb.AttributeType.STRING,
            ),
            projection_type=aws_dynamodb.ProjectionType.ALL,
        )

        self.alerts_dlq = aws_sqs.Queue(
            self,
            "alerts-dlq",
            queue_name=sqs_dlq_name,
            visibility_timeout=Duration.seconds(70),
            retention_period=Duration.days(14),
            # SQS4: require SSL-only access (aws:SecureTransport deny policy)
            enforce_ssl=True,
        )

        self.alerts_queue = aws_sqs.Queue(
            self,
            "alerts-queue",
            queue_name=sqs_queue_name,
            visibility_timeout=Duration.seconds(70),
            retention_period=Duration.hours(16),
            dead_letter_queue=aws_sqs.DeadLetterQueue(
                max_receive_count=5,
                queue=self.alerts_dlq,
            ),
            # SQS4: require SSL-only access (aws:SecureTransport deny policy)
            enforce_ssl=True,
        )

        self.role = aws_iam.Role(
            self,
            "lambda-role",
            assumed_by=aws_iam.ServicePrincipal("lambda.amazonaws.com"),
            inline_policies={
                "lambda-inline-access": aws_iam.PolicyDocument(
                    statements=[
                        # DynamoDB: Read (GetItem) and write (UpdateItem) alerts
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "dynamodb:GetItem",
                                "dynamodb:UpdateItem",
                            ],
                            resources=[
                                self.alerts_table.table_arn,
                            ],
                        ),
                        # Also include indexes if used in your SDK logic
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=["dynamodb:Query"],
                            resources=[f"{self.alerts_table.table_arn}/index/*"],
                        ),
                        # SQS: Delete successful messages
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "sqs:DeleteMessageBatch",
                                "sqs:DeleteMessage",
                                "sqs:GetQueueAttributes",
                                "sqs:ReceiveMessage",
                            ],
                            resources=[
                                self.alerts_queue.queue_arn,
                            ],
                        ),
                        # S3: Write transformed alerts
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "s3:PutObject",
                            ],
                            resources=[
                                f"{self.alerts_bucket_construct.bucket.bucket_arn}/*",
                                f"{self.error_data_bucket.bucket.bucket_arn}/*",
                            ],
                        ),
                        # Logs: CloudWatch Logs
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                            ],
                            resources=[
                                Stack.of(self).format_arn(
                                    service="logs",
                                    resource="log-group",
                                    resource_name=f"/aws/lambda/{unique_alerts_processor_lambda_name}",
                                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                ),
                                Stack.of(self).format_arn(
                                    service="logs",
                                    resource="log-group",
                                    resource_name=f"/aws/lambda/{unique_alerts_processor_lambda_name}:log-stream:*",
                                    arn_format=ArnFormat.COLON_RESOURCE_NAME,
                                ),
                            ],
                        ),
                    ]
                )
            },
        )

        self.alerts_processor_function = aws_lambda.Function(
            self,
            "lambda-function",
            code=create_poetry_bundling(f"{os.getcwd()}/../lambda/alerts_processor"),
            handler="function.main.handler",
            function_name=unique_alerts_processor_lambda_name,
            role=self.role,
            runtime=aws_lambda.Runtime.PYTHON_3_13,
            timeout=Duration.minutes(1),
            layers=[common_dependency_layer],
            memory_size=512,
            environment={
                "ALERTS_TABLE": self.alerts_table.table_name,
                "ALERTS_QUEUE_URL": self.alerts_queue.queue_url,
                "ALERTS_BUCKET": self.alerts_bucket_construct.bucket.bucket_name,
                "ALERTS_BUCKET_PREFIX": "alerts",
                "USER_AGENT_STRING": user_agent_string,
                "POWERTOOLS_METRICS_NAMESPACE": self.cloud_watch_custom_namespace,
            },
            log_retention=aws_logs.RetentionDays.THREE_MONTHS,
        )

        self.alerts_table.grant_read_write_data(self.alerts_processor_function)
        self.alerts_bucket_construct.bucket.grant_read_write(
            self.alerts_processor_function
        )
        self.alerts_queue.grant_consume_messages(self.alerts_processor_function)

        self.alerts_processor_function.add_event_source(
            aws_lambda_event_sources.SqsEventSource(
                self.alerts_queue,
                batch_size=10,
                report_batch_item_failures=True,
            )
        )
        MonitoringLambdaRegistry.register_lambda(
            self.alerts_processor_lambda_name, self.alerts_processor_function
        )

        self.alerts_transformer_function = aws_lambda.Function(
            self,
            "transform-predictions-to-alerts",
            code=create_poetry_bundling(f"{os.getcwd()}/../lambda/transform_predictions_to_alerts"),
            handler="function.main.handler",
            function_name=unique_alerts_transformer_lambda_name,
            runtime=aws_lambda.Runtime.PYTHON_3_13,
            timeout=Duration.minutes(5),
            layers=[common_dependency_layer],
            memory_size=512,
            environment={
                "ALERTS_TABLE": self.alerts_table.table_name,
                "ALERTS_QUEUE_URL": self.alerts_queue.queue_url,
                "USER_AGENT_STRING": user_agent_string,
                "POWERTOOLS_METRICS_NAMESPACE": self.cloud_watch_custom_namespace,
                "ERROR_DATA_BUCKET": self.error_data_bucket.bucket.bucket_name,
                "ANOMALY_THRESHOLD_PARAMETER": self.anomaly_threshold_ssm_parameter.parameter_name,
            },
            log_retention=aws_logs.RetentionDays.THREE_MONTHS,
        )

        self.alerts_table.grant_read_write_data(self.alerts_transformer_function)
        self.alerts_queue.grant_send_messages(self.alerts_transformer_function)
        self.anomaly_threshold_ssm_parameter.grant_read(self.alerts_transformer_function)
        self.anomaly_threshold_ssm_parameter.grant_write(self.alerts_transformer_function)
        
        MonitoringLambdaRegistry.register_lambda(
            self.alerts_transformer_lambda_name, self.alerts_transformer_function
        )
        self.error_data_bucket.bucket.grant_write(self.alerts_transformer_function)

        # Create the alerts_cleaner_function to process DLQ messages and update DynamoDB items
        self.alerts_cleaner_function = aws_lambda.Function(
            self,
            self.alerts_cleaner_lambda_name,
            code=create_poetry_bundling(f"{os.getcwd()}/../lambda/alerts_cleaner"),
            handler="function.main.handler",
            function_name=unique_alerts_cleaner_lambda_name,
            runtime=aws_lambda.Runtime.PYTHON_3_13,
            timeout=Duration.minutes(1),
            layers=[common_dependency_layer],
            memory_size=512,
            environment={
                "ALERTS_TABLE": self.alerts_table.table_name,
                "USER_AGENT_STRING": user_agent_string,
                "POWERTOOLS_METRICS_NAMESPACE": self.cloud_watch_custom_namespace,
            },
            log_retention=aws_logs.RetentionDays.THREE_MONTHS,
        )

        self.alerts_table.grant_read_write_data(self.alerts_cleaner_function)
        self.alerts_dlq.grant_consume_messages(self.alerts_cleaner_function)

        self.alerts_cleaner_function.add_event_source(
            aws_lambda_event_sources.SqsEventSource(
                self.alerts_dlq,
                batch_size=10,
                report_batch_item_failures=True,
            )
        )

        MonitoringLambdaRegistry.register_lambda(
            self.alerts_cleaner_lambda_name, self.alerts_cleaner_function
        )

        # ---------------------------------------------------------------------------
        # NagSuppressions — documented justifications, reviewed per-resource.
        # ---------------------------------------------------------------------------

        # AwsSolutions-L1 (#6, #7, #8): PM Lambdas pinned to python3.13.
        # Rationale (decisions.md 2026-07-16): bumping to python3.14 breaks synth because the
        # shared common_dependencies Lambda layer is built with build-python3.13 and declares
        # compatible_runtimes=[PYTHON_3_13].  Bumping the runtime requires a coordinated layer
        # rebuild (SAM build image + compatible_runtimes + dep-compat validation) — tracked as
        # a follow-up task, not done piecemeal.
        for fn in (
            self.alerts_processor_function,
            self.alerts_transformer_function,
            self.alerts_cleaner_function,
        ):
            NagSuppressions.add_resource_suppressions(
                fn,
                suppressions=[
                    {
                        "id": "AwsSolutions-L1",
                        "reason": (
                            "PM Lambdas are pinned to python3.13 to match the shared "
                            "common_dependencies Lambda layer (built with SAM build-python3.13, "
                            "compatible_runtimes=[PYTHON_3_13]).  Bumping the runtime requires a "
                            "coordinated layer rebuild and dependency-compatibility validation — "
                            "tracked as a follow-up, not done piecemeal."
                        ),
                    }
                ],
            )

        # AwsSolutions-IAM4 (#9, #10): CDK auto-created Lambda execution roles for
        # alerts_transformer and alerts_cleaner use AWSLambdaBasicExecutionRole.
        # These ServiceRoles are auto-created by CDK when a Lambda function is defined
        # without an explicit role=; they carry only the managed execution role.
        # Removing the managed policy and adding an explicit inline-policy role requires
        # re-creating the functions with explicit roles — a separate hardening task.
        for fn in (self.alerts_transformer_function, self.alerts_cleaner_function):
            NagSuppressions.add_resource_suppressions(
                fn.role,
                suppressions=[
                    {
                        "id": "AwsSolutions-IAM4",
                        "reason": (
                            "CDK-auto-created Lambda execution role uses "
                            "AWSLambdaBasicExecutionRole.  The managed policy grants only "
                            "CloudWatch Logs write access — the minimum required by the Lambda "
                            "runtime.  Replacing with a customer-managed policy is a hardening "
                            "follow-up; no additional privileges are granted here."
                        ),
                        "appliesTo": [
                            "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
                        ],
                    }
                ],
                apply_to_children=True,
            )

        # AwsSolutions-IAM5 (#4): alerts-system/lambda-role inline policy wildcards.
        #   • DDB index/*: multiple named GSIs exist; enumerating each individual index ARN
        #     would be fragile (every future index addition would require a policy update).
        #     The table ARN itself is already scoped.
        #   • S3 bucket/*: object-level operations (PutObject) require the /* suffix;
        #     the bucket ARN is already scoped to the specific construct-provisioned bucket.
        #   • CW log-stream *: the Lambda runtime writes to a stream whose name includes
        #     the execution ID, which is unknown at deploy time.  This is the standard AWS
        #     Lambda CW Logs pattern.
        NagSuppressions.add_resource_suppressions(
            self.role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Inline policy wildcards on alerts-system lambda-role are operationally required: "
                        "(1) DDB index/* — multiple named GSIs (alerts-by-time, alerts-by-status); "
                        "enumerating each index ARN individually would break on any future GSI addition. "
                        "Table ARN is already scoped to this specific alerts table. "
                        "(2) S3 bucket/* — object-level PutObject requires the /* suffix; "
                        "bucket ARNs are already scoped to the specific construct-provisioned buckets. "
                        "(3) CW log-stream * — Lambda writes to execution-ID-suffixed log streams "
                        "whose exact names are unknown at deploy time (standard AWS Lambda logging). "
                        "apply_to_children=True covers the CDK-grant-generated DefaultPolicy on this role "
                        "(from table.grant_read_write_data / bucket.grant_read_write / queue grants) "
                        "which expands to action wildcards (s3:GetObject*, s3:DeleteObject*, etc.) "
                        "and resource wildcards (bucket/*, DDB index/*) — inherent to CDK L2 grant pattern."
                    ),
                }
            ],
            apply_to_children=True,
        )

        # AwsSolutions-IAM5 (#5, #11, #12): CDK-grant-generated DefaultPolicy wildcards.
        # CDK's .grant_read_write_data(), .grant_read_write(), .grant_consume_messages(),
        # and .grant_send_messages() expand to action wildcards (s3:GetObject*, s3:DeleteObject*,
        # etc.) and resource wildcards (bucket/*, DDB index/*) by design.
        # The resource scope is already tightly bounded to specific table/bucket/queue ARNs
        # by the CDK grant APIs — only the action-level wildcard remains.
        for fn in (
            self.alerts_processor_function,
            self.alerts_transformer_function,
            self.alerts_cleaner_function,
        ):
            NagSuppressions.add_resource_suppressions(
                fn,
                suppressions=[
                    {
                        "id": "AwsSolutions-IAM5",
                        "reason": (
                            "Wildcard actions in DefaultPolicy are generated by CDK grant methods "
                            "(table.grant_read_write_data, bucket.grant_read_write, "
                            "queue.grant_consume_messages, queue.grant_send_messages). "
                            "Resource scope is already tightly bounded to specific "
                            "table/bucket/queue ARNs by the CDK grant APIs — only the action-level "
                            "wildcard (e.g. s3:GetObject*, s3:DeleteObject*) remains, which is "
                            "inherent to the CDK L2 grant pattern."
                        ),
                    }
                ],
                apply_to_children=True,
            )
