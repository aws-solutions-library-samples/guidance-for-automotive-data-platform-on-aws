"""Per-product tests for `energy_usage` (net-new in this spec)."""

from __future__ import annotations

import pytest

import schema_loader as sl  # noqa: E402


def test_schema_loads():
    s = sl.load_schema("energy_usage", kind="product")
    assert s.first_table().name == "energy_usage"


def test_partition_by_usage_date():
    s = sl.load_schema("energy_usage", kind="product")
    assert s.first_table().partition_keys == ("usage_date",)


def test_grain_is_vin_per_day():
    s = sl.load_schema("energy_usage", kind="product")
    assert s.first_table().primary_key == ("vin", "usage_date")


def test_battery_signals_present():
    s = sl.load_schema("energy_usage", kind="product")
    tbl = s.first_table()
    for col in (
        "start_soc_pct",
        "end_soc_pct",
        "min_soc_pct",
        "max_soc_pct",
        "avg_soc_pct",
        "state_of_health_pct",
        "regen_kwh_recovered",
    ):
        assert tbl.column_by_name(col) is not None, f"Missing {col}"


@pytest.mark.needs_curated
def test_row_count_90_day_window(curated_root):
    """5M VINs × 90 days × ~70% active ≈ 315M rows (target 450M before active filter)."""
    pytest.skip("Implemented in Group 3 PySpark generator.")


@pytest.mark.needs_curated
def test_soh_decline_correlates_with_battery_age(curated_root):
    """SoH should decline ~2% per year of battery age."""
    pytest.skip("Implemented in Group 3 generator with realistic narratives.")
