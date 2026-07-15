"""Shared pytest fixtures for ADP foundation tests.

Tests skip with a clear reason when their fixture data is not yet
available (Group 2/3 not run). The skip is per-test, not per-module,
so schema-only tests (which don't need fixture data) still run in
the test-skeleton phase.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# Make `from schema_loader import ...` work without installing the package.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LIB = _REPO_ROOT / "source" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return _REPO_ROOT


@pytest.fixture(scope="session")
def curated_root() -> Path:
    """Root directory under which Group 3 generators write per-product parquet.

    Defaults to ``platform-foundation/curated/`` for local dev. Tests that
    need real fixture data should ``pytest.skip`` if this path is missing
    or empty.

    Override via ``ADP_CURATED_ROOT`` env var for CI / local-S3 emulators.
    """
    override = os.environ.get("ADP_CURATED_ROOT")
    if override:
        return Path(override)
    return _REPO_ROOT / "curated"


@pytest.fixture(scope="session")
def dimension_root() -> Path:
    """Root directory for dimension parquet (Group 2 dimension generator output)."""
    override = os.environ.get("ADP_DIMENSION_ROOT")
    if override:
        return Path(override)
    return _REPO_ROOT / "dimensions"


@pytest.fixture(scope="session")
def docs_root() -> Path:
    return _REPO_ROOT.parent / "docs"


@pytest.fixture(scope="session")
def product_names() -> list[str]:
    return [
        "vehicle_telemetry_aggregated",
        "vehicle_identity",
        "charging_sessions",
        "energy_usage",
        "ota_campaigns",
        "customer_360",
        "customer_interactions",
        "service_records",
        "tire_health",
        "vehicle_knowledge_base",
    ]


@pytest.fixture(scope="session")
def dimension_names() -> list[str]:
    return [
        "vins",
        "customers",
        "dealers",
        "suppliers",
        "parts",
        "time_calendar",
        "charging_stations",
    ]


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Auto-skip tests whose required fixture data isn't present.

    - ``needs_curated`` → requires curated parquet tree (Group 3 output).
      Override via ``ADP_CURATED_ROOT`` env var (matches the
      ``curated_root`` session fixture above).
    - ``needs_dimensions`` → requires ``<repo>/dimensions/`` (Group 2 output).
      Override via ``ADP_DIMENSION_ROOT`` env var.
    """
    repo = _REPO_ROOT

    cur_root_override = os.environ.get("ADP_CURATED_ROOT")
    if cur_root_override:
        curated = Path(cur_root_override)
    else:
        curated = repo / "curated"
    has_curated = curated.exists() and any(curated.iterdir())

    dim_root_override = os.environ.get("ADP_DIMENSION_ROOT")
    if dim_root_override:
        dim_root = Path(dim_root_override)
    else:
        dim_root = repo / "dimensions"
    has_dimensions = dim_root.exists() and any(dim_root.iterdir())

    skip_curated = pytest.mark.skipif(
        True,
        reason=f"{curated}/ has no fixture data — Group 3 generators have not run.",
    )
    skip_dimensions = pytest.mark.skipif(
        True,
        reason=f"{dim_root}/ has no fixture data — Group 2 dimension generator has not run.",
    )
    for item in items:
        if "needs_curated" in item.keywords and not has_curated:
            item.add_marker(skip_curated)
        if "needs_dimensions" in item.keywords and not has_dimensions:
            item.add_marker(skip_dimensions)
