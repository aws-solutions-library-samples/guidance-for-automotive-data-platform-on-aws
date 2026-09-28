"""C1: the Lake Formation KMS grant must be DECLARED, not applied by hand.

The lake CMK is CDK-managed (foundation_stack.py, `LakeKey`). A manual
`aws kms put-key-policy` is drift: the next template change touching that key --
most plausibly a `grant_*` for a new consumer -- regenerates the key policy and
silently drops the statement, restoring a blocker that presents as
PERMISSION_DENIED on kms:GenerateDataKey deep inside an Athena INSERT.

Reading needs kms:Decrypt; WRITING encrypted objects needs kms:GenerateDataKey.
Every prior ADP interaction with this lake was a read, which is why the gap was
invisible until the Iceberg conversion became the first write through Athena.

See issues/2026-09-20-group4-three-stacked-blockers/ and D18.
"""
from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from stacks.foundation_stack import FoundationStack

_ACCOUNT = "123456789012"
_REGION = "us-east-1"
_SID = "AllowLakeFormationDataAccessRoleEncryptDecrypt"
_LF_ROLE_FRAGMENT = (
    "role/aws-service-role/lakeformation.amazonaws.com/"
    "AWSServiceRoleForLakeFormationDataAccess"
)


def _key_policy(stage: str) -> dict:
    app = cdk.App(context={"stage": stage})
    stack = FoundationStack(
        app, f"adp-{stage}-foundation-lake", stage=stage,
        env=cdk.Environment(account=_ACCOUNT, region=_REGION),
    )
    tmpl = Template.from_stack(stack)
    keys = tmpl.find_resources("AWS::KMS::Key")
    assert len(keys) == 1, f"expected exactly one CMK, found {list(keys)}"
    return next(iter(keys.values()))["Properties"]["KeyPolicy"]


@pytest.mark.parametrize("stage", ["staging", "prod"])
def test_lake_key_grants_lake_formation_generate_data_key(stage):
    """The grant exists, on BOTH stages -- prod inherits it without a manual step."""
    pol = _key_policy(stage)
    stmts = [s for s in pol["Statement"] if s.get("Sid") == _SID]
    assert len(stmts) == 1, (
        f"{stage}: expected exactly one {_SID} statement, got {len(stmts)}"
    )
    s = stmts[0]
    assert s["Effect"] == "Allow"
    actions = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
    # kms:GenerateDataKey is the load-bearing one: without it, writes fail.
    assert "kms:GenerateDataKey" in actions, actions
    assert "kms:Decrypt" in actions, actions
    principal = str(s.get("Principal"))
    assert _LF_ROLE_FRAGMENT in principal, principal


@pytest.mark.parametrize("stage", ["staging", "prod"])
def test_lake_key_grant_is_least_privilege(stage):
    """Exactly two actions and one principal -- not kms:* and not a wildcard.

    Asserts the SCOPE, not merely the statement's presence: widening Action to
    kms:* or the principal to "*" would still satisfy an existence check.
    """
    pol = _key_policy(stage)
    s = next(x for x in pol["Statement"] if x.get("Sid") == _SID)
    actions = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
    assert sorted(actions) == ["kms:Decrypt", "kms:GenerateDataKey"], actions
    assert "kms:*" not in actions
    principal = s.get("Principal")
    assert principal != "*" and principal != {"AWS": "*"}, principal
    assert isinstance(principal, dict) and "AWS" in principal


@pytest.mark.parametrize("stage", ["staging", "prod"])
def test_lake_key_retains_the_account_root_statement(stage):
    """The added grant must not have replaced the default root statement."""
    pol = _key_policy(stage)
    root = [
        s for s in pol["Statement"]
        if s.get("Sid") != _SID and "kms:*" in str(s.get("Action"))
    ]
    assert root, f"{stage}: account-root kms:* statement missing: {pol}"
