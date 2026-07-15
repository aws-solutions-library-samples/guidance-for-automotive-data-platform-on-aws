"""Per-product tests for `charging_sessions` (net-new in this spec)."""

from __future__ import annotations

import pytest

import schema_loader as sl  # noqa: E402


def test_schema_loads():
    s = sl.load_schema("charging_sessions", kind="product")
    assert s.first_table().name == "charging_sessions"


def test_session_id_pk():
    s = sl.load_schema("charging_sessions", kind="product")
    assert s.first_table().primary_key == ("session_id",)


def test_three_foreign_keys():
    s = sl.load_schema("charging_sessions", kind="product")
    fks = {fk.references_table for fk in s.first_table().foreign_keys}
    assert {"vins", "customers", "charging_stations"}.issubset(fks)


def test_cost_columns_are_decimal_typed():
    s = sl.load_schema("charging_sessions", kind="product")
    tbl = s.first_table()
    cost = tbl.column_by_name("cost_usd")
    assert cost is not None and cost.type == "decimal"
    assert cost.decimal_precision == 10 and cost.decimal_scale == 4


def test_station_type_enum():
    s = sl.load_schema("charging_sessions", kind="product")
    col = s.first_table().column_by_name("station_type")
    assert col is not None
    assert set(col.enum_values) == {"home_l1", "home_l2", "public_dc_fast", "destination_l2"}


def test_interrupt_reason_enum():
    s = sl.load_schema("charging_sessions", kind="product")
    col = s.first_table().column_by_name("interrupt_reason")
    assert col is not None
    assert set(col.enum_values) == {
        "user_unplug", "station_fault", "vehicle_fault", "network_drop"
    }


@pytest.mark.needs_curated
def test_distribution_70_25_5(curated_root):
    """Spec realism: ~70% home, ~25% public DC fast, ~5% destination L2."""
    pytest.skip("Implemented in Group 3 generator.")


@pytest.mark.needs_curated
def test_total_session_count(curated_root):
    """20M sessions ± 200K."""
    pytest.skip("Implemented in Group 3 generator.")
