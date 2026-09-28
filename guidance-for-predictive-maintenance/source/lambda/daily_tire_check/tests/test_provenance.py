# -*- coding: utf-8 -*-
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Provenance tests for daily_tire_check — RED phase.

Spec: .kiro/specs/2026-08-10-adp-tire-prediction-batch-only-deploy/spec.md § D3

Every alert row written by this Lambda must carry:
  - source = "adp-tire-ml"
  - modelVersion (non-empty string)
  - confidence (present — model score for thresholding without re-deriving)
  - computedAt (ISO-8601 timestamp, so staleness is visible)

Without these fields the 1,750-row output table looks identical whether the ML
pipeline has ever run or not. These fields make "has the ML produced anything?"
a single query rather than an archaeology exercise.

Additive constraint: no existing attribute is renamed or dropped; CMS reads
this table today via two REST routes and its e2e tests pass.

These tests are currently RED — main.py does not yet write any of the four
provenance fields. They pass once § D3 implementation is complete.
"""

import importlib
import sys
import types
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pressure_readings(n: int = 15, slope: float = -0.5, base: float = 29.5) -> list[dict]:
    """Return n telemetry readings with a declining pressure trend that should
    trigger a slow-leak alert.  slope is PSI-per-reading."""
    rows = []
    for i in range(n):
        pressure = base + slope * i
        ts = 1_700_000_000_000 + i * 3_600_000  # 1-hour spacing
        rows.append(
            {
                "vehicleId": "VEH-001",
                "timestamp": Decimal(str(ts)),
                "tire_pressure_fl": Decimal(str(round(pressure, 2))),
                "tire_pressure_fr": Decimal("32.0"),
                "tire_pressure_rl": Decimal("32.0"),
                "tire_pressure_rr": Decimal("32.0"),
            }
        )
    return rows


def _import_main() -> types.ModuleType:
    """Import main.py from daily_tire_check fresh (bypass any cached import).

    We re-import on every call so environment-variable patches in individual
    tests take effect without interference.
    """
    module_name = "daily_tire_check_main"
    if module_name in sys.modules:
        del sys.modules[module_name]

    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        module_name,
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "main.py",
        ),
    )
    assert spec and spec.loader, "Could not locate main.py relative to test file"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    sys.modules[module_name] = module
    return module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ddb_tables():
    """Return mock DynamoDB table objects pre-loaded with minimal data."""
    vehicles_table = MagicMock()
    vehicles_table.scan.return_value = {"Items": [{"vehicleId": "VEH-001"}]}

    telemetry_table = MagicMock()
    # Provide 15 readings with a -0.5 PSI/hour slope — enough to cross the
    # -0.3 PSI/day threshold and produce at least one alert.
    telemetry_table.query.return_value = {"Items": _make_pressure_readings()}

    alerts_table = MagicMock()
    batch_writer = MagicMock()
    alerts_table.batch_writer.return_value.__enter__ = MagicMock(return_value=batch_writer)
    alerts_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

    return {
        "vehicles": vehicles_table,
        "telemetry": telemetry_table,
        "alerts": alerts_table,
        "batch_writer": batch_writer,
    }


@pytest.fixture()
def ssm_mock():
    """SSM client that returns a non-empty model version string."""
    client = MagicMock()
    client.get_parameter.return_value = {
        "Parameter": {"Value": "tire-prediction-model-v1.2.3"}
    }
    return client


def _run_handler_with_mocks(ddb_tables: dict, ssm_mock: MagicMock) -> dict:
    """Patch boto3, import main fresh, invoke handler, return result."""
    def fake_ddb_table(name: str) -> MagicMock:
        if "vehicles" in name:
            return ddb_tables["vehicles"]
        if "telemetry" in name:
            return ddb_tables["telemetry"]
        if "maintenance-alerts" in name or "alerts" in name:
            return ddb_tables["alerts"]
        raise ValueError(f"Unexpected table name: {name}")

    ddb_resource = MagicMock()
    ddb_resource.Table.side_effect = fake_ddb_table

    with (
        patch("boto3.resource", return_value=ddb_resource),
        patch("boto3.client", return_value=ssm_mock),
    ):
        main = _import_main()
        return main.handler()


# ---------------------------------------------------------------------------
# Test: every written row carries source="adp-tire-ml"
# ---------------------------------------------------------------------------

class TestSourceField:
    """source must be "adp-tire-ml" on every written alert.

    The existing table already carries source="fwe-uds-dtc" (1,145 rows) and
    unsourced simulator threshold rules (605 rows).  A distinct, stable
    source value is what makes the ML rows distinguishable at a query level.
    """

    def test_source_is_adp_tire_ml(self, ddb_tables, ssm_mock):
        """Every written row must carry source="adp-tire-ml"."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        assert batch_writer.put_item.called, (
            "Expected at least one alert to be written for the declining-pressure fixture"
        )

        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert item.get("source") == "adp-tire-ml", (
                f"Row missing source='adp-tire-ml': {item}"
            )

    def test_old_source_value_never_written(self, ddb_tables, ssm_mock):
        """The legacy source value 'predictive-maintenance' must not appear."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert item.get("source") != "predictive-maintenance", (
                f"Stale source value 'predictive-maintenance' must not be written: {item}"
            )


# ---------------------------------------------------------------------------
# Test: every written row carries a non-empty modelVersion
# ---------------------------------------------------------------------------

class TestModelVersionField:
    """modelVersion must be present and non-empty on every written alert.

    Today zero rows in the 1,750-row table carry this field.  Its absence
    is what made a pipeline that never ran look identical to one that worked.
    """

    def test_model_version_present_and_non_empty(self, ddb_tables, ssm_mock):
        """Every written row must carry a non-empty modelVersion."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        assert batch_writer.put_item.called

        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            model_version = item.get("modelVersion")
            assert model_version is not None, (
                f"Row missing modelVersion: {item}"
            )
            assert str(model_version).strip() != "", (
                f"Row has empty modelVersion: {item}"
            )

    def test_model_version_comes_from_ssm(self, ddb_tables, ssm_mock):
        """modelVersion must be sourced from SSM (the model-name parameter the
        training pipeline writes), not a hardcoded literal."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        assert batch_writer.put_item.called

        expected_version = ssm_mock.get_parameter.return_value["Parameter"]["Value"]
        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert item.get("modelVersion") == expected_version, (
                f"modelVersion must match SSM parameter value '{expected_version}': {item}"
            )


# ---------------------------------------------------------------------------
# Test: every written row carries a confidence score (categorical)
# ---------------------------------------------------------------------------

class TestConfidenceField:
    """confidence must be present on every written alert as a categorical value.

    confidence is derived from DATA SUFFICIENCY — how many readings the trend
    was fitted over, against MIN_READINGS.  It uses the vocabulary
    "high" | "medium" | "low" which matches cvx/agents/tier2/contract.py's
    VALID_CONFIDENCES so CVX's Tier 2 agent can consume without translation.

    It is NOT a probability / normalised slope.  That value is now reported
    separately as trendMagnitude.
    """

    VALID_CONFIDENCES = {"high", "medium", "low"}

    def test_confidence_present(self, ddb_tables, ssm_mock):
        """Every written row must carry a confidence field."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        assert batch_writer.put_item.called

        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert "confidence" in item, (
                f"Row missing confidence field: {item}"
            )
            assert item["confidence"] is not None, (
                f"Row has null confidence: {item}"
            )

    def test_confidence_is_never_numeric(self, ddb_tables, ssm_mock):
        """confidence must be a categorical string, NEVER a numeric value.

        The original implementation set confidence = min(1.0, |slope|/2.0),
        a normalised trend magnitude.  A consumer reading that as P(correct)
        and thresholding at 0.8 would silently discard slow leaks with
        slope < 1.6 PSI/day — exactly the ones this pipeline exists to catch.
        Asserting non-numeric here enforces that the data-contract defect
        cannot be reintroduced.
        """
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            confidence = item.get("confidence")
            assert not isinstance(confidence, (int, float, Decimal)), (
                f"confidence must not be numeric (found {type(confidence).__name__}={confidence!r}). "
                f"confidence is a data-sufficiency category, not a slope magnitude. "
                f"The slope is reported separately as trendMagnitude."
            )

    def test_confidence_is_valid_category(self, ddb_tables, ssm_mock):
        """confidence must be one of the three categorical values that match
        cvx/agents/tier2/contract.py's VALID_CONFIDENCES."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        assert batch_writer.put_item.called

        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            confidence = item.get("confidence")
            assert confidence in self.VALID_CONFIDENCES, (
                f"confidence must be one of {self.VALID_CONFIDENCES}, "
                f"got {confidence!r}: {item}"
            )


# ---------------------------------------------------------------------------
# Test: every written row carries trendMagnitude (the numeric slope)
# ---------------------------------------------------------------------------

class TestTrendMagnitudeField:
    """trendMagnitude must be present on every written alert as a numeric value.

    This is the actual quantity the pipeline computes — the linear-regression
    slope of pressure over time, in PSI/day.  It is negative for a declining
    trend.  Reporting it separately from confidence means consumers who want
    the magnitude can still get it, while consumers reading confidence for
    data-quality thresholding get the right field.
    """

    def test_trend_magnitude_present(self, ddb_tables, ssm_mock):
        """Every written row must carry a trendMagnitude field."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        assert batch_writer.put_item.called

        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert "trendMagnitude" in item, (
                f"Row missing trendMagnitude field: {item}"
            )
            assert item["trendMagnitude"] is not None, (
                f"Row has null trendMagnitude: {item}"
            )

    def test_trend_magnitude_is_numeric(self, ddb_tables, ssm_mock):
        """trendMagnitude must be a numeric value (the signed PSI/day slope)."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            trend_magnitude = item.get("trendMagnitude")
            assert isinstance(trend_magnitude, (int, float, Decimal)), (
                f"trendMagnitude must be numeric (PSI/day), got "
                f"{type(trend_magnitude).__name__}={trend_magnitude!r}: {item}"
            )

    def test_trend_magnitude_is_negative_for_declining_pressure(self, ddb_tables, ssm_mock):
        """For the declining-pressure fixture, trendMagnitude must be negative
        (pressure is dropping, so the slope is negative PSI/day)."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        assert batch_writer.put_item.called

        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            trend_magnitude = float(item.get("trendMagnitude", 0))
            assert trend_magnitude < 0, (
                f"trendMagnitude should be negative for a declining-pressure alert, "
                f"got {trend_magnitude}: {item}"
            )


# ---------------------------------------------------------------------------
# Test: SSM failure raises, not returns
# ---------------------------------------------------------------------------

class TestSSMFailureRaises:
    """If the SSM read for modelVersion fails, the Lambda must raise — not return.

    Returning a success dict on SSM failure would record a successful EventBridge
    invocation for a run that wrote zero alerts, which is the exact failure mode
    this spec exists to eliminate (spec § D3; review cycle 1 Critical).

    Raising increments the Lambda error metric, fires CloudWatch alarms, and
    makes the dead-letter queue receive the event.  A nightly job that fails
    loudly is recoverable; one that fails quietly is what produced this issue.
    """

    def test_ssm_failure_raises_exception(self, ddb_tables):
        """When SSM raises, the handler must propagate an exception rather than
        returning a success dict.  EventBridge must see a failed invocation."""
        ssm_failing = MagicMock()
        ssm_failing.get_parameter.side_effect = Exception("ParameterNotFound")

        def fake_ddb_table(name: str) -> MagicMock:
            if "vehicles" in name:
                return ddb_tables["vehicles"]
            if "telemetry" in name:
                return ddb_tables["telemetry"]
            if "maintenance-alerts" in name or "alerts" in name:
                return ddb_tables["alerts"]
            raise ValueError(f"Unexpected table name: {name}")

        ddb_resource = MagicMock()
        ddb_resource.Table.side_effect = fake_ddb_table

        with (
            patch("boto3.resource", return_value=ddb_resource),
            patch("boto3.client", return_value=ssm_failing),
        ):
            main = _import_main()
            with pytest.raises(Exception) as exc_info:
                main.handler()

        assert exc_info.value is not None, (
            "Handler must raise when SSM is unavailable, not return a success dict"
        )
        # Must not be a clean return masquerading as an exception
        assert not isinstance(exc_info.value, (SystemExit,)), (
            "Handler must raise a real exception, not call sys.exit()"
        )

    def test_ssm_failure_does_not_write_any_alerts(self, ddb_tables):
        """When SSM raises, no alert rows must be written to DynamoDB."""
        ssm_failing = MagicMock()
        ssm_failing.get_parameter.side_effect = Exception("ParameterNotFound")

        def fake_ddb_table(name: str) -> MagicMock:
            if "vehicles" in name:
                return ddb_tables["vehicles"]
            if "telemetry" in name:
                return ddb_tables["telemetry"]
            if "maintenance-alerts" in name or "alerts" in name:
                return ddb_tables["alerts"]
            raise ValueError(f"Unexpected table name: {name}")

        ddb_resource = MagicMock()
        ddb_resource.Table.side_effect = fake_ddb_table

        with (
            patch("boto3.resource", return_value=ddb_resource),
            patch("boto3.client", return_value=ssm_failing),
        ):
            main = _import_main()
            try:
                main.handler()
            except Exception:
                pass  # Expected — we just want to check no writes happened

        batch_writer = ddb_tables["batch_writer"]
        assert not batch_writer.put_item.called, (
            "No alerts must be written when SSM is unavailable — an unattributed "
            "row is indistinguishable from the 605 existing unsourced rows"
        )




class TestComputedAtField:
    """computedAt must be present on every written alert.

    This is what makes staleness visible. A Tier 1 agent reading this table
    can say "as of last Tuesday" rather than presenting a stale result as live.
    Aligns with the Tier 2 artifact contract: computed_at.
    """

    def test_computed_at_present(self, ddb_tables, ssm_mock):
        """Every written row must carry a computedAt field."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        assert batch_writer.put_item.called

        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert "computedAt" in item, (
                f"Row missing computedAt field: {item}"
            )
            assert item["computedAt"] is not None, (
                f"Row has null computedAt: {item}"
            )

    def test_computed_at_is_non_empty_string(self, ddb_tables, ssm_mock):
        """computedAt must be a non-empty string (ISO-8601 format expected)."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            computed_at = item.get("computedAt")
            assert isinstance(computed_at, str) and computed_at.strip(), (
                f"computedAt must be a non-empty string: {item}"
            )


# ---------------------------------------------------------------------------
# Test: no row missing any provenance field is ever written
# ---------------------------------------------------------------------------

class TestNoRowWrittenWithoutProvenance:
    """Structural guard: a row missing ANY of the four fields must not be written.

    This is the hardest invariant — it cannot be satisfied by writing good rows
    alongside bad ones. The handler must refuse to persist an incomplete row.

    Implementation note: these tests verify the ABSENCE of bad writes, not just
    the presence of good ones. They use a fixture with a single vehicle and
    single alert opportunity so failures are unambiguous.
    """

    REQUIRED_FIELDS = ("source", "modelVersion", "confidence", "computedAt", "trendMagnitude")

    def test_no_row_lacking_source_is_written(self, ddb_tables, ssm_mock):
        """A row must never reach batch_writer.put_item without a source field."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert "source" in item and item["source"], (
                f"A row without 'source' reached the database: {item}"
            )

    def test_no_row_lacking_model_version_is_written(self, ddb_tables, ssm_mock):
        """A row must never reach batch_writer.put_item without a modelVersion."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert "modelVersion" in item and str(item.get("modelVersion", "")).strip(), (
                f"A row without 'modelVersion' reached the database: {item}"
            )

    def test_no_row_lacking_confidence_is_written(self, ddb_tables, ssm_mock):
        """A row must never reach batch_writer.put_item without a confidence field."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert "confidence" in item and item.get("confidence") is not None, (
                f"A row without 'confidence' reached the database: {item}"
            )

    def test_no_row_lacking_computed_at_is_written(self, ddb_tables, ssm_mock):
        """A row must never reach batch_writer.put_item without a computedAt field."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert "computedAt" in item and item.get("computedAt"), (
                f"A row without 'computedAt' reached the database: {item}"
            )

    def test_no_row_lacking_trend_magnitude_is_written(self, ddb_tables, ssm_mock):
        """A row must never reach batch_writer.put_item without a trendMagnitude field."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            assert "trendMagnitude" in item and item.get("trendMagnitude") is not None, (
                f"A row without 'trendMagnitude' reached the database: {item}"
            )

    def test_all_provenance_fields_present_together(self, ddb_tables, ssm_mock):
        """Composite: every written row must carry all five provenance fields
        simultaneously, not just each one in isolation."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        assert batch_writer.put_item.called, (
            "Handler wrote no alerts for the declining-pressure fixture — "
            "check that _make_pressure_readings produces a triggering slope"
        )

        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            missing = [f for f in self.REQUIRED_FIELDS if f not in item or not item[f]]
            assert not missing, (
                f"Row is missing provenance field(s) {missing}: {item}"
            )


# ---------------------------------------------------------------------------
# Test: existing attributes are preserved (additive-only guard)
# ---------------------------------------------------------------------------

class TestAdditiveOnly:
    """Provenance fields must be additions, not replacements.

    CMS reads this table today via GET /api/v1/maintenance-alerts and
    GET /api/v1/vehicles/{id}/maintenance-alerts.  The attributes it relies on
    (alertId, vehicleId, alertType, severity, description, timestamp, status,
    estimatedCost, metadata) must still be present.
    """

    PRESERVED_ATTRIBUTES = (
        "alertId",
        "vehicleId",
        "alertType",
        "severity",
        "description",
        "timestamp",
        "status",
        "estimatedCost",
        "metadata",
    )

    def test_existing_cms_attributes_still_present(self, ddb_tables, ssm_mock):
        """Adding provenance fields must not remove the attributes CMS already reads."""
        _run_handler_with_mocks(ddb_tables, ssm_mock)

        batch_writer = ddb_tables["batch_writer"]
        assert batch_writer.put_item.called

        for call_args in batch_writer.put_item.call_args_list:
            item: dict[str, Any] = call_args.kwargs.get("Item") or call_args.args[0]["Item"]
            missing = [a for a in self.PRESERVED_ATTRIBUTES if a not in item]
            assert not missing, (
                f"Existing attribute(s) {missing} were dropped — additive-only constraint "
                f"violated: {item}"
            )
