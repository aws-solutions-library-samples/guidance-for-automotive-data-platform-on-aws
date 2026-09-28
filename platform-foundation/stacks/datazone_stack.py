"""ADP foundation DataZone V2 domain stack.

Provisions a single DataZone V2 domain with IAM Identity Center SSO,
a default project profile, and the standard Tooling + MLExperiments
blueprint enablement (handled by the projects stack). Deploys
per-stage; staging and prod each get their own domain (design §2.4,
§3 "Duplicated").

Layered design rationale
------------------------
The IAM trust + permission policies for the domain execution role
and the domain service role mirror the working CFN template at
``cloudformation/datazone-domain.yaml``. We re-implement them in CDK
(rather than wrapping the CFN template) so:

1. ``cdk-nag`` can inspect every IAM statement at synth time.
2. Per-resource suppressions live alongside the policy statements
   they justify, instead of in YAML comments.
3. Future SCP / boundary attachments are first-class CDK constructs.

Domain name
-----------
The domain is named ``adp-{stage}-foundation-domain`` per design §2.4.
``CfnDomain.name`` is immutable post-create; staging and prod domains
co-exist via the stage prefix.

Identity Center
---------------
The IDC instance ARN is supplied via context flag. Default in
``cdk.json`` is ``null``; if not provided at deploy time, the stack
synthesizes without the SingleSignOn block, leaving the domain in
"IAM principals" mode for early prototyping. Production deploys
should always pass the IDC ARN.
"""

from __future__ import annotations

from typing import Optional

from aws_cdk import (
    Aws,
    CfnOutput,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_datazone as datazone
from aws_cdk import aws_iam as iam
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks._naming import _stage_name, validate_stage


# Auto-discovered for the user's account (sso-admin list-instances).
# Override at deploy time via:  -c identity_center_instance_arn=arn:aws:sso:::instance/...
_DEFAULT_IDC_INSTANCE_ARN = "arn:aws:sso:::instance/ssoins-7223ca64466274fc"


class DataZoneStack(Stack):
    """DataZone V2 domain + execution/service roles + default project profile."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        lake_bucket_name: str,
        identity_center_instance_arn: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        validate_stage(stage)
        self.stage = stage

        idc_arn = identity_center_instance_arn or _DEFAULT_IDC_INSTANCE_ARN

        # Source-account condition for service-principal trust (defense in depth
        # against the confused-deputy pattern).
        _source_acct_condition = {
            "StringEquals": {"aws:SourceAccount": Aws.ACCOUNT_ID}
        }

        # Per-stage Glue ARN scope (stage-isolated execution role only sees
        # its own stage's databases/tables — design §3 "Duplicated").
        _glue_db_arn_pattern = (
            f"arn:aws:glue:{Aws.REGION}:{Aws.ACCOUNT_ID}:database/adp_{stage}_*"
        )
        _glue_tbl_arn_pattern = (
            f"arn:aws:glue:{Aws.REGION}:{Aws.ACCOUNT_ID}:table/adp_{stage}_*/*"
        )

        # --- Domain execution role -----------------------------------------
        execution_role = iam.Role(
            self,
            "DomainExecutionRole",
            role_name=_stage_name(stage, "datazone-execution-role"),
            assumed_by=iam.CompositePrincipal(
                iam.ServicePrincipal(
                    "datazone.amazonaws.com",
                    conditions=_source_acct_condition,
                ),
                iam.ServicePrincipal(
                    "sagemaker.amazonaws.com",
                    conditions=_source_acct_condition,
                ),
                iam.ServicePrincipal(
                    "lakeformation.amazonaws.com",
                    conditions=_source_acct_condition,
                ),
                iam.ServicePrincipal(
                    "glue.amazonaws.com",
                    conditions=_source_acct_condition,
                ),
            ),
        )

        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="SageMakerAccess",
                actions=[
                    "sagemaker:Describe*",
                    "sagemaker:List*",
                    "sagemaker:Search",
                    "sagemaker:CreateDomain",
                    "sagemaker:CreateUserProfile",
                    "sagemaker:CreateApp",
                    "sagemaker:DeleteDomain",
                    "sagemaker:DeleteUserProfile",
                    "sagemaker:DeleteApp",
                ],
                resources=[f"arn:aws:sagemaker:{Aws.REGION}:{Aws.ACCOUNT_ID}:*"],
            )
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="LakeBucketAccess",
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:ListBucket",
                    "s3:GetBucketLocation",
                ],
                resources=[
                    f"arn:aws:s3:::{lake_bucket_name}",
                    f"arn:aws:s3:::{lake_bucket_name}/*",
                    f"arn:aws:s3:::datazone-*-{Aws.ACCOUNT_ID}",
                    f"arn:aws:s3:::datazone-*-{Aws.ACCOUNT_ID}/*",
                ],
            )
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="GlueCatalogAccess",
                actions=[
                    "glue:GetDatabase*",
                    "glue:GetTable*",
                    "glue:GetPartition*",
                    "glue:BatchGetPartition",
                    "glue:CreateDatabase",
                    "glue:CreateTable",
                    "glue:UpdateDatabase",
                    "glue:UpdateTable",
                ],
                resources=[
                    f"arn:aws:glue:{Aws.REGION}:{Aws.ACCOUNT_ID}:catalog",
                    _glue_db_arn_pattern,
                    _glue_tbl_arn_pattern,
                ],
            )
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="AthenaAccess",
                actions=[
                    "athena:GetQueryExecution",
                    "athena:GetQueryResults",
                    "athena:StartQueryExecution",
                    "athena:GetWorkGroup",
                ],
                resources=[
                    f"arn:aws:athena:{Aws.REGION}:{Aws.ACCOUNT_ID}:workgroup/*"
                ],
            )
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="LakeFormationAccess",
                actions=[
                    "lakeformation:GetDataAccess",
                    "lakeformation:GrantPermissions",
                    "lakeformation:RevokePermissions",
                    "lakeformation:RegisterResource",
                    "lakeformation:DeregisterResource",
                ],
                resources=["*"],  # Lake Formation requires wildcard; cdk-nag suppression below
            )
        )
        execution_role.add_to_policy(
            iam.PolicyStatement(
                sid="DataZoneSelfAccess",
                actions=[
                    "datazone:Get*",
                    "datazone:List*",
                    "datazone:CreateEnvironment",
                    "datazone:DeleteEnvironment",
                    "datazone:CreateProject",
                    "datazone:DeleteProject",
                ],
                resources=["*"],  # DataZone requires wildcard; cdk-nag suppression below
            )
        )

        # --- Domain service role -------------------------------------------
        service_role = iam.Role(
            self,
            "DomainServiceRole",
            role_name=_stage_name(stage, "datazone-service-role"),
            assumed_by=iam.ServicePrincipal(
                "datazone.amazonaws.com",
                conditions=_source_acct_condition,
            ),
        )

        service_role.add_to_policy(
            iam.PolicyStatement(
                sid="DataZoneDomain",
                actions=[
                    "datazone:Get*",
                    "datazone:List*",
                    "datazone:CreateDomain",
                    "datazone:DeleteDomain",
                    "datazone:UpdateDomain",
                ],
                resources=["*"],
            )
        )
        service_role.add_to_policy(
            iam.PolicyStatement(
                sid="SsoDescribe",
                actions=[
                    "sso:DescribeInstance",
                    "sso:ListInstances",
                    "sso:GetApplicationAssignmentConfiguration",
                    "sso:ListApplicationAssignments",
                ],
                resources=[idc_arn],
            )
        )
        service_role.add_to_policy(
            iam.PolicyStatement(
                sid="IdentityStoreLookup",
                actions=[
                    "identitystore:DescribeUser",
                    "identitystore:DescribeGroup",
                    "identitystore:ListUsers",
                    "identitystore:ListGroups",
                ],
                resources=["*"],  # IdentityStore requires wildcard
            )
        )

        # --- DataZone V2 domain --------------------------------------------
        sso_block = (
            datazone.CfnDomain.SingleSignOnProperty(
                idc_instance_arn=idc_arn,
                type="IAM_IDC",
                user_assignment="AUTOMATIC",
            )
            if idc_arn
            else None
        )

        self.domain = datazone.CfnDomain(
            self,
            "Domain",
            name=_stage_name(stage, "domain"),
            description=(
                f"ADP foundational data platform — EV-startup data products "
                f"(stage={stage})"
            ),
            domain_execution_role=execution_role.role_arn,
            service_role=service_role.role_arn,
            domain_version="V2",
            single_sign_on=sso_block,
        )
        self.domain.apply_removal_policy(RemovalPolicy.RETAIN)

        # --- Default project profile ---------------------------------------
        self.default_project_profile = datazone.CfnProjectProfile(
            self,
            "DefaultProjectProfile",
            domain_identifier=self.domain.attr_id,
            domain_unit_identifier=self.domain.attr_root_domain_unit_id,
            name=_stage_name(stage, "default-profile"),
            description=f"Default project profile for ADP foundation product projects (stage={stage})",
            status="ENABLED",
        )

        # Outputs (stage-prefixed export names per design §2.11)
        CfnOutput(
            self,
            "DomainId",
            value=self.domain.attr_id,
            export_name=_stage_name(stage, "datazone-domain-id"),
        )
        CfnOutput(
            self,
            "DomainArn",
            value=self.domain.attr_arn,
            export_name=_stage_name(stage, "datazone-domain-arn"),
        )
        CfnOutput(
            self,
            "DomainPortalUrl",
            value=self.domain.attr_portal_url,
            export_name=_stage_name(stage, "datazone-portal-url"),
        )
        CfnOutput(
            self,
            "DomainRootUnitId",
            value=self.domain.attr_root_domain_unit_id,
            export_name=_stage_name(stage, "datazone-root-unit-id"),
        )
        CfnOutput(
            self,
            "DefaultProjectProfileId",
            value=self.default_project_profile.attr_id,
            export_name=_stage_name(stage, "datazone-default-profile-id"),
        )

        # cdk-nag suppressions: documented wildcards required by AWS service APIs.
        NagSuppressions.add_resource_suppressions(
            execution_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Lake Formation, DataZone, and Glue resource ARNs require "
                        "wildcards for Get/Grant/Revoke. Resources are scoped to "
                        "this account by the assume-role trust condition "
                        "(aws:SourceAccount). Glue ARNs are scoped to "
                        f"adp_{stage}_* databases (per-stage isolation). SageMaker "
                        "resources are scoped by account+region."
                    ),
                    "applies_to": [
                        "Resource::*",
                        "Resource::arn:aws:sagemaker:<AWS::Region>:<AWS::AccountId>:*",
                        f"Resource::arn:aws:s3:::datazone-*-<AWS::AccountId>",
                        f"Resource::arn:aws:s3:::datazone-*-<AWS::AccountId>/*",
                        "Resource::arn:aws:athena:<AWS::Region>:<AWS::AccountId>:workgroup/*",
                        f"Resource::arn:aws:glue:<AWS::Region>:<AWS::AccountId>:database/adp_{stage}_*",
                        f"Resource::arn:aws:glue:<AWS::Region>:<AWS::AccountId>:table/adp_{stage}_*/*",
                    ],
                },
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            service_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "DataZone CreateDomain/UpdateDomain require resource:* per "
                        "AWS docs. IdentityStore Describe* require wildcard. SSO "
                        "instance ARN is scoped explicitly for sso:* actions."
                    ),
                    "applies_to": ["Resource::*"],
                },
            ],
            apply_to_children=True,
        )

        self._domain_id_export = self.domain.attr_id
        self._default_project_profile_id_export = self.default_project_profile.attr_id

    @property
    def domain_id_export(self) -> str:
        """The DataZone domain identifier, suitable for cross-stack reference."""
        return self._domain_id_export

    @property
    def default_project_profile_id_export(self) -> str:
        """The default project profile id, required by every CfnProject in V2."""
        return self._default_project_profile_id_export
