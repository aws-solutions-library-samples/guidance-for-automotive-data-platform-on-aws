"""Per-product tests for `vehicle_telemetry_aggregated`."""

from __future__ import annotations

import pytest

import schema_loader as sl  # noqa: E402


def test_schema_loads():
    s = sl.load_schema("vehicle_telemetry_aggregated", kind="product")
    assert s.first_table().name == "vehicle_telemetry_aggregated"


def test_partition_and_bucketing():
    s = sl.load_schema("vehicle_telemetry_aggregated", kind="product")
    tbl = s.first_table()
    assert tbl.partition_keys == ("event_date",)
    assert tbl.bucketing == {"vin": 16}


def test_fk_to_vins():
    s = sl.load_schema("vehicle_telemetry_aggregated", kind="product")
    fks = s.first_table().foreign_keys
    assert any(fk.references_table == "vins" for fk in fks)


@pytest.mark.needs_curated
def test_row_count_at_scale(curated_root):
    p = curated_root / "vehicle_telemetry_aggregated"
    if not p.exists() or not any(p.iterdir()):
        pytest.skip("Generator not run yet")
    pytest.skip("Implemented as part of Group 3 generator + Group 6 verify.")


@pytest.mark.needs_curated
def test_has_vss_aligned_columns(curated_root):
    """Spot-check: speed_kmh, start_soc_pct, motor_temp_c are present."""
    pytest.skip("Implemented in Group 3.")
