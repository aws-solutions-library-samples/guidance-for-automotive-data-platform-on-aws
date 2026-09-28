"""Tests for dimension catalog generators.

Most tests in this file require Group 2's `generate_all` step to have
written parquet under `dimensions/<dim>/data.parquet`. Until then they
skip with a clear reason. Tests that are pure schema introspection
(naming, primary keys, expected dimensions) run in the test-skeleton
phase.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import schema_loader as sl  # noqa: E402

# Expected row counts per dimension at scale (per spec).
EXPECTED_ROW_COUNTS = {
    "vins": 4_734_904,  # Meridian organic ramp (spec 2026-09-10-adp-meridian-ev-oem-reseed, D1)
    "customers": 5_000_000,
    "dealers": 200,
    "suppliers": 500,
    "parts": 50_000,
    "time_calendar": 3650,  # ~10 years
    "charging_stations": 50_000,
}


def _dim_parquet_path(dimension_root: Path, name: str) -> Path:
    return dimension_root / name / "data.parquet"


# --- Schema-only checks (run in skeleton phase) ------------------------------


@pytest.mark.parametrize("name", list(EXPECTED_ROW_COUNTS.keys()))
def test_dimension_schema_loads(name):
    s = sl.load_schema(name, kind="dimension")
    assert s.kind == "dimension"
    assert s.name == name
    assert s.first_table().primary_key, f"{name} missing primary_key"


def test_charging_stations_is_present():
    """charging_stations is net-new for this spec; verify its dimension schema is registered."""
    s = sl.load_schema("charging_stations", kind="dimension")
    assert s.first_table().column_by_name("network_provider") is not None
    assert s.first_table().column_by_name("station_type") is not None


def test_suppliers_retained_for_parts_fk():
    """Spec keeps suppliers even though supplier_traceability product is dropped."""
    s = sl.load_schema("suppliers", kind="dimension")
    assert s.first_table().primary_key == ("supplier_id",)


def test_parts_references_suppliers_via_pattern():
    s = sl.load_schema("parts", kind="dimension")
    assert s.first_table().column_by_name("supplier_id") is not None


# --- Data-presence tests (skipped pre-Group-2) -------------------------------


@pytest.mark.needs_dimensions
@pytest.mark.parametrize("name,expected", list(EXPECTED_ROW_COUNTS.items()))
def test_dimension_row_count(dimension_root, name, expected):
    p = _dim_parquet_path(dimension_root, name)
    if not p.exists():
        pytest.skip(f"{p} not produced yet — Group 2 dimension generator pending")
    import pyarrow.parquet as pq  # local import — pyarrow not required at skeleton phase

    actual = pq.read_metadata(str(p)).num_rows
    # tolerance ±1% for stochastic dimensions, ±4 for time_calendar (leap days in 10y window)
    if name == "time_calendar":
        assert 3650 <= actual <= 3654, f"time_calendar: got {actual}, expected 3650..3654 (10y ± leap days)"
    else:
        assert abs(actual - expected) / max(expected, 1) <= 0.01, (
            f"{name}: got {actual}, expected {expected}"
        )


@pytest.mark.needs_dimensions
@pytest.mark.parametrize("name", list(EXPECTED_ROW_COUNTS.keys()))
def test_primary_key_unique(dimension_root, name):
    p = _dim_parquet_path(dimension_root, name)
    if not p.exists():
        pytest.skip(f"{p} not produced yet — Group 2 dimension generator pending")
    import pyarrow.parquet as pq

    s = sl.load_schema(name, kind="dimension")
    pk = list(s.first_table().primary_key)
    table = pq.read_table(str(p), columns=pk)
    df = table.to_pandas()
    assert df.duplicated(subset=pk).sum() == 0, f"{name} has duplicate primary keys"


@pytest.mark.needs_dimensions
def test_dimension_seed_reproducibility(dimension_root, tmp_path: Path):
    """Re-running the dimension generator with the same seed produces byte-identical files."""
    pytest.skip("Re-run smoke depends on Group 2 generator CLI; revisit post-Group-2")


@pytest.mark.needs_dimensions
def test_charging_stations_distribution(dimension_root):
    """Tesla SC ~20%, EA ~20%, EVgo ~10%, ChargePoint ~10%, home/destination ~40%."""
    p = _dim_parquet_path(dimension_root, "charging_stations")
    if not p.exists():
        pytest.skip("charging_stations not produced yet")
    import pyarrow.parquet as pq

    df = pq.read_table(str(p), columns=["network_code"]).to_pandas()
    counts = df["network_code"].value_counts(normalize=True)
    # Loose bounds — generator can tune within these.
    assert 0.15 <= counts.get("TS", 0) <= 0.25
    assert 0.15 <= counts.get("EA", 0) <= 0.25
    assert 0.05 <= counts.get("EVGO", 0) <= 0.15
    assert 0.05 <= counts.get("CP", 0) <= 0.15
    home_dest = counts.get("HOME", 0) + counts.get("DEST", 0)
    assert 0.30 <= home_dest <= 0.50
