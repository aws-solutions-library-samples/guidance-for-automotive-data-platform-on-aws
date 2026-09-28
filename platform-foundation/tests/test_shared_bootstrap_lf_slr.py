"""F6.5 / review Cycle 7 C1 — the Lake Formation SLR is a bootstrap prerequisite.

FoundationStack's LakeKey policy names
``AWSServiceRoleForLakeFormationDataAccess`` as a principal so Lake Formation can
WRITE encrypted objects (kms:GenerateDataKey). **KMS validates that key-policy
principals exist** and rejects the policy otherwise with
``MalformedPolicyDocumentException: Policy contains a statement with one or more
invalid principals.`` Confirmed empirically against a throwaway key, not assumed.

Nothing else creates the role in time: it is otherwise a side effect of
GovernanceStack's ``use_service_linked_role=True``, and ``app.py`` declares
``governance.add_dependency(lake)`` -- so governance runs AFTER lake. That cannot
be fixed by reordering, because the lake bucket must exist before Lake Formation
can register it.

So the role is created in the account-singular bootstrap stack, which
``make bootstrap`` runs once before the per-stage rollout.
"""
from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from stacks.shared_bootstrap_stack import SharedBootstrapStack

_ENV = cdk.Environment(account="123456789012", region="us-east-1")


def _tmpl(**kw) -> Template:
    app = cdk.App()
    return Template.from_stack(
        SharedBootstrapStack(app, "adp-shared-bootstrap", env=_ENV, **kw)
    )


def test_slr_created_by_default():
    """Default MUST be on: a fresh account needs it before the lake stack."""
    slrs = _tmpl().find_resources("AWS::IAM::ServiceLinkedRole")
    assert len(slrs) == 1, slrs
    props = next(iter(slrs.values()))["Properties"]
    assert props["AWSServiceName"] == "lakeformation.amazonaws.com", props


def test_slr_is_retained_not_deleted():
    """Account-scoped: other Lake Formation consumers outlive this stack."""
    slrs = _tmpl().find_resources("AWS::IAM::ServiceLinkedRole")
    assert next(iter(slrs.values())).get("DeletionPolicy") == "Retain"


def test_slr_can_be_opted_out_for_accounts_that_already_have_it():
    """CloudFormation cannot create a service-linked role that already exists.

    Accounts that already used Lake Formation before deploying ADP will hit this;
    the opt-out must genuinely remove the resource rather than merely disable it.
    """
    tmpl = _tmpl(create_lakeformation_slr=False)
    assert tmpl.find_resources("AWS::IAM::ServiceLinkedRole") == {}


@pytest.mark.parametrize("create", [True, False])
def test_macie_session_is_unaffected_either_way(create):
    """The pre-existing bootstrap resource must not be disturbed by this change."""
    tmpl = _tmpl(create_lakeformation_slr=create)
    macie = tmpl.find_resources("AWS::Macie::Session")
    assert len(macie) == 1, macie
    assert next(iter(macie.values())).get("DeletionPolicy") == "Retain"


def test_bootstrap_exports_no_value_the_lake_stack_imports():
    """The stack's contract is "deployed once, assumed live" -- no synth coupling.

    Ordering between bootstrap and the lake stack is enforced OPERATIONALLY by
    ``make bootstrap`` preceding the per-stage rollout. If a per-stage stack ever
    Fn::ImportValue'd from here, a fresh-account deploy would couple two stacks
    the design deliberately keeps independent.
    """
    outs = _tmpl().to_json().get("Outputs", {})
    names = {o.get("Export", {}).get("Name") for o in outs.values()}
    # Outputs exist for operators, and both are plain strings -- no ARNs or IDs
    # a downstream stack could be tempted to import for wiring.
    assert "adp-shared-bootstrap-lakeformation-slr" in names
    for o in outs.values():
        assert "Fn::GetAtt" not in str(o.get("Value")), o


# ---------------------------------------------------------------------------
# The app.py context layer -- the one `cdk deploy` actually uses.
# Cycle 8's M22 and Cycle 9 both found the default unpinned HERE: flipping
# app.py rendered 0 SLRs with every stack-level test still green, because they
# all construct SharedBootstrapStack directly and bypass the context parse.
# ---------------------------------------------------------------------------

import importlib.util
from pathlib import Path


def _app_module():
    app_py = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("adp_app_under_test", app_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synth_slr_count(*extra_ctx: str) -> int:
    """Synth adp-shared-bootstrap through the REAL cdk entrypoint.

    Subprocess rather than in-process because the defect both Cycle 8 (M22) and
    Cycle 9 found is in ``app.py``'s context parse, which only runs when cdk
    drives the app. Every other test here constructs SharedBootstrapStack
    directly and therefore cannot see it: flipping ``app.py`` rendered zero SLRs
    with all of them green.
    """
    import json
    import subprocess

    root = Path(__file__).resolve().parents[1]
    cmd = [
        "npx", "cdk", "synth", "adp-shared-bootstrap",
        "-c", "stage=staging", *extra_ctx, "--json",
    ]
    out = subprocess.run(
        cmd, cwd=root, capture_output=True, text=True
    ).stdout
    doc = json.loads(out[out.index("{"):])
    return sum(
        1 for r in doc.get("Resources", {}).values()
        if r.get("Type") == "AWS::IAM::ServiceLinkedRole"
    )


@pytest.mark.parametrize(
    "extra,expected",
    [
        ((), 1),                                         # default MUST create it
        (("-c", "createLakeFormationSlr=0"), 0),         # permissive parse made this 1
    ],
)
def test_context_flag_parse_at_the_app_layer(extra, expected):
    assert _synth_slr_count(*extra) == expected, (extra, expected)


def test_unrecognised_flag_value_fails_closed():
    """A bootstrap flag that changes the account's identity graph must not guess."""
    mod = _app_module()
    src = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    # The parse must reject rather than default. Pinned on the allowlist shape so
    # a reversion to `!= "false"` fails here even if synth cannot be driven.
    assert 'if _flag in ("false", "0", "no", "off", "")' in src, (
        "app.py's createLakeFormationSlr parse is no longer an explicit "
        "false-allowlist -- a permissive parse silently creates the role"
    )
    assert 'elif _flag in ("true", "1", "yes", "on")' in src
    assert "is not recognised" in src, "unrecognised values must raise, not default"
    # And the default when the flag is absent must be True.
    assert "_create_lf_slr = True" in src
