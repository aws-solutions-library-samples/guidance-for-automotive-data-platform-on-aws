"""Tests for VehicleKnowledgeBaseStack — S3 Vectors migration.

T1.2: skeletons authored (RED phase).
T3.1: concrete assertions implemented (GREEN phase).

Performance discipline: ``_make_template`` caches the synthesized ``Template``
keyed by ``(tuple(principals or ()), stage, 's3vectors')`` so tests share
synthesized templates instead of re-synthesizing per-test.

Cache key updated per spec Decision (I) and T1.2: the literal ``'s3vectors'``
tag prevents a future dual-KB spec from inadvertently reusing these cache
entries.
"""

from __future__ import annotations

import sys
import os

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stacks.vehicle_knowledge_base_stack import VehicleKnowledgeBaseStack

_PLACEHOLDER_ACCOUNT = "123456789012"
_REGION = "us-east-1"

ROLE_ARN = "arn:aws:iam::123456789012:role/test-role"
ROLE_ARN_2 = "arn:aws:iam::123456789012:role/test-role-2"

_TEMPLATE_CACHE: dict[tuple, Template] = {}


def _make_template(principals=None, stage="staging") -> Template:
    """Synthesize a fresh VKB stack and return ``Template.from_stack`` (cached).

    Cache key is ``(tuple(principals or ()), stage, 's3vectors')`` — the
    literal ``'s3vectors'`` tag is included so a future dual-KB spec can't
    inadvertently reuse cache entries from this suite.

    Note: ``deploy_role_arn`` is intentionally NOT passed here. That kwarg
    was deleted in Group 2 per spec § Decision (I).
    """
    key = (tuple(principals or ()), stage, "s3vectors")
    if key in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[key]

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
    template = Template.from_stack(stack)
    _TEMPLATE_CACHE[key] = template
    return template


# ---------------------------------------------------------------------------
# T3.1: 12 positive-path S3 Vectors assertions (spec § Test plan tests 1-12)
# ---------------------------------------------------------------------------

def test_synthesizes_without_cvx_kb_principals_single_account_default():
    """Test 1 — template synth succeeds without principals."""
    tmpl = _make_template(principals=None)
    assert tmpl is not None


def test_exactly_one_kb_and_one_data_source():
    """Test 2 — exactly one KB and one DataSource resource."""
    tmpl = _make_template()
    tmpl.resource_count_is("AWS::Bedrock::KnowledgeBase", 1)
    tmpl.resource_count_is("AWS::Bedrock::DataSource", 1)


def test_exactly_one_vector_bucket_and_one_vector_index():
    """Test 3 — exactly one VectorBucket and one Index resource."""
    tmpl = _make_template()
    tmpl.resource_count_is("AWS::S3Vectors::VectorBucket", 1)
    tmpl.resource_count_is("AWS::S3Vectors::Index", 1)


def test_kb_index_arn_is_fn_getatt_not_placeholder():
    """Test 4 — KB StorageConfiguration.S3VectorsConfiguration.IndexArn is a
    CFN intrinsic (Fn::GetAtt), not a literal string placeholder.
    """
    tmpl = _make_template()
    kb_resources = tmpl.find_resources("AWS::Bedrock::KnowledgeBase")
    assert len(kb_resources) == 1, f"expected 1 KB, got {len(kb_resources)}"
    kb_props = next(iter(kb_resources.values()))["Properties"]
    index_arn = (
        kb_props["StorageConfiguration"]["S3VectorsConfiguration"]["IndexArn"]
    )
    assert isinstance(index_arn, dict), (
        f"IndexArn must be a CFN intrinsic dict (e.g. Fn::GetAtt), not {type(index_arn)}"
    )
    assert "Fn::GetAtt" in index_arn, (
        f"IndexArn must use Fn::GetAtt; got keys {list(index_arn.keys())}"
    )


def test_kb_storage_configuration_type_is_s3_vectors():
    """Test 5 — StorageConfiguration.Type == 'S3_VECTORS'."""
    tmpl = _make_template()
    kb_resources = tmpl.find_resources("AWS::Bedrock::KnowledgeBase")
    assert len(kb_resources) == 1
    kb_props = next(iter(kb_resources.values()))["Properties"]
    assert kb_props["StorageConfiguration"]["Type"] == "S3_VECTORS"


def test_embedding_model_arn_is_titan_v2():
    """Test 6 — EmbeddingModelArn ends with amazon.titan-embed-text-v2:0."""
    tmpl = _make_template()
    kb_resources = tmpl.find_resources("AWS::Bedrock::KnowledgeBase")
    assert len(kb_resources) == 1
    kb_props = next(iter(kb_resources.values()))["Properties"]
    embedding_arn = (
        kb_props["KnowledgeBaseConfiguration"]
        ["VectorKnowledgeBaseConfiguration"]
        ["EmbeddingModelArn"]
    )
    assert str(embedding_arn).endswith("amazon.titan-embed-text-v2:0"), (
        f"EmbeddingModelArn must end with 'amazon.titan-embed-text-v2:0'; got {embedding_arn}"
    )


def test_data_source_inclusion_prefixes_exact():
    """Test 7 — DataSource inclusion prefix is exactly the expected S3 path."""
    tmpl = _make_template()
    ds_resources = tmpl.find_resources("AWS::Bedrock::DataSource")
    assert len(ds_resources) == 1
    ds_props = next(iter(ds_resources.values()))["Properties"]
    prefixes = (
        ds_props["DataSourceConfiguration"]
        ["S3Configuration"]
        ["InclusionPrefixes"]
    )
    assert prefixes == ["knowledge/vehicle_knowledge_base/sources/"], (
        f"InclusionPrefixes must be exactly ['knowledge/vehicle_knowledge_base/sources/']; "
        f"got {prefixes}"
    )


def test_vector_index_dimension_1024_datatype_float32_distance_cosine():
    """Test 8 — VectorIndex has Dimension=1024 (int), DataType='float32',
    DistanceMetric='cosine'.
    """
    tmpl = _make_template()
    idx_resources = tmpl.find_resources("AWS::S3Vectors::Index")
    assert len(idx_resources) == 1, f"expected 1 Index, got {len(idx_resources)}"
    idx_props = next(iter(idx_resources.values()))["Properties"]
    assert idx_props["Dimension"] == 1024, (
        f"Dimension must be integer 1024; got {idx_props['Dimension']!r}"
    )
    assert idx_props["DataType"] == "float32", (
        f"DataType must be 'float32'; got {idx_props['DataType']!r}"
    )
    assert idx_props["DistanceMetric"] == "cosine", (
        f"DistanceMetric must be 'cosine'; got {idx_props['DistanceMetric']!r}"
    )


def test_vector_index_has_amazon_bedrock_text_and_metadata_nonfilterable():
    """Test 9 — VectorIndex MetadataConfiguration.NonFilterableMetadataKeys must
    contain BOTH ``AMAZON_BEDROCK_TEXT`` and ``AMAZON_BEDROCK_METADATA``.

    Bedrock KB auto-populates two filterable metadata keys that each exceed the
    2 KB per-vector filterable cap. Missing either produces per-chunk ingestion
    failures (empirically: 23/92 failed on staging when only AMAZON_BEDROCK_TEXT
    was non-filterable — see decisions.md § T4B.3 ingestion partial failure).
    Both keys must be present; order-independent (list-equality would also
    accept the swapped order, so use set comparison to be explicit).
    """
    tmpl = _make_template()
    idx_resources = tmpl.find_resources("AWS::S3Vectors::Index")
    assert len(idx_resources) == 1
    idx_props = next(iter(idx_resources.values()))["Properties"]
    non_filterable = (
        idx_props["MetadataConfiguration"]["NonFilterableMetadataKeys"]
    )
    assert set(non_filterable) == {"AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"}, (
        f"NonFilterableMetadataKeys must contain exactly "
        f"{{'AMAZON_BEDROCK_TEXT', 'AMAZON_BEDROCK_METADATA'}}; "
        f"got {non_filterable!r}"
    )


def test_kb_role_has_s3vectors_grants_scoped_to_index_arn():
    """Test 10 — KB execution role has all 6 s3vectors: actions and resources
    include both the vector-bucket ARN and the /index/* wildcard (both as
    CFN intrinsic refs, not literal strings).
    """
    from aws_cdk.assertions import Match

    tmpl = _make_template()

    # Use has_resource_properties with Match to assert all 6 actions are present.
    # The resource list must contain two entries derived from the vector bucket ARN.
    tmpl.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with([
                    Match.object_like({
                        "Action": Match.array_with([
                            "s3vectors:GetIndex",
                            "s3vectors:QueryVectors",
                            "s3vectors:PutVectors",
                            "s3vectors:GetVectors",
                            "s3vectors:ListVectors",
                            "s3vectors:DeleteVectors",
                        ]),
                    })
                ])
            }
        }
    )

    # Also verify the resource scoping via inspection: must have exactly 2 entries —
    # the vector-bucket ARN and the ${vectorBucketArn}/index/* wildcard — both
    # expressed as CFN intrinsic refs (not literal strings).
    policies = tmpl.find_resources("AWS::IAM::Policy")
    s3vectors_stmt = None
    for pol in policies.values():
        for stmt in pol["Properties"]["PolicyDocument"]["Statement"]:
            action = stmt.get("Action")
            actions = action if isinstance(action, list) else [action]
            if "s3vectors:GetIndex" in actions:
                s3vectors_stmt = stmt
                break
        if s3vectors_stmt:
            break

    assert s3vectors_stmt is not None, "No IAM statement with s3vectors:GetIndex found"

    resources = s3vectors_stmt.get("Resource", [])
    assert len(resources) == 2, (
        f"s3vectors statement must have exactly 2 Resource entries "
        f"(bucket ARN + /index/* wildcard); got {len(resources)}: {resources}"
    )
    # Both entries must be CFN intrinsics (dict), not literal strings
    for resource in resources:
        assert isinstance(resource, dict), (
            f"s3vectors Resource entry must be a CFN intrinsic ref (dict), "
            f"not a literal string: {resource!r}"
        )


def test_kb_role_titan_invoke_and_s3_read_and_kms_decrypt_unchanged():
    """Test 11 — regression guard: KB role still has bedrock:InvokeModel,
    s3:GetObject on the sources/* prefix, and kms:Decrypt scoped by
    kms:ViaService=s3.<region>.amazonaws.com.
    """
    from aws_cdk.assertions import Match

    tmpl = _make_template()

    # Assert bedrock:InvokeModel exists on some IAM policy
    tmpl.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with([
                    Match.object_like({"Action": "bedrock:InvokeModel"})
                ])
            }
        }
    )

    # Assert s3:GetObject exists (part of lake grant)
    policies = tmpl.find_resources("AWS::IAM::Policy")
    has_s3_get = False
    has_kms_decrypt = False
    kms_condition_ok = False
    for pol in policies.values():
        for stmt in pol["Properties"]["PolicyDocument"]["Statement"]:
            action = stmt.get("Action")
            actions = action if isinstance(action, list) else [action]
            if any(isinstance(a, str) and a.startswith("s3:GetObject") for a in actions):
                has_s3_get = True
            if "kms:Decrypt" in actions:
                has_kms_decrypt = True
                cond = stmt.get("Condition", {}).get("StringEquals", {})
                via = cond.get("kms:ViaService")
                if via is not None and "s3" in str(via):
                    kms_condition_ok = True

    assert has_s3_get, "KB role must have an s3:GetObject statement (lake read grant)"
    assert has_kms_decrypt, "KB role must have a kms:Decrypt statement"
    assert kms_condition_ok, (
        "kms:Decrypt statement must be scoped by kms:ViaService=s3.<region>.amazonaws.com"
    )


def test_five_outputs_with_stage_scoped_export_names():
    """Test 12 — template has ≥5 Outputs with export names containing the
    expected fragments for the 4 existing outputs + 1 new VectorBucketArn.
    """
    tmpl = _make_template()
    outputs = tmpl.find_outputs("*")

    # Collect export names from all outputs
    export_names = []
    for output_value in outputs.values():
        export_block = output_value.get("Export")
        if export_block:
            export_name = export_block.get("Name")
            if export_name:
                # Export name may be a CFN intrinsic (Fn::Join etc.) or a string
                export_names.append(export_name)

    assert len(export_names) >= 5, (
        f"Expected ≥5 outputs with Export.Name; got {len(export_names)}: {export_names}"
    )

    # Verify the 5 required fragment patterns are present in at least one export name.
    # Export names are typically CFN Join intrinsics like
    #   {"Fn::Join": ["-", ["adp", "staging", "foundation", "vehicle-knowledge-id"]]}
    # so we serialize the whole structure to a string for fragment matching.
    required_fragments = [
        "vehicle-knowledge-id",
        "vehicle-knowledge-arn",
        "vehicle-knowledge-bucket-arn",
        "vehicle-knowledge-sources-prefix",
        "vehicle-knowledge-vector-bucket-arn",
    ]
    export_names_str = str(export_names)
    for fragment in required_fragments:
        assert fragment in export_names_str, (
            f"Export names do not contain required fragment '{fragment}'. "
            f"Export names found: {export_names}"
        )


# ---------------------------------------------------------------------------
# Existing regression tests — KEPT BYTE-IDENTICAL per T3.1 constraints.
# ---------------------------------------------------------------------------

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
