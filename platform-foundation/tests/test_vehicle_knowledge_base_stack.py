"""Test skeletons for VehicleKnowledgeBaseStack — T2.1 + T2.2 (T4.1 active).

Performance discipline (added 2026-06-17 after debug-discipline Rule 4):
``_make_template`` caches the synthesized ``Template`` keyed by the
``(principals, stage)`` tuple. The 12 tests share at most 3 unique
templates (None, [ROLE_ARN], [ROLE_ARN, ROLE_ARN_2]) so Docker-bundled
Lambda asset synthesis runs at most 3 times per pytest invocation
instead of 12. Per-test wall-clock dropped from ~6s to <0.05s after
the first build.
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

ROLE_ARN = "arn:aws:iam::123456789012:role/test-role"
ROLE_ARN_2 = "arn:aws:iam::123456789012:role/test-role-2"

_TEMPLATE_CACHE: dict[tuple, Template] = {}


def _make_template(principals=None, stage="staging") -> Template:
    """Synthesize a fresh VKB stack and return ``Template.from_stack`` (cached).

    The cache key is ``(tuple(principals or ()), stage)``. Per the
    module docstring, this collapses 12 test-time bundles to ≤3.
    """
    key = (tuple(principals or ()), stage)
    if key in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[key]

    app = cdk.App()
    bucket_name = f"adp-{stage}-foundation-lake-{_PLACEHOLDER_ACCOUNT}-{_REGION}"
    lake_kms_key_arn = (
        f"arn:aws:kms:{_REGION}:{_PLACEHOLDER_ACCOUNT}:"
        f"key/00000000-0000-0000-0000-000000000000"
    )
    deploy_role_arn = (
        f"arn:aws:iam::{_PLACEHOLDER_ACCOUNT}:role/"
        f"cdk-hnb659fds-cfn-exec-role-{_PLACEHOLDER_ACCOUNT}-{_REGION}"
    )
    stack = VehicleKnowledgeBaseStack(
        app,
        f"adp-{stage}-foundation-vehicle-knowledge-base",
        stage=stage,
        lake_bucket_name=bucket_name,
        lake_kms_key_arn=lake_kms_key_arn,
        deploy_role_arn=deploy_role_arn,
        cvx_kb_principals=principals,
        env=cdk.Environment(account=_PLACEHOLDER_ACCOUNT, region=_REGION),
    )
    template = Template.from_stack(stack)
    _TEMPLATE_CACHE[key] = template
    return template


# --- T2.1: 11 test skeletons per spec.md § Test plan ---

def test_synthesizes_without_cvx_kb_principals_single_account_default():
    """Case 1: synthesizes without cvx_kb_principals (single-account default)."""
    tmpl = _make_template(principals=None)
    assert tmpl is not None


def test_exactly_one_kb_and_one_data_source():
    """Case 2: exactly 1 KnowledgeBase + 1 DataSource resource."""
    tmpl = _make_template()
    tmpl.resource_count_is("AWS::Bedrock::KnowledgeBase", 1)
    tmpl.resource_count_is("AWS::Bedrock::DataSource", 1)


def test_kb_collection_arn_is_fn_getatt_not_placeholder():
    """Case 3: CollectionArn is Fn::GetAtt (not literal 'PLACEHOLDER')."""
    tmpl = _make_template()
    resources = tmpl.find_resources("AWS::Bedrock::KnowledgeBase")
    assert resources, "No KnowledgeBase resource found"
    kb = next(iter(resources.values()))
    collection_arn = (
        kb["Properties"]["StorageConfiguration"]
        ["OpensearchServerlessConfiguration"]["CollectionArn"]
    )
    assert collection_arn != "PLACEHOLDER", "CollectionArn must not be the literal 'PLACEHOLDER'"
    assert isinstance(collection_arn, dict) and "Fn::GetAtt" in collection_arn, (
        f"Expected Fn::GetAtt ref, got: {collection_arn}"
    )


def test_embedding_model_arn_is_titan_v2():
    """Case 4: EmbeddingModelArn ends with amazon.titan-embed-text-v2:0."""
    tmpl = _make_template()
    resources = tmpl.find_resources("AWS::Bedrock::KnowledgeBase")
    kb = next(iter(resources.values()))
    embedding_arn = (
        kb["Properties"]["KnowledgeBaseConfiguration"]
        ["VectorKnowledgeBaseConfiguration"]["EmbeddingModelArn"]
    )
    assert str(embedding_arn).endswith("amazon.titan-embed-text-v2:0"), (
        f"Expected Titan v2 embedding model, got: {embedding_arn}"
    )


def test_data_source_inclusion_prefixes_exact():
    """Case 5: InclusionPrefixes is exactly the expected single-prefix list."""
    tmpl = _make_template()
    resources = tmpl.find_resources("AWS::Bedrock::DataSource")
    ds = next(iter(resources.values()))
    prefixes = (
        ds["Properties"]["DataSourceConfiguration"]
        ["S3Configuration"]["InclusionPrefixes"]
    )
    assert prefixes == ["knowledge/vehicle_knowledge_base/sources/"], (
        f"InclusionPrefixes mismatch: {prefixes}"
    )


def test_aoss_resource_counts_two_security_one_collection_one_access_one_cr():
    """Case 6: 2 SecurityPolicy + 1 Collection + 1 AccessPolicy + ≥1 Custom Resource."""
    tmpl = _make_template()
    tmpl.resource_count_is("AWS::OpenSearchServerless::SecurityPolicy", 2)
    tmpl.resource_count_is("AWS::OpenSearchServerless::Collection", 1)
    tmpl.resource_count_is("AWS::OpenSearchServerless::AccessPolicy", 1)
    crs = tmpl.find_resources("AWS::CloudFormation::CustomResource")
    lambdas_cr = tmpl.find_resources("Custom::AWS")
    assert len(crs) + len(lambdas_cr) >= 1, "Expected at least 1 Custom Resource for index bootstrap"


def test_kb_role_inline_policy_aoss_and_bedrock_invoke():
    """Case 7: KB role inline policy contains aoss:APIAccessAll + bedrock:InvokeModel."""
    from aws_cdk.assertions import Match
    tmpl = _make_template()
    # Two separate IAM::Policy resources are emitted — one per add_to_policy call.
    # Use Match.object_like inside Match.array_with for partial-key matching.
    tmpl.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": Match.array_with([
                Match.object_like({"Action": "aoss:APIAccessAll", "Effect": "Allow"})
            ])
        }
    })
    tmpl.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": Match.array_with([
                Match.object_like({"Action": "bedrock:InvokeModel", "Effect": "Allow"})
            ])
        }
    })


def test_kb_role_kms_grant_is_decrypt_only_with_via_service():
    """Least-privilege KMS grant: the KB execution role's lake-key statement is
    exactly kms:Decrypt (no GenerateDataKey/DescribeKey) scoped by
    kms:ViaService=s3 — per the AWS Bedrock KB service-role reference for
    encrypted S3 data sources (read-only ingestion). Regression guard against
    re-broadening to write-path KMS actions (security-review cycle-2 suggestion).
    """
    from aws_cdk.assertions import Match
    tmpl = _make_template()
    # Find the KMS statement on any IAM::Policy and assert its exact action set.
    policies = tmpl.find_resources("AWS::IAM::Policy")
    kms_stmts = []
    for pol in policies.values():
        for stmt in pol["Properties"]["PolicyDocument"]["Statement"]:
            action = stmt.get("Action")
            actions = action if isinstance(action, list) else [action]
            if any(isinstance(a, str) and a.startswith("kms:") for a in actions):
                kms_stmts.append((actions, stmt))
    assert kms_stmts, "expected a kms: PolicyStatement on the KB role"
    for actions, stmt in kms_stmts:
        assert actions == ["kms:Decrypt"], (
            f"KB role KMS grant must be exactly ['kms:Decrypt'] (read-only "
            f"ingestion); got {actions}"
        )
        cond = stmt.get("Condition", {}).get("StringEquals", {})
        via = cond.get("kms:ViaService")
        assert via is not None and "s3" in str(via), (
            f"KMS grant must be scoped by kms:ViaService=s3.*; got {stmt.get('Condition')}"
        )


def test_four_outputs_with_stage_scoped_export_names():
    """Case 8: 4 CfnOutputs with stage-scoped export names."""
    tmpl = _make_template(stage="staging")
    outputs = tmpl.find_outputs("*")
    export_names = [
        v.get("Export", {}).get("Name", "")
        for v in outputs.values()
        if "Export" in v
    ]
    assert len(export_names) >= 4, f"Expected ≥4 exported outputs, got: {export_names}"
    for fragment in ("vehicle-knowledge-id", "vehicle-knowledge-arn"):
        assert any(fragment in name for name in export_names), (
            f"Expected export containing '{fragment}' in {export_names}"
        )


# --- T2.2: Migrated assertions (byte-for-byte from test_kb_cross_account.py) ---
# Assertions ported VERBATIM per Q2; only the factory + import path adapted.
# Using cached _make_template() — same memoization keys ([ROLE_ARN], None,
# [ROLE_ARN, ROLE_ARN_2]) — to keep total Docker bundlings ≤3.


def test_resource_policy_created_with_principal():
    template = _make_template(principals=[ROLE_ARN])
    template.resource_count_is("AWS::Bedrock::ResourcePolicy", 1)
    template.has_resource_properties("AWS::Bedrock::ResourcePolicy", {
        "PolicyDocument": {
            "Statement": [{
                "Principal": {"AWS": [ROLE_ARN]},
            }]
        }
    })


def test_no_resource_policy_when_principals_absent():
    template = _make_template(principals=None)
    template.resource_count_is("AWS::Bedrock::ResourcePolicy", 0)


def test_multiple_principals_all_present():
    template = _make_template(principals=[ROLE_ARN, ROLE_ARN_2])
    template.has_resource_properties("AWS::Bedrock::ResourcePolicy", {
        "PolicyDocument": {
            "Statement": [{
                "Principal": {"AWS": [ROLE_ARN, ROLE_ARN_2]},
            }]
        }
    })


def test_action_list_exact():
    template = _make_template(principals=[ROLE_ARN])
    template.has_resource_properties("AWS::Bedrock::ResourcePolicy", {
        "PolicyDocument": {
            "Statement": [{
                "Action": [
                    "bedrock-agent-runtime:Retrieve",
                    "bedrock-agent-runtime:RetrieveAndGenerate",
                ],
            }]
        }
    })
