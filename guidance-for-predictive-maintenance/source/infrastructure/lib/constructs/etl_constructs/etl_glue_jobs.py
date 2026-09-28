# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from .etl_data_buckets import ETLDataBuckets
from .normalization_stats import NormalizationStats

# AWS Libraries
from aws_cdk import (
    aws_glue,
    aws_iam,
    aws_s3,
    aws_s3_deployment,
    Duration,
    aws_cloudwatch,
    aws_events,
    aws_events_targets,
)
from cdk_nag import NagSuppressions
from constructs import Construct

class ETLPipeline(Construct):
    def __init__(
        self,
        scope: Construct,
        id: str,
        asset_bucket: aws_s3.Bucket,
        etl_data_buckets: ETLDataBuckets,
        etl_glue_scripts_location: str,
        normalization_stats: NormalizationStats,
    ):
        super().__init__(scope, id)

        etl_glue_job_role = aws_iam.Role(
            self,
            "etl-glue-job-role",
            assumed_by=aws_iam.ServicePrincipal("glue.amazonaws.com"),
            inline_policies={
                "s3-read-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "s3:GetObject",
                                "s3:ListBucket",
                                "s3:GetObjectVersion",
                            ],
                            resources=[
                                etl_data_buckets.raw_data_bucket.bucket_arn,
                                f"{etl_data_buckets.raw_data_bucket.bucket_arn}/*",
                                asset_bucket.bucket_arn,
                                f"{asset_bucket.bucket_arn}/*",
                            ],
                        ),
                    ]
                ),
                "s3-write-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "s3:PutObject",
                                "s3:ListBucket",
                            ],
                            resources=[
                                etl_data_buckets.training_data_bucket.bucket_arn,
                                f"{etl_data_buckets.training_data_bucket.bucket_arn}/*",
                                etl_data_buckets.inference_data_bucket.bucket_arn,
                                f"{etl_data_buckets.inference_data_bucket.bucket_arn}/*",
                            ],
                        ),
                    ]
                ),
                "logs-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "logs:CreateLogGroup",
                                "logs:CreateLogStream",
                                "logs:PutLogEvents",
                            ],
                            resources=[
                                "arn:aws:logs:*:*:/aws-glue/*",
                            ],
                        ),
                    ]
                ),
                "ssm-policy": aws_iam.PolicyDocument(
                    statements=[
                        aws_iam.PolicyStatement(
                            effect=aws_iam.Effect.ALLOW,
                            actions=[
                                "ssm:GetParameter",
                                "ssm:PutParameter",
                            ],
                            resources=[
                                normalization_stats.stats_ssm_parameter.parameter_arn,
                            ],
                        ),
                    ]
                ),
            },
        )

        deploy_scripts = aws_s3_deployment.BucketDeployment(
            self,
            "deploy-scripts",
            sources=[aws_s3_deployment.Source.asset(etl_glue_scripts_location)],
            destination_bucket=asset_bucket,
            destination_key_prefix="etl-scripts",
            prune=False,
        )

        # AwsSolutions-IAM4 + IAM5 + L1 on the CDK-generated BucketDeployment custom resource.
        # BucketDeployment provisions a CDK-framework Lambda that copies assets to S3.
        # The Lambda role uses AWSLambdaBasicExecutionRole (IAM4) and S3 wildcards (IAM5);
        # the runtime may lag the latest AWS Lambda GA version (L1).
        # None of these are authored by this accelerator.
        NagSuppressions.add_resource_suppressions(
            deploy_scripts,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "CDK-framework BucketDeployment custom resource Lambda execution role "
                        "uses AWSLambdaBasicExecutionRole — not authored by this accelerator.  "
                        "This is the standard CDK L2 BucketDeployment pattern."
                    ),
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "CDK-framework BucketDeployment custom resource Lambda role uses "
                        "S3 action wildcards (GetBucket*, GetObject*, List*, Abort*, DeleteObject*) "
                        "and S3 resource wildcards (CDK assets bucket/*, destination bucket/*). "
                        "These wildcards are inherent to the CDK BucketDeployment L2 construct "
                        "and are not authored by this accelerator."
                    ),
                },
                {
                    "id": "AwsSolutions-L1",
                    "reason": (
                        "CDK-framework BucketDeployment custom resource Lambda runtime is managed "
                        "by CDK — not authored by this accelerator."
                    ),
                },
            ],
            apply_to_children=True,
        )

        self.etl_glue_job = aws_glue.CfnJob(
            self,
            "etl-glue-job",
            name="etl-glue-job",
            role=etl_glue_job_role.role_arn,
            command=aws_glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"s3://{asset_bucket.bucket_name}/etl-scripts/etl_glue_job.py",
            ),
            default_arguments={
                "--job-language": "python",
                "--enable-metrics": "true",
                "--enable-continuous-cloudwatch-log": "true",
                "--enable-glue-datacatalog": "true",
                "--normalization-stats-parameter": normalization_stats.stats_ssm_parameter.parameter_name,
                "--source-s3-bucket-uri": f"s3://{etl_data_buckets.raw_data_bucket.bucket_name}",
                "--training-s3-bucket-uri": f"s3://{etl_data_buckets.training_data_bucket.bucket_name}",
                "--inference-s3-bucket-uri": f"s3://{etl_data_buckets.inference_data_bucket.bucket_name}",
                "--current-date": "default",
            },
            glue_version="5.0",
            max_retries=0,
            timeout=60,
            number_of_workers=10,
            worker_type="G.8X",
        )

        # CloudWatch Alarm for Glue Job Failures
        self.glue_job_failure_alarm = aws_cloudwatch.Alarm(
            self,
            "etl-glue-job-failure-alarm",
            alarm_name="etl-glue-job-failure-alarm",
            alarm_description="Alarm triggered when ETL Glue job fails",
            metric=aws_cloudwatch.Metric(
                namespace="Glue",
                metric_name="glue.driver.aggregate.numFailedTasks",
                dimensions_map={
                    "JobName": self.etl_glue_job.name,
                    "Type": "count",
                },
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=aws_cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=aws_cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # EventBridge rule to trigger Glue job daily at 3 AM UTC, turn it on for a scheduled run
        # glue_job_schedule_rule = aws_events.Rule(
        #     self,
        #     "etl-glue-job-schedule",
        #     schedule=aws_events.Schedule.cron(
        #         minute="0",
        #         hour="3",
        #         month="*",
        #         week_day="*",
        #         year="*",
        #     ),
        #     description="Trigger ETL Glue job daily at 3 AM UTC",
        # )

        # Create IAM role for EventBridge to start Glue job
        # glue_job_trigger_role = aws_iam.Role(
        #     self,
        #     "glue-job-trigger-role",
        #     assumed_by=aws_iam.ServicePrincipal("events.amazonaws.com"),
        # )

        # glue_job_trigger_role.add_to_policy(
        #     aws_iam.PolicyStatement(
        #         effect=aws_iam.Effect.ALLOW,
        #         actions=["glue:StartJobRun"],
        #         resources=[
        #             f"arn:aws:glue:{self.etl_glue_job.stack.region}:{self.etl_glue_job.stack.account}:job/{self.etl_glue_job.name}"
        #         ],
        #     )
        # )

        # Add Glue job as target for the EventBridge rule
        # glue_job_schedule_rule.add_target(
        #     aws_events_targets.AwsApi(
        #         service="glue",
        #         action="startJobRun",
        #         parameters={"JobName": self.etl_glue_job.name},
        #     )
        # )

        # ---------------------------------------------------------------------------
        # NagSuppressions — documented justifications, reviewed per-resource.
        # ---------------------------------------------------------------------------

        # AwsSolutions-GL1 (#15): Glue job has no security configuration (CW log encryption).
        # Glue security configurations (SecurityConfiguration resources) are account-level
        # shared infrastructure — a single security config covers multiple Glue jobs.
        # Creating one per stack/construct would cause naming conflicts on multi-deploy.
        # This is the same suppression pattern used by the CMS ingest stack (cms_ingest_stack.py
        # lines ~622-654). Operators should attach an account-level security config in production.
        NagSuppressions.add_resource_suppressions(
            self.etl_glue_job,
            suppressions=[
                {
                    "id": "AwsSolutions-GL1",
                    "reason": (
                        "Glue security configurations (for CW log encryption) are account-level "
                        "shared infrastructure — provisioning one per stack would cause naming "
                        "conflicts.  This is consistent with the CMS ingest stack's existing "
                        "suppression pattern (cms_ingest_stack.py).  Operators deploying to "
                        "production should attach an account-level Glue security configuration "
                        "that enforces CW log encryption appropriate for their environment."
                    ),
                }
            ],
        )

        # AwsSolutions-GL3 (#16): Glue job has no job-bookmark encryption.
        # Job-bookmark encryption is also part of a Glue security configuration — same rationale
        # as GL1 above.  Both are suppressed together as they share the same mitigation path
        # (account-level Glue SecurityConfiguration applied by the operator).
        NagSuppressions.add_resource_suppressions(
            self.etl_glue_job,
            suppressions=[
                {
                    "id": "AwsSolutions-GL3",
                    "reason": (
                        "Glue job-bookmark encryption requires a Glue security configuration, "
                        "which is account-level shared infrastructure (same rationale as GL1). "
                        "Consistent with the CMS ingest stack suppression pattern.  Operators "
                        "should attach an account-level Glue security configuration in production."
                    ),
                }
            ],
        )

        # AwsSolutions-IAM5 (#17): etl-glue-job-role S3 prefix wildcards and CW logs wildcard.
        #   • S3 bucket/*: Glue Spark jobs write dynamically-partitioned output (date/partition
        #     subdirectories) whose exact key paths are determined at runtime — object-level
        #     PutObject/GetObject requires the /* suffix; bucket ARNs are already scoped.
        #   • CW logs arn:aws:logs:*:*:/aws-glue/*: the Glue Spark runtime delivers logs to
        #     log groups named /aws/glue/<job-name>/<run-id> — both the job name and run ID
        #     are partially runtime-determined.  The account-/region-wildcard pattern (arn:aws:logs:*:*)
        #     combined with the /aws-glue/* prefix is the documented Glue IAM pattern.
        NagSuppressions.add_resource_suppressions(
            etl_glue_job_role,
            suppressions=[
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Operationally-required wildcards for the Glue ETL job role: "
                        "(1) S3 bucket/*: Glue Spark writes dynamically-partitioned output whose "
                        "exact key paths (date/partition subdirectories) are determined at runtime; "
                        "bucket ARNs are already scoped to specific CDK-provisioned buckets. "
                        "(2) CW logs arn:aws:logs:*:*:/aws-glue/*: Glue Spark runtime delivers "
                        "logs to /aws/glue/<job>/<run-id> log groups; the account- and region-wildcard "
                        "combined with /aws-glue/* prefix is the documented AWS Glue IAM pattern "
                        "(same as cms_ingest_stack.py's glue_role suppression)."
                    ),
                }
            ],
            apply_to_children=True,
        )
