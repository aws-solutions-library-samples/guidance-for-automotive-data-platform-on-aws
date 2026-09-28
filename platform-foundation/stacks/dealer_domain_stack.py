"""ADP dealer domain stack — DMS accelerator v1 Group 3.

Spec: ``~/automotive-data-platform-on-aws/.kiro/specs/2026-08-26-adp-dealer-domain/spec.md``
DMS driving spec: ``~/guidance-for-dealer-management-system-on-aws/.kiro/specs/2026-08-26-dms-accelerator-v1/spec.md``

Creates:
- One ``glue.CfnDatabase`` (``adp_{stage}_dealer_domain``) for the 5
  dealer-operations data products.
- One ``datazone.CfnProject`` inside the existing domain (NOT a new
  CfnDomain — ADP has exactly one per stage; ``CfnDomain.name`` is
  immutable post-create).
- One region-suffixed IAM role for Glue/PySpark generator jobs.
- Lake S3 prefixes for 5 products (no ``glue.CfnTable`` — tables are
  created by one-shot Glue/PySpark generators per the closed spec
  ``2026-06-09-adp-pyspark-glue-products``).

Naming conventions (per stacks/_naming.py and
~/.kiro/steering/cross-region-namespace.md):
- Database: ``_stage_db_name(stage, "dealer_domain")``
  → ``adp_{stage}_dealer_domain``
- IAM role: ``{_stage_name(stage, "dealer-domain-glue-role")}-{region}``
  → ``adp-{stage}-foundation-dealer-domain-glue-role-{region}``
  (region-suffixed — account-wide IAM namespace, HIGH collision risk)
- DataZone project: technical name ``dealer_domain`` (unchanged across stages)

Design decisions (authoritative — read before modifying):
1. "Domain" in the DMS spec means a DataZone *project* here, not a
   CfnDomain. See spec Decision 1 and the Group 3 path-corrections header
   in the DMS tasks.md.
2. Glue databases ARE CDK-managed (foundation_stack.py:159); Glue tables
   are NOT — tables are created by one-shot Glue/PySpark generators.
   A correct implementation emits zero AWS::Glue::Table resources.
3. project_profile_id is required for domain_version="V2" domains.
   Reuse datazone_stack.py's default_project_profile (exposed as
   datazone_stack.default_project_profile_id_export).
4. IAM role name must be region-suffixed. Mirror the pattern at
   data_products_stack.py (SparkEtlRole) and cms_ingest_stack.py:388
   (GlueMergeJobRole).

5 lake prefixes (products, per spec § "Data products in ADP"):
  - service_records
  - dealer_performance
  - certification_scores
  - dealer_inventory
  - deal_pipeline

Product owner metadata: "DMS accelerator"
"""

from __future__ import annotations

from aws_cdk import (
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

# 5 data products for the dealer domain.
# Each tuple: (product_suffix, lake_prefix, description)
# - product_suffix: used to build S3 prefixes and as a reference label.
# - lake_prefix:    relative path under s3://lake-bucket/curated/
#                   where the Glue/PySpark generators will write.
# - description:    human-readable; surfaced in comments and cdk outputs.
_DEALER_PRODUCTS: list[tuple[str, str, str]] = [
    (
        "service_records",
        "curated/dealer_domain/service_records",
        "Service records joining VIN, customer, dealer, and parts (DMS domain).",
    ),
    (
        "dealer_performance",
        "curated/dealer_domain/dealer_performance",
        "Dealer performance rollups across KPIs and time windows (DMS domain).",
    ),
    (
        "certification_scores",
        "curated/dealer_domain/certification_scores",
        "STAR interface certification scores per dealer × interface (DMS domain).",
    ),
    (
        "dealer_inventory",
        "curated/dealer_domain/dealer_inventory",
        "Dealer vehicle inventory snapshots (DMS domain).",
    ),
    (
        "deal_pipeline",
        "curated/dealer_domain/deal_pipeline",
        "Active deal pipeline with F&I stage tracking (DMS domain).",
    ),
]


def _pascal(snake: str) -> str:
    """Convert snake_case to PascalCase for CDK construct IDs."""
    return "".join(part.capitalize() for part in snake.split("_"))


class DealerDomainStack(Stack):
    """ADP dealer domain stack for the DMS accelerator v1.

    Provisions the Glue database, DataZone project, and Glue-job IAM role
    for the 5 DMS dealer-operations data products in the ``adp_dealer_domain``.

    Parameters
    ----------
    stage:
        Deployment stage — ``"staging"`` or ``"prod"``.
    lake_bucket_name:
        Name of the ADP lake S3 bucket (from ``FoundationStack``).
    domain_id_export:
        DataZone domain ID (from ``DataZoneStack.domain_id_export``).
    project_profile_id_export:
        Default project profile ID (from
        ``DataZoneStack.default_project_profile_id_export``). Required for
        V2 domains.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        lake_bucket_name: str,
        domain_id_export: str,
        project_profile_id_export: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        validate_stage(stage)
        self.stage = stage

        # ------------------------------------------------------------------
        # 1. Glue database for the dealer domain
        #    Name: adp_{stage}_dealer_domain  (via _stage_db_name)
        #    No glue.CfnTable here — tables are one-shot PySpark jobs.
        # ------------------------------------------------------------------
        db_name = _stage_db_name(stage, "dealer_domain")
        self.dealer_db = glue.CfnDatabase(
            self,
            "DealerDomainDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=db_name,
                description=(
                    f"ADP dealer domain Glue database — 5 DMS data products "
                    f"(service_records, dealer_performance, certification_scores, "
                    f"dealer_inventory, deal_pipeline). "
                    f"Product owner: DMS accelerator (stage={stage})."
                ),
                location_uri=(
                    f"s3://{lake_bucket_name}/curated/dealer_domain/"
                ),
            ),
        )

        # ------------------------------------------------------------------
        # 2. DataZone project — inside the *existing* domain; NOT a new domain.
        #    Technical name ``dealer_domain`` is unchanged across stages per
        #    DataZoneProjectsStack convention (design §2.5 Option A).
        # ------------------------------------------------------------------
        display_name_suffix = " [Staging]" if stage == "staging" else ""
        stage_description_suffix = f" (stage={stage})"

        self.dealer_project = datazone.CfnProject(
            self,
            "DealerDomainProject",
            domain_identifier=domain_id_export,
            name="dealer_domain",
            description=(
                f"DMS Dealer Domain{display_name_suffix} — "
                f"5 dealer-operations data products: service records, "
                f"dealer performance, certification scores, dealer inventory, "
                f"deal pipeline. Product owner: DMS accelerator."
                f"{stage_description_suffix}"
            ),
            project_profile_id=project_profile_id_export,
        )
        self.dealer_project.apply_removal_policy(RemovalPolicy.RETAIN)

        # ------------------------------------------------------------------
        # 3. Region-suffixed IAM role for Glue/PySpark generator jobs.
        #    Pattern: {_stage_name(stage, "dealer-domain-glue-role")}-{region}
        #    → adp-{stage}-foundation-dealer-domain-glue-role-{region}
        #    Required per cross-region-namespace.md — IAM is account-wide.
        #    Mirrors DataProductsStack (SparkEtlRole) and
        #    CmsIngestStack (GlueMergeJobRole) patterns.
        # ------------------------------------------------------------------
        role_name = f"{_stage_name(stage, 'dealer-domain-glue-role')}-{self.region}"

        self.glue_job_role = iam.Role(
            self,
            "DealerDomainGlueJobRole",
            role_name=role_name,
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            description=(
                f"ADP dealer domain Glue/PySpark generator role for DMS "
                f"accelerator v1. Writes to 5 dealer_domain lake prefixes "
                f"(stage={stage}). Region-suffixed per "
                f"cross-region-namespace.md."
            ),
        )

        # Standard Glue service role baseline (CloudWatch + asset reads).
        self.glue_job_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSGlueServiceRole"
            )
        )

        # S3 grants — read on lake bucket root for dimensions; read+write on
        # the 5 dealer_domain prefixes + scripts/tmp/athena-results.
        bucket_arn = f"arn:aws:s3:::{lake_bucket_name}"
        write_prefixes = [p for _, p, _ in _DEALER_PRODUCTS] + [
            "scripts",
            "tmp",
            "athena-results",
        ]
        list_prefixes = ["dimensions"] + write_prefixes

        self.glue_job_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3ListBucketScoped",
                actions=["s3:ListBucket", "s3:GetBucketLocation"],
                resources=[bucket_arn],
                conditions={
                    "StringLike": {
                        "s3:prefix": [f"{p}/*" for p in list_prefixes]
                        + list_prefixes,
                    }
                },
            )
        )
        self.glue_job_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3ReadDimensions",
                actions=["s3:GetObject"],
                resources=[f"{bucket_arn}/dimensions/*"],
            )
        )
        self.glue_job_role.add_to_policy(
            iam.PolicyStatement(
                sid="S3WriteDealerDomainPrefixes",
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                ],
                resources=(
                    [f"{bucket_arn}/{p}/*" for p in write_prefixes]
                ),
            )
        )

        # Glue Catalog — scoped to the dealer_domain database.
        self.glue_job_role.add_to_policy(
            iam.PolicyStatement(
                sid="GlueCatalogDealerDomain",
                actions=[
                    "glue:GetDatabase",
                    "glue:GetDatabases",
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                    "glue:BatchCreatePartition",
                    "glue:CreateTable",
                    "glue:UpdateTable",
                    "glue:BatchDeletePartition",
                ],
                resources=[
                    f"arn:aws:glue:{self.region}:{self.account}:catalog",
                    f"arn:aws:glue:{self.region}:{self.account}:database/{db_name}",
                    f"arn:aws:glue:{self.region}:{self.account}:table/{db_name}/*",
                ],
            )
        )

        # CloudWatch Logs — standard Glue job log groups.
        self.glue_job_role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudWatchGlueLogs",
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws-glue/jobs/*",
                    f"arn:aws:logs:{self.region}:{self.account}:log-group:/aws-glue/jobs:*",
                ],
            )
        )

        # ------------------------------------------------------------------
        # 4. CFN outputs — region-prefixed export names for cross-stack refs.
        # ------------------------------------------------------------------
        CfnOutput(
            self,
            "DealerDomainDatabaseName",
            value=db_name,
            export_name=_stage_name(stage, "dealer-domain-db-name"),
            description="Glue database name for adp_dealer_domain products.",
        )
        CfnOutput(
            self,
            "DealerDomainProjectId",
            value=self.dealer_project.attr_id,
            export_name=_stage_name(stage, "dealer-domain-project-id"),
            description="DataZone project ID for the dealer_domain logical domain.",
        )
        CfnOutput(
            self,
            "DealerDomainGlueJobRoleArn",
            value=self.glue_job_role.role_arn,
            export_name=_stage_name(stage, "dealer-domain-glue-role-arn"),
            description=(
                "ARN of the region-suffixed IAM role for Glue/PySpark "
                "dealer_domain generators."
            ),
        )

        # ------------------------------------------------------------------
        # 5. cdk-nag suppressions — documented per finding.
        #    security-review Cycle 1 W4, 2026-09-03: rationale updated to
        #    accurately distinguish dealer-domain-specific vs shared prefixes.
        # ------------------------------------------------------------------
        NagSuppressions.add_resource_suppressions(
            self.glue_job_role,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWS-managed AWSGlueServiceRole is the canonical baseline "
                        "for Glue ETL roles (CloudWatch log perms + asset-bucket "
                        "reads). Same pattern as DataProductsStack (SparkEtlRole) "
                        "and CmsIngestStack (GlueMergeJobRole) in this repo."
                    ),
                    "applies_to": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSGlueServiceRole"
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        # (1) S3 write wildcards are narrowed to specific prefixes,
                        # with distinct treatment of dealer-domain-specific vs
                        # PORTFOLIO-SHARED prefixes:
                        #  - curated/dealer_domain/<product>/*  (5 dealer-domain-
                        #    specific per-product WRITE prefixes)
                        #  - dimensions/*                        (portfolio-shared
                        #    READ; every product's Glue generator resolves FKs
                        #    from the same dimensions/ prefix)
                        #  - scripts/*, tmp/*, athena-results/*  (portfolio-SHARED
                        #    Glue-job scratch + Athena workgroup output prefixes;
                        #    the standard shared scratch space, not dealer-only)
                        # (2) Glue Catalog wildcards are narrowed to the single
                        # target database (adp_{stage}_dealer_domain) and its
                        # tables — no catalog-wide grants, no iam:PassRole.
                        # (3) CloudWatch Logs wildcard is /aws-glue/jobs/* — the
                        # AWS-recommended Glue-ETL-job log-group prefix
                        # (not /aws-glue/* which would also cover crawlers /
                        # workflows / notebooks).
                        "S3 wildcards: WRITE grants scoped to 5 dealer-domain-"
                        "specific per-product prefixes (curated/dealer_domain/"
                        "<product>/*). READ grant scoped to the portfolio-SHARED "
                        "dimensions/* prefix (FK resolution — every product "
                        "generator reads from the same shared dimensions prefix). "
                        "scripts/*, tmp/*, athena-results/* are portfolio-SHARED "
                        "Glue-job scratch and Athena workgroup output prefixes, "
                        "not dealer-domain-private. Glue Catalog wildcards are "
                        "narrowed to the single target database "
                        f"(adp_{{stage}}_dealer_domain) and its tables. "
                        "CloudWatch Logs wildcard is /aws-glue/jobs/* — the "
                        "AWS-recommended Glue-ETL-job log-group path."
                    ),
                },
            ],
            apply_to_children=True,
        )
