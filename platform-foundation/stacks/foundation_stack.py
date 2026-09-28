"""ADP foundation lake stack — S3 lake bucket + Glue catalog.

Creates the canonical lake bucket and the eleven Glue databases that
own the data products and the dimension catalog. Iceberg tables
themselves are created by the Group 3 generators (using the schema
loader's DDL output executed via Athena Engine V3); this stack just
provides the buckets, KMS key, and database namespaces.

Per ``staging-prod-design.md``, this stack is per-stage: staging and
prod each deploy their own copy. Resource names are stage-prefixed
via ``stacks._naming._stage_name`` and ``_stage_db_name``.

Resources (per stage)
---------------------
- KMS CMK with key rotation, alias ``alias/adp-{stage}-foundation-lake``,
  scoped to the lake bucket.
- S3 bucket ``adp-{stage}-foundation-lake-<account>-<region>`` with:
  - SSE-KMS using the CMK
  - PublicAccessBlock = block all
  - VersioningEnabled = true
  - Server access logs delivered to a separate logs bucket
  - Lifecycle: noncurrent versions to GLACIER after 90 days, expire after 1 year
- ``adp-{stage}-foundation-lake-logs-<account>-<region>`` log bucket
  (S3-managed encryption, per AWS recommendation since KMS-encrypted
  log delivery is not supported).
- 11 Glue databases:
  - ``adp_{stage}_dimensions`` — shared dimension catalog
  - ``adp_{stage}_<product>`` × 10 — one per data product

The bucket name and ARN are exported via CfnOutput (with stage-
prefixed export names per design §2.11) so downstream stacks
(DataZone, Governance) consume them via Fn::ImportValue rather than
direct cross-stack refs (avoids tight coupling).
"""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks._naming import _stage_db_name, _stage_name, validate_stage


# Per spec.md "Data product catalog" — keep this list as the single
# source of truth for catalog DB suffixes. The schema loader generates
# the per-product suffix from the schema YAML; the stage prefix is
# composed via :func:`_stage_db_name` at synth time.
#
# Entries are ``(product_suffix, description)``. The Glue database
# name is ``adp_{stage}_{product_suffix}``.
DATA_PRODUCT_DATABASES: list[tuple[str, str]] = [
    ("dimensions", "Shared dimension catalog (vins, customers, dealers, suppliers, parts, time_calendar, charging_stations)"),
    ("vehicle_telemetry_aggregated", "Per-VIN time-windowed aggregate telemetry rollups (rolling 90 days)"),
    ("vehicle_identity", "Vehicle Identity Graph — VIN → make/model/trim/build → suppliers/parts"),
    ("charging_sessions", "EV charging sessions (home + public DC fast + destination L2)"),
    ("energy_usage", "Per-VIN per-day battery and energy metrics (90-day window)"),
    ("ota_campaigns", "Software OTA campaigns and per-VIN dispatch events"),
    ("customer_360", "Customer profile snapshots with health and churn scores"),
    ("customer_interactions", "Customer interactions across dealer/service/app/web/call channels"),
    ("service_records", "Service records joining VIN, customer, dealer, parts"),
    ("tire_health", "Per-VIN per-tire daily telemetry with wear labels (tread/pressure/temp + needs_replacement + wear_category)"),
    ("vehicle_knowledge_base", "Knowledge artifacts seeded into Bedrock KB (DTC guides, TSBs, manuals, etc.)"),
]


class FoundationStack(Stack):
    """S3 lake bucket + KMS CMK + 11 Glue databases (per-stage)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        validate_stage(stage)
        self.stage = stage

        # KMS CMK for lake bucket SSE-KMS
        self.kms_key = kms.Key(
            self,
            "LakeKey",
            description=f"ADP {stage} foundation lake encryption key",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,  # encrypted data outlives stack delete
            alias=f"alias/{_stage_name(stage, 'lake')}",
        )

        # Lake Formation must be able to WRITE encrypted objects, not just read
        # them. Reading needs kms:Decrypt; writing needs kms:GenerateDataKey.
        #
        # This grant is declared here rather than applied by hand because the key
        # policy is CDK-managed: a manual `aws kms put-key-policy` is drift, and
        # the next template change touching LakeKey (most plausibly a grant_* for
        # a new consumer) would regenerate the policy and silently drop it —
        # restoring a blocker that presents as PERMISSION_DENIED on
        # kms:GenerateDataKey deep inside an Athena INSERT.
        #
        # The gap was invisible until 2026-09-20 because every prior ADP
        # interaction with this lake was a read; the Iceberg conversion
        # (spec 2026-09-19-adp-curated-products-vin-scope-pruning, Group 4) was
        # the first write through Athena. See
        # issues/2026-09-20-group4-three-stacked-blockers/ and D18.
        #
        # Scope note: the grantee is the account-wide Lake Formation
        # service-linked role and this statement carries no kms:ViaService
        # condition, so it is not narrowed to this lake. That matches AWS's
        # documented "register the LF role as a KMS key user" pattern; tightening
        # it is tracked as a follow-on.
        self.kms_key.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowLakeFormationDataAccessRoleEncryptDecrypt",
                effect=iam.Effect.ALLOW,
                principals=[
                    iam.ArnPrincipal(
                        f"arn:aws:iam::{self.account}:role/aws-service-role/"
                        "lakeformation.amazonaws.com/"
                        "AWSServiceRoleForLakeFormationDataAccess"
                    )
                ],
                actions=["kms:GenerateDataKey", "kms:Decrypt"],
                resources=["*"],  # within a key policy, "*" means this key only
            )
        )

        # Server access logs bucket (S3-managed encryption — KMS not supported for log delivery)
        logs_bucket_name = f"{_stage_name(stage, 'lake-logs')}-{self.account}-{self.region}"
        self.logs_bucket = s3.Bucket(
            self,
            "LakeLogsBucket",
            bucket_name=logs_bucket_name,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=False,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-old-logs",
                    enabled=True,
                    expiration=Duration.days(365),
                )
            ],
        )

        # Main lake bucket
        lake_bucket_name = f"{_stage_name(stage, 'lake')}-{self.account}-{self.region}"
        self.lake_bucket = s3.Bucket(
            self,
            "LakeBucket",
            bucket_name=lake_bucket_name,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.kms_key,
            bucket_key_enabled=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            server_access_logs_bucket=self.logs_bucket,
            server_access_logs_prefix="access-logs/",
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="noncurrent-to-glacier-then-expire",
                    enabled=True,
                    noncurrent_version_transitions=[
                        s3.NoncurrentVersionTransition(
                            storage_class=s3.StorageClass.GLACIER,
                            transition_after=Duration.days(90),
                        )
                    ],
                    noncurrent_version_expiration=Duration.days(365),
                ),
                s3.LifecycleRule(
                    id="abort-incomplete-mpu",
                    enabled=True,
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                ),
            ],
        )

        # 11 Glue databases (dimensions + 10 products), stage-prefixed
        self.databases: dict[str, glue.CfnDatabase] = {}
        for suffix, description in DATA_PRODUCT_DATABASES:
            db_name = _stage_db_name(stage, suffix)
            db = glue.CfnDatabase(
                self,
                f"GlueDb{_pascal(suffix)}",
                catalog_id=self.account,
                database_input=glue.CfnDatabase.DatabaseInputProperty(
                    name=db_name,
                    description=description,
                    location_uri=f"s3://{self.lake_bucket.bucket_name}/curated/{suffix}/",
                ),
            )
            self.databases[db_name] = db

        # Outputs (stage-prefixed export names per design §2.11)
        CfnOutput(
            self,
            "LakeBucketName",
            value=self.lake_bucket.bucket_name,
            export_name=_stage_name(stage, "lake-bucket-name"),
        )
        CfnOutput(
            self,
            "LakeBucketArn",
            value=self.lake_bucket.bucket_arn,
            export_name=_stage_name(stage, "lake-bucket-arn"),
        )
        CfnOutput(
            self,
            "LakeKmsKeyArn",
            value=self.kms_key.key_arn,
            export_name=_stage_name(stage, "lake-kms-key-arn"),
        )
        CfnOutput(
            self,
            "GlueDatabaseNames",
            value=",".join(_stage_db_name(stage, suffix) for suffix, _ in DATA_PRODUCT_DATABASES),
            export_name=_stage_name(stage, "glue-databases"),
        )

        # cdk-nag suppressions for the logs bucket (it doesn't itself need access logs).
        NagSuppressions.add_resource_suppressions(
            self.logs_bucket,
            [
                {
                    "id": "AwsSolutions-S1",
                    "reason": (
                        "This IS the access-logs target bucket. Recursive access-log "
                        "delivery would create a loop. AWS recommends the logs bucket "
                        "not log to itself."
                    ),
                },
                {
                    "id": "AwsSolutions-S10",
                    "reason": (
                        "enforce_ssl=True is set; this rule's check on the underlying "
                        "BucketPolicy can lag the construct's enforce_ssl flag — verified "
                        "manually that the synthesized bucket policy denies non-TLS access."
                    ),
                },
            ],
        )

    @property
    def bucket_name_export(self) -> str:
        """Public name to reference the lake bucket from other stacks."""
        return self.lake_bucket.bucket_name

    @property
    def bucket_arn_export(self) -> str:
        return self.lake_bucket.bucket_arn


def _pascal(s: str) -> str:
    """Convert ``snake_case`` → ``PascalCase`` for CDK construct ids."""
    return "".join(part.capitalize() for part in s.split("_"))
