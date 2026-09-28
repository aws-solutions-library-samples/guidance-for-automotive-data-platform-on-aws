# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Pagination and skip-accounting tests for daily_tire_check.

Issue: issues/2026-08-10-daily-tire-check-unpaginated-query-truncation/

These tests exist because `test_provenance.py` could not fail on the bug they
cover.  Its mock returns a dict with no `LastEvaluatedKey`, so a single-page read
and a fully-paginated read are indistinguishable to it — the provenance suite
passed on an alert computed from 272 of 4,643 real readings.

The distinguishing move here is a mock that **pages**: `query` is driven by
`ExclusiveStartKey` and returns `LastEvaluatedKey` until exhausted.  A stub
cannot fail the way a service fails unless it is built to reproduce the
service's boundary, and the 1 MB page boundary is the whole defect.

Covered:
  - the trend uses readings beyond page 1 (the regression test for the bug)
  - the telemetry read is newest-first, so a truncated read keeps recent data
  - the vehicles scan is paginated
  - safety bounds report rather than truncate silently
  - a per-vehicle query failure is counted, not swallowed
  - an all-vehicles read failure raises instead of reporting success
"""

import importlib.util
import os
import sys
import time
import types
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

NOW_MS = int(time.time() * 1000)
HOUR_MS = 3_600_000
DAY_MS = 86_400_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_main() -> types.ModuleType:
    """Import main.py fresh (env vars come from conftest.py)."""
    module_name = "daily_tire_check_main_pagination"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name, os.path.join(os.path.dirname(__file__), "..", "main.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    sys.modules[module_name] = module
    return module


def _truncation_shaped_window() -> list:
    """Readings shaped like the real VEH-1780081115 failure.

    30 readings with a genuine -0.8 PSI/day decline across 5 days, of which the
    **newest 10 sit inside a single hour**.  That shape is what made the bug
    invisible: one page's worth of readings spans 0.04 days, which the
    `time_span_days < 0.1` guard rejects, so the vehicle with the most data
    produced no output at all.

    Returned oldest-first; the mock serves them newest-first, as DynamoDB does
    with ScanIndexForward=False.
    """
    rows = []
    total = 30
    for i in range(total):
        # Pressure declines linearly 33.0 -> 29.0 across the series.
        pressure = 33.0 - (4.0 * i / (total - 1))
        if i < 20:
            # 20 older readings spread from 5 days ago to 1 day ago.
            ts = NOW_MS - int(5 * DAY_MS) + int(i * (4 * DAY_MS) / 19)
        else:
            # 10 newest readings clustered inside the final hour.
            ts = NOW_MS - HOUR_MS + int((i - 20) * (HOUR_MS / 10))
        rows.append(
            {
                "vehicleId": "VEH-PAGED",
                "timestamp": Decimal(str(ts)),
                "tire_pressure_fl": Decimal(str(round(pressure, 2))),
                "tire_pressure_fr": Decimal("32.0"),
                "tire_pressure_rl": Decimal("32.0"),
                "tire_pressure_rr": Decimal("32.0"),
            }
        )
    return rows


class PagingTelemetryTable:
    """Mock telemetry table that honours ScanIndexForward and paginates.

    `rows` is supplied oldest-first. With ScanIndexForward=False the table serves
    them newest-first in pages of `page_size`, setting LastEvaluatedKey until the
    final page — exactly the contract the real service offers and the one the
    production code previously ignored.
    """

    def __init__(self, rows: list, page_size: int = 10):
        self._rows_asc = sorted(rows, key=lambda r: int(r["timestamp"]))
        self.page_size = page_size
        self.calls: list = []

    def query(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        ordered = (
            self._rows_asc
            if kwargs.get("ScanIndexForward", True)
            else list(reversed(self._rows_asc))
        )
        offset = int(kwargs.get("ExclusiveStartKey", {}).get("_offset", 0))
        page = ordered[offset : offset + self.page_size]
        resp: dict = {"Items": page}
        if offset + self.page_size < len(ordered):
            resp["LastEvaluatedKey"] = {"_offset": offset + self.page_size}
        return resp


def _alerts_mock():
    alerts_table = MagicMock()
    batch_writer = MagicMock()
    alerts_table.batch_writer.return_value.__enter__ = MagicMock(return_value=batch_writer)
    alerts_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)
    return alerts_table, batch_writer


def _ssm_mock():
    client = MagicMock()
    client.get_parameter.return_value = {"Parameter": {"Value": "model-v1"}}
    return client


def _run(vehicles_table, telemetry_table, alerts_table, context=None):
    def fake_table(name: str):
        if "vehicles" in name:
            return vehicles_table
        if "telemetry" in name:
            return telemetry_table
        if "alerts" in name:
            return alerts_table
        raise ValueError(name)

    ddb_resource = MagicMock()
    ddb_resource.Table.side_effect = fake_table
    with (
        patch("boto3.resource", return_value=ddb_resource),
        patch("boto3.client", return_value=_ssm_mock()),
    ):
        main = _import_main()
        return main.handler(None, context)


def _written_items(batch_writer) -> list:
    out = []
    for c in batch_writer.put_item.call_args_list:
        out.append(c.kwargs.get("Item") or c.args[0]["Item"])
    return out


# ---------------------------------------------------------------------------
# The regression test for the bug itself
# ---------------------------------------------------------------------------

class TestReadsBeyondFirstPage:
    """The trend must be fitted over the whole window, not one page of it."""

    def test_alert_produced_from_readings_spanning_multiple_pages(self):
        """A declining trend whose newest page spans under the guard threshold
        must still alert, because the older pages are read.

        Pre-fix this returned zero alerts: page 1 spanned ~0.04 days and the
        `time_span_days < 0.1` guard discarded the tire outright.
        """
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-PAGED"}]}
        telemetry = PagingTelemetryTable(_truncation_shaped_window(), page_size=10)
        alerts, batch_writer = _alerts_mock()

        result = _run(vehicles, telemetry, alerts)

        assert len(telemetry.calls) > 1, (
            "Telemetry was read with a single query — LastEvaluatedKey was not "
            "followed, which is the defect this test exists to prevent"
        )
        items = _written_items(batch_writer)
        assert items, (
            "No alert written. The window holds a -0.8 PSI/day decline ending at "
            "29.0 PSI across 5 days; only a truncated read hides it."
        )
        assert result["telemetry_pages_read"] == len(telemetry.calls)

    def test_trend_span_reflects_full_window_not_one_page(self):
        """The recorded trend span must be the window's span, not a page's."""
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-PAGED"}]}
        telemetry = PagingTelemetryTable(_truncation_shaped_window(), page_size=10)
        alerts, batch_writer = _alerts_mock()

        _run(vehicles, telemetry, alerts)

        items = _written_items(batch_writer)
        assert items
        span = float(items[0]["metadata"]["trend_span_days"])
        assert span > 4.0, (
            f"trend_span_days={span} — a full read spans ~5 days; anything near "
            f"0.04 means only the newest page was analysed"
        )

    def test_readings_analyzed_counts_all_pages(self):
        """readings_analyzed must count every reading, not one page's worth."""
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-PAGED"}]}
        telemetry = PagingTelemetryTable(_truncation_shaped_window(), page_size=10)
        alerts, batch_writer = _alerts_mock()

        _run(vehicles, telemetry, alerts)

        items = _written_items(batch_writer)
        assert items
        assert int(items[0]["metadata"]["readings_analyzed"]) == 30


# ---------------------------------------------------------------------------
# Read direction
# ---------------------------------------------------------------------------

class TestNewestFirstRead:
    """The telemetry read must be newest-first.

    DynamoDB defaults to ascending, which put the *oldest* slice of the window on
    page 1. Beyond truncating the trend, that made `current_pressure` a reading up
    to 7 days old while `computedAt` said now.
    """

    def test_scan_index_forward_is_false(self):
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-PAGED"}]}
        telemetry = PagingTelemetryTable(_truncation_shaped_window(), page_size=10)
        alerts, _ = _alerts_mock()

        _run(vehicles, telemetry, alerts)

        assert telemetry.calls, "No query was issued"
        for call_kwargs in telemetry.calls:
            assert call_kwargs.get("ScanIndexForward") is False, (
                "Telemetry must be queried newest-first so that a truncated read "
                "retains recent readings rather than week-old ones"
            )

    def test_current_pressure_is_the_newest_reading(self):
        """current_pressure must be the most recent value in the window."""
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-PAGED"}]}
        rows = _truncation_shaped_window()
        telemetry = PagingTelemetryTable(rows, page_size=10)
        alerts, batch_writer = _alerts_mock()

        _run(vehicles, telemetry, alerts)

        newest = max(rows, key=lambda r: int(r["timestamp"]))
        items = _written_items(batch_writer)
        assert items
        assert float(items[0]["metadata"]["current_pressure"]) == pytest.approx(
            float(newest["tire_pressure_fl"]), abs=0.05
        )

    def test_alert_records_staleness_of_newest_reading(self):
        """metadata must carry the age of the freshest reading behind the alert.

        The window admits readings up to 7 days old — measured 2026-08-10, the
        freshest real tire reading in staging was 142h old — so an alert stamped
        computedAt=now can rest on days-old data.
        """
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-PAGED"}]}
        telemetry = PagingTelemetryTable(_truncation_shaped_window(), page_size=10)
        alerts, batch_writer = _alerts_mock()

        _run(vehicles, telemetry, alerts)

        items = _written_items(batch_writer)
        assert items
        assert "newest_reading_age_hours" in items[0]["metadata"]
        age = float(items[0]["metadata"]["newest_reading_age_hours"])
        assert 0 <= age < 2, f"fixture's newest reading is <1h old, got {age}h"


# ---------------------------------------------------------------------------
# Vehicles scan
# ---------------------------------------------------------------------------

class TestVehiclesScanPagination:
    """The vehicles scan must follow LastEvaluatedKey.

    It returned all 54 staging vehicles by luck. Past one 1 MB page it would have
    dropped vehicles from the sweep with no error and no log line.
    """

    def test_vehicles_beyond_first_scan_page_are_checked(self):
        vehicles = MagicMock()
        vehicles.scan.side_effect = [
            {"Items": [{"vehicleId": "VEH-A"}], "LastEvaluatedKey": {"vehicleId": "VEH-A"}},
            {"Items": [{"vehicleId": "VEH-B"}]},
        ]
        telemetry = PagingTelemetryTable([], page_size=10)
        alerts, _ = _alerts_mock()

        result = _run(vehicles, telemetry, alerts)

        assert result["vehicles_checked"] == 2, (
            "A vehicle on the second scan page was dropped — the scan is not paginated"
        )
        assert vehicles.scan.call_count == 2


# ---------------------------------------------------------------------------
# Safety bounds must announce themselves
# ---------------------------------------------------------------------------

class TestSafetyBoundsAreReported:
    """A bound that truncates silently would reintroduce the defect elsewhere."""

    def test_page_cap_truncation_is_counted(self, monkeypatch):
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-PAGED"}]}
        # 30 rows at 1 row/page = 30 pages, against a cap of 2.
        telemetry = PagingTelemetryTable(_truncation_shaped_window(), page_size=1)
        alerts, _ = _alerts_mock()

        def fake_table(name: str):
            if "vehicles" in name:
                return vehicles
            if "telemetry" in name:
                return telemetry
            return alerts

        ddb_resource = MagicMock()
        ddb_resource.Table.side_effect = fake_table
        with (
            patch("boto3.resource", return_value=ddb_resource),
            patch("boto3.client", return_value=_ssm_mock()),
        ):
            main = _import_main()
            monkeypatch.setattr(main, "MAX_PAGES_PER_VEHICLE", 2)
            result = main.handler()

        assert result["truncated_reads"] == 1, (
            "Hitting the page cap must be reported in the result, not absorbed"
        )
        assert len(telemetry.calls) == 2

    def test_time_budget_truncation_is_counted(self, monkeypatch):
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-PAGED"}]}
        telemetry = PagingTelemetryTable(_truncation_shaped_window(), page_size=1)
        alerts, _ = _alerts_mock()

        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 1_000  # nearly out of time

        result = _run(vehicles, telemetry, alerts, context=context)

        assert result["truncated_reads"] == 1
        assert len(telemetry.calls) == 1, (
            "Pagination must stop when the invocation is nearly out of time"
        )


# ---------------------------------------------------------------------------
# Read failures must not be silent
# ---------------------------------------------------------------------------

class TestReadFailuresAreVisible:
    """`except Exception: continue` made a throttle look like a healthy tire."""

    def test_single_vehicle_query_error_is_counted_not_swallowed(self):
        vehicles = MagicMock()
        vehicles.scan.return_value = {
            "Items": [{"vehicleId": "VEH-BAD"}, {"vehicleId": "VEH-PAGED"}]
        }

        good = PagingTelemetryTable(_truncation_shaped_window(), page_size=10)

        class PartiallyFailing:
            calls: list = []

            def query(self, **kwargs):
                vid = kwargs["ExpressionAttributeValues"][":v"]
                if vid == "VEH-BAD":
                    raise RuntimeError("ProvisionedThroughputExceededException")
                return good.query(**kwargs)

        alerts, batch_writer = _alerts_mock()
        result = _run(vehicles, PartiallyFailing(), alerts)

        assert result["query_errors"] == 1, (
            "A failed per-vehicle read must be counted so it can be alarmed on"
        )
        # The healthy vehicle must still be processed — one bad read cannot
        # abort a sweep of the whole fleet.
        assert _written_items(batch_writer), "The readable vehicle was not processed"

    def test_all_vehicles_failing_raises(self):
        """A systemic read failure must not report a successful run.

        Same reasoning as the SSM guard: zero alerts from an unreadable table is
        indistinguishable from zero alerts from a healthy fleet, and that
        ambiguity is the root of the parent issue.
        """
        vehicles = MagicMock()
        vehicles.scan.return_value = {
            "Items": [{"vehicleId": "VEH-A"}, {"vehicleId": "VEH-B"}]
        }

        class AlwaysFailing:
            def query(self, **kwargs):
                raise RuntimeError("AccessDeniedException")

        alerts, batch_writer = _alerts_mock()
        with pytest.raises(RuntimeError, match="failed for all"):
            _run(vehicles, AlwaysFailing(), alerts)

        assert not batch_writer.put_item.called


# ---------------------------------------------------------------------------
# Skip accounting
# ---------------------------------------------------------------------------

class TestSkipAccounting:
    """Every discarded candidate must be attributable to a reason."""

    def test_vehicle_below_min_readings_is_recorded(self):
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-THIN"}]}
        telemetry = PagingTelemetryTable(_truncation_shaped_window()[:3], page_size=10)
        alerts, _ = _alerts_mock()

        result = _run(vehicles, telemetry, alerts)

        assert result["skips"].get("below_min_readings_vehicle") == 1
        assert result["warnings"] == 0

    def test_healthy_fleet_is_distinguishable_from_a_broken_read(self):
        """Zero alerts from healthy tires must report the reason.

        This is the distinction the 2026-08-10 run could not make: the log said
        "No tire pressure anomalies detected" whether the tires were fine or the
        readings were never read.
        """
        healthy = []
        for i in range(30):
            healthy.append(
                {
                    "vehicleId": "VEH-OK",
                    "timestamp": Decimal(str(NOW_MS - int((29 - i) * 4 * HOUR_MS))),
                    "tire_pressure_fl": Decimal("32.0"),
                    "tire_pressure_fr": Decimal("32.0"),
                    "tire_pressure_rl": Decimal("32.0"),
                    "tire_pressure_rr": Decimal("32.0"),
                }
            )
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-OK"}]}
        telemetry = PagingTelemetryTable(healthy, page_size=10)
        alerts, _ = _alerts_mock()

        result = _run(vehicles, telemetry, alerts)

        assert result["warnings"] == 0
        assert result["query_errors"] == 0
        assert result["truncated_reads"] == 0
        assert result["skips"].get("no_qualifying_trend") == 4, (
            "A flat, healthy fleet must report four evaluated-but-not-alerting "
            "tires, proving the readings were actually analysed"
        )
