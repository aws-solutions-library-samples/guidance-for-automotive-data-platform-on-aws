"""T2.3 — Cross-account principal-resolution tests for app.py helpers.

Tests ``_resolve_cvx_kb_principals`` contract per tasks.md T1.4.
Uses monkeypatch for env vars; never reads real environment.

Note: ``_resolve_kb_deploy_role_arn`` was removed (spec
2026-08-03-adp-vkb-s3-vectors § Decision (I)).  The import of that
helper is intentionally absent; keeping it would break collection
once Group 2 deletes the function from app.py.
"""

from __future__ import annotations

import sys
import os

import aws_cdk as cdk
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import _resolve_cvx_kb_principals

_ACCOUNT = "123456789012"
_REGION = "us-east-1"
_ENV = cdk.Environment(account=_ACCOUNT, region=_REGION)


def test_cvx_kb_principals_from_cdk_context():
    """CDK ctx cvxKbPrincipals=arn1,arn2 → list of 2 ARNs."""
    arn1 = "arn:aws:iam::123456789012:role/role-a"
    arn2 = "arn:aws:iam::123456789012:role/role-b"
    app = cdk.App(context={"cvxKbPrincipals": f"{arn1},{arn2}"})
    result = _resolve_cvx_kb_principals(app)
    assert result == [arn1, arn2]


def test_cvx_kb_principals_from_env_var(monkeypatch):
    """Env var ADP_KB_CVX_PRINCIPAL_ARNS=arn1,arn2 → list of 2 ARNs."""
    arn1 = "arn:aws:iam::123456789012:role/role-a"
    arn2 = "arn:aws:iam::123456789012:role/role-b"
    monkeypatch.setenv("ADP_KB_CVX_PRINCIPAL_ARNS", f"{arn1},{arn2}")
    app = cdk.App()
    result = _resolve_cvx_kb_principals(app)
    assert result == [arn1, arn2]


def test_cvx_kb_principals_both_unset(monkeypatch):
    """Both context and env var unset → None."""
    monkeypatch.delenv("ADP_KB_CVX_PRINCIPAL_ARNS", raising=False)
    app = cdk.App()
    result = _resolve_cvx_kb_principals(app)
    assert result is None


def test_app_vkb_wiring_no_deploy_role_arn_kwarg():
    """app.py must not pass deploy_role_arn= to VehicleKnowledgeBaseStack.

    The kwarg was retired per spec 2026-08-03-adp-vkb-s3-vectors § Decision (I).
    """
    import os
    app_py_path = os.path.join(os.path.dirname(__file__), '..', 'app.py')
    with open(app_py_path) as f:
        source = f.read()
    assert 'deploy_role_arn=' not in source, (
        'app.py must not pass deploy_role_arn= to VehicleKnowledgeBaseStack; '
        'the kwarg was retired per spec 2026-08-03-adp-vkb-s3-vectors § Decision (I).'
    )


def test_app_helpers_no_resolve_kb_deploy_role_arn_function():
    """_resolve_kb_deploy_role_arn must not be importable from app.

    The helper was deleted per spec 2026-08-03-adp-vkb-s3-vectors § Decision (I).
    """
    try:
        from app import _resolve_kb_deploy_role_arn  # noqa: F401
        pytest.fail('_resolve_kb_deploy_role_arn should be gone from app.py')
    except ImportError:
        pass
