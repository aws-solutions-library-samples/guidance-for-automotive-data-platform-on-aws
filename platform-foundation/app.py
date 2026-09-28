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
from stacks.parts_domain_stack import PartsDomainStack
from stacks.dealer_domain_stack import DealerDomainStack


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


def _resolve_dms_kb_principals(app: cdk.App) -> list[str] | None:
    """Resolve DMS KB resource-policy principals via CDK ctx OR env var.

    Mirrors :func:`_resolve_cvx_kb_principals` for the DMS-side principal
    list per spec ``2026-08-26-adp-dealer-domain`` T3.4 / Group 6.
    Order: ``-c dmsKbPrincipals=arn1,arn2`` (comma-split); else env
    ``ADP_KB_DMS_PRINCIPAL_ARNS=arn1,arn2``; else None.

    Context wins if both are set (precedence identical to the CVX resolver).
    """
    raw = app.node.try_get_context('dmsKbPrincipals') or os.environ.get('ADP_KB_DMS_PRINCIPAL_ARNS')
    if not raw:
        return None
    arns = [a.strip() for a in str(raw).split(',') if a.strip()]
    return arns or None


def _resolve_identity_store_id(app: cdk.App) -> str | None:
    """Resolve the IAM Identity Center IdentityStore ID.

    Order:
      1. ``-c identity_store_id=d-...`` from CDK context
      2. ``ADP_IDENTITY_STORE_ID`` env var
      3. Auto-discover via ``aws sso-admin list-instances`` at synth time
         (single-instance-per-account is the AWS-supported topology as of
         2026-08; multi-instance accounts should override via context).
      4. None — governance stack will then skip Identity Center group
         creation entirely (fail-closed, avoids the ``d-XXXXXXXXXX``
         placeholder that CFN now rejects at change-set validation).

    Rationale: the historical default was the string ``d-XXXXXXXXXX``,
    which passes an ``or``-truthy check but fails CFN's IdentityStoreId
    pattern ``^d-[0-9a-f]{10}$``. Any deploy without ``-c identity_store_id=...``
    is blocked at change-set creation on the 3 ``AWS::IdentityStore::Group``
    resources in ``adp-{stage}-foundation-governance``. Empirically hit
    during spec ``2026-08-03-adp-vkb-s3-vectors`` T4A.2 (2026-08-30), which
    forced ``--exclusively adp-prod-foundation-vehicle-knowledge-base`` as
    a bypass. See backlog row ``Governance identity-store`` P2.
    """
    val = app.node.try_get_context('identity_store_id') or os.environ.get('ADP_IDENTITY_STORE_ID')
    if val:
        return str(val).strip() or None
    # Auto-discover from the deploy-time AWS credentials. Skipped in
    # synth-only CI contexts where AWS credentials are absent.
    if not os.environ.get('CDK_DEFAULT_ACCOUNT'):
        return None
    try:
        import boto3  # deferred; only needed at deploy time
        # sso-admin is a global service surfaced regionally; the KB's region
        # (us-east-1) is a safe default that matches this app's env.
        client = boto3.client('sso-admin', region_name='us-east-1')
        resp = client.list_instances()
        instances = resp.get('Instances') or []
        if instances:
            store = instances[0].get('IdentityStoreId')
            if store:
                sys.stderr.write(
                    f"[app.py] identity_store_id auto-discovered via sso-admin.list_instances: {store}\n"
                )
                return store
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(
            f"[app.py] identity_store_id auto-discovery skipped: {exc}\n"
        )
    return None


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
    # and the Lake Formation service-linked role (and any future
    # account-singular resources). NOT part of the per-stage
    # rollout — instantiated unconditionally and NOT a synth-time dependency
    # of any per-stage stack. See ``stacks/shared_bootstrap_stack.py`` for
    # the full contract.
    #
    # The bootstrap stack does NOT inherit ``adp:stage`` because it is
    # account-singular. Tag it with the project/spec/owner subset only.
    #
    # ``-c createLakeFormationSlr=false`` opts out of creating the Lake
    # Formation service-linked role. Default is TRUE because a fresh account
    # NEEDS it before the lake stack can deploy (its KMS key policy names the
    # role as a principal, and KMS rejects policies naming principals that do
    # not exist). Set it false in an account where Lake Formation was already
    # in use before ADP — CloudFormation cannot create a service-linked role
    # that already exists. Run the existence check in docs/DEPLOYMENT.md
    # § "Bootstrap command" to determine the right value for your account.
    bootstrap_tags = {k: v for k, v in common_tags.items() if k != "adp:stage"}
    _raw_slr_flag = app.node.try_get_context("createLakeFormationSlr")
    if _raw_slr_flag is None:
        _create_lf_slr = True
    elif isinstance(_raw_slr_flag, bool):
        _create_lf_slr = _raw_slr_flag
    else:
        _flag = str(_raw_slr_flag).strip().lower()
        # Explicit allowlist on BOTH sides. A permissive `!= "false"` parse made
        # `=0`, `=no`, `=off` and `=` all silently create the role — a bootstrap
        # flag whose wrong value changes the account's identity graph has to
        # reject what it does not understand. Review Cycle 8 W3.
        if _flag in ("false", "0", "no", "off", ""):
            _create_lf_slr = False
        elif _flag in ("true", "1", "yes", "on"):
            _create_lf_slr = True
        else:
            raise ValueError(
                f"createLakeFormationSlr={_raw_slr_flag!r} is not recognised. "
                f"Use true/1/yes/on or false/0/no/off. This flag decides whether "
                f"bootstrap creates the Lake Formation service-linked role, so it "
                f"fails closed rather than guessing."
            )
    SharedBootstrapStack(
        app,
        "adp-shared-bootstrap",
        env=env,
        create_lakeformation_slr=_create_lf_slr,
        description=(
            "ADP account-singular bootstrap (Macie::Session, Lake Formation "
            "service-linked role). Deployed once per account."
        ),
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

    # --- Parts domain (adp_parts_domain) — T3.5 DMS accelerator -----------
    # Decision 1: implemented as a DataZone PROJECT inside the existing single
    # domain (not a new CfnDomain, which is immutable post-create).
    # Decision 2: no glue.CfnTable — tables are created by PySpark generators.
    # Decision 3: access_channel column present for REPAIR Act forward-readiness;
    #             v1 seeds franchise only.
    # Auto Care licensing: ACES/PIES shape only; all IDs are DMS-prefixed synthetic.
    parts_domain = PartsDomainStack(
        app,
        _stage_name(stage, "parts-domain"),
        env=env,
        description=(
            f"ADP adp_parts_domain — ACES 5.0 + PIES 8.0 structured parts data "
            f"(parts_catalog, parts_fitment, parts_interchange). "
            f"DMS accelerator R2a. Synthetic IDs only; no licensed Auto Care data. "
            f"(stage={stage})"
        ),
        tags={**common_tags, "adp:domain": "parts"},
        stage=stage,
        domain_id=domain.domain_id_export,
        project_profile_id=domain.default_project_profile_id_export,
        lake_bucket_name=lake.bucket_name_export,
    )
    parts_domain.add_dependency(domain)
    parts_domain.add_dependency(lake)

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
        identity_store_id=_resolve_identity_store_id(app),
        cvx_account_id=(
            app.node.try_get_context("cvxAccountId")
            or os.environ.get("ADP_KB_CVX_ACCOUNT_ID")
        ),
        dms_account_id=(
            app.node.try_get_context("dmsAccountId")
            or os.environ.get("ADP_KB_DMS_ACCOUNT_ID")
        ),
        cms_account_id=(
            app.node.try_get_context("cmsAccountId")
            or os.environ.get("ADP_CMS_ACCOUNT_ID")
        ),
        # The CMS consuming role ARN. Same-account, a `:root` grant confers
        # nothing on an individual role, so this is the grant that actually
        # authorizes the Fleet Intelligence Lambda's Athena reads. Optional:
        # unset means no role grant is issued, which is the pre-2026-09-13
        # behaviour. See GovernanceStack._grant_cms_consumer_role.
        cms_consumer_role_arn=(
            app.node.try_get_context("cmsConsumerRoleArn")
            or os.environ.get("ADP_CMS_CONSUMER_ROLE_ARN")
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

    # --- Dealer domain (DMS accelerator v1, Group 3) -----------------------
    # Creates the adp_{stage}_dealer_domain Glue database, a DataZone project
    # inside the existing domain, and a region-suffixed Glue-job IAM role for
    # the 5 dealer-operations data products. No CfnTable -- tables are created
    # by one-shot Glue/PySpark generators per closed spec
    # 2026-06-09-adp-pyspark-glue-products.
    dealer_domain = DealerDomainStack(
        app,
        _stage_name(stage, "dealer-domain"),
        env=env,
        description=(
            f"ADP dealer domain — DataZone project + Glue database + IAM role "
            f"for 5 DMS accelerator data products (stage={stage})"
        ),
        tags={**common_tags, "adp:domain": "dealer"},
        stage=stage,
        lake_bucket_name=lake.bucket_name_export,
        domain_id_export=domain.domain_id_export,
        project_profile_id_export=domain.default_project_profile_id_export,
    )
    dealer_domain.add_dependency(lake)
    dealer_domain.add_dependency(domain)

    # --- Bedrock Knowledge Base + Amazon S3 Vectors store ------
    # Storage swapped from OpenSearch Serverless to Amazon S3 Vectors
    # per spec `2026-08-03-adp-vkb-s3-vectors`.
    vehicle_kb = VehicleKnowledgeBaseStack(
        app,
        _stage_name(stage, 'vehicle-knowledge-base'),
        env=env,
        description=(
            f'ADP foundation Bedrock Knowledge Base + Amazon S3 Vectors store '
            f'+ ingestion data source (stage={stage})'
        ),
        tags=common_tags,
        stage=stage,
        lake_bucket_name=lake.bucket_name_export,
        lake_kms_key_arn=lake.kms_key.key_arn,
        cvx_kb_principals=_resolve_cvx_kb_principals(app),
        dms_kb_principals=_resolve_dms_kb_principals(app),
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
