"""T2.3 — Cross-account principal-resolution tests for app.py helpers.

Tests ``_resolve_cvx_kb_principals`` and ``_resolve_kb_deploy_role_arn``
contract per tasks.md T2.3. Marked skip until T5.1 lands the helpers.
Uses monkeypatch for env vars; never reads real environment.
"""

from __future__ import annotations

import sys
import os

import aws_cdk as cdk
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import _resolve_cvx_kb_principals, _resolve_kb_deploy_role_arn

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


def test_deploy_role_arn_from_cdk_context():
    """CDK ctx adpKbDeployRoleArn=<arn> → exact string."""
    arn = f"arn:aws:iam::{_ACCOUNT}:role/my-deploy-role"
    app = cdk.App(context={"adpKbDeployRoleArn": arn})
    result = _resolve_kb_deploy_role_arn(app, _ENV)
    assert result == arn


def test_deploy_role_arn_from_env_var(monkeypatch):
    """Env var ADP_KB_DEPLOY_ROLE_ARN fallback → exact string."""
    arn = f"arn:aws:iam::{_ACCOUNT}:role/env-deploy-role"
    monkeypatch.setenv("ADP_KB_DEPLOY_ROLE_ARN", arn)
    monkeypatch.delenv("CDK_CONTEXT_adpKbDeployRoleArn", raising=False)
    app = cdk.App()
    result = _resolve_kb_deploy_role_arn(app, _ENV)
    assert result == arn


def test_deploy_role_arn_default_when_neither_set(monkeypatch):
    """Neither set → synth-time default cdk-hnb659fds-cfn-exec-role ARN."""
    monkeypatch.delenv("ADP_KB_DEPLOY_ROLE_ARN", raising=False)
    app = cdk.App()
    result = _resolve_kb_deploy_role_arn(app, _ENV)
    expected = (
        f"arn:aws:iam::{_ACCOUNT}:role/"
        f"cdk-hnb659fds-cfn-exec-role-{_ACCOUNT}-{_REGION}"
    )
    assert result == expected


def test_deploy_role_arn_malformed_raises(monkeypatch):
    """Malformed ARN → ValueError or SystemExit."""
    monkeypatch.setenv("ADP_KB_DEPLOY_ROLE_ARN", "not-an-arn")
    app = cdk.App()
    with pytest.raises((ValueError, SystemExit)):
        _resolve_kb_deploy_role_arn(app, _ENV)
