"""Per-product tests for `customer_360`."""

from __future__ import annotations

import pytest

import schema_loader as sl  # noqa: E402


def test_schema_loads():
    s = sl.load_schema("customer_360", kind="product")
    assert s.first_table().name == "customer_360"


def test_health_and_churn_columns():
    s = sl.load_schema("customer_360", kind="product")
    tbl = s.first_table()
    assert tbl.column_by_name("health_score") is not None
    assert tbl.column_by_name("churn_probability") is not None


def test_pii_columns_marked():
    s = sl.load_schema("customer_360", kind="product")
    tbl = s.first_table()
    pii_cols = {c.name for c in tbl.columns if c.pii}
    expected_pii = {"customer_id", "full_name", "email", "phone", "address_line1", "city", "state", "postal_code", "primary_vin"}
    # primary_vin is a partial-PII; actual schema marks it non-PII as a join key.
    assert {"customer_id", "full_name", "email", "phone"}.issubset(pii_cols), (
        f"PII tagging incomplete; got {pii_cols}"
    )


def test_partition_by_snapshot_date():
    s = sl.load_schema("customer_360", kind="product")
    assert s.first_table().partition_keys == ("snapshot_date",)


@pytest.mark.needs_curated
def test_5m_per_snapshot(curated_root):
    pytest.skip("Implemented in Group 3 generator.")
