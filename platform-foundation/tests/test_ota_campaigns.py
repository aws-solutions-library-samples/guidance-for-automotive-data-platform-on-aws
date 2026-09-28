"""Per-product tests for `ota_campaigns` (net-new in this spec, multi-table)."""

from __future__ import annotations

import pytest

import schema_loader as sl  # noqa: E402


def test_schema_has_two_tables():
    s = sl.load_schema("ota_campaigns", kind="product")
    assert s.is_multi_table()
    assert {t.name for t in s.tables} == {"ota_campaigns", "ota_campaign_events"}


def test_header_partition_by_campaign_id():
    s = sl.load_schema("ota_campaigns", kind="product")
    header = next(t for t in s.tables if t.name == "ota_campaigns")
    assert header.partition_keys == ("campaign_id",)


def test_events_partition_by_dispatch_date():
    s = sl.load_schema("ota_campaigns", kind="product")
    events = next(t for t in s.tables if t.name == "ota_campaign_events")
    assert events.partition_keys == ("dispatch_date",)


def test_severity_enum_matches_spec():
    s = sl.load_schema("ota_campaigns", kind="product")
    header = next(t for t in s.tables if t.name == "ota_campaigns")
    col = header.column_by_name("severity")
    assert col is not None
    assert set(col.enum_values) == {"critical", "high", "medium", "low"}


def test_final_status_enum_includes_all_states():
    s = sl.load_schema("ota_campaigns", kind="product")
    events = next(t for t in s.tables if t.name == "ota_campaign_events")
    col = events.column_by_name("final_status")
    assert col is not None
    expected = {
        "not_yet_dispatched",
        "dispatched",
        "downloading",
        "download_failed",
        "installing",
        "install_failed",
        "installed",
        "rolled_back",
        "declined_by_user",
    }
    assert set(col.enum_values) == expected


def test_phased_rollout_pct_is_array_int():
    s = sl.load_schema("ota_campaigns", kind="product")
    header = next(t for t in s.tables if t.name == "ota_campaigns")
    col = header.column_by_name("phased_rollout_pct")
    assert col is not None
    assert col.type == "array<int>"


@pytest.mark.needs_curated
def test_adoption_curve(curated_root):
    """60% within 7 days, 85% within 30 days, ~10% never adopt."""
    pytest.skip("Implemented in Group 3 generator.")
