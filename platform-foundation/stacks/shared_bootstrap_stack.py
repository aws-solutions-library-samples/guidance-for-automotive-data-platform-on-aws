"""ADP shared bootstrap stack — account-singular, stage-agnostic resources.

This stack is deployed **once per account** via ``make bootstrap`` and
is **not** part of the per-stage rollout. It owns AWS resources that
are account-singular by definition and would conflict if both stages
attempted to create them (per ``staging-prod-design.md`` §3 "Resources
that look shared but are duplicated" / §3 "Proposed shared-resource
boundary"). Currently this is just the AWS Macie account-level
session; future account-singular resources can be added here.

Design notes
------------
- The stack name is ``adp-shared-bootstrap`` (no ``{stage}`` segment).
- ``app.py`` instantiates this stack **unconditionally** — outside the
  per-stage loop and without a ``stage`` context value.
- Per-stage stacks (governance, lake, etc.) MUST NOT import this
  stack's outputs via ``Fn::ImportValue``. The contract is "deployed
  once, assumed live" — there is no synth-time coupling.
- The Macie ``CfnSession`` carries ``RemovalPolicy.RETAIN``. AWS
  enforces a 30-day deletion cool-down on Macie sessions (see
  https://docs.aws.amazon.com/macie/latest/user/macie-disable.html);
  retaining the resource on stack churn avoids accidentally tripping
  the cool-down and leaving Macie unusable until it expires.
- The per-stage Macie classification *job* (created post-deploy by
  ``scripts/macie-create-job.sh``) is independent of this stack and
  remains scoped to its stage's lake bucket.
"""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_iam as iam
from aws_cdk import aws_macie as macie
from constructs import Construct


class SharedBootstrapStack(Stack):
    """Account-singular bootstrap resources (Macie session, Lake Formation SLR)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        create_lakeformation_slr: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Macie account-level session -----------------------------------
        # Macie is enabled at the account level here; per-stage classification
        # jobs are created post-deploy by ``scripts/macie-create-job.sh`` and
        # live with each stage's governance stack (job orchestration only —
        # no CFN resource for ``ClassificationJob``).
        #
        # ``finding_publishing_frequency`` is held at ``FIFTEEN_MINUTES`` to
        # match the prior governance-stack behavior; ``status`` is ``ENABLED``
        # so Macie discovers PII as soon as the per-stage job runs.
        self.macie_session = macie.CfnSession(
            self,
            "MacieSession",
            finding_publishing_frequency="FIFTEEN_MINUTES",
            status="ENABLED",
        )
        # 30-day cool-down on Macie session deletion — RETAIN avoids tripping
        # it during stack churn (per the design doc §3 / task A1 constraints).
        self.macie_session.apply_removal_policy(RemovalPolicy.RETAIN)

        # Human-readable confirmation surfaced in the CFN console. No per-stage
        # stack imports this — it exists for operators only.
        CfnOutput(
            self,
            "MacieSessionStatus",
            value="ENABLED",
            export_name="adp-shared-bootstrap-macie-session-status",
            description="Macie account-level session status (deployed by adp-shared-bootstrap).",
        )

        # --- Lake Formation service-linked role ----------------------------
        # Account-singular by definition, same as the Macie session above, and
        # here for the same reason: it would conflict if two stages tried to
        # create it.
        #
        # WHY IT HAS TO EXIST BEFORE THE LAKE STACK. FoundationStack's LakeKey
        # policy names this role as a principal so Lake Formation can WRITE
        # encrypted objects (kms:GenerateDataKey). **KMS validates that
        # key-policy principals exist** and rejects the policy otherwise with
        # ``MalformedPolicyDocumentException: Policy contains a statement with
        # one or more invalid principals.`` That was confirmed empirically
        # against a throwaway key, not assumed.
        #
        # Nothing else creates it in time. It is otherwise a side effect of
        # GovernanceStack's ``use_service_linked_role=True`` registration, and
        # ``app.py`` declares ``governance.add_dependency(lake)`` — so governance
        # runs AFTER lake and the ordering is inverted. It cannot be fixed by
        # reordering those two, because the lake bucket must exist before it can
        # be registered.
        #
        # This can fire in a fresh account that has never used Lake Formation —
        # the SLR must exist before the lake stack registers its bucket.
        # A fresh account that has never used Lake Formation would fail on the
        # lake stack's first deploy without this. Found by review Cycle 7 (C1);
        # see issues/2026-09-20-group4-three-stacked-blockers/.
        #
        # Consistent with this stack's stated contract — "deployed once, assumed
        # live", no synth-time coupling — ordering is enforced OPERATIONALLY by
        # ``make bootstrap`` preceding the per-stage rollout, not by a CFN
        # dependency. Per-stage stacks still import nothing from here.
        #
        # RETAIN because the role is account-scoped and other consumers (any
        # other Lake Formation use in the account) depend on it outliving this
        # stack.
        self.lakeformation_slr = None
        if create_lakeformation_slr:
            self.lakeformation_slr = iam.CfnServiceLinkedRole(
                self,
                "LakeFormationServiceLinkedRole",
                aws_service_name="lakeformation.amazonaws.com",
                description=(
                    "Lake Formation data access. Required by adp-{stage}-foundation-lake's "
                    "LakeKey policy, which names it as a principal for kms:GenerateDataKey."
                ),
            )
            self.lakeformation_slr.apply_removal_policy(RemovalPolicy.RETAIN)

            CfnOutput(
                self,
                "LakeFormationSlrCreated",
                value="true",
                export_name="adp-shared-bootstrap-lakeformation-slr",
                description=(
                    "Lake Formation service-linked role created by bootstrap. "
                    "Prerequisite for the lake stack's KMS key policy."
                ),
            )
