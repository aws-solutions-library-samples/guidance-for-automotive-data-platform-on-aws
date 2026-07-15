"""Per-product tests for `vehicle_identity`."""

from __future__ import annotations

import pytest

import schema_loader as sl  # noqa: E402


def test_schema_loads():
    s = sl.load_schema("vehicle_identity", kind="product")
    assert s.first_table().name == "vehicle_identity"


def test_one_to_one_with_vins():
    s = sl.load_schema("vehicle_identity", kind="product")
    assert s.first_table().primary_key == ("vin",)


def test_ev_columns_present():
    s = sl.load_schema("vehicle_identity", kind="product")
    tbl = s.first_table()
    for col in ("battery_chemistry", "battery_pack_kwh", "motor_count", "drive_type", "max_charging_rate_kw"):
        assert tbl.column_by_name(col) is not None, f"Missing EV column: {col}"


def test_partition_by_model_year():
    s = sl.load_schema("vehicle_identity", kind="product")
    assert s.first_table().partition_keys == ("model_year",)


@pytest.mark.needs_curated
def test_row_count_matches_vins(dimension_root, curated_root):
    pytest.skip("1:1 with vins dimension — verified post-Group-3.")
