"""ADP Data Products stack — persistent IAM role for Spark-ETL on Glue.

Spec: ``.kiro/specs/2026-06-09-adp-pyspark-glue-products/spec.md``

This stack is the materialization of OQ #2 (Option A): a NEW minimal
stack ``adp-{stage}-foundation-data-products`` that holds the
persistent CDK-managed IAM role used by one-shot Glue 4.0 jobs that
generate the 2 PySpark-based ADP data products
(``vehicle_telemetry_aggregated``, ``energy_usage``).

Why a new stack rather than extending ``foundation_stack.py`` or
``governance_stack.py``:

* Future-proofs the production-scale follow-up (100M / 450M rows) and
  the Glue 5.0 bump path — both can extend this stack without touching
  the existing 5 per-stage stacks.
* The role has a different lifecycle from foundation/governance:
  re-runnable by an orchestration script on demand, persisting only
  the role + S3-uploaded scripts — the Glue jobs themselves are
  one-shot boto3 resources (per OQ #1 + OQ #3).

Per ``staging-prod-design.md`` §2 + ``~/.kiro/steering/cross-region-namespace.md``
Check 1: the role name is region-suffixed
(``adp-{stage}-foundation-spark-etl-role-{region}``) so a future
multi-region deployment does not collide on the account-wide IAM
namespace.

Pattern reference: ``stacks/optional/cms_ingest_stack.py::CmsIngestStack``
lines 388–460 (``GlueMergeJobRole``) — the existing canonical
Spark-ETL role idiom in this repo. This stack mirrors that pattern,
narrowed to the 2 target Glue databases and the lake-bucket prefixes
used by the PySpark generators.
"""

from __future__ import annotations

from typing import Optional

from aws_cdk import (
    CfnOutput,
    Stack,
)
from aws_cdk import aws_iam as iam
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks._naming import _stage_name, validate_stage


class DataProductsStack(Stack):
    """Persistent IAM role for one-shot Glue 4.0 PySpark generators.

    The role grants minimum-IAM access to:

    * S3 lake bucket — read on ``dimensions/``; read+write on
      ``curated/vehicle_telemetry_aggregated/*``,
      ``curated/energy_usage/*``, ``scripts/*``, ``tmp/*``,
      ``athena-results/*``.
    * Glue Catalog scoped to exactly 2 databases:
      ``adp_{stage}_vehicle_telemetry_aggregated`` and
      ``adp_{stage}_energy_usage`` (and their tables).
    * Athena ``primary`` workgroup (for self-test paths; the
      architect's verify runs from the operator host, not the role).
    * CloudWatch Logs for the standard Glue job log groups.
    * KMS via the lake CMK if known, else ``*`` constrained by
      ``kms:ViaService`` (matches the cms_ingest_stack pattern at
      line 443–460).
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        stage: str,
        lake_bucket_name: str,
        lake_kms_key_arn: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)
        validate_stage(stage)

        # Region-suffixed role name — required per
        # ``~/.kiro/steering/cross-region-namespace.md`` Check 1
        # (account-wide IAM namespace).
        role_name = f"{_stage_name(stage, 'spark-etl-role')}-{self.region}"

        spark_etl_role = iam.Role(
            self,
            "SparkEtlRole",
            role_name=role_name,
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            description=(
                f"ADP foundation persistent Spark-ETL role for one-shot "
                f"Glue 4.0 PySpark generators (stage={stage}). Used by "
                f"`scripts/run-pyspark-products.py` per spec "
                f"`2026-06-09-adp-pyspark-glue-products`."
            ),
        )

        # Baseline Glue service role — provides ``cloudwatch:*`` standard
        # Glue logging perms + asset-bucket reads. Same as the
        # cms_ingest_stack pattern.
        spark_etl_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSGlueServiceRole"
            )
        )

        # ------------------------------------------------------------------
        # S3 lake bucket — list + read on dimensions; write on curated
        # for the 2 target products + scripts + tmp + athena-results.
        # ------------------------------------------------------------------
        bucket_arn = f"arn:aws:s3:::{lake_bucket_name}"
        write_prefixes = (
            "curated/vehicle_telemetry_aggregated",
            "curated/energy_usage",
            "scripts",
            "tmp",
            "athena-results",
        )
        list_prefixes = ("dimensions",) + write_prefixes

        spark_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3ListBucketScoped",
                actions=["s3:ListBucket", "s3:GetBucketLocation"],
                resources=[bucket_arn],
                conditions={
                    "StringLike": {
                        "s3:prefix": [
                            f"{p}/*" for p in list_prefixes
                        ]
                        + list(list_prefixes),
                    }
                },
            )
        )
        spark_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3DimensionsRead",
                actions=["s3:GetObject"],
                resources=[f"{bucket_arn}/dimensions/*"],
            )
        )
        spark_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3CuratedAndOpsWrite",
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                ],
                resources=[
                    f"{bucket_arn}/{prefix}/*" for prefix in write_prefixes
                ],
            )
        )

        # ------------------------------------------------------------------
        # Glue Catalog scoped to exactly the 2 target databases.
        # NO catalog-wide reads. NO access to other ADP databases.
        # ------------------------------------------------------------------
        catalog_arn = f"arn:aws:glue:{self.region}:{self.account}:catalog"
        target_dbs = (
            f"adp_{stage}_vehicle_telemetry_aggregated",
            f"adp_{stage}_energy_usage",
        )
        glue_db_arns = [
            f"arn:aws:glue:{self.region}:{self.account}:database/{db}"
            for db in target_dbs
        ]
        glue_table_arns = [
            f"arn:aws:glue:{self.region}:{self.account}:table/{db}/*"
            for db in target_dbs
        ]

        spark_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="GlueCatalogScoped",
                actions=[
                    "glue:GetDatabase",
                    "glue:GetDatabases",
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:CreateTable",
                    "glue:UpdateTable",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                    "glue:CreatePartition",
                    "glue:UpdatePartition",
                    "glue:BatchCreatePartition",
                ],
                resources=[catalog_arn] + glue_db_arns + glue_table_arns,
            )
        )

        # ------------------------------------------------------------------
        # Athena ``primary`` workgroup only — for symmetry; the verify
        # path runs from the architect's host, not the Glue role.
        # ------------------------------------------------------------------
        spark_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="AthenaPrimaryWorkgroup",
                actions=[
                    "athena:StartQueryExecution",
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                    "athena:StopQueryExecution",
                    "athena:GetWorkGroup",
                ],
                resources=[
                    f"arn:aws:athena:{self.region}:{self.account}:workgroup/primary"
                ],
            )
        )

        # ------------------------------------------------------------------
        # CloudWatch Logs — standard Glue convention.
        # ------------------------------------------------------------------
        spark_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="GlueJobLogs",
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:AssociateKmsKey",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws-glue/jobs/*"
                ],
            )
        )

        # ------------------------------------------------------------------
        # KMS — lake CMK if known, else ``*`` constrained by
        # ``kms:ViaService`` (matches cms_ingest_stack:443-460).
        # ------------------------------------------------------------------
        if lake_kms_key_arn:
            spark_etl_role.add_to_policy(
                iam.PolicyStatement(
                    sid="KmsForLakeKey",
                    actions=[
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:GenerateDataKey",
                        "kms:GenerateDataKeyWithoutPlaintext",
                        "kms:DescribeKey",
                        "kms:ReEncryptFrom",
                        "kms:ReEncryptTo",
                    ],
                    resources=[lake_kms_key_arn],
                )
            )
        else:
            spark_etl_role.add_to_policy(
                iam.PolicyStatement(
                    sid="KmsViaServiceConstraint",
                    actions=[
                        "kms:Encrypt",
                        "kms:Decrypt",
                        "kms:GenerateDataKey",
                        "kms:GenerateDataKeyWithoutPlaintext",
                        "kms:DescribeKey",
                        "kms:ReEncryptFrom",
                        "kms:ReEncryptTo",
                    ],
                    resources=["*"],
                    conditions={
                        "StringEquals": {
                            "kms:ViaService": [
                                f"s3.{self.region}.amazonaws.com",
                                f"glue.{self.region}.amazonaws.com",
                            ]
                        }
                    },
                )
            )

        self.spark_etl_role = spark_etl_role

        # CloudFormation export so other stacks / operator scripts can
        # resolve the ARN by export name.
        self.spark_etl_role_arn_export = CfnOutput(
            self,
            "SparkEtlRoleArn",
            value=spark_etl_role.role_arn,
            export_name=_stage_name(stage, "spark-etl-role-arn"),
            description=(
                "Persistent IAM role for Glue 4.0 PySpark generators. "
                "Used by `scripts/run-pyspark-products.py`."
            ),
        )

        # ------------------------------------------------------------------
        # cdk-nag suppressions — documented per finding, NOT raw-suppressed.
        # ------------------------------------------------------------------
        NagSuppressions.add_resource_suppressions(
            spark_etl_role,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWS-managed AWSGlueServiceRole is the canonical baseline "
                        "for Glue ETL roles. It provides the standard CloudWatch "
                        "log perms + asset-bucket reads that every Glue 4.0 job "
                        "needs. Same pattern as cms_ingest_stack.py's "
                        "GlueMergeJobRole."
                    ),
                    "applies_to": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSGlueServiceRole"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Wildcard scoped: (1) S3 object-level wildcards are "
                        "narrowed to specific lake-bucket prefixes "
                        "(curated/<2 products>/*, scripts/*, tmp/*, "
                        "athena-results/*); (2) Glue Catalog wildcards are "
                        "narrowed to exactly the 2 target databases' tables "
                        "(adp_{stage}_vehicle_telemetry_aggregated/*, "
                        "adp_{stage}_energy_usage/*) — no catalog-wide grants; "
                        "(3) CloudWatch logs wildcard is the AWS-recommended "
                        "/aws-glue/jobs/* group prefix; (4) KMS wildcard is "
                        "constrained by kms:ViaService for s3 + glue only "
                        "when lake_kms_key_arn is not provided. No "
                        "iam:PassRole. Matches cms_ingest_stack.py:443-460 "
                        "pattern."
                    ),
                },
            ],
            apply_to_children=True,
        )
