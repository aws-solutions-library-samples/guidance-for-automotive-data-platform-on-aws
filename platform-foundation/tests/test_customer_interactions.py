"""Per-product tests for `customer_interactions`."""

from __future__ import annotations

import pytest

import schema_loader as sl  # noqa: E402


def test_schema_loads():
    s = sl.load_schema("customer_interactions", kind="product")
    assert s.first_table().name == "customer_interactions"


def test_ev_relevant_channels_present():
    s = sl.load_schema("customer_interactions", kind="product")
    col = s.first_table().column_by_name("channel")
    assert col is not None
    assert "mobile_app_charging_issue" in col.enum_values
    assert "ota_update_notification" in col.enum_values


def test_partition_by_interaction_date():
    s = sl.load_schema("customer_interactions", kind="product")
    assert s.first_table().partition_keys == ("interaction_date",)


def test_bucketing_on_customer_id():
    s = sl.load_schema("customer_interactions", kind="product")
    assert s.first_table().bucketing.get("customer_id") == 16


@pytest.mark.needs_curated
def test_row_count_50m(curated_root):
    pytest.skip("Implemented in Group 3 PySpark generator.")
