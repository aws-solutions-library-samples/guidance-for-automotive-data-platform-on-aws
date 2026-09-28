# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
GovernedGlueEtlConstruct
========================
A Glue 5.0 ETL job that:

  1. Reads ``tire_health``, ``vehicle_telemetry_aggregated``, and
     ``service_records`` from the ADP foundation Glue catalog via Lake
     Formation-governed access (LF vends short-lived S3 credentials).
  2. Joins the three products on ``vin`` + ``event_date``.
  3. Writes a training-ready Parquet dataset to the PM
     ``training_data_bucket``.

Script
------
The PySpark script ``source/assets/etl_scripts/governed_etl_job.py`` (deployed
to the asset bucket alongside the existing ``etl_glue_job.py``) does the actual
join.  The CDK construct manages the job definition + IAM wiring only.

Job arguments passed to the script:
  ``--stage``                   deployment stage (e.g. ``staging``)
  ``--training-s3-bucket-uri``  write destination (PM training bucket)
  ``--normalization-stats-parameter``  SSM parameter name for stats
  ``--athena-workgroup``        Athena workgroup name for query attribution
  ``--current-date``            override for deterministic replay (default: today)

No ``--source-s3-bucket-uri`` argument — the job reads via the Glue catalog
(LF-governed) instead of a raw S3 bucket URI.  This is the key difference
from the existing ``ETLPipeline`` construct.

IAM role
--------
The role is the ``GovernedDataAccessConstruct.glue_etl_role``; this construct
takes it as a parameter so the two concerns (IAM + job definition) remain
cleanly separated.
"""

from __future__ import annotations

import os

from aws_cdk import (
    Duration,
    Stack,
)
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from cdk_nag import NagSuppressions
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from aws_cdk import aws_ssm as ssm
from constructs import Construct


class GovernedGlueEtlConstruct(Construct):
    """Glue 5.0 job: joins tire_health + VTA + service_records → training Parquet.

    Parameters
    ----------
    scope / id:
        Standard CDK parent/id.
    stage:
        Deployment stage (``staging`` | ``prod``).
    glue_etl_role:
        IAM role with LF + Glue/Athena + S3-write permissions
        (from ``GovernedDataAccessConstruct``).
    asset_bucket:
        The PM asset bucket; the PySpark script is deployed here.
    training_data_bucket:
        Write destination for the training-ready Parquet dataset.
    normalization_stats_ssm_parameter:
        SSM parameter that holds normalization stats (read + write by job).
    pm_workgroup_name:
        Athena workgroup name for cost attribution.
    etl_scripts_path:
        Filesystem path to the ``etl_scripts/`` directory containing
        ``governed_etl_job.py``.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        stage: str,
        glue_etl_role: iam.Role,
        asset_bucket: s3.Bucket,
        training_data_bucket: s3.Bucket,
        normalization_stats_ssm_parameter: ssm.StringParameter,
        pm_workgroup_name: str,
        etl_scripts_path: str,
    ) -> None:
        super().__init__(scope, id)

        stack = Stack.of(self)

        # Deploy the PySpark script to the asset bucket alongside the
        # existing etl_glue_job.py.  prune=False ensures we don't delete
        # the legacy etl_glue_job.py uploaded by ETLPipeline (rollback path).
        s3deploy.BucketDeployment(
            self,
            "deploy-governed-etl-scripts",
            sources=[s3deploy.Source.asset(etl_scripts_path)],
            destination_bucket=asset_bucket,
            destination_key_prefix="etl-scripts",
            prune=False,
        )

        # Add SSM permissions to the ETL role for the normalization stats
        # parameter (same pattern as ETLPipeline).
        glue_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="NormalizationStatsParameter",
                actions=["ssm:GetParameter", "ssm:PutParameter"],
                resources=[normalization_stats_ssm_parameter.parameter_arn],
            )
        )

        # ------------------------------------------------------------------
        # Glue job definition
        # ------------------------------------------------------------------
        self.governed_glue_job = glue.CfnJob(
            self,
            "governed-glue-job",
            name=f"pm-{stage}-governed-etl-job",  # stage-prefixed for clarity
            role=glue_etl_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=(
                    f"s3://{asset_bucket.bucket_name}"
                    f"/etl-scripts/governed_etl_job.py"
                ),
            ),
            default_arguments={
                "--job-language": "python",
                "--enable-metrics": "true",
                "--enable-continuous-cloudwatch-log": "true",
                "--enable-glue-datacatalog": "true",
                # NOTE: --source-s3-bucket-uri intentionally absent.
                # The job reads via the Glue catalog (LF-governed).
                "--stage": stage,
                "--training-s3-bucket-uri": (
                    f"s3://{training_data_bucket.bucket_name}"
                ),
                "--normalization-stats-parameter": (
                    normalization_stats_ssm_parameter.parameter_name
                ),
                "--athena-workgroup": pm_workgroup_name,
                "--current-date": "default",  # override for deterministic replay
            },
            glue_version="5.0",
            max_retries=0,
            timeout=60,
            number_of_workers=10,
            worker_type="G.8X",
            description=(
                "PM governed ETL: reads tire_health + vehicle_telemetry_aggregated"
                " + service_records via Lake Formation, joins on vin+event_date,"
                " writes training-ready Parquet to PM training bucket."
            ),
        )

        # ------------------------------------------------------------------
        # CloudWatch Alarm for job failures (mirrors ETLPipeline pattern).
        # ------------------------------------------------------------------
        self.governed_glue_job_failure_alarm = cloudwatch.Alarm(
            self,
            "governed-glue-job-failure-alarm",
            alarm_name=f"pm-{stage}-governed-etl-job-failure-alarm",
            alarm_description=(
                "Alarm triggered when PM governed Glue ETL job fails"
            ),
            metric=cloudwatch.Metric(
                namespace="Glue",
                metric_name="glue.driver.aggregate.numFailedTasks",
                dimensions_map={
                    "JobName": self.governed_glue_job.name,
                    "Type": "count",
                },
                statistic="Sum",
                period=Duration.minutes(5),
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        # ------------------------------------------------------------------
        # cdk-nag suppressions for the Glue job (CfnJob resource).
        # ------------------------------------------------------------------
        NagSuppressions.add_resource_suppressions(
            self.governed_glue_job,
            [
                {
                    "id": "AwsSolutions-GL1",
                    "reason": (
                        "The PM governed Glue ETL job writes to the PM training "
                        "bucket (AES-256 SSE) and reads via Lake Formation "
                        "short-lived credentials.  A Glue security configuration "
                        "with CWL encryption is not required by this reference "
                        "architecture because the CloudWatch log group itself is "
                        "not expected to contain sensitive data (Glue system "
                        "metrics only); operators can add a security configuration "
                        "for production hardening."
                    ),
                },
                {
                    "id": "AwsSolutions-GL3",
                    "reason": (
                        "Job bookmark encryption is not applicable to this job: "
                        "the governed ETL job is designed for full-refresh runs "
                        "(no incremental bookmark state is maintained).  Enabling "
                        "bookmark encryption without bookmarks has no security "
                        "benefit and adds operational complexity."
                    ),
                },
            ],
        )
