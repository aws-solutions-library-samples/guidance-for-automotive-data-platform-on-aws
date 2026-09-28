"""Per-product tests for `service_records`."""

from __future__ import annotations

import pytest

import schema_loader as sl  # noqa: E402


def test_schema_loads():
    s = sl.load_schema("service_records", kind="product")
    assert s.first_table().name == "service_records"


def test_monthly_partition():
    s = sl.load_schema("service_records", kind="product")
    assert s.first_table().partition_keys == ("service_month",)


def test_three_foreign_keys():
    s = sl.load_schema("service_records", kind="product")
    fks = {fk.references_table for fk in s.first_table().foreign_keys}
    assert {"vins", "customers", "dealers"}.issubset(fks)


def test_dtc_codes_array_string():
    s = sl.load_schema("service_records", kind="product")
    col = s.first_table().column_by_name("dtc_codes")
    assert col is not None
    assert col.type == "array<string>"


@pytest.mark.needs_curated
def test_row_count_10m(curated_root):
    pytest.skip("Implemented in Group 3 generator.")
