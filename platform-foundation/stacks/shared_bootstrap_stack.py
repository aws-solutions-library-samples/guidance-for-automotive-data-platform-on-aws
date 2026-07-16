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
from aws_cdk import aws_macie as macie
from constructs import Construct


class SharedBootstrapStack(Stack):
    """Account-singular bootstrap resources (Macie session today)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
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
