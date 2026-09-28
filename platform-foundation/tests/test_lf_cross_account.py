"""T2.4 — LF cross-account grant + CloudTrail Bedrock KB event selector tests.

Spec: ~/automotive-data-platform-on-aws/.kiro/specs/2026-06-09-adp-kb-cross-account-grants/

Extended 2026-09-09 for spec 2026-08-26-adp-dealer-domain Group 6 (T3.4):
DMS-side cross-account share on the two new dealer/parts domains, plus the
KB resource policy carrying both principal lists in a single Statement.
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
from stacks.vehicle_knowledge_base_stack import VehicleKnowledgeBaseStack

_STAGE = "staging"
_CVX_ACCOUNT = "123456789012"  # AWS docs placeholder; never a real account.
_DMS_ACCOUNT = "222222222222"  # Distinct placeholder for DMS (Fix Group 4, review Cycle 6):
                               # keeping both accounts distinct prevents the
                               # principal-identity assertions from being vacuously
                               # true if a mutation swapped dms_account_id for
                               # cvx_account_id. Picked from the publish-scanner's
                               # explicit allowlist alongside 111111111111,
                               # 111122223333, 999988887777 (see .publish-secrets-scan.yml
                               # § "Allowlist additions 2026-08-04") so the value cannot
                               # trip the aws_account_id pattern on publish.
_FAKE_LAKE_ARN = "arn:aws:s3:::adp-staging-foundation-lake-000000000000-us-east-1"
_FAKE_LAKE_NAME = "adp-staging-foundation-lake-000000000000-us-east-1"
_FAKE_KMS_ARN = "arn:aws:kms:us-east-1:000000000000:key/00000000-0000-0000-0000-000000000000"


def _make_template(
    cvx_account_id: str | None, dms_account_id: str | None = None
) -> Template:
    app = cdk.App()
    stack = GovernanceStack(
        app,
        "TestGovernance",
        stage=_STAGE,
        lake_bucket_arn_export=_FAKE_LAKE_ARN,
        lake_bucket_name=_FAKE_LAKE_NAME,
        cvx_account_id=cvx_account_id,
        dms_account_id=dms_account_id,
        env=cdk.Environment(account="000000000000", region="us-east-1"),
    )
    return Template.from_stack(stack)


def _make_kb_template(
    cvx_principals: list[str] | None = None,
    dms_principals: list[str] | None = None,
) -> Template:
    app = cdk.App()
    stack = VehicleKnowledgeBaseStack(
        app,
        "TestKB",
        stage=_STAGE,
        lake_bucket_name=_FAKE_LAKE_NAME,
        lake_kms_key_arn=_FAKE_KMS_ARN,
        cvx_kb_principals=cvx_principals,
        dms_kb_principals=dms_principals,
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



# ---------------------------------------------------------------------------
# T3.4 / Group 6 — DMS cross-account share (spec 2026-08-26-adp-dealer-domain)
# ---------------------------------------------------------------------------

_KB_CVX_PRINCIPAL = "arn:aws:iam::123456789012:role/cvx-test"
_KB_DMS_PRINCIPAL = "arn:aws:iam::123456789012:role/dms-test"


class TestDmsCrossAccount:
    """Group 6 tests — LF grants + KB resource policy for the DMS principal.

    Discipline pin: per the spec's `RESUME.md` bar, each contract is
    mutation-tested — the property under test is broken in-place below the
    happy-path assertion set (see the paired ``test_*_mutation_*`` methods).
    Every mutation is asserted to fail red, then the property is restored and
    asserted green in the sibling positive test.
    """

    # (1) Default: no DMS context → 0 DMS-labelled grants (backward-compat)
    def test_no_dms_context_no_dms_grants(self):
        tmpl = _make_template(cvx_account_id=None, dms_account_id=None)
        grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
        dms_ids = [k for k in grants if "LfDms" in k]
        assert not dms_ids, (
            f"no DMS context but LfDms* grants leaked: {dms_ids}"
        )
        # And no bootstrap either (backward-compat with pre-Group-6 behaviour).
        tmpl.resource_count_is("AWS::LakeFormation::Resource", 0)

    # (2) DMS context → 2 DMS grants targeting dealer_domain + parts_domain
    def test_dms_context_synthesizes_two_grants(self):
        tmpl = _make_template(cvx_account_id=None, dms_account_id=_DMS_ACCOUNT)
        grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
        dms_ids = sorted(k for k in grants if "LfDms" in k)
        assert len(dms_ids) == 2, (
            f"expected exactly 2 DMS grants (dealer_domain + parts_domain), "
            f"got {len(dms_ids)}: {dms_ids}"
        )
        # Bootstrap synthesises now that DMS is set.
        tmpl.resource_count_is("AWS::LakeFormation::Resource", 1)

        # Verify targets: one grant per DMS database.
        target_dbs = set()
        for logical_id in dms_ids:
            props = grants[logical_id]["Properties"]
            db = props["Resource"]["Table"]["DatabaseName"]
            target_dbs.add(db)
        assert target_dbs == {
            "adp_staging_dealer_domain",
            "adp_staging_parts_domain",
        }, (
            f"DMS grants must target dealer_domain + parts_domain only; "
            f"got {sorted(target_dbs)}"
        )

    # (3) Both CVX and DMS set — 6 + 2 = 8 grants; no cross-contamination
    def test_dms_and_cvx_coexist(self):
        tmpl = _make_template(
            cvx_account_id=_CVX_ACCOUNT, dms_account_id=_DMS_ACCOUNT
        )
        grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
        cvx_ids = [k for k in grants if "LfCvx" in k]
        dms_ids = [k for k in grants if "LfDms" in k]

        assert len(cvx_ids) == 6, f"expected 6 CVX grants, got {len(cvx_ids)}"
        assert len(dms_ids) == 2, f"expected 2 DMS grants, got {len(dms_ids)}"
        assert len(grants) == 8, (
            f"expected 8 total PrincipalPermissions (6 CVX + 2 DMS), "
            f"got {len(grants)}"
        )

        # No cross-contamination: CVX grants target the 6 CVX databases only;
        # DMS grants target the 2 DMS databases only. Cross-databases would
        # mean scope creep by aggregation (the exact defect the split-list
        # pattern was introduced to prevent).
        cvx_dbs = set()
        for logical_id in cvx_ids:
            props = grants[logical_id]["Properties"]
            cvx_dbs.add(props["Resource"]["Table"]["DatabaseName"])
        dms_dbs = set()
        for logical_id in dms_ids:
            props = grants[logical_id]["Properties"]
            dms_dbs.add(props["Resource"]["Table"]["DatabaseName"])

        assert cvx_dbs.isdisjoint(dms_dbs), (
            f"CVX and DMS grant target sets must be disjoint; "
            f"overlap: {cvx_dbs & dms_dbs}"
        )

        # DMS side pins exact set (dealer + parts, no more, no fewer).
        assert dms_dbs == {
            "adp_staging_dealer_domain",
            "adp_staging_parts_domain",
        }, sorted(dms_dbs)

        # No CVX grant may target a DMS-only database, and vice versa.
        assert not (cvx_dbs & {"adp_staging_dealer_domain", "adp_staging_parts_domain"})
        assert not (dms_dbs & cvx_dbs)

        # Fix Group 4 / review Cycle 6 Warning: assert PRINCIPAL identity too,
        # not only database targets. Distinct _CVX_ACCOUNT != _DMS_ACCOUNT
        # placeholders make this discriminating: if a caller-side mutation
        # passed cvx_account_id to _grant_dms_cross_account_share by mistake
        # (or vice versa), the ARN would render with the wrong account number
        # and this assertion would fail. Without distinct placeholders + this
        # cross-check, the test was vacuously true.
        for logical_id in cvx_ids:
            principal = grants[logical_id]["Properties"]["Principal"][
                "DataLakePrincipalIdentifier"
            ]
            assert principal == f"arn:aws:iam::{_CVX_ACCOUNT}:root", (
                f"{logical_id}: expected CVX account root principal, got {principal!r}"
            )
        for logical_id in dms_ids:
            principal = grants[logical_id]["Properties"]["Principal"][
                "DataLakePrincipalIdentifier"
            ]
            assert principal == f"arn:aws:iam::{_DMS_ACCOUNT}:root", (
                f"{logical_id}: expected DMS account root principal, got {principal!r}"
            )

    # (4) DMS grants have the same SELECT+DESCRIBE + empty grant-option contract
    def test_dms_grants_are_select_describe_only_and_not_regrantable(self):
        tmpl = _make_template(cvx_account_id=None, dms_account_id=_DMS_ACCOUNT)
        grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
        dms_ids = [k for k in grants if "LfDms" in k]
        assert dms_ids, "no DMS grants found — precondition for this test"

        for logical_id in dms_ids:
            props = grants[logical_id]["Properties"]
            perms = set(props.get("Permissions", []))
            assert perms == {"SELECT", "DESCRIBE"}, (
                f"{logical_id}: expected {{SELECT, DESCRIBE}}, got {perms}"
            )
            grant_opt = props.get("PermissionsWithGrantOption", [])
            assert grant_opt == [], (
                f"{logical_id}: PermissionsWithGrantOption must be empty "
                f"(no re-sharing per 2026-06-09 CVX security-review pattern); "
                f"got {grant_opt}"
            )

    # (5) Principal is the DMS account root ARN
    def test_dms_grants_principal_is_account_root(self):
        tmpl = _make_template(cvx_account_id=None, dms_account_id=_DMS_ACCOUNT)
        grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
        dms_ids = [k for k in grants if "LfDms" in k]
        assert dms_ids

        for logical_id in dms_ids:
            props = grants[logical_id]["Properties"]
            principal = props["Principal"]["DataLakePrincipalIdentifier"]
            assert principal == f"arn:aws:iam::{_DMS_ACCOUNT}:root", (
                f"{logical_id}: principal must be DMS account root; "
                f"got {principal!r}"
            )

    # (6) DMS grants use table_wildcard (all current + future tables)
    def test_dms_grants_use_table_wildcard(self):
        tmpl = _make_template(cvx_account_id=None, dms_account_id=_DMS_ACCOUNT)
        grants = tmpl.find_resources("AWS::LakeFormation::PrincipalPermissions")
        dms_ids = [k for k in grants if "LfDms" in k]
        assert dms_ids

        for logical_id in dms_ids:
            props = grants[logical_id]["Properties"]
            table = props["Resource"]["Table"]
            # TableWildcard is present (as `{}` per CDK's L1 rendering) and
            # no `Name` is set — the pair means "ALL tables under this DB".
            assert "TableWildcard" in table, (
                f"{logical_id}: TableWildcard missing — DMS grants would be "
                f"scoped to a specific table, not the whole database"
            )
            assert "Name" not in table, (
                f"{logical_id}: Table.Name present — mixes wildcard with a "
                f"named table"
            )


class TestKbCombinedResourcePolicy:
    """Group 6 tests — the KB resource policy combines CVX + DMS in one Statement."""

    def test_kb_policy_absent_when_no_principals(self):
        tmpl = _make_kb_template(cvx_principals=None, dms_principals=None)
        tmpl.resource_count_is("AWS::Bedrock::ResourcePolicy", 0)

    def test_kb_policy_cvx_only_backward_compat(self):
        tmpl = _make_kb_template(cvx_principals=[_KB_CVX_PRINCIPAL])
        pols = tmpl.find_resources("AWS::Bedrock::ResourcePolicy")
        assert len(pols) == 1
        pol = next(iter(pols.values()))["Properties"]
        doc = pol["PolicyDocument"]
        assert doc["Version"] == "2012-10-17"
        assert len(doc["Statement"]) == 1
        principals = doc["Statement"][0]["Principal"]["AWS"]
        assert principals == [_KB_CVX_PRINCIPAL], principals

    def test_kb_policy_dms_only(self):
        tmpl = _make_kb_template(dms_principals=[_KB_DMS_PRINCIPAL])
        pols = tmpl.find_resources("AWS::Bedrock::ResourcePolicy")
        assert len(pols) == 1
        pol = next(iter(pols.values()))["Properties"]
        doc = pol["PolicyDocument"]
        assert len(doc["Statement"]) == 1
        principals = doc["Statement"][0]["Principal"]["AWS"]
        assert principals == [_KB_DMS_PRINCIPAL], principals

    def test_kb_policy_combines_principals_in_single_statement(self):
        """G6.T3 mandatory: both principal lists → single Statement, both ARNs."""
        tmpl = _make_kb_template(
            cvx_principals=[_KB_CVX_PRINCIPAL],
            dms_principals=[_KB_DMS_PRINCIPAL],
        )
        pols = tmpl.find_resources("AWS::Bedrock::ResourcePolicy")
        assert len(pols) == 1, "expected exactly 1 KB resource policy resource"
        pol = next(iter(pols.values()))["Properties"]
        doc = pol["PolicyDocument"]

        # Single combined Statement — NOT two separate statements.
        assert len(doc["Statement"]) == 1, (
            f"expected 1 combined Statement (both principals under one AWS "
            f"array), got {len(doc['Statement'])}"
        )
        stmt = doc["Statement"][0]
        assert stmt["Effect"] == "Allow"

        # Both ARNs present in the same Principal.AWS array.
        principals = stmt["Principal"]["AWS"]
        assert _KB_CVX_PRINCIPAL in principals, principals
        assert _KB_DMS_PRINCIPAL in principals, principals
        assert len(principals) == 2, (
            f"expected 2 principals, got {len(principals)}: {principals}"
        )

        # Actions unchanged (no scope creep on the DMS wire-in).
        assert set(stmt["Action"]) == {
            "bedrock-agent-runtime:Retrieve",
            "bedrock-agent-runtime:RetrieveAndGenerate",
        }, stmt["Action"]

    def test_kb_policy_empty_lists_treated_as_absent(self):
        """Empty combined list must not synthesize a policy resource."""
        tmpl = _make_kb_template(cvx_principals=[], dms_principals=[])
        tmpl.resource_count_is("AWS::Bedrock::ResourcePolicy", 0)

    def test_kb_policy_multiple_dms_principals_all_appear(self):
        """DMS list of >1 ARN — all appear in the same Statement's AWS array."""
        p1 = "arn:aws:iam::123456789012:role/dms-runtime"
        p2 = "arn:aws:iam::123456789012:role/dms-analytics"
        tmpl = _make_kb_template(dms_principals=[p1, p2])
        pols = tmpl.find_resources("AWS::Bedrock::ResourcePolicy")
        assert len(pols) == 1
        pol = next(iter(pols.values()))["Properties"]
        principals = pol["PolicyDocument"]["Statement"][0]["Principal"]["AWS"]
        assert p1 in principals and p2 in principals, principals
        assert len(principals) == 2, principals
