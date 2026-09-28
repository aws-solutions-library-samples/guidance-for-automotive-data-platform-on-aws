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
  Two further consumer shares follow the same shape, each with its own
  principal and its own explicit database list:

  ===============  ==========================  =============================
  Consumer         Supplied via                Databases
  ===============  ==========================  =============================
  CVX              ``cvxAccountId`` /           six — see
                   ``ADP_KB_CVX_ACCOUNT_ID``    :attr:`GovernanceStack._CVX_SHARE_DATABASES`
  DMS              ``dmsAccountId`` /           two — see
                   ``ADP_KB_DMS_ACCOUNT_ID``    :attr:`GovernanceStack._DMS_SHARE_DATABASES`
  CMS              ``cmsAccountId`` /           five — see
                   ``ADP_CMS_ACCOUNT_ID``       :attr:`GovernanceStack._CMS_SHARE_DATABASES`
  ===============  ==========================  =============================

  The lists are intentionally NOT unioned: a consumer sees exactly the
  databases its spec names, and an addition to one share cannot widen
  another by aggregation.
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
# stage-independent, but it is also account-specific — so there is no
# code-side default that would be safe across accounts. Operators MUST
# provide it at deploy time via CDK context:
#     cdk deploy -c identity_store_id=d-<10 hex chars> ...
# or via cdk.json / cdk.context.json, or by relying on the
# ``_resolve_identity_store_id`` helper in ``app.py`` which auto-discovers
# from ``aws sso-admin list-instances`` at synth time. When no ID is
# resolvable, the governance stack SKIPS Identity Center group creation
# entirely (fail-closed, per ``2026-08-30`` governance-fix; see backlog
# row ``Governance identity-store`` P2). This replaces the historical
# ``_DEFAULT_IDENTITY_STORE_ID = "d-XXXXXXXXXX"`` placeholder that
# passed an ``or``-truthy check but was rejected by CFN's IdentityStoreId
# pattern ``^d-[0-9a-f]{10}$`` at change-set creation.


# Macie excluded prefixes (high-row, non-PII surfaces — keep scan cost down).
MACIE_EXCLUDED_PREFIXES: list[str] = [
    "dimensions/",
    "curated/vehicle_telemetry_aggregated/",
    "curated/energy_usage/",
    "knowledge/",  # KB artifacts handled via Bedrock KB ingestion
]


def _validate_role_arn(param_name: str, value: str) -> None:
    """Raise ``ValueError`` unless ``value`` looks like an IAM **role** ARN.

    Mirrors :func:`_validate_account_id`'s fail-closed posture for the same
    reason: a malformed principal synthesizes cleanly and then fails opaquely
    inside Lake Formation at deploy, so the error surfaces far from its cause.

    Deliberately not a full ARN grammar — the two realistic mis-plumbings are a
    bare role NAME (``cms-staging-ui-FleetIntelligenceRole...``, from someone
    passing the name where the ARN was wanted) and a ``:user/`` ARN. A prefix
    check plus ``:role/`` catches both. Whitespace is rejected rather than
    stripped: a padded value means the caller's plumbing is wrong, and accepting
    it hides that.

    Review finding W1, Group 5 cycle 1.
    """
    if (
        not value
        or value != value.strip()
        or not value.startswith("arn:aws:iam::")
        or ":role/" not in value
        # An empty role name: what `...:role/$ROLE_NAME` gives when the lookup
        # of ROLE_NAME printed nothing. It would point every role grant at a
        # role that doesn't exist.
        or not value.split(":role/", 1)[1].strip("/")
    ):
        raise ValueError(
            f"{param_name} must be an IAM role ARN of the form "
            f"'arn:aws:iam::<account>:role/<name>' (no surrounding whitespace); "
            f"got {value!r}. A bare role name or a ':user/' ARN synthesizes "
            f"cleanly and then fails opaquely inside Lake Formation at deploy."
        )


def _validate_account_id(param_name: str, value: str) -> None:
    """Raise ``ValueError`` unless ``value`` is exactly 12 decimal digits.

    ``str.isdigit()`` alone is not sufficient: it returns True for Unicode
    decimal forms (e.g. Arabic-Indic digits, superscripts), which would pass
    the check and then render an ARN Lake Formation rejects. ``str.isascii()``
    pins it to ASCII 0-9. Whitespace is rejected rather than stripped — a
    padded value in CDK context or an env var means the caller's plumbing is
    wrong, and silently accepting it hides that.
    """
    if not (len(value) == 12 and value.isascii() and value.isdigit()):
        raise ValueError(
            f"{param_name} must be exactly 12 ASCII digits (an AWS account id); "
            f"got {value!r}"
        )


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
        dms_account_id: Optional[str] = None,
        cms_account_id: Optional[str] = None,
        cms_consumer_role_arn: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        validate_stage(stage)
        self.stage = stage

        # Fail closed on a malformed CMS account id rather than rendering
        # `arn:aws:iam::<garbage>:root`, which synthesizes happily and then
        # fails deep inside Lake Formation at deploy with an opaque principal
        # error. Applied to the CMS share only — retrofitting the CVX and DMS
        # paths is out of Group 3's scope and is filed as a follow-on (see the
        # spec's decisions.md); the asymmetry is deliberate, not an oversight.
        if cms_account_id:
            _validate_account_id("cms_account_id", cms_account_id)
        if cms_consumer_role_arn:
            _validate_role_arn("cms_consumer_role_arn", cms_consumer_role_arn)

        idc_arn = identity_center_instance_arn  # currently unused at this layer
        idc_store = identity_store_id  # None when unresolvable; skips group creation below

        # --- Lake Formation tag --------------------------------------------
        # Tag *key* stays unprefixed (per design §2 A2 constraint). NOTE
        # (2026-07-16, ADP prod Foundation deploy): LF-tags are scoped to
        # the AWS Glue Data Catalog (account+region), NOT per-stage or
        # per-domain — there is exactly one `adp-classification` LF-tag
        # per catalog, shared by both stages, contra the "scope is implicit
        # per stage's catalog/domain context" assumption above (that
        # assumption does not hold; Lake Formation has no domain-scoping
        # concept for tags). Only the FIRST stage to deploy governance
        # (staging, 2026-05-29) creates the CfnTag; a second stage
        # attempting to create the identical tag key fails at CFN
        # early-validation with "Resource ... already exists" (confirmed
        # live during the 2026-07-16 prod deploy attempt). Guard creation
        # to stage == "staging" so prod's governance stack imports/shares
        # the existing tag rather than re-creating it. See
        # `issues/2026-07-16-adp-prod-foundation-deploy/`.
        if stage == "staging":
            self.lf_tag = lakeformation.CfnTag(
                self,
                "LfTagClassification",
                tag_key="adp-classification",
                tag_values=["PII", "non-PII"],
            )
        else:
            self.lf_tag = None

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
        # T3.4 (spec 2026-08-26-adp-dealer-domain, Group 6) extends the same
        # bootstrap to feed a DMS-side cross-account share when
        # ``dms_account_id`` is supplied. T3.2 (spec
        # 2026-09-10-cms-fleet-intelligence-adp-consumer, Group 3) extends it
        # again for CMS. The bootstrap resource is account-singular for this
        # stack (one ``LfLakeBucketResource`` L1), so run it exactly once when
        # ANY consumer account ID is set; the three grant helpers below are
        # additive and independent.
        #
        # The ``cms_account_id`` term in the bootstrap guard is load-bearing,
        # not defensive: a CMS-only deploy that skipped the bootstrap would
        # synthesize five grants over a bucket Lake Formation does not manage.
        # The grants render correctly in the console and every query still
        # fails at ``GetDataAccess`` — a silent-success shape, so it is pinned
        # by ``test_cms_only_still_bootstraps_lake_formation``.
        if cvx_account_id or dms_account_id or cms_account_id:
            self._bootstrap_lake_formation(lake_bucket_name)
        if cvx_account_id:
            self._grant_cvx_cross_account_share(cvx_account_id)
        if dms_account_id:
            self._grant_dms_cross_account_share(dms_account_id)
        if cms_account_id:
            self._grant_cms_cross_account_share(cms_account_id)
        if cms_consumer_role_arn:
            self._grant_cms_consumer_role(cms_consumer_role_arn)

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

    # In-scope databases for DMS cross-account share (T3.4 — spec
    # 2026-08-26-adp-dealer-domain, Group 6). DMS consumers read only the two
    # new dealer/parts domains registered by the accelerator; they do NOT read
    # any of the six ADP-Foundation databases exposed to CVX (spec Decision 1;
    # DMS spec § R3). Keeping the two lists disjoint prevents scope creep by
    # aggregation.
    _DMS_SHARE_DATABASES = [
        "dealer_domain",
        "parts_domain",
    ]

    def _grant_dms_cross_account_share(self, dms_account_id: str) -> None:
        """Issue per-database wildcard SELECT+DESCRIBE grants to the DMS account root.

        Mirrors :meth:`_grant_cvx_cross_account_share` but targets the DMS
        account and the two DMS-facing databases. One CfnPrincipalPermissions
        per database; table_wildcard covers all current and future tables in
        each database. ``permissions_with_grant_option=[]`` — the DMS
        principal cannot re-share (mirrors the 2026-06-09 security-review
        finding on the CVX side).
        """
        dms_principal = f"arn:aws:iam::{dms_account_id}:root"
        for db_product in self._DMS_SHARE_DATABASES:
            db_name = _stage_db_name(self.stage, db_product)
            lakeformation.CfnPrincipalPermissions(
                self,
                f"LfDmsGrant{db_product.replace('_', '').title()}",
                principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
                    data_lake_principal_identifier=dms_principal,
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


    # In-scope databases for the CMS cross-account share (T3.2 — spec
    # 2026-09-10-cms-fleet-intelligence-adp-consumer § D3). CMS Fleet
    # Intelligence reads five products to compute cost-per-mile, PM
    # compliance, and lifecycle signals across a mixed-OEM fleet.
    #
    # Three of the five (``service_records``, ``charging_sessions``,
    # ``vehicle_identity``) also appear in ``_CVX_SHARE_DATABASES``. That
    # overlap is intended and is NOT redundancy to be factored out: Lake
    # Formation grants are per-principal, so CMS needs its own grant even on a
    # database CVX already reads. Sharing one list between two consumers would
    # mean a future addition for one silently widens the other — the scope
    # creep by aggregation that the disjoint-list pattern exists to prevent.
    #
    # ``vehicle_telemetry_aggregated`` is deliberately excluded (spec § D11,
    # "Deferred products"); ``test_cms_grants_exclude_vehicle_telemetry_aggregated``
    # pins that so a later edit has to be deliberate.
    _CMS_SHARE_DATABASES = [
        "service_records",
        "charging_sessions",
        "vehicle_identity",
        "energy_usage",
        "tire_health",
    ]

    # Dimension tables the CMS consuming ROLE may read (spec
    # 2026-09-25-cms-fi-adp-wide-lifecycle, Q3/Q4): the ADP-wide lifecycle
    # rollup joins ``adp_{stage}_dimensions.vins`` for model and model year.
    # ``vehicle_identity`` has no model year, so it can't stand in.
    #
    # Granted per TABLE by name, never ``table_wildcard``: the same database
    # holds ``customers``, which is PII, and a wildcard would include it and any
    # table added later. The database grant is DESCRIBE only, which Athena needs
    # to plan the query ("Required Describe on <database>"); it grants no table.
    #
    # Role grant only, not added to the ``:root`` share: that share is inert
    # same-account (see ``_grant_cms_consumer_role``), and widening a
    # cross-account share should be its own decision. Must stay in lockstep
    # with CMS ``_fleet_intelligence_naming.ADP_DIMENSION_TABLES``.
    _CMS_DIMENSION_TABLES = ["vins"]

    def _grant_cms_consumer_role(self, consumer_role_arn: str) -> None:
        """Grant the CMS consuming ROLE directly — the grant that actually works.

        **Why this exists in addition to** :meth:`_grant_cms_cross_account_share`.

        CMS and ADP are the SAME AWS account today. ``arn:aws:iam::<acct>:root``
        is the *cross-account* Lake Formation idiom: it shares a resource with
        another account, whose admin then sub-grants to its own principals.
        Same-account it does NOT confer permissions on individual IAM roles, so
        the ``:root`` grants above are inert for the CMS Lambda that has to read.

        Established empirically 2026-09-13 running T5.3 of CMS spec
        2026-09-10-cms-fleet-intelligence-adp-consumer: with BOTH table-level and
        database-level ``:root`` grants live, Athena still returned
        ``Insufficient Lake Formation permission(s): Required Describe on
        adp_staging_service_records``. Granting the Lambda's execution role
        directly moved the error to the next un-granted database
        (``service_records`` -> ``vehicle_identity``) and then to a 200. Every
        principal that actually reads in this account is granted per-role,
        including both of CVX's.

        The ``:root`` grants are RETAINED rather than replaced: they are correct
        and necessary if CMS ever moves to its own account, they are inert rather
        than harmful today, and removing them would be an unrelated change to a
        share another spec owns.

        **Why the ARN is a parameter and not derived here.** The consuming role is
        ``cms-<stage>-ui-FleetIntelligenceRole<SUFFIX>`` where SUFFIX is
        CDK-generated, so it cannot be reconstructed from the stage. Naming it
        here would couple this stack to an opaque token — the reason spec § D3
        rejected "Option B" in the first place. Passing it in keeps the grant
        replayable from IaC while leaving the token where it is already known.

        **Known limitation, tracked**: if that role is ever REPLACED its ARN
        changes and this grant goes stale, exactly as a manual grant would. The
        durable fix is an explicit ``role_name`` on the role CMS-side, which is
        blocked on ``ui_stack.py`` being held by a concurrent session. Filed as a
        P1 follow-on. This construct is strictly better than the CLI grants it
        replaces — those existed in no repository at all.
        """
        for db_product in self._CMS_SHARE_DATABASES:
            db_name = _stage_db_name(self.stage, db_product)
            suffix = db_product.replace("_", "").title()
            lakeformation.CfnPrincipalPermissions(
                self,
                f"LfCmsRoleDbGrant{suffix}",
                principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
                    data_lake_principal_identifier=consumer_role_arn,
                ),
                resource=lakeformation.CfnPrincipalPermissions.ResourceProperty(
                    database=lakeformation.CfnPrincipalPermissions.DatabaseResourceProperty(
                        catalog_id=self.account,
                        name=db_name,
                    ),
                ),
                permissions=["DESCRIBE"],
                permissions_with_grant_option=[],
            )
            lakeformation.CfnPrincipalPermissions(
                self,
                f"LfCmsRoleTableGrant{suffix}",
                principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
                    data_lake_principal_identifier=consumer_role_arn,
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

        # Dimensions: DESCRIBE on the database, SELECT+DESCRIBE on each named
        # table. See ``_CMS_DIMENSION_TABLES`` for why this is not a wildcard.
        dimensions_db = _stage_db_name(self.stage, "dimensions")
        lakeformation.CfnPrincipalPermissions(
            self,
            "LfCmsRoleDimensionsDbGrant",
            principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
                data_lake_principal_identifier=consumer_role_arn,
            ),
            resource=lakeformation.CfnPrincipalPermissions.ResourceProperty(
                database=lakeformation.CfnPrincipalPermissions.DatabaseResourceProperty(
                    catalog_id=self.account,
                    name=dimensions_db,
                ),
            ),
            permissions=["DESCRIBE"],
            permissions_with_grant_option=[],
        )
        for table in self._CMS_DIMENSION_TABLES:
            lakeformation.CfnPrincipalPermissions(
                self,
                f"LfCmsRoleDimensionsTableGrant{table.replace('_', '').title()}",
                principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
                    data_lake_principal_identifier=consumer_role_arn,
                ),
                resource=lakeformation.CfnPrincipalPermissions.ResourceProperty(
                    table=lakeformation.CfnPrincipalPermissions.TableResourceProperty(
                        catalog_id=self.account,
                        database_name=dimensions_db,
                        name=table,
                    ),
                ),
                permissions=["SELECT", "DESCRIBE"],
                permissions_with_grant_option=[],
            )

    def _grant_cms_cross_account_share(self, cms_account_id: str) -> None:
        """Issue CMS's cross-account share: database DESCRIBE + table SELECT+DESCRIBE.

        Mirrors :meth:`_grant_cvx_cross_account_share` and
        :meth:`_grant_dms_cross_account_share` but targets the CMS account and
        the five CMS-facing databases. **Two** CfnPrincipalPermissions per
        database — a database-level DESCRIBE and a table-wildcard
        SELECT+DESCRIBE — because Lake Formation requires both before Athena
        will plan a query; table grants alone fail with "Required Describe on
        <database>". The CVX and DMS shares here issue table grants only and are
        NOT known to be sufficient on their own; CVX works because its consuming
        role holds a database-level DESCRIBE granted outside this stack. See the
        inline note below and the follow-on filed against those two shares.

        table_wildcard covers all current and future tables in each database.
        ``permissions_with_grant_option=[]`` — the CMS principal cannot re-share
        (mirrors the 2026-06-09 security-review finding on the CVX side).

        Principal is the account **root**, per spec § D3 "Decision: Option A".
        Option B — granting to the consuming role ARN
        (``cms-{stage}-ui-FleetIntelligenceRole*``) — was considered and
        rejected: that role's logical-id suffix is CDK-generated, so naming it
        here would couple this stack to an opaque token that a CMS-side
        ``cdk deploy`` can rotate, silently breaking the grant. Actual scoping
        is enforced by the IAM policy on the consuming role (spec § D4), which
        is the same containment CVX relies on today.
        """
        cms_principal = f"arn:aws:iam::{cms_account_id}:root"
        for db_product in self._CMS_SHARE_DATABASES:
            db_name = _stage_db_name(self.stage, db_product)
            # DATABASE-level DESCRIBE.
            #
            # Table-level SELECT+DESCRIBE alone is NOT sufficient: Lake Formation
            # additionally requires DESCRIBE on the *database* before a query may
            # reference a table inside it. Without it Athena fails the whole
            # statement at planning time with
            #   Insufficient Lake Formation permission(s):
            #     Required Describe on adp_staging_service_records
            # naming the DATABASE, not the table — which reads like a table grant
            # problem and is not one.
            #
            # Found 2026-09-12 running T5.3 of
            # 2026-09-10-cms-fleet-intelligence-adp-consumer against live Athena.
            # T5.1 had verified the table-level grants and reported them correct,
            # which they were; its own note records that
            # `list-permissions --principal` rejects without a Resource and
            # concludes "keep the per-table Resource form", so its verification
            # could not observe a database-level gap. CVX's consuming role holds
            # database-level DESCRIBE from outside this stack, which is why CVX's
            # read path worked and CMS's did not, and why this pattern was never
            # mirrored here: no grant in this stack used DatabaseResourceProperty.
            #
            # DESCRIBE only — the read itself is authorized table-side. No
            # CREATE_TABLE / ALTER / DROP, and no grant option.
            lakeformation.CfnPrincipalPermissions(
                self,
                f"LfCmsDbGrant{db_product.replace('_', '').title()}",
                principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
                    data_lake_principal_identifier=cms_principal,
                ),
                resource=lakeformation.CfnPrincipalPermissions.ResourceProperty(
                    database=lakeformation.CfnPrincipalPermissions.DatabaseResourceProperty(
                        catalog_id=self.account,
                        name=db_name,
                    ),
                ),
                permissions=["DESCRIBE"],
                permissions_with_grant_option=[],
            )
            lakeformation.CfnPrincipalPermissions(
                self,
                f"LfCmsGrant{db_product.replace('_', '').title()}",
                principal=lakeformation.CfnPrincipalPermissions.DataLakePrincipalProperty(
                    data_lake_principal_identifier=cms_principal,
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
