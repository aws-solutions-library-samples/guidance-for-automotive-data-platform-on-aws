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

        aws_s3_deployment.BucketDeployment(
            self,
            "deploy-scripts",
            sources=[aws_s3_deployment.Source.asset(etl_glue_scripts_location)],
            destination_bucket=asset_bucket,
            destination_key_prefix="etl-scripts",
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
