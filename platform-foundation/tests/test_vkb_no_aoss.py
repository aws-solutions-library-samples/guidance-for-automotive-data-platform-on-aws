"""AOSS-retirement negative-path test skeletons — spec 2026-08-03-adp-vkb-s3-vectors T1.3.

Tests 13-15 from spec.md § Test plan. These guard that, after the S3 Vectors
migration, every OpenSearch Serverless resource and the AOSS index-bootstrap
Custom Resource have been fully removed from the synthesised template.

No template cache is used here — each of the 3 tests builds a fresh Template
(no shared mutable state, and the 3-test run-cost is trivial vs the safety
property being asserted).
"""

from __future__ import annotations

import sys
import os

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stacks.vehicle_knowledge_base_stack import VehicleKnowledgeBaseStack

_PLACEHOLDER_ACCOUNT = "123456789012"
_REGION = "us-east-1"


def _make_template(principals=None, stage="staging") -> Template:
    """Construct a fresh VehicleKnowledgeBaseStack and return its Template.

    Per spec.md § Decision (I), the ``deploy_role_arn`` constructor kwarg has
    been dropped from VehicleKnowledgeBaseStack.  This helper does NOT pass it.
    No caching — each call produces an independent Template instance.
    """
    app = cdk.App()
    bucket_name = f"adp-{stage}-foundation-lake-{_PLACEHOLDER_ACCOUNT}-{_REGION}"
    lake_kms_key_arn = (
        f"arn:aws:kms:{_REGION}:{_PLACEHOLDER_ACCOUNT}:"
        f"key/00000000-0000-0000-0000-000000000000"
    )
    stack = VehicleKnowledgeBaseStack(
        app,
        f"adp-{stage}-foundation-vehicle-knowledge-base",
        stage=stage,
        lake_bucket_name=bucket_name,
        lake_kms_key_arn=lake_kms_key_arn,
        cvx_kb_principals=principals,
        env=cdk.Environment(account=_PLACEHOLDER_ACCOUNT, region=_REGION),
    )
    return Template.from_stack(stack)


# ---------------------------------------------------------------------------
# Test 13 — spec.md § Test plan #13
# ---------------------------------------------------------------------------

def test_zero_aoss_resources_in_template():
    """All three OpenSearch Serverless resource types must be absent (count = 0)."""
    tmpl = _make_template()
    tmpl.resource_count_is("AWS::OpenSearchServerless::SecurityPolicy", 0)
    tmpl.resource_count_is("AWS::OpenSearchServerless::Collection", 0)
    tmpl.resource_count_is("AWS::OpenSearchServerless::AccessPolicy", 0)


# ---------------------------------------------------------------------------
# Test 14 — spec.md § Test plan #14
# ---------------------------------------------------------------------------

def test_zero_custom_resources_for_index_bootstrap():
    """No Custom::AWS and no AWS::CloudFormation::CustomResource resources remain."""
    tmpl = _make_template()
    tmpl.resource_count_is("AWS::CloudFormation::CustomResource", 0)
    custom_aws = tmpl.find_resources("Custom::AWS")
    assert not any(
        "IndexName" in v.get("Properties", {}) for v in custom_aws.values()
    ), f"Found Custom::AWS with IndexName property: {custom_aws}"


# ---------------------------------------------------------------------------
# Test 15 — spec.md § Test plan #15
# ---------------------------------------------------------------------------

def test_kb_role_has_no_aoss_action():
    """No IAM policy statement in the template may contain any 'aoss:' action."""
    tmpl = _make_template()
    policies = tmpl.find_resources("AWS::IAM::Policy")
    for logical_id, resource in policies.items():
        statements = (
            resource.get("Properties", {})
            .get("PolicyDocument", {})
            .get("Statement", [])
        )
        for stmt in statements:
            actions = stmt.get("Action", [])
            # Action may be a single string or a list of strings
            if isinstance(actions, str):
                actions = [actions]
            for action in actions:
                assert not str(action).startswith("aoss:"), (
                    f"Policy {logical_id} contains forbidden aoss: action '{action}' "
                    f"in statement: {stmt}"
                )
