"""Unit tests for aoss_index_bootstrap Lambda handler.

All tests are hermetic — no real HTTP calls. The OpenSearch client and
AWS4Auth are patched at import time.
"""
import importlib
import sys
import types
from unittest.mock import MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Minimal fake opensearchpy module so tests run without the real package
# installed in the test venv (it will be in the layer at deploy time,
# but the pip install in the Verify step installs it before running).
# ---------------------------------------------------------------------------

def _ensure_opensearchpy():
    """Install real opensearchpy if available; otherwise provide a minimal stub."""
    try:
        import opensearchpy  # noqa: F401
        return
    except ImportError:
        pass
    # Stub minimal classes used by the handler
    mod = types.ModuleType("opensearchpy")
    class _BaseExc(Exception):
        def __init__(self, *a, status_code=None, **kw):
            self.status_code = status_code
            super().__init__(*a)
    class NotFoundError(_BaseExc): pass
    class RequestError(_BaseExc): pass
    class AuthorizationException(_BaseExc): pass
    class RequestsHttpConnection: pass
    class OpenSearch:
        def __init__(self, **kw): self.indices = MagicMock()
    mod.NotFoundError = NotFoundError
    mod.RequestError = RequestError
    mod.AuthorizationException = AuthorizationException
    mod.RequestsHttpConnection = RequestsHttpConnection
    mod.OpenSearch = OpenSearch
    sys.modules["opensearchpy"] = mod
    sys.modules["requests_aws4auth"] = types.ModuleType("requests_aws4auth")
    sys.modules["requests_aws4auth"].AWS4Auth = MagicMock

_ensure_opensearchpy()


# ---------------------------------------------------------------------------
# Load the handler module (after stubs are in place)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reload_handler():
    """Re-import handler fresh per test to avoid module-level state leakage."""
    if "lambda.aoss_index_bootstrap.index" in sys.modules:
        del sys.modules["lambda.aoss_index_bootstrap.index"]
    if "aoss_index_bootstrap.index" in sys.modules:
        del sys.modules["aoss_index_bootstrap.index"]


def _load(monkeypatch, endpoint="https://test.us-east-1.aoss.amazonaws.com",
          index_name="test-index", dimensions="1024", space_type="l2", engine="faiss"):
    monkeypatch.setenv("COLLECTION_ENDPOINT", endpoint)
    monkeypatch.setenv("INDEX_NAME", index_name)
    monkeypatch.setenv("INDEX_DIMENSIONS", dimensions)
    monkeypatch.setenv("INDEX_SPACE_TYPE", space_type)
    monkeypatch.setenv("INDEX_ENGINE", engine)
    # Resolve the lambda dir relative to this test file (portable across
    # machines / CI — never a hardcoded absolute path).
    from pathlib import Path
    _lambda_dir = Path(__file__).resolve().parents[1] / "lambda"
    sys.path.insert(0, str(_lambda_dir))
    import importlib
    mod = importlib.import_module("aoss_index_bootstrap.index")
    importlib.reload(mod)
    return mod


class _FakeContext:
    aws_request_id = "test-req-123"


# ---------------------------------------------------------------------------
# Helper: build a minimal fake credentials chain
# ---------------------------------------------------------------------------

def _fake_boto3_session():
    creds = MagicMock()
    creds.get_frozen_credentials.return_value = MagicMock(
        access_key="AKIATEST", secret_key="secret", token=None
    )
    session = MagicMock()
    session.get_credentials.return_value = creds
    session.region_name = "us-east-1"
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_returns_success_on_200(monkeypatch):
    mod = _load(monkeypatch)
    mock_client = MagicMock()
    mock_client.indices.create.return_value = {"result": "created"}

    with patch.object(mod, "_get_client", return_value=mock_client):
        result = mod.handler({"RequestType": "Create"}, _FakeContext())

    assert result["PhysicalResourceId"] == "test-index"
    assert result["Data"]["IndexName"] == "test-index"
    mock_client.indices.create.assert_called_once()


def test_create_returns_success_on_409_already_exists(monkeypatch):
    """409 / resource_already_exists_exception on Create is treated as success."""
    mod = _load(monkeypatch)
    from opensearchpy import RequestError

    already_exists = RequestError("resource_already_exists_exception", MagicMock(), {})
    mock_client = MagicMock()
    mock_client.indices.create.side_effect = already_exists

    with patch.object(mod, "_get_client", return_value=mock_client):
        result = mod.handler({"RequestType": "Create"}, _FakeContext())

    assert result["PhysicalResourceId"] == "test-index"


def test_create_retries_on_403_then_succeeds(monkeypatch):
    """Two AuthorizationException then success — create called ≥3 times."""
    mod = _load(monkeypatch)
    from opensearchpy import AuthorizationException

    mock_client = MagicMock()
    mock_client.indices.create.side_effect = [
        AuthorizationException("403"),
        AuthorizationException("403"),
        {"result": "created"},
    ]

    with patch.object(mod, "_get_client", return_value=mock_client), \
         patch("time.sleep"):  # speed up retries
        result = mod.handler({"RequestType": "Create"}, _FakeContext())

    assert result["PhysicalResourceId"] == "test-index"
    assert mock_client.indices.create.call_count >= 3


def test_create_fails_hard_on_500(monkeypatch):
    """Non-403/409 errors propagate — CFN marks the resource Failed."""
    mod = _load(monkeypatch)

    mock_client = MagicMock()
    mock_client.indices.create.side_effect = Exception("InternalServerError 500")

    with patch.object(mod, "_get_client", return_value=mock_client):
        with pytest.raises(Exception, match="500"):
            mod.handler({"RequestType": "Create"}, _FakeContext())


def test_delete_returns_success(monkeypatch):
    mod = _load(monkeypatch)
    mock_client = MagicMock()
    mock_client.indices.delete.return_value = {"acknowledged": True}

    with patch.object(mod, "_get_client", return_value=mock_client):
        result = mod.handler({"RequestType": "Delete"}, _FakeContext())

    assert result["PhysicalResourceId"] == "test-index"
    mock_client.indices.delete.assert_called_once_with(index="test-index")


def test_delete_treats_404_as_success(monkeypatch):
    mod = _load(monkeypatch)
    from opensearchpy import NotFoundError

    mock_client = MagicMock()
    mock_client.indices.delete.side_effect = NotFoundError("404")

    with patch.object(mod, "_get_client", return_value=mock_client):
        result = mod.handler({"RequestType": "Delete"}, _FakeContext())

    assert result["PhysicalResourceId"] == "test-index"


def test_no_full_body_in_logs(monkeypatch, caplog):
    """Handler must not log the full index body (security + verbosity guard)."""
    import json
    mod = _load(monkeypatch)
    mock_client = MagicMock()
    mock_client.indices.create.return_value = {"result": "created"}

    with patch.object(mod, "_get_client", return_value=mock_client), \
         caplog.at_level("DEBUG", logger="lambda.aoss_index_bootstrap.index"), \
         caplog.at_level("DEBUG", logger="aoss_index_bootstrap.index"):
        mod.handler({"RequestType": "Create"}, _FakeContext())

    # Build the full body string as the handler would produce it
    body = mod._build_index_body(1024, "l2", "faiss")
    body_str = json.dumps(body)

    for record in caplog.records:
        assert body_str not in record.getMessage(), \
            f"Log record contains full request body: {record.getMessage()!r}"
