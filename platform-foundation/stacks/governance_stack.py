"""ADP foundation governance stack — Lake Formation, Macie job orchestration, CloudTrail, IAM IDC.

Layers governance over the lake bucket and Glue catalog without
re-deploying them. Deploys per-stage; staging and prod each get their
own trail, IDC groups, and Macie classification job (the account-
singular ``Macie::Session`` lives in ``adp-shared-bootstrap`` per
design §3 / task A1).

Resources (per stage)
---------------------
- Lake Formation tag (LF-tag) ``adp-classification`` with values
  ``[PII, non-PII]`` — the LF-tag *key* stays unprefixed per design
  §2 constraint (tag scope is implicit per stage's catalog).
- Macie classification job (created post-deploy by
  ``scripts/macie-create-job.sh``) scoped to PII-bearing products
  only. Per spec, ``vehicle_telemetry_aggregated`` and
  ``energy_usage`` are excluded (no PII columns and high row counts
  → expensive scans). ``dimensions/`` is also excluded.

  The account-level ``Macie::Session`` itself is owned by the
  ``adp-shared-bootstrap`` stack (see
  ``stacks/shared_bootstrap_stack.py``) — it is account-singular and
  cannot live in a per-stage stack.
- CloudTrail trail ``adp-{stage}-foundation-lake-trail`` with data
  events on the lake bucket. The trail log bucket is separate from
  both the lake and the lake-logs bucket, encrypted with a per-stage
  KMS CMK (``alias/adp-{stage}-foundation-trail``). Advanced event
  selector for ``AWS::Bedrock::KnowledgeBase`` data events is added
  via L1 escape hatch (T2.3 — spec 2026-06-09-adp-kb-cross-account-grants).
- IAM Identity Center groups: ``adp-{stage}-data-owners``,
  ``adp-{stage}-data-consumers``, ``adp-{stage}-platform-admins``.
  These are the groups DataZone subscriptions and Lake Formation
  grants will reference. Created only if ``identity_store_id`` is
  supplied (defaults to the auto-discovered store ID for this
  account).
- Lake Formation cross-account share (optional, T2.2 —
  spec 2026-06-09-adp-kb-cross-account-grants): when ``cvx_account_id``
  is supplied (via ``cvxAccountId`` CDK context or
  ``ADP_KB_CVX_ACCOUNT_ID`` env var), bootstraps LF management and
  grants SELECT+DESCRIBE on all in-scope ``adp_{stage}_*`` databases
  to the CVX account root principal via database-wildcard shares (LF v4).
"""

from __future__ import annotations

import os
from typing import Optional

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_cloudtrail as cloudtrail
from aws_cdk import aws_iam as iam
from aws_cdk import aws_identitystore as identitystore
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lakeformation as lakeformation
from aws_cdk import aws_s3 as s3
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks._naming import _stage_db_name, _stage_group_name, _stage_name, validate_stage


# Per-account IDC IdentityStore ID. The value is account-level and
# stage-independent, but it is also account-specific — so the source
# default is a placeholder. Operators MUST override at deploy time via
# CDK context:
#     cdk deploy -c identity_store_id=d-XXXXXXXXXX ...
# or via cdk.json / cdk.context.json. The placeholder is intentionally
# non-routable so a missing override fails fast at deploy rather than
# silently targeting another account's identity store.
_DEFAULT_IDENTITY_STORE_ID = "d-XXXXXXXXXX"


# Macie excluded prefixes (high-row, non-PII surfaces — keep scan cost down).
MACIE_EXCLUDED_PREFIXES: list[str] = [
    "dimensions/",
    "curated/vehicle_telemetry_aggregated/",
    "curated/energy_usage/",
    "knowledge/",  # KB artifacts handled via Bedrock KB ingestion
]


class GovernanceStack(Stack):
    """Lake Formation + Macie job orchestration + CloudTrail + IAM Identity Center groups."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        lake_bucket_arn_export: str,
        lake_bucket_name: str,
        identity_center_instance_arn: Optional[str] = None,
        identity_store_id: Optional[str] = None,
        cvx_account_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        validate_stage(stage)
        self.stage = stage

        idc_arn = identity_center_instance_arn  # currently unused at this layer
        idc_store = identity_store_id or _DEFAULT_IDENTITY_STORE_ID

        # --- Lake Formation tag --------------------------------------------
        # Tag *key* stays unprefixed (per design §2 A2 constraint); tag
        # scope is implicit per stage's catalog/domain context.
        self.lf_tag = lakeformation.CfnTag(
            self,
            "LfTagClassification",
            tag_key="adp-classification",
            tag_values=["PII", "non-PII"],
        )

        # --- CloudTrail data-event trail on the lake bucket ----------------
        # Separate bucket (cannot use the lake itself for its own audit).
        trail_logs_bucket_name = (
            f"{_stage_name(stage, 'trail-logs')}-{self.account}-{self.region}"
        )
        trail_logs_bucket = s3.Bucket(
            self,
            "TrailLogsBucket",
            bucket_name=trail_logs_bucket_name,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=False,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-old-trail",
                    enabled=True,
                    expiration=Duration.days(365),
                )
            ],
        )

        trail_kms = kms.Key(
            self,
            "TrailKey",
            description=f"ADP {stage} foundation CloudTrail encryption key",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
            alias=f"alias/{_stage_name(stage, 'trail')}",
        )

        # CloudTrail service principal grants on the trail KMS key.
        # The CDK ``cloudtrail.Trail`` construct does NOT auto-inject these
        # statements when an external KMS key is supplied. Without them,
        # ``CreateTrail`` fails with "Insufficient permissions to access
        # ... KMS key". The required statements come from
        # https://docs.aws.amazon.com/awscloudtrail/latest/userguide/create-kms-key-policy-for-cloudtrail.html
        # and use the ``aws:SourceArn`` condition (security best practice)
        # to restrict the key to this specific (per-stage) trail.
        trail_name = _stage_name(stage, "lake-trail")
        _trail_arn_pattern = (
            f"arn:aws:cloudtrail:{self.region}:{self.account}:trail/{trail_name}"
        )
        trail_kms.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowCloudTrailEncryptLogs",
                actions=["kms:GenerateDataKey*"],
                principals=[iam.ServicePrincipal("cloudtrail.amazonaws.com")],
                resources=["*"],
                conditions={
                    "StringEquals": {"aws:SourceArn": _trail_arn_pattern},
                    "StringLike": {
                        "kms:EncryptionContext:aws:cloudtrail:arn": (
                            f"arn:aws:cloudtrail:*:{self.account}:trail/*"
                        )
                    },
                },
            )
        )
        trail_kms.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowCloudTrailDescribeKey",
                actions=["kms:DescribeKey"],
                principals=[iam.ServicePrincipal("cloudtrail.amazonaws.com")],
                resources=["*"],
                conditions={
                    "StringEquals": {"aws:SourceArn": _trail_arn_pattern},
                },
            )
        )
        # Allow account principals (e.g., trail-log readers, CloudTrail
        # console viewers) to decrypt log files. Restricted via SourceArn so
        # only requests originating from our own trail can decrypt.
        trail_kms.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowPrincipalsDecryptTrailLogs",
                actions=["kms:Decrypt", "kms:ReEncryptFrom"],
                principals=[iam.AccountRootPrincipal()],
                resources=["*"],
                conditions={
                    "StringEquals": {"kms:CallerAccount": self.account},
                    "StringLike": {
                        "kms:EncryptionContext:aws:cloudtrail:arn": (
                            f"arn:aws:cloudtrail:*:{self.account}:trail/*"
                        )
                    },
                },
            )
        )

        self.trail = cloudtrail.Trail(
            self,
            "LakeTrail",
            trail_name=trail_name,
            bucket=trail_logs_bucket,
            encryption_key=trail_kms,
            include_global_service_events=False,
            is_multi_region_trail=False,
            enable_file_validation=True,
            send_to_cloud_watch_logs=False,
        )
        # T2.3 fix (review cycle 2) — CloudTrail advanced_event_selectors and
        # event_selectors are mutually exclusive on a single trail; the previous
        # implementation called ``add_s3_event_selector`` (legacy event_selectors
        # API) AND assigned ``cfn_trail.advanced_event_selectors``, which would
        # have caused CloudFormation to reject the trail OR one selector to
        # silently overwrite the other. Both selectors are now expressed as
        # AdvancedEventSelectorProperty entries in a single
        # ``advanced_event_selectors`` array, replacing the
        # ``add_s3_event_selector`` call entirely.
        cfn_trail = self.trail.node.default_child  # type: cloudtrail.CfnTrail
        bedrock_kb_arn_prefix = (
            f"arn:aws:bedrock:{self.region}:{self.account}:knowledge-base/"
        )
        lake_bucket_arn_prefix = f"{lake_bucket_arn_export}/"
        cfn_trail.advanced_event_selectors = [
            # Lake bucket S3 data events (preserves read-write coverage that the
            # legacy add_s3_event_selector previously configured).
            cloudtrail.CfnTrail.AdvancedEventSelectorProperty(
                name="LakeBucketS3DataEvents",
                field_selectors=[
                    cloudtrail.CfnTrail.AdvancedFieldSelectorProperty(
                        field="eventCategory",
                        equal_to=["Data"],
                    ),
                    cloudtrail.CfnTrail.AdvancedFieldSelectorProperty(
                        field="resources.type",
                        equal_to=["AWS::S3::Object"],
                    ),
                    cloudtrail.CfnTrail.AdvancedFieldSelectorProperty(
                        field="resources.ARN",
                        starts_with=[lake_bucket_arn_prefix],
                    ),
                ],
            ),
            # Bedrock KnowledgeBase data events (T2.3 — CVX cross-account audit).
            cloudtrail.CfnTrail.AdvancedEventSelectorProperty(
                name="BedrockKnowledgeBaseDataEvents",
                field_selectors=[
                    cloudtrail.CfnTrail.AdvancedFieldSelectorProperty(
                        field="eventCategory",
                        equal_to=["Data"],
                    ),
                    cloudtrail.CfnTrail.AdvancedFieldSelectorProperty(
                        field="resources.type",
                        equal_to=["AWS::Bedrock::KnowledgeBase"],
                    ),
                    cloudtrail.CfnTrail.AdvancedFieldSelectorProperty(
                        field="resources.ARN",
                        starts_with=[bedrock_kb_arn_prefix],
                    ),
                ],
            ),
        ]
        # Defensive: the L2 Trail construct emits an empty ``EventSelectors: []``
        # by default. CFN docs state advanced_event_selectors and event_selectors
        # are mutually exclusive; an empty array is normally treated as unset,
        # but force-omit the property to remove all ambiguity at deploy time.
        cfn_trail.add_property_deletion_override("EventSelectors")

        # T2.2 — Lake Formation bootstrap + CVX cross-account share (Option Y).
        # Only wired when cvx_account_id is supplied (backward-compatible default=None).
        if cvx_account_id:
            self._bootstrap_lake_formation(lake_bucket_name)
            self._grant_cvx_cross_account_share(cvx_account_id)

        # --- Macie classification job (post-deploy, script-driven) --------
        # CloudFormation has NO ``AWS::Macie::ClassificationJob`` resource,
        # and the account-level ``Macie::Session`` resource is owned by the
        # ``adp-shared-bootstrap`` stack (account-singular — see
        # ``stacks/shared_bootstrap_stack.py``). The per-bucket scheduled
        # classification job for this stage's lake bucket is created
        # post-deploy via ``platform-foundation/scripts/macie-create-job.sh``.
        # The script is invoked automatically by the deploy runbook and is
        # idempotent (skips if a job with the same name already exists).
        # ``MACIE_EXCLUDED_PREFIXES`` (below as a CfnOutput) drives the
        # script's ``--excludes`` argument.

        # --- IAM Identity Center groups ------------------------------------
        if idc_store:
            self.group_data_owners = identitystore.CfnGroup(
                self,
                "GroupDataOwners",
                identity_store_id=idc_store,
                display_name=_stage_group_name(stage, "data-owners"),
                description=(
                    f"Owners of ADP foundation data products (stage={stage}). "
                    "Manage subscriptions and Lake Formation grants."
                ),
            )
            self.group_data_consumers = identitystore.CfnGroup(
                self,
                "GroupDataConsumers",
                identity_store_id=idc_store,
                display_name=_stage_group_name(stage, "data-consumers"),
                description=(
                    f"Subscribers to ADP foundation data products (stage={stage}). "
                    "Read-only access via DataZone subscription."
                ),
            )
            self.group_platform_admins = identitystore.CfnGroup(
                self,
                "GroupPlatformAdmins",
                identity_store_id=idc_store,
                display_name=_stage_group_name(stage, "platform-admins"),
                description=(
                    f"ADP foundation platform admins (stage={stage}). "
                    "Manage stacks and infrastructure."
                ),
            )
            CfnOutput(
                self,
                "GroupDataOwnersId",
                value=self.group_data_owners.attr_group_id,
                export_name=_stage_name(stage, "group-data-owners-id"),
            )
            CfnOutput(
                self,
                "GroupDataConsumersId",
                value=self.group_data_consumers.attr_group_id,
                export_name=_stage_name(stage, "group-data-consumers-id"),
            )
            CfnOutput(
                self,
                "GroupPlatformAdminsId",
                value=self.group_platform_admins.attr_group_id,
                export_name=_stage_name(stage, "group-platform-admins-id"),
            )

        # Outputs (stage-prefixed export names per design §2.11)
        CfnOutput(
            self,
            "TrailArn",
            value=self.trail.trail_arn,
            export_name=_stage_name(stage, "trail-arn"),
        )
        CfnOutput(
            self,
            "MacieExcludedPrefixes",
            value=",".join(MACIE_EXCLUDED_PREFIXES),
            export_name=_stage_name(stage, "macie-excluded-prefixes"),
        )

        # cdk-nag suppressions
        NagSuppressions.add_resource_suppressions(
            trail_logs_bucket,
            [
                {
                    "id": "AwsSolutions-S1",
                    "reason": (
                        "CloudTrail logs bucket; recursive logging is intentionally "
                        "absent. AWS pattern: use a separate access-log bucket "
                        f"(adp-{stage}-foundation-lake-logs-* in foundation_stack.py)."
                    ),
                },
            ],
        )

    # --- Lake Formation helpers (T2.2 — Option Y) --------------------------

    def _bootstrap_lake_formation(self, lake_bucket_name: str) -> None:
        """Register the foundation lake bucket as an LF resource and configure LF v4.

        Idempotent: LF tolerates re-registration of an already-registered resource.
        Preserves existing data-lake admins by appending the CFN execution role.
        """
        lake_bucket_arn = f"arn:aws:s3:::{lake_bucket_name}"

        # Register lake bucket as LF-managed resource (SLR handles permissions).
        lakeformation.CfnResource(
            self,
            "LfLakeBucketResource",
            resource_arn=lake_bucket_arn,
            use_service_linked_role=True,
        )

        # CfnDataLakeSettings INTENTIONALLY OMITTED (security-review cycle 1).
        # AWS Lake Formation `PutDataLakeSettings` REPLACES the entire settings
        # object — it does not append. The previous implementation that set
        # `admins=[cfn_exec_role_arn]` would have silently dropped existing
        # admins on deploy (per decisions.md Q6 audit: the data-lake admin IAM
        # user + CDK exec role). LF settings are account-singleton and don't fit
        # the per-stack CDK lifecycle.
        #
        # Required manual prerequisite (one-time per account, before first
        # `cdk deploy` of this stack with `cvxAccountId` set):
        #
        #   aws lakeformation put-data-lake-settings --region us-east-1 \\
        #     --data-lake-settings '{
        #       "DataLakeAdmins": [<existing-admins-from-get-data-lake-settings>],
        #       "AllowExternalDataFiltering": true,
        #       "Parameters": {"CROSS_ACCOUNT_VERSION": "4"}
        #     }'
        #
        # See docs/cvx-integration-contract.md § "Cross-account grants for
        # CVX" → "Manual prerequisite" for the full runbook.

    # In-scope databases for CVX cross-account share (per spec + decisions.md Option Y).
    _CVX_SHARE_DATABASES = [
        "vehicle_identity",
        "service_records",
        "charging_sessions",
        "customer_360",
        "customer_interactions",
        "ota_campaigns",
    ]

    def _grant_cvx_cross_account_share(self, cvx_account_id: str) -> None:
        """Issue per-database wildcard SELECT+DESCRIBE grants to the CVX account root.

        One CfnPrincipalPermissions per database; table_wildcard covers all
        current and future tables in each database (including PySpark-gated ones
        per decisions.md Option Y).
        """
        cvx_principal = f"arn:aws:iam::{cvx_account_id}:root"
        for db_product in self._CVX_SHARE_DATABASES:
            db_name = _stage_db_name(self.stage, db_product)
            lakeformation.CfnPrincipalPermissions(
                self,
                f"LfCvxGrant{db_product.replace('_', '').title()}",
                principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
                    data_lake_principal_identifier=cvx_principal,
                ),
                resource=lakeformation.CfnPrincipalPermissions.ResourceProperty(
                    table=lakeformation.CfnPrincipalPermissions.TableResourceProperty(
                        catalog_id=self.account,
                        database_name=db_name,
                        table_wildcard={},  # ALL_TABLES wildcard
                    ),
                ),
                permissions=["SELECT", "DESCRIBE"],
                permissions_with_grant_option=[],
            )
