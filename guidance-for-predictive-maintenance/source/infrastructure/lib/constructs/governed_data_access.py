# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""
GovernedDataAccessConstruct
===========================
Provisions the IAM Glue-ETL role that allows the PM pipeline to read the
three governed platform-foundation data products:

  * ``tire_health``
  * ``vehicle_telemetry_aggregated``
  * ``service_records``

Access is via **DataZone consumer-project subscription → Lake Formation
auto-grant**, following decision (f) in decisions.md.

Governance mechanism chosen — DataZone subscription (NOT direct
``s3:GetObject``):
  - Matches the CVX cross-account precedent documented in
    ``docs/cvx-integration-contract.md`` §2/§3.
  - PM is same-account, so no cross-account LF resource share is needed;
    DataZone still issues the LF grant and provides data-lineage tracking.
  - The IAM role below holds ``lakeformation:GetDataAccess`` and the
    Glue/Athena actions listed in cvx-integration-contract.md §2.1.
  - Hard ``s3:GetObject`` on the lake bucket is explicitly ABSENT — the
    role relies on LF-vended short-lived credentials per the LF data-access
    model (iam.PolicyDocument has NO ``s3:GetObject`` on the lake ARN).

Role name pattern follows ``adp-{stage}-foundation-spark-etl-role-{region}``
(region-suffixed per cross-region-namespace.md Check 1 — IAM is
account-wide scope).  PM's role is named
  ``adp-{stage}-pm-governed-etl-role-{region}``

All IAM actions are scoped to the minimum needed:
  * ``glue:GetDatabase`` / ``GetTable`` / ``GetTables`` / ``GetPartitions`` —
    read-only catalog access, scoped to the 3 target databases.
  * ``athena:StartQueryExecution`` / GetQueryExecution / GetQueryResults /
    StopQueryExecution / GetWorkGroup — scoped to the PM workgroup ARN.
  * ``lakeformation:GetDataAccess`` — required by LF to vend S3 credentials.
  * KMS ``Decrypt`` / ``DescribeKey`` — for the lake CMK (via ViaService
    constraint when the key ARN is not known at synth time).
  * S3 write on the PM training / inference buckets only.
  * CloudWatch Logs write on the standard Glue log group prefix.
  * DataZone subscription lifecycle actions scoped to the foundation domain
    (domain ID resolved via CloudFormation import of
    ``adp-{stage}-foundation-datazone-domain-id``).

NO ``s3:GetObject`` on the lake bucket ARN — LF handles that through
its credential-vending path.
"""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Fn,
    Stack,
)
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from cdk_nag import NagSuppressions
from constructs import Construct


# Products PM subscribes to and reads.
_PM_SUBSCRIBED_PRODUCTS: tuple[str, ...] = (
    "tire_health",
    "vehicle_telemetry_aggregated",
    "service_records",
)


class GovernedDataAccessConstruct(Construct):
    """IAM role + DataZone subscription permissions for PM governed read path.

    Parameters
    ----------
    scope / id:
        Standard CDK parent/id.
    stage:
        Deployment stage (``staging`` | ``prod``).  Used to resolve the
        CFN export ``adp-{stage}-foundation-datazone-domain-id`` and to
        name IAM resources per cross-region-namespace discipline.
    training_data_bucket:
        The PM-side ``training_data_bucket``; the ETL role may write here.
    inference_data_bucket:
        The PM-side ``inference_data_bucket``; the ETL role may write here.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        stage: str,
        training_data_bucket: s3.Bucket,
        inference_data_bucket: s3.Bucket,
    ) -> None:
        super().__init__(scope, id)

        stack = Stack.of(self)
        region = stack.region
        account = stack.account

        # ------------------------------------------------------------------
        # Foundation export names (same pattern used by platform-foundation
        # stacks — see foundation_stack.py CfnOutput export_name values).
        # ------------------------------------------------------------------
        foundation_prefix = f"adp-{stage}-foundation"
        domain_id = Fn.import_value(f"{foundation_prefix}-datazone-domain-id")
        domain_arn = f"arn:aws:datazone:{region}:{account}:domain/{domain_id}"

        # ------------------------------------------------------------------
        # Athena workgroup for cost attribution — PM gets its own workgroup
        # name (per tech.md §3.6).  The workgroup itself is NOT managed by
        # this construct (operator creates it; here we only reference the
        # ARN for IAM scoping).
        # ------------------------------------------------------------------
        pm_workgroup_name = f"pm-{stage}-analytics"
        pm_workgroup_arn = (
            f"arn:aws:athena:{region}:{account}:workgroup/{pm_workgroup_name}"
        )

        # ------------------------------------------------------------------
        # Glue catalog ARNs — scoped to the 3 subscribed databases only.
        # ------------------------------------------------------------------
        catalog_arn = f"arn:aws:glue:{region}:{account}:catalog"
        target_dbs = [
            f"adp_{stage}_{product}" for product in _PM_SUBSCRIBED_PRODUCTS
        ]
        glue_db_arns = [
            f"arn:aws:glue:{region}:{account}:database/{db}" for db in target_dbs
        ]
        glue_table_arns = [
            f"arn:aws:glue:{region}:{account}:table/{db}/*" for db in target_dbs
        ]

        # ------------------------------------------------------------------
        # PM training / inference bucket ARNs (write targets only).
        # ------------------------------------------------------------------
        training_bucket_arn = training_data_bucket.bucket_arn
        inference_bucket_arn = inference_data_bucket.bucket_arn

        # ------------------------------------------------------------------
        # Role name — region-suffixed (account-wide IAM namespace).
        # Pattern: adp-{stage}-pm-governed-etl-role-{region}
        # Length check: len("adp-staging-pm-governed-etl-role-ap-northeast-1") = 47 ≤ 64 ✓
        # ------------------------------------------------------------------
        role_name = f"adp-{stage}-pm-governed-etl-role-{region}"

        self.glue_etl_role = iam.Role(
            self,
            "PmGovernedEtlRole",
            role_name=role_name,
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            description=(
                f"PM governed ETL role — reads tire_health, "
                f"vehicle_telemetry_aggregated, service_records via "
                f"Lake Formation; writes to PM training/inference buckets. "
                f"Stage={stage}. No direct s3:GetObject on lake bucket."
            ),
        )

        # Baseline Glue service role — standard CloudWatch + asset reads.
        self.glue_etl_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSGlueServiceRole"
            )
        )

        # ------------------------------------------------------------------
        # Glue Catalog — read-only, scoped to the 3 subscribed databases.
        # No catalog-wide wildcard, no writes to the foundation catalog.
        # ------------------------------------------------------------------
        self.glue_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="GlueCatalogReadScoped",
                actions=[
                    "glue:GetDatabase",
                    "glue:GetDatabases",
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                    "glue:BatchGetPartition",
                ],
                resources=[catalog_arn] + glue_db_arns + glue_table_arns,
            )
        )

        # ------------------------------------------------------------------
        # Athena — scoped to PM workgroup only.
        # Athena results bucket is the PM training bucket (re-uses it for
        # Athena spill; operator may set a dedicated bucket later).
        # ------------------------------------------------------------------
        self.glue_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="AthenaWorkgroupScoped",
                actions=[
                    "athena:StartQueryExecution",
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                    "athena:StopQueryExecution",
                    "athena:GetWorkGroup",
                ],
                resources=[pm_workgroup_arn],
            )
        )

        # ------------------------------------------------------------------
        # Lake Formation — GetDataAccess is REQUIRED for LF to vend the
        # short-lived S3 credentials on behalf of the Glue/Athena role.
        # Resource "*" is unavoidable (LF does not support resource-scoped
        # GetDataAccess calls; the security boundary is the LF grant itself).
        # ------------------------------------------------------------------
        self.glue_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="LakeFormationGetDataAccess",
                actions=["lakeformation:GetDataAccess"],
                resources=["*"],
            )
        )

        # ------------------------------------------------------------------
        # S3 write — PM training + inference buckets ONLY.
        # No s3:GetObject on the lake bucket ARN (LF vends those credentials
        # separately; hard-binding s3:GetObject on the lake bypasses LF
        # row/column filters — anti-pattern per tech.md §3.1).
        # ------------------------------------------------------------------
        self.glue_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="PmBucketWrite",
                actions=[
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                    "s3:ListBucket",
                ],
                resources=[
                    training_bucket_arn,
                    f"{training_bucket_arn}/*",
                    inference_bucket_arn,
                    f"{inference_bucket_arn}/*",
                ],
            )
        )

        # ------------------------------------------------------------------
        # DataZone — subscription lifecycle actions on the foundation domain.
        # Resource scoped to the domain ARN (uses Fn.import_value token;
        # CDK resolves this as a Ref/ImportValue at synth time so the ARN
        # string contains a CFN intrinsic — this is correct and expected).
        # ------------------------------------------------------------------
        self.glue_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="DataZoneSubscriptionLifecycle",
                actions=[
                    "datazone:ListDomains",
                    "datazone:GetDomain",
                    "datazone:ListProjects",
                    "datazone:GetProject",
                    "datazone:SearchListings",
                    "datazone:GetListing",
                    "datazone:CreateSubscriptionRequest",
                    "datazone:GetSubscriptionRequest",
                    "datazone:ListSubscriptionRequests",
                    "datazone:ListSubscriptionGrants",
                    "datazone:GetSubscriptionGrant",
                ],
                resources=[domain_arn],
            )
        )

        # ------------------------------------------------------------------
        # CloudWatch Logs — standard Glue log group prefix.
        # ------------------------------------------------------------------
        self.glue_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="GlueJobLogs",
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:AssociateKmsKey",
                ],
                resources=[
                    f"arn:aws:logs:{region}:{account}:log-group:/aws-glue/jobs/*"
                ],
            )
        )

        # ------------------------------------------------------------------
        # KMS — via-service constraint so we don't hardcode the lake CMK ARN
        # at synth time (foundation may not be deployed yet in some CI paths).
        # Same pattern as data_products_stack.py lines 258-275.
        # ------------------------------------------------------------------
        self.glue_etl_role.add_to_policy(
            iam.PolicyStatement(
                sid="KmsViaServiceConstraint",
                actions=[
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
                            f"s3.{region}.amazonaws.com",
                            f"glue.{region}.amazonaws.com",
                            f"lakeformation.{region}.amazonaws.com",
                        ]
                    }
                },
            )
        )

        # ------------------------------------------------------------------
        # Expose the DataZone domain ID import for downstream use (e.g. by
        # the operator subscription script).
        # ------------------------------------------------------------------
        self.foundation_domain_id = domain_id
        self.pm_workgroup_name = pm_workgroup_name

        # ------------------------------------------------------------------
        # cdk-nag suppressions — documented, not raw-suppressed.
        #
        # apply_to_children=True is required because add_to_policy() places
        # inline policies on the Role's auto-generated DefaultPolicy child
        # resource; without it the suppressions apply only to the Role L1
        # resource itself and the DefaultPolicy findings remain unsuppressed.
        # ------------------------------------------------------------------
        NagSuppressions.add_resource_suppressions(
            self.glue_etl_role,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWS-managed AWSGlueServiceRole is the canonical baseline "
                        "for Glue ETL roles (same pattern as "
                        "data_products_stack.py SparkEtlRole). It provides the "
                        "standard CloudWatch log perms + asset-bucket reads that "
                        "every Glue 4.0 job needs."
                    ),
                    "applies_to": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSGlueServiceRole"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Four scoped wildcards in the PM governed ETL role: "
                        "(1) lakeformation:GetDataAccess on '*' — LF does not "
                        "support resource-level scoping for this action; the "
                        "security boundary is the LF grant itself "
                        "(https://docs.aws.amazon.com/lake-formation/latest/dg/access-control-underlying-data.html). "
                        "(2) KMS on '*' constrained by kms:ViaService to "
                        "s3/glue/lakeformation in this region — hardcoding the "
                        "lake CMK ARN at PM synth time creates an unresolvable "
                        "cross-stack dependency. "
                        "(3) Glue table ARNs include '/*' — minimum needed for "
                        "all tables within the 3 subscribed databases; individual "
                        "table names are not knowable at synth time. "
                        "(4) CloudWatch Logs '/aws-glue/jobs/*' — standard Glue "
                        "log group prefix; narrowing to a single job name is not "
                        "possible because the CfnJob name is a CFN ref at synth time. "
                        "(5) PM training/inference bucket '/*' — required for "
                        "Parquet multi-part write (PutObject + AbortMultipartUpload "
                        "+ DeleteObject on individual keys, which are not known "
                        "at synth time)."
                    ),
                },
            ],
            apply_to_children=True,
        )
