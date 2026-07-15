"""ADP Foundation — single CDK app entry point.

Per ``staging-prod-design.md``, the foundation deploys side-by-side as
``staging`` and ``prod`` stages in the same AWS account + ``us-east-1``
region. Stage is supplied via the CDK context flag ``-c stage=...``
(propagated by the Makefile from ``STAGE=...``). The app **fails
closed** when ``stage`` is missing or not in ``{"staging", "prod"}``.

Stacks deployed
---------------

Account-singular (no ``stage`` prefix, deployed once via
``make bootstrap``):

- ``adp-shared-bootstrap`` — Macie::Session.

Per-stage (deployed via ``make deploy STAGE=...``):

- ``adp-{stage}-foundation-network`` — VPC + endpoints
- ``adp-{stage}-foundation-lake`` — S3 lake bucket + Glue catalog
  (10 stage-prefixed databases)
- ``adp-{stage}-foundation-datazone`` — DataZone V2 domain
- ``adp-{stage}-foundation-datazone-projects`` — 9 product projects +
  smoke-test consumer
- ``adp-{stage}-foundation-governance`` — Lake Formation, CloudTrail,
  IAM Identity Center groups
- ``adp-{stage}-foundation-cms-ingest`` *(optional, off by default)* —
  DDB Streams → Firehose → S3 → Iceberg

CDK context flags (set via ``-c key=value`` on the CLI):

- ``stage=staging|prod`` *(required for per-stage stacks)*.
- ``enable_cms_ingest=true|false`` (default: ``false``) — gate the
  optional CMS ingest stack. When ``true``, also pass
  ``cms_vehicle_state_table_arn=...``.
- ``identity_center_instance_arn=arn:aws:sso:::instance/ssoins-...``
  (default: auto-discover via ``aws sso-admin list-instances``).
- ``identity_store_id=d-...`` (default: auto-discover).

Synth / deploy:

::

    cd platform-foundation
    make bootstrap                  # one-time, account-level
    make synth STAGE=staging
    make deploy STAGE=staging

cdk-nag is wired on every stack; suppressions live alongside the
resources they exempt.
"""

from __future__ import annotations

import os
import re
import sys

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from stacks._naming import VALID_STAGES, _stage_name
from stacks.datazone_projects_stack import DataZoneProjectsStack
from stacks.datazone_stack import DataZoneStack
from stacks.foundation_stack import FoundationStack
from stacks.governance_stack import GovernanceStack
from stacks.network_stack import NetworkStack
from stacks.data_products_stack import DataProductsStack
from stacks.optional.cms_ingest_stack import CmsIngestStack
from stacks.shared_bootstrap_stack import SharedBootstrapStack
from stacks.vehicle_knowledge_base_stack import VehicleKnowledgeBaseStack


def _ctx_bool(app: cdk.App, key: str, *, default: bool = False) -> bool:
    raw = app.node.try_get_context(key)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def _resolve_stage(app: cdk.App) -> str:
    """Read and validate the ``stage`` context value.

    Fails closed (exits non-zero) if ``stage`` is missing, empty, or
    not in :data:`stacks._naming.VALID_STAGES`. The error message
    references ``make deploy STAGE=...`` per design §1.
    """
    stage = app.node.try_get_context("stage")
    if stage is None or stage == "":
        sys.stderr.write(
            "ERROR: -c stage=staging|prod is required.\n"
            "       Run via Makefile: make deploy STAGE=staging\n"
            "                    or:  make deploy STAGE=prod\n"
        )
        raise SystemExit(2)
    if stage not in VALID_STAGES:
        sys.stderr.write(
            f"ERROR: stage must be 'staging' or 'prod' (got {stage!r}).\n"
            "       Run via Makefile: make deploy STAGE=staging\n"
            "                    or:  make deploy STAGE=prod\n"
        )
        raise SystemExit(2)
    return stage


_DEPLOY_ROLE_ARN_RE = re.compile(r'^arn:aws:iam::\d{12}:role/.+$')


def _resolve_cvx_kb_principals(app: cdk.App) -> list[str] | None:
    """Resolve CVX KB resource-policy principals via CDK ctx OR env var.

    Order: ``-c cvxKbPrincipals=arn1,arn2`` (comma-split); else env
    ``ADP_KB_CVX_PRINCIPAL_ARNS=arn1,arn2``; else None.
    """
    raw = app.node.try_get_context('cvxKbPrincipals') or os.environ.get('ADP_KB_CVX_PRINCIPAL_ARNS')
    if not raw:
        return None
    arns = [a.strip() for a in str(raw).split(',') if a.strip()]
    return arns or None


def _resolve_kb_deploy_role_arn(app: cdk.App, env: cdk.Environment) -> str:
    """Resolve the AOSS data-access-policy deploy-role ARN per Q4.

    Order: ``-c adpKbDeployRoleArn=arn:aws:iam::...``; else env
    ``ADP_KB_DEPLOY_ROLE_ARN``; else default built from
    ``Environment.account`` + ``Environment.region`` using the standard
    ``hnb659fds`` CDK bootstrap qualifier. Validates the ARN matches
    ``arn:aws:iam::<12 digits>:role/<role-name>`` and raises ValueError on
    malformed input at synth time.
    """
    arn = (
        app.node.try_get_context('adpKbDeployRoleArn')
        or os.environ.get('ADP_KB_DEPLOY_ROLE_ARN')
    )
    if not arn:
        account = env.account
        region = env.region
        arn = f'arn:aws:iam::{account}:role/cdk-hnb659fds-cfn-exec-role-{account}-{region}'
    arn = str(arn).strip()
    if not _DEPLOY_ROLE_ARN_RE.match(arn):
        raise ValueError(
            f'adpKbDeployRoleArn / ADP_KB_DEPLOY_ROLE_ARN must match '
            f'arn:aws:iam::<12 digits>:role/<role-name>; got {arn!r}'
        )
    return arn


def main() -> None:
    app = cdk.App()

    # --- Stage validation (fail closed) ------------------------------------
    stage = _resolve_stage(app)

    account = os.environ.get("CDK_DEFAULT_ACCOUNT")
    region = os.environ.get("CDK_DEFAULT_REGION", "us-east-1")
    if not account:
        # Allow synth without real account (cdk synth in CI without AWS auth).
        # Use a deterministic placeholder so CFN templates remain stable.
        account = "000000000000"

    env = cdk.Environment(account=account, region=region)
    common_tags = {
        "adp:project": "adp-foundation",
        "adp:spec": "2026-05-28-adp-ev-startup-foundation",
        "adp:owner": "platform-team",
        # Per design §2.12: enables per-stage cost reporting in Cost Explorer
        # / Budgets once activated as a Cost Allocation Tag in the Billing
        # console (one-time, ~24h propagation).
        "adp:stage": stage,
    }

    # --- Shared bootstrap (account-singular, stage-agnostic) ---------------
    # Deployed once per account via ``make bootstrap``. Houses Macie::Session
    # (and any future account-singular resources). NOT part of the per-stage
    # rollout — instantiated unconditionally and NOT a synth-time dependency
    # of any per-stage stack. See ``stacks/shared_bootstrap_stack.py`` for
    # the full contract.
    #
    # The bootstrap stack does NOT inherit ``adp:stage`` because it is
    # account-singular. Tag it with the project/spec/owner subset only.
    bootstrap_tags = {k: v for k, v in common_tags.items() if k != "adp:stage"}
    SharedBootstrapStack(
        app,
        "adp-shared-bootstrap",
        env=env,
        description="ADP account-singular bootstrap (Macie::Session). Deployed once per account.",
        tags=bootstrap_tags,
    )

    # --- Network -----------------------------------------------------------
    network = NetworkStack(
        app,
        _stage_name(stage, "network"),
        env=env,
        description=f"ADP foundation VPC + VPC endpoints (stage={stage})",
        tags=common_tags,
        stage=stage,
    )

    # --- Lake bucket + Glue catalog ----------------------------------------
    lake = FoundationStack(
        app,
        _stage_name(stage, "lake"),
        env=env,
        description=f"ADP foundation S3 lake bucket + Glue catalog (stage={stage})",
        tags=common_tags,
        stage=stage,
    )

    # --- DataZone V2 domain ------------------------------------------------
    domain = DataZoneStack(
        app,
        _stage_name(stage, "datazone"),
        env=env,
        description=f"ADP foundation DataZone V2 domain (stage={stage})",
        tags=common_tags,
        stage=stage,
        lake_bucket_name=lake.bucket_name_export,
    )
    domain.add_dependency(lake)

    # --- DataZone projects (9 products + 1 smoke-test consumer) ------------
    projects = DataZoneProjectsStack(
        app,
        _stage_name(stage, "datazone-projects"),
        env=env,
        description=(
            f"9 DataZone projects (one per data product) + data-consumer-test "
            f"(stage={stage})"
        ),
        tags=common_tags,
        stage=stage,
        domain_id_export=domain.domain_id_export,
        project_profile_id_export=domain.default_project_profile_id_export,
    )
    projects.add_dependency(domain)

    # --- Governance: Lake Formation + Macie + CloudTrail + IAM IDC ---------
    governance = GovernanceStack(
        app,
        _stage_name(stage, "governance"),
        env=env,
        description=(
            "Lake Formation tag-based access, CloudTrail, IAM Identity "
            f"Center groups (stage={stage})"
        ),
        tags=common_tags,
        stage=stage,
        lake_bucket_arn_export=lake.bucket_arn_export,
        lake_bucket_name=lake.bucket_name_export,
        identity_center_instance_arn=app.node.try_get_context(
            "identity_center_instance_arn"
        ),
        identity_store_id=app.node.try_get_context("identity_store_id"),
        cvx_account_id=(
            app.node.try_get_context("cvxAccountId")
            or os.environ.get("ADP_KB_CVX_ACCOUNT_ID")
        ),
    )
    governance.add_dependency(lake)

    # --- Persistent Spark-ETL IAM role (per spec 2026-06-09-adp-pyspark-glue-products)
    data_products = DataProductsStack(
        app,
        _stage_name(stage, "data-products"),
        env=env,
        description=(
            f"Persistent IAM role for one-shot Glue 4.0 PySpark "
            f"generators (vehicle_telemetry_aggregated + energy_usage) "
            f"(stage={stage})"
        ),
        tags=common_tags,
        stage=stage,
        lake_bucket_name=lake.bucket_name_export,
    )
    data_products.add_dependency(lake)

    # --- Bedrock Knowledge Base + AOSS vector store (Group 5) ----
    vehicle_kb = VehicleKnowledgeBaseStack(
        app,
        _stage_name(stage, 'vehicle-knowledge-base'),
        env=env,
        description=(
            f'ADP foundation Bedrock Knowledge Base + AOSS vector store '
            f'+ ingestion data source (stage={stage})'
        ),
        tags=common_tags,
        stage=stage,
        lake_bucket_name=lake.bucket_name_export,
        lake_kms_key_arn=lake.kms_key.key_arn,
        deploy_role_arn=_resolve_kb_deploy_role_arn(app, env),
        cvx_kb_principals=_resolve_cvx_kb_principals(app),
    )
    vehicle_kb.add_dependency(lake)

    # --- Optional: CMS→ADP ingest (off by default) -------------------------
    if _ctx_bool(app, "enable_cms_ingest"):
        cms_ingest = CmsIngestStack(
            app,
            _stage_name(stage, "cms-ingest"),
            env=env,
            description=(
                f"(Optional) CMS DDB Streams → Firehose → S3 → Glue Iceberg "
                f"ingest (stage={stage})"
            ),
            tags=common_tags,
            stage=stage,
            lake_bucket_name=lake.bucket_name_export,
            cms_vehicle_state_table_arn=app.node.try_get_context(
                "cms_vehicle_state_table_arn"
            ),
        )
        cms_ingest.add_dependency(lake)

    # --- cdk-nag (AwsSolutions ruleset) ------------------------------------
    cdk.Aspects.of(app).add(AwsSolutionsChecks(verbose=True))

    app.synth()


if __name__ == "__main__":
    main()
