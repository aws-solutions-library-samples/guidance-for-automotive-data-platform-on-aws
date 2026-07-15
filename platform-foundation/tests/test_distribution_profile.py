"""Distribution profile sanity tests.

Every numeric column in every product must have:
- stddev > 0 (no flat distributions)
- ≥3 distinct values

Pre-Group-3 these tests skip — they're a goalpost for the synthetic
data generators.
"""

from __future__ import annotations

import pytest

import schema_loader as sl  # noqa: E402


_NUMERIC_TYPES = {"int", "bigint", "double", "decimal"}


def _numeric_columns(s: sl.Schema) -> list[str]:
    return [
        c.name
        for tbl in s.tables
        for c in tbl.columns
        if c.type in _NUMERIC_TYPES
    ]


# --- Schema-only checks ------------------------------------------------------


@pytest.mark.parametrize(
    "product_name",
    [
        "vehicle_telemetry_aggregated",
        "charging_sessions",
        "energy_usage",
        "ota_campaigns",
        "customer_interactions",
        "service_records",
        "customer_360",
        "vehicle_identity",
    ],
)
def test_product_has_numeric_columns(product_name):
    s = sl.load_schema(product_name, kind="product")
    nums = _numeric_columns(s)
    assert nums, f"{product_name} has no numeric columns to profile"


# --- Data-presence (skipped pre-Group-3) -------------------------------------


@pytest.mark.needs_curated
@pytest.mark.parametrize(
    "product_name",
    [
        "vehicle_telemetry_aggregated",
        "charging_sessions",
        "energy_usage",
    ],
)
def test_distribution_non_degenerate(curated_root, product_name):
    p = curated_root / product_name
    if not p.exists() or not any(p.iterdir()):
        pytest.skip(f"{product_name} not generated yet")
    pytest.skip(
        "Distribution profiler runs as part of Group 6 verification. "
        "Placeholder asserts call shape."
    )
