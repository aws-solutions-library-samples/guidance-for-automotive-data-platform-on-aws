"""T2.4 — LF cross-account grant + CloudTrail Bedrock KB event selector tests.

Spec: ~/automotive-data-platform-on-aws/.kiro/specs/2026-06-09-adp-kb-cross-account-grants/
"""

from __future__ import annotations

import os
import sys

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

# Ensure stacks package is importable from test runner.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stacks.governance_stack import GovernanceStack

_STAGE = "staging"
_CVX_ACCOUNT = "123456789012"  # AWS docs placeholder; never a real account.
_FAKE_LAKE_ARN = "arn:aws:s3:::adp-staging-foundation-lake-000000000000-us-east-1"
_FAKE_LAKE_NAME = "adp-staging-foundation-lake-000000000000-us-east-1"


def _make_template(cvx_account_id: str | None) -> Template:
    app = cdk.App()
    stack = GovernanceStack(
        app,
        "TestGovernance",
        stage=_STAGE,
        lake_bucket_arn_export=_FAKE_LAKE_ARN,
        lake_bucket_name=_FAKE_LAKE_NAME,
        cvx_account_id=cvx_account_id,
        env=cdk.Environment(account="000000000000", region="us-east-1"),
    )
    return Template.from_stack(stack)


# (a) cvxAccountId set → LF resource, DataLakeSettings v4, ≥1 PrincipalPermissions
def test_lf_resources_present_when_cvx_account_set():
    tmpl = _make_template(_CVX_ACCOUNT)

    # LF bucket resource registered
    tmpl.resource_count_is("AWS::LakeFormation::Resource", 1)
    tmpl.has_resource_properties(
        "AWS::LakeFormation::Resource",
        {"UseServiceLinkedRole": True},
    )

    # DataLakeSettings is INTENTIONALLY NOT created by CDK (security-review
    # cycle 1: AWS PutDataLakeSettings replaces the admin list, would silently
    # drop existing admins). It's a manual prerequisite step now.
    tmpl.resource_count_is("AWS::LakeFormation::DataLakeSettings", 0)

    # At least one PrincipalPermissions grant issued
    resources = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
    assert len(resources) >= 1, "Expected ≥1 AWS::LakeFormation::PrincipalPermissions"


# (b) cvxAccountId absent → no LF cross-account resources
def test_no_lf_cross_account_resources_without_cvx_account():
    tmpl = _make_template(None)

    tmpl.resource_count_is("AWS::LakeFormation::Resource", 0)
    tmpl.resource_count_is("AWS::LakeFormation::DataLakeSettings", 0)
    tmpl.resource_count_is("AWS::LakeFormation::PrincipalPermissions", 0)


# (c) CloudTrail trail has Bedrock::KnowledgeBase in its advanced event selector
def test_cloudtrail_trail_has_bedrock_kb_event_selector():
    tmpl = _make_template(None)  # CloudTrail config is independent of cvxAccountId

    trails = tmpl.find_resources("AWS::CloudTrail::Trail")
    assert trails, "Expected AWS::CloudTrail::Trail resource"

    trail_props = next(iter(trails.values()))["Properties"]
    advanced_selectors = trail_props.get("AdvancedEventSelectors", [])

    kb_selector_found = any(
        any(
            fs.get("Field") == "resources.type"
            and "AWS::Bedrock::KnowledgeBase" in (fs.get("Equals") or [])
            for fs in selector.get("FieldSelectors", [])
        )
        for selector in advanced_selectors
    )
    assert kb_selector_found, (
        "Expected AdvancedEventSelector with resources.type=AWS::Bedrock::KnowledgeBase"
    )


# (d) Permissions are SELECT+DESCRIBE only; permissions_with_grant_option is empty
def test_permissions_are_select_describe_only():
    tmpl = _make_template(_CVX_ACCOUNT)

    grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
    assert grants, "Expected AWS::LakeFormation::PrincipalPermissions resources"

    for logical_id, resource in grants.items():
        props = resource["Properties"]
        perms = set(props.get("Permissions", []))
        assert perms == {"SELECT", "DESCRIBE"}, (
            f"{logical_id}: expected {{SELECT, DESCRIBE}}, got {perms}"
        )
        grant_opt = props.get("PermissionsWithGrantOption", [])
        assert grant_opt == [], (
            f"{logical_id}: PermissionsWithGrantOption must be empty, got {grant_opt}"
        )
