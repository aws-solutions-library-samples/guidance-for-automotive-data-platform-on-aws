"""T2.2 — DataProductsStack assertion tests.

Spec: ``.kiro/specs/2026-06-09-adp-pyspark-glue-products/``

Hermetic — no real AWS calls. Uses ``aws_cdk.assertions.Template``
against synthesized templates. Account IDs are the AWS docs
placeholder ``123456789012``; bucket names use placeholder accounts.
"""

from __future__ import annotations

import json
import os
import sys

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

# Ensure the stacks package is importable from the test runner.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stacks.data_products_stack import DataProductsStack


_PLACEHOLDER_ACCOUNT = "123456789012"
_REGION = "us-east-1"


def _make_template(stage: str = "staging") -> Template:
    """Synthesize a fresh DataProductsStack for the given stage."""
    app = cdk.App()
    bucket_name = f"adp-{stage}-foundation-lake-{_PLACEHOLDER_ACCOUNT}-{_REGION}"
    stack = DataProductsStack(
        app,
        f"adp-{stage}-foundation-data-products",
        stage=stage,
        lake_bucket_name=bucket_name,
        env=cdk.Environment(account=_PLACEHOLDER_ACCOUNT, region=_REGION),
    )
    return Template.from_stack(stack)


def test_stack_synthesizes_one_iam_role():
    tmpl = _make_template()
    tmpl.resource_count_is("AWS::IAM::Role", 1)


def test_role_name_has_region_suffix():
    tmpl = _make_template("staging")
    tmpl.has_resource_properties(
        "AWS::IAM::Role",
        {"RoleName": "adp-staging-foundation-spark-etl-role-us-east-1"},
    )


def test_role_name_has_region_suffix_prod():
    tmpl = _make_template("prod")
    tmpl.has_resource_properties(
        "AWS::IAM::Role",
        {"RoleName": "adp-prod-foundation-spark-etl-role-us-east-1"},
    )


def test_role_assumed_by_glue_service_principal():
    tmpl = _make_template()
    roles = tmpl.find_resources("AWS::IAM::Role")
    assert len(roles) == 1
    role = next(iter(roles.values()))
    assume_doc = role["Properties"]["AssumeRolePolicyDocument"]
    statements = assume_doc["Statement"]
    assert any(
        s["Principal"].get("Service") == "glue.amazonaws.com"
        for s in statements
    ), f"Expected glue.amazonaws.com service principal; got {assume_doc}"


def test_inline_policy_scopes_glue_catalog_to_two_databases():
    tmpl = _make_template("staging")
    # Look at the full template JSON to find Glue Catalog ARNs.
    rendered = json.dumps(tmpl.to_json())
    # Exactly the two target databases + their tables.
    assert "database/adp_staging_vehicle_telemetry_aggregated" in rendered, rendered
    assert "database/adp_staging_energy_usage" in rendered, rendered
    assert "table/adp_staging_vehicle_telemetry_aggregated/*" in rendered, rendered
    assert "table/adp_staging_energy_usage/*" in rendered, rendered
    # Catalog-wide read should NOT appear with any other db.
    assert "database/adp_staging_charging_sessions" not in rendered
    assert "database/adp_staging_customer_360" not in rendered
    assert "database/adp_staging_dimensions" not in rendered


def test_inline_policy_scopes_s3_to_lake_bucket():
    tmpl = _make_template("staging")
    rendered = json.dumps(tmpl.to_json())
    expected_bucket = (
        f"adp-staging-foundation-lake-{_PLACEHOLDER_ACCOUNT}-{_REGION}"
    )
    assert expected_bucket in rendered
    # No other bucket names should appear in S3 ARNs.
    # Sanity: the AWSGlueServiceRole managed policy ARN format is
    # iam::aws:policy/... so any mention of other ADP bucket names
    # would be suspicious.
    for forbidden in (
        "adp-prod-foundation-lake",
        "adp-staging-foundation-lake-OTHER",
        "cms-staging-",
    ):
        assert forbidden not in rendered, f"Unexpected bucket reference: {forbidden}"


def test_role_arn_export_present():
    tmpl = _make_template("staging")
    outputs = tmpl.find_outputs("*")
    export_names = {
        v.get("Export", {}).get("Name") for v in outputs.values()
    }
    assert "adp-staging-foundation-spark-etl-role-arn" in export_names, (
        f"Expected export name not present in {export_names}"
    )


def test_no_iam_passrole():
    tmpl = _make_template("staging")
    rendered = json.dumps(tmpl.to_json())
    assert "iam:PassRole" not in rendered, (
        "DataProductsStack must not grant iam:PassRole — Spark ETL "
        "uses service-principal-trust, not delegated PassRole."
    )


def test_aws_managed_glue_service_role_attached():
    tmpl = _make_template("staging")
    roles = tmpl.find_resources("AWS::IAM::Role")
    role = next(iter(roles.values()))
    managed_policies = role["Properties"].get("ManagedPolicyArns", [])
    # ManagedPolicyArns contains CDK Fn::Join structures for the partition.
    rendered = json.dumps(managed_policies)
    assert "service-role/AWSGlueServiceRole" in rendered, (
        f"AWSGlueServiceRole not attached; got {managed_policies}"
    )


@pytest.mark.parametrize("stage", ["staging", "prod"])
def test_role_name_region_suffix_per_stage(stage):
    tmpl = _make_template(stage)
    tmpl.has_resource_properties(
        "AWS::IAM::Role",
        {"RoleName": f"adp-{stage}-foundation-spark-etl-role-us-east-1"},
    )
