# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Positive control for the pagination fix.

Issue: issues/2026-08-10-daily-tire-check-unpaginated-query-truncation/

A regression test is only worth its runtime if it can fail. `test_pagination.py`
asserts the fixed read finds a leak; this file asserts the **legacy** read misses
that same leak, which is what proves the fixture has diagnostic power rather than
merely agreeing with whatever the code currently does.

The mechanism reproduced here is the stale-`current_pressure` half of the defect:
an ascending single-page read returns the *oldest* slice of the window, so
`pressures[-1]` is a days-old reading presented as current, and the pressure gate
(`< 30 PSI`) never opens. In the live 2026-08-10 incident the *other* half fired
first — page 1 spanned 67 minutes and `time_span_days < 0.1` discarded the tire
before the pressure gate was reached. Both halves come from the same two lines;
either alone is sufficient to lose a real leak.
"""

import importlib.util
import os
import sys
import types
from decimal import Decimal
from unittest.mock import MagicMock, patch

# tests/ is a package, so import the sibling module by path rather than by
# bare name — this keeps the file runnable both as `pytest tests/` from the
# lambda directory and as `pytest` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_pagination import (  # noqa: E402  — reuse the exact fixture under test
    PagingTelemetryTable,
    _alerts_mock,
    _ssm_mock,
    _truncation_shaped_window,
    _written_items,
)


def _import_main() -> types.ModuleType:
    module_name = "daily_tire_check_main_positive_control"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name, os.path.join(os.path.dirname(__file__), "..", "main.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    sys.modules[module_name] = module
    return module


def _legacy_read(telemetry_table, vehicle_id, cutoff, context):
    """The read as it shipped before 2026-08-10: one page, ascending order.

    Reproduced verbatim in behaviour — no ScanIndexForward, no LastEvaluatedKey
    loop — so the control degrades exactly the way production did.
    """
    resp = telemetry_table.query(
        KeyConditionExpression="vehicleId = :v AND #ts > :cutoff",
        ExpressionAttributeNames={"#ts": "timestamp"},
        ExpressionAttributeValues={":v": vehicle_id, ":cutoff": Decimal(str(cutoff))},
        ProjectionExpression=(
            "vehicleId, #ts, tire_pressure_fl, tire_pressure_fr, "
            "tire_pressure_rl, tire_pressure_rr"
        ),
    )
    items = [
        r
        for r in resp.get("Items", [])
        if any(
            r.get(a)
            for a in (
                "tire_pressure_fl",
                "tire_pressure_fr",
                "tire_pressure_rl",
                "tire_pressure_rr",
            )
        )
    ]
    return items, 1, "complete"


class TestLegacyReadMissesTheLeak:
    """The pre-fix read must fail on the fixture the post-fix read passes."""

    def test_legacy_single_page_ascending_read_writes_no_alert(self, monkeypatch):
        vehicles = MagicMock()
        vehicles.scan.return_value = {"Items": [{"vehicleId": "VEH-PAGED"}]}
        telemetry = PagingTelemetryTable(_truncation_shaped_window(), page_size=10)
        alerts, batch_writer = _alerts_mock()

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
            monkeypatch.setattr(main, "_read_tire_readings", _legacy_read)
            main.handler()

        assert len(telemetry.calls) == 1, "The legacy control must issue exactly one query"
        assert not _written_items(batch_writer), (
            "The legacy read produced an alert, so the fixture cannot distinguish "
            "the bug from the fix — the regression test in test_pagination.py is "
            "not actually guarding anything and the fixture needs reshaping"
        )
