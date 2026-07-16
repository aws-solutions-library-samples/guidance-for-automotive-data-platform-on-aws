"""ADP foundation DataZone projects stack — 9 products + 1 smoke-test consumer.

Creates one DataZone project per published data product. Each project
later gains a Glue-data-source association (Group 3) and an asset
publication (Group 3) so the catalog asset is discoverable by
subscribers.

Project list comes from spec.md "Data product catalog" — single
source of truth. Display names match the PRD's user-facing names.

Per ``staging-prod-design.md`` §2.5 Option A:

- **Technical names** (the snake_case ``CfnProject.name`` field —
  e.g., ``vehicle_telemetry_aggregated``) are **UNCHANGED across
  stages**. Two stage domains can use identical technical names
  because DataZone projects are scoped within their domain.
- **Display names** get a ``[Staging]`` suffix on staging and NO
  suffix on prod (prod is the canonical; staging is the variant —
  asymmetric on purpose per design §2.5 to match operator mental
  model). Display name lives at the start of the project's
  ``description`` field (DataZone V2 ``CfnProject`` has no separate
  display-name attribute; the team's convention prefixes the
  description with the human-readable display name).
- **CFN export names** are stage-prefixed via
  :func:`stacks._naming._stage_name` so the two stages don't fight
  for the same export within the same account+region.
"""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_datazone as datazone
from constructs import Construct

from stacks._naming import _stage_name, validate_stage


# (technical_name, display_name, description)
DATA_PRODUCT_PROJECTS: list[tuple[str, str, str]] = [
    (
        "vehicle_telemetry_aggregated",
        "Vehicle Telemetry (Aggregated)",
        "Per-VIN time-windowed aggregate telemetry rollups (rolling 90 days).",
    ),
    (
        "vehicle_identity",
        "Vehicle Identity Graph",
        "VIN → make/model/trim/build → suppliers → parts.",
    ),
    (
        "charging_sessions",
        "Charging Sessions",
        "EV charging sessions (home + public DC fast + destination L2).",
    ),
    (
        "energy_usage",
        "Energy Usage",
        "Per-VIN per-day battery and energy metrics (90-day window).",
    ),
    (
        "ota_campaigns",
        "OTA Campaigns",
        "Software OTA campaigns (header) and per-VIN dispatch events.",
    ),
    (
        "customer_360",
        "Customer 360",
        "Customer profile snapshots with health and churn scores.",
    ),
    (
        "customer_interactions",
        "Customer Interactions",
        "Customer interactions across dealer/service/app/web/call channels.",
    ),
    (
        "service_records",
        "Service Records",
        "Service records joining VIN, customer, dealer, parts.",
    ),
    (
        "vehicle_knowledge_base",
        "Vehicle Knowledge Base",
        "Knowledge artifacts seeded into Bedrock KB (DTC, TSBs, manuals, etc.).",
    ),
]

# Smoke-test consumer project used by ``scripts/smoke-test-subscription.sh``
SMOKE_TEST_PROJECT_TECHNICAL = "data_consumer_test"
SMOKE_TEST_PROJECT_DISPLAY = "Data Consumer Test"
SMOKE_TEST_PROJECT_DESCRIPTION = (
    "End-to-end DataZone subscription smoke-test consumer. Subscribes "
    "to vehicle_telemetry_aggregated and runs an Athena query."
)


class DataZoneProjectsStack(Stack):
    """One DataZone project per data product + 1 smoke-test consumer."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        domain_id_export: str,
        project_profile_id_export: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        validate_stage(stage)
        self.stage = stage

        # Per design §2.5 Option A: prod is the canonical display name;
        # staging gets a human-readable ``[Staging]`` indicator appended to
        # the display name. Technical names (CfnProject.name) stay
        # unchanged across stages — only the display-name portion of the
        # description gets the suffix. Prod has NO ``[Prod]`` suffix
        # (asymmetric on purpose to match operator mental model).
        display_name_suffix = " [Staging]" if stage == "staging" else ""

        # Per-stage description parenthetical (operator clarity in the
        # DataZone portal). This is in addition to — and distinct from —
        # the display-name suffix above.
        stage_description_suffix = f" (stage={stage})"

        self.projects: dict[str, datazone.CfnProject] = {}

        for technical, display, description in DATA_PRODUCT_PROJECTS:
            project = datazone.CfnProject(
                self,
                f"Project{_pascal(technical)}",
                domain_identifier=domain_id_export,
                # Technical name UNCHANGED across stages per design §2.5 Option A.
                name=technical,
                description=(
                    f"{display}{display_name_suffix} — {description}"
                    f"{stage_description_suffix}"
                ),
                project_profile_id=project_profile_id_export,
            )
            project.apply_removal_policy(RemovalPolicy.RETAIN)
            self.projects[technical] = project

        # Smoke-test consumer project (technical name unchanged across stages;
        # display name gets the same ``[Staging]`` treatment per A4 constraint).
        self.smoke_test_project = datazone.CfnProject(
            self,
            f"Project{_pascal(SMOKE_TEST_PROJECT_TECHNICAL)}",
            domain_identifier=domain_id_export,
            name=SMOKE_TEST_PROJECT_TECHNICAL,
            description=(
                f"{SMOKE_TEST_PROJECT_DISPLAY}{display_name_suffix} — "
                f"{SMOKE_TEST_PROJECT_DESCRIPTION}{stage_description_suffix}"
            ),
            project_profile_id=project_profile_id_export,
        )
        self.smoke_test_project.apply_removal_policy(RemovalPolicy.RETAIN)

        # Outputs — one per project + the consumer (stage-prefixed export names)
        for technical, project in self.projects.items():
            CfnOutput(
                self,
                f"ProjectId{_pascal(technical)}",
                value=project.attr_id,
                export_name=_stage_name(
                    stage, f"datazone-project-{technical.replace('_', '-')}-id"
                ),
            )
        CfnOutput(
            self,
            "SmokeTestProjectId",
            value=self.smoke_test_project.attr_id,
            export_name=_stage_name(
                stage,
                f"datazone-project-{SMOKE_TEST_PROJECT_TECHNICAL.replace('_', '-')}-id",
            ),
        )


def _pascal(s: str) -> str:
    return "".join(part.capitalize() for part in s.split("_"))
