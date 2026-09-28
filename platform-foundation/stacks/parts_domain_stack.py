"""ADP parts domain stack — `adp_parts_domain` DataZone project + Glue database.

Implements T3.5 of the DMS accelerator spec
``~/guidance-for-dealer-management-system-on-aws/.kiro/specs/2026-08-26-dms-accelerator-v1/``.

Governing spec: ``~/automotive-data-platform-on-aws/.kiro/specs/2026-08-26-adp-dealer-domain/spec.md``
Decisions 1–4 and Constraints are binding.

Three Iceberg products (tables created by one-shot Glue/PySpark generators —
NOT by CfnTable, per Decision 2 and the closed spec
``2026-06-09-adp-pyspark-glue-products``):

    parts_catalog  — PIES 8.0 conformant shape
                     PK (brand_aaia_id, part_number)
                     brand_aaia_id is always a DMS-BR-* synthetic value;
                     never a real Auto Care Brand Table BrandAAIAID (licensed).

    parts_fitment  — ACES 5.0 conformant shape
                     PK (part_number, vehicle_config_id, position_id, qualifier_hash)
                     vehicle_config_id is always a DMS-VCFG-* synthetic value;
                     never a real Auto Care VCdb VehicleID (licensed).

    parts_interchange — supersession + OE-cross-reference + aftermarket-equivalent
                     PK (primary_part_number, replacement_part_number)
                     relationship_type IN ('supersession','oe_cross','aftermarket_equivalent')
                     Separate product (not columns on catalog) because supersession
                     is 1:N and OE cross-refs are bidirectional.

All three carry ``access_channel ∈ {franchise, independent}`` per Decision 3
(REPAIR Act forward-readiness, 2026-08-27 user decision). v1 seeds and enables
``franchise`` only. No independent-aftermarket persona, group or API in v1.

Auto Care licensing constraint (Decision 4 + ADP spec § Constraints):
- VCdb, PCdb, Qdb, PAdb and the Brand Table are subscription-based licensed
  property (Auto Care Technology License Agreement, rev. 2025-02-28).
- This repo ships ACES/PIES-conformant schema shape and message structure ONLY,
  populated with synthetic values.
- Every synthetic ID lives in a DMS-prefixed namespace:
  DMS-VCFG-* (vehicle config), DMS-BR-* (brand), DMS-PT-* (part terminology),
  DMS-QT-* (qualifier), DMS-PA-* (attribute).
- Where a field needs a licensed range to be shape-meaningful, it is an opaque
  varchar; the value-space constraint lives in T3.7's lint.
- Enforced by ``scripts/lint_no_licensed_autocare_ids.py``.

Relationship to existing parts-catalog KB category (Decision 4 / spec.md § 4,
updated 2026-08-27 per DMS R2d — SUPERSESSION, not coexistence):
    ``adp_parts_domain`` (this stack) is **authoritative** — structured,
    standards-shaped Iceberg data for SQL and joins.
    The ``parts-catalog`` KB category (in vehicle_knowledge_base/sources/)
    is a **derived read surface regenerated from
    ``adp_parts_domain.parts_catalog``** — one markdown document per SKU
    (~500 docs), replacing the pre-2026-08-27 5 category-narrative docs.
    The sidecar value ``source_category: "parts_catalog"`` is preserved
    **byte-for-byte** as a compatibility contract for three live CVX
    consumers (agents/supervisor/tools/parts_lookup.py, persona_definitions.py,
    tests/test_kb_tools.py). Coexistence would have left two divergent
    lineups; regeneration collapses them into one source of truth while
    keeping the CVX consumers green. Regeneration is implemented in
    Group 5 of the ADP-side spec. Documented in
    ``docs/parts-surface-boundary.md``.

IAM role name is region-suffixed per
``~/.kiro/steering/cross-region-namespace.md`` Check 1 (account-wide IAM
namespace, HIGH collision risk).  Pattern mirrors
``stacks/optional/cms_ingest_stack.py`` GlueMergeJobRole.
"""

from __future__ import annotations

from aws_cdk import (
    Aws,
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_datazone as datazone
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks._naming import _stage_db_name, _stage_name, validate_stage


# ---------------------------------------------------------------------------
# Product manifest — consumed both for Glue database metadata and for the
# DataZone project description.  Single source of truth for product names.
# ---------------------------------------------------------------------------

_PARTS_PRODUCTS: list[tuple[str, str, str]] = [
    (
        "parts_catalog",
        "Parts Catalog (PIES 8.0)",
        "PIES 8.0 conformant parts catalog. "
        "PK (brand_aaia_id, part_number). "
        "brand_aaia_id is always a DMS-BR-* synthetic value — never a real "
        "Auto Care Brand Table BrandAAIAID (licensed). "
        "access_channel dimension present for REPAIR Act forward-readiness.",
    ),
    (
        "parts_fitment",
        "Parts Fitment (ACES 5.0)",
        "ACES 5.0 conformant vehicle-application records. "
        "PK (part_number, vehicle_config_id, position_id, qualifier_hash). "
        "vehicle_config_id is always a DMS-VCFG-* synthetic value — never a "
        "real Auto Care VCdb VehicleID (licensed). "
        "qualifier_hash = SHA-256 over qualifier text; not a Qdb QualifierID (licensed).",
    ),
    (
        "parts_interchange",
        "Parts Interchange",
        "Supersession, OE cross-reference, and aftermarket-equivalent relationships. "
        "PK (primary_part_number, replacement_part_number). "
        "relationship_type IN ('supersession','oe_cross','aftermarket_equivalent'). "
        "Separate product (not columns on catalog) because supersession is 1:N "
        "and OE cross-refs are bidirectional.",
    ),
]


class PartsDomainStack(Stack):
    """Registers ``adp_parts_domain`` in the existing ADP DataZone domain.

    Creates:
    - One ``glue.CfnDatabase`` (``adp_{stage}_parts_domain``)
    - One ``datazone.CfnProject`` in the existing domain (NOT a new CfnDomain)
    - One region-suffixed IAM role for future Spark-ETL generators
    - CfnOutputs for the project id and Glue database name

    Does NOT create glue.CfnTable resources — tables are created by
    one-shot Glue/PySpark generators per the existing ADP convention.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        domain_id: str,
        project_profile_id: str,
        lake_bucket_name: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        validate_stage(stage)
        self.stage = stage

        # --- Glue database -------------------------------------------------
        # Name follows _stage_db_name convention: adp_{stage}_parts_domain
        db_name = _stage_db_name(stage, "parts_domain")
        self.glue_database = glue.CfnDatabase(
            self,
            "PartsDomainDatabase",
            catalog_id=Aws.ACCOUNT_ID,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=db_name,
                description=(
                    f"ADP parts domain Glue database (stage={stage}). "
                    "Hosts three ACES/PIES-conformant products: "
                    "parts_catalog (PIES 8.0), parts_fitment (ACES 5.0), "
                    "parts_interchange. "
                    "Tables are created by one-shot PySpark generators, not CDK. "
                    "Auto Care licensing: all IDs are synthetic DMS-prefixed values; "
                    "no licensed VCdb/PCdb/Qdb/PAdb/BrandTable data shipped."
                ),
            ),
        )

        # --- DataZone project ----------------------------------------------
        # Decision 1: projects are the subdivision mechanism beneath a domain.
        # No new CfnDomain is created.
        display_name_suffix = " [Staging]" if stage == "staging" else ""
        product_list = ", ".join(p[0] for p in _PARTS_PRODUCTS)
        self.datazone_project = datazone.CfnProject(
            self,
            "PartsDomainProject",
            domain_identifier=domain_id,
            name="adp_parts_domain",
            description=(
                f"Parts Domain (ACES/PIES){display_name_suffix} — "
                f"ACES 5.0 + PIES 8.0 structured parts data for SQL and joins. "
                f"Products: {product_list}. "
                f"Authoritative source-of-truth for parts data (Decision 4, 2026-08-27 supersession): "
                f"the parts-catalog KB category in vehicle_knowledge_base/sources/ is a "
                f"derived read surface regenerated from adp_parts_domain.parts_catalog "
                f"(source_category='parts_catalog' sidecar preserved byte-for-byte for CVX consumers). "
                f"Product owner: DMS accelerator R2a. "
                f"Auto Care licensing: shape-conformant, synthetic DMS-prefixed IDs only. "
                f"(stage={stage})"
            ),
            project_profile_id=project_profile_id,
        )
        self.datazone_project.apply_removal_policy(RemovalPolicy.RETAIN)

        # --- Spark-ETL IAM role --------------------------------------------
        # Region-suffixed per cross-region-namespace.md (account-wide namespace).
        # Mirrors the GlueMergeJobRole pattern at cms_ingest_stack.py:388 and
        # the DealerDomainGlueJobRole in dealer_domain_stack.py for symmetry.
        # The role is a placeholder for when the PySpark generators are authored
        # in T3.6; it holds only the minimum S3 + Glue grants needed.
        # Naming rationale: 'parts-domain-glue-role' mirrors 'dealer-domain-glue-role'
        # so that spec Verify + governance grep patterns can key on a single suffix
        # (`{dealer|parts}-domain-glue-role-<region>`) rather than divergent shapes.
        role_name = _stage_name(stage, f"parts-domain-glue-role-{Aws.REGION}")
        self.spark_etl_role = iam.Role(
            self,
            "PartsDomainGlueJobRole",
            role_name=role_name,
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            description=(
                f"Spark-ETL IAM role for adp_parts_domain PySpark generators "
                f"(stage={stage}). Created by PartsDomainStack; used by one-shot "
                f"Glue jobs that populate parts_catalog, parts_fitment, parts_interchange."
            ),
        )

        # S3 — dimensions read (mirrors DealerDomainStack.S3ReadDimensions,
        # security-review Cycle 1 W3, 2026-09-03).
        # Prior grant was `s3:GetObject` on `arn:...:{bucket}/*` — bucket-wide
        # read authority — which allowed the parts-domain role to read every
        # prefix in the lake (CMS ingest, KB corpus, dealer-domain data, etc.).
        # Least-privilege default for an unknown-but-parts-domain-only access
        # pattern: read `dimensions/*` (the only lake prefix all product
        # generators need for FK resolution) + list the bucket, nothing more.
        # Write scopes on lines below remain per-product-scoped and unchanged.
        lake_bucket_arn = f"arn:aws:s3:::{lake_bucket_name}"
        self.spark_etl_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="LakeBucketList",
                effect=iam.Effect.ALLOW,
                actions=["s3:ListBucket", "s3:GetBucketLocation"],
                resources=[lake_bucket_arn],
                conditions={
                    "StringLike": {
                        # ListBucket needs `s3:prefix` conditions per AWS docs.
                        # We list the parts-domain product prefixes + dimensions
                        # + athena-results + scripts/tmp for Glue-job scratch.
                        "s3:prefix": [
                            "dimensions", "dimensions/*",
                            "curated/parts_catalog", "curated/parts_catalog/*",
                            "curated/parts_fitment", "curated/parts_fitment/*",
                            "curated/parts_interchange", "curated/parts_interchange/*",
                            "athena-results", "athena-results/*",
                            "scripts", "scripts/*",
                            "tmp", "tmp/*",
                        ],
                    }
                },
            )
        )
        self.spark_etl_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="LakeReadDimensions",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject"],
                resources=[f"{lake_bucket_arn}/dimensions/*"],
            )
        )
        for product_name, _, _ in _PARTS_PRODUCTS:
            prefix = f"curated/{product_name}/"
            self.spark_etl_role.add_to_principal_policy(
                iam.PolicyStatement(
                    sid=f"LakeWrite{_pascal(product_name)}",
                    effect=iam.Effect.ALLOW,
                    actions=[
                        "s3:GetObject",
                        "s3:PutObject",
                        "s3:DeleteObject",
                        "s3:AbortMultipartUpload",
                    ],
                    resources=[f"{lake_bucket_arn}/{prefix}*"],
                )
            )

        # Athena results prefix for interactive queries during development
        self.spark_etl_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="AthenaResults",
                effect=iam.Effect.ALLOW,
                actions=["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                resources=[f"{lake_bucket_arn}/athena-results/*"],
            )
        )

        # Glue — catalog access scoped to the parts_domain database and its tables
        self.spark_etl_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="GlueCatalogPartsDomain",
                effect=iam.Effect.ALLOW,
                actions=[
                    "glue:GetDatabase",
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:CreateTable",
                    "glue:UpdateTable",
                    "glue:BatchCreatePartition",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                    "glue:BatchGetPartition",
                ],
                resources=[
                    f"arn:aws:glue:{Aws.REGION}:{Aws.ACCOUNT_ID}:catalog",
                    f"arn:aws:glue:{Aws.REGION}:{Aws.ACCOUNT_ID}:database/{db_name}",
                    f"arn:aws:glue:{Aws.REGION}:{Aws.ACCOUNT_ID}:table/{db_name}/*",
                ],
            )
        )

        # CloudWatch Logs (Glue job logs)
        # security-review Cycle 1 W4/Suggestion: tightened from
        # /aws-glue/* (all Glue log-group prefixes — crawlers, notebooks,
        # workflows) to /aws-glue/jobs/* (only Glue ETL job logs), matching
        # DealerDomainStack.CloudWatchGlueLogs. See ~/.kiro/steering/spec-workflow.md.
        self.spark_etl_role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="CloudWatchLogs",
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{Aws.REGION}:{Aws.ACCOUNT_ID}:log-group:/aws-glue/jobs/*",
                    f"arn:aws:logs:{Aws.REGION}:{Aws.ACCOUNT_ID}:log-group:/aws-glue/jobs:*",
                ],
            )
        )

        # cdk-nag suppressions -----------------------------------------------
        # security-review Cycle 1 W4, 2026-09-03: rewritten to name every
        # applies_to entry with a concrete rationale, matching the tightened
        # grants above. No blanket rationales; no wider-than-stated grants.
        NagSuppressions.add_resource_suppressions(
            self.spark_etl_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        # Rationale per applies_to entry, in the same order:
                        # 1) Glue table wildcard — required because Iceberg
                        #    creates partition sub-paths at runtime under
                        #    table/adp_{stage}_parts_domain/* and the exact
                        #    partition names are not knowable at synth time;
                        #    database scope is explicit (no catalog-wide grant).
                        # 2) CloudWatch Logs — scoped to /aws-glue/jobs/*
                        #    (only Glue ETL job logs, not crawlers/notebooks/
                        #    workflows), matching the DealerDomainStack idiom.
                        #    Standard Glue-job log path; cannot narrow further
                        #    without breaking Glue's own logging.
                        # 3) LakeReadDimensions — read grant on the shared
                        #    dimensions/ prefix only; scoped from the previous
                        #    bucket-wide read (security-review W3 remediation).
                        # 4-6) Per-product WRITE prefixes under curated/parts_*
                        #    — one applies_to entry per parts-domain product.
                        # 7) athena-results/* — SHARED Athena workgroup output
                        #    prefix (used by all data-platform generators for
                        #    interactive queries during development); not this
                        #    role's private prefix.
                        "Glue Iceberg table ARNs require wildcard suffix "
                        f"(table/adp_{{stage}}_parts_domain/*) because Iceberg "
                        "creates partition sub-paths at runtime; database scope "
                        "is explicit. "
                        "CloudWatch Logs scoped to /aws-glue/jobs/* — the standard "
                        "Glue ETL job log path (tightened from /aws-glue/* per "
                        "security-review W4). "
                        "LakeReadDimensions is scoped to the shared dimensions/ "
                        "prefix only (parts-domain generators need FK-resolution "
                        "reads; tightened from bucket-wide GetObject per "
                        "security-review W3). "
                        "Per-product WRITE grants are individually scoped to "
                        "curated/parts_catalog/*, curated/parts_fitment/*, and "
                        "curated/parts_interchange/*. "
                        "athena-results/* is the SHARED Athena workgroup output "
                        "prefix used by all data-platform Glue jobs for "
                        "interactive queries — this is not a parts-domain-private "
                        "prefix but the standard shared scratch space."
                    ),
                    "applies_to": [
                        f"Resource::arn:aws:glue:<AWS::Region>:<AWS::AccountId>:table/{db_name}/*",
                        "Resource::arn:aws:logs:<AWS::Region>:<AWS::AccountId>:log-group:/aws-glue/jobs/*",
                        "Resource::arn:aws:logs:<AWS::Region>:<AWS::AccountId>:log-group:/aws-glue/jobs:*",
                        f"Resource::arn:aws:s3:::{lake_bucket_name}/dimensions/*",
                        f"Resource::arn:aws:s3:::{lake_bucket_name}/curated/parts_catalog/*",
                        f"Resource::arn:aws:s3:::{lake_bucket_name}/curated/parts_fitment/*",
                        f"Resource::arn:aws:s3:::{lake_bucket_name}/curated/parts_interchange/*",
                        f"Resource::arn:aws:s3:::{lake_bucket_name}/athena-results/*",
                    ],
                },
            ],
            apply_to_children=True,
        )

        # --- Outputs -------------------------------------------------------
        CfnOutput(
            self,
            "PartsDomainProjectId",
            value=self.datazone_project.attr_id,
            export_name=_stage_name(stage, "datazone-project-adp-parts-domain-id"),
        )
        CfnOutput(
            self,
            "PartsDomainGlueDatabaseName",
            value=db_name,
            export_name=_stage_name(stage, "parts-domain-glue-db-name"),
        )
        CfnOutput(
            self,
            "PartsDomainGlueJobRoleArn",
            value=self.spark_etl_role.role_arn,
            export_name=_stage_name(stage, "parts-domain-glue-role-arn"),
            description=(
                "ARN of the region-suffixed IAM role for Glue/PySpark "
                "parts_domain generators. Mirrors DealerDomainGlueJobRoleArn."
            ),
        )

    # --- Public attributes for cross-stack references ----------------------

    @property
    def glue_database_name(self) -> str:
        """The Glue database name, e.g. ``adp_staging_parts_domain``."""
        return _stage_db_name(self.stage, "parts_domain")

    @property
    def datazone_project_id(self) -> str:
        """The DataZone project attr_id (CloudFormation token)."""
        return self.datazone_project.attr_id

    @property
    def spark_etl_role_arn(self) -> str:
        """ARN of the Spark-ETL IAM role for cross-stack wiring."""
        return self.spark_etl_role.role_arn


def _pascal(s: str) -> str:
    """Convert snake_case to PascalCase for CDK construct IDs."""
    return "".join(part.capitalize() for part in s.split("_"))
