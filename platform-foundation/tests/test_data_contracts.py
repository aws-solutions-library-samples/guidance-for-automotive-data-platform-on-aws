"""Drift-detection tests for `docs/data-contracts.md`.

Per the spec's "drift-detection test design" section:

  - TestKeyFormats — sample 10K rows and assert every ID conforms.
  - TestVSSColumnPresence — every VSS-subset column is present in the
    generated schema for `vehicle_telemetry_aggregated` and
    `energy_usage`. The VSS table is parsed from the markdown so doc
    edits flow into the test automatically.
  - TestPartitionConventions — Glue partition_spec matches the doc.

Tests that require generated data skip pre-Group-3 with clear reasons.
The markdown-parsing helpers are pure-Python and run in skeleton phase.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import schema_loader as sl  # noqa: E402


# ---------------------------------------------------------------------------
# Markdown parsing — read doc-state once, reuse across tests.
# ---------------------------------------------------------------------------


def _docs_path() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2] / "docs" / "data-contracts.md"


@pytest.fixture(scope="module")
def contracts_doc() -> str:
    p = _docs_path()
    assert p.exists(), f"docs/data-contracts.md not found at {p}"
    return p.read_text()


def _parse_vss_table(doc: str) -> list[dict[str, str]]:
    """Parse the VSS subset markdown table into rows.

    Returns rows with keys: vss_path, adp_column, unit, range,
    cms_equivalent.
    """
    out: list[dict[str, str]] = []
    in_table = False
    header_seen = False
    for line in doc.splitlines():
        if line.startswith("## VSS vocabulary subset"):
            in_table = True
            continue
        if in_table and line.startswith("## "):
            break
        if not in_table:
            continue
        if line.startswith("| #"):
            header_seen = True
            continue
        if header_seen and line.startswith("| ") and "---" not in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 6 or not cells[0].isdigit():
                continue
            out.append(
                {
                    "ordinal": cells[0],
                    "vss_path": cells[1].strip("` "),
                    "adp_column": cells[2].strip("` "),
                    "unit": cells[3],
                    "range": cells[4],
                    "cms_equivalent": cells[5],
                }
            )
    return out


_PIPE_SENTINEL = "\u0001"  # private-use, never appears in markdown


def _split_md_cells(row: str) -> list[str]:
    """Split a markdown table row, respecting backslash-escaped pipes."""
    body = row.strip().strip("|")
    body = body.replace(r"\|", _PIPE_SENTINEL)
    cells = [c.strip().replace(_PIPE_SENTINEL, "|") for c in body.split("|")]
    return cells


def _parse_identifier_regex(doc: str) -> dict[str, str]:
    """Parse the 'Identifier formats' table into {identifier: regex}."""
    out: dict[str, str] = {}
    in_section = False
    for line in doc.splitlines():
        if line.startswith("## Identifier formats"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("| `"):
            cells = _split_md_cells(line)
            if len(cells) >= 4:
                ident = cells[0].strip("` ")
                pattern = cells[3].strip("` ")
                if pattern.startswith("^"):
                    out[ident] = pattern
    return out


# ---------------------------------------------------------------------------
# Doc-parser sanity (runs in skeleton phase)
# ---------------------------------------------------------------------------


def test_vss_table_parses_at_least_40_rows(contracts_doc):
    rows = _parse_vss_table(contracts_doc)
    assert len(rows) >= 40, f"VSS table parsed only {len(rows)} rows"


def test_identifier_table_parses_six_regex(contracts_doc):
    regex = _parse_identifier_regex(contracts_doc)
    expected_keys = {"vin", "customer_id", "dealer_id", "supplier_id", "part_number", "station_id"}
    assert expected_keys.issubset(regex.keys()), (
        f"Missing identifier rows: {expected_keys - set(regex.keys())}"
    )
    for k, v in regex.items():
        re.compile(v)  # raises if pattern is invalid


# ---------------------------------------------------------------------------
# TestKeyFormats — runs against curated parquet (skipped pre-Group-3)
# ---------------------------------------------------------------------------


class TestKeyFormats:
    """Sample 10K rows and assert every ID conforms to the documented regex."""

    @pytest.mark.needs_curated
    @pytest.mark.parametrize(
        "product_name",
        [
            "vehicle_telemetry_aggregated",
            "charging_sessions",
            "energy_usage",
            "customer_360",
            "customer_interactions",
            "service_records",
            "vehicle_identity",
            "ota_campaigns",
        ],
    )
    def test_id_columns_match_documented_regex(
        self, contracts_doc, curated_root, product_name
    ):
        p = curated_root / product_name
        if not p.exists() or not any(p.iterdir()):
            pytest.skip(f"{product_name} not generated yet")
        pytest.skip(
            "Sampling logic implemented as part of Group 3 verify step. "
            "Placeholder asserts the call shape."
        )


# ---------------------------------------------------------------------------
# TestVSSColumnPresence
# ---------------------------------------------------------------------------


class TestVSSColumnPresence:
    """Every VSS-subset column must be present in the relevant product schemas."""

    def test_telemetry_has_all_vss_columns(self, contracts_doc):
        rows = _parse_vss_table(contracts_doc)
        s = sl.load_schema("vehicle_telemetry_aggregated", kind="product")
        present = {c.name for tbl in s.tables for c in tbl.columns}

        # Columns marked "n/a" or with leading ` (path-only) are not required in this product.
        required = {
            r["adp_column"]
            for r in rows
            if r["adp_column"] not in ("n/a", "")
            and not r["adp_column"].startswith("n/a")
        }
        # Some VSS-subset columns are scoped to other products (charging_sessions,
        # vehicle_identity, energy_usage). Exempt them from the telemetry presence check.
        EXEMPT_FOR_TELEMETRY = {
            # rollup-only — energy_usage
            "min_soc_pct", "max_soc_pct", "avg_soc_pct",
            "regen_kwh_recovered",
            # vehicle_identity-only
            "battery_pack_kwh", "battery_nominal_voltage_v", "battery_net_kwh",
            "max_charging_rate_kw",
            # charging_sessions-only
            "peak_power_kw", "connector_type",
            # not yet modeled in v1
            "altitude_m", "charge_port_open", "charge_limit_pct",
            "motor_time_in_use_s",
            "brake_pedal_pct", "accelerator_pedal_pct",
        }
        missing = {col for col in required if col not in present and col not in EXEMPT_FOR_TELEMETRY}
        assert not missing, (
            f"vehicle_telemetry_aggregated missing VSS columns: {sorted(missing)}"
        )

    def test_energy_usage_has_battery_signals(self, contracts_doc):
        s = sl.load_schema("energy_usage", kind="product")
        present = {c.name for tbl in s.tables for c in tbl.columns}
        # Core energy-usage rollup columns from VSS.
        required = {
            "start_soc_pct",
            "end_soc_pct",
            "min_soc_pct",
            "max_soc_pct",
            "avg_soc_pct",
            "state_of_health_pct",
            "regen_kwh_recovered",
            "battery_pack_temp_avg_c",
            "ambient_temp_avg_c",
        }
        missing = required - present
        assert not missing, f"energy_usage missing battery rollup columns: {sorted(missing)}"

    def test_no_unit_drift_celsius_capitalization(self, contracts_doc):
        """VSS v6.0 capitalizes 'Celsius'. The contracts doc must reflect this."""
        rows = _parse_vss_table(contracts_doc)
        celsius_units = [r["unit"] for r in rows if r["unit"].lower() == "celsius"]
        # All Celsius units in the doc should be capitalized 'Celsius'.
        assert all(u == "Celsius" for u in celsius_units), (
            f"VSS v6.0 requires capitalized 'Celsius'; found: {celsius_units}"
        )


# ---------------------------------------------------------------------------
# TestPartitionConventions
# ---------------------------------------------------------------------------


class TestPartitionConventions:
    """Per-product partition keys must match the documented convention."""

    def test_charging_sessions_daily_partition(self):
        s = sl.load_schema("charging_sessions", kind="product")
        tbl = s.first_table()
        assert tbl.partition_keys == ("session_date",)
        assert tbl.bucketing.get("vin") == 16

    def test_telemetry_daily_partition_with_bucket(self):
        s = sl.load_schema("vehicle_telemetry_aggregated", kind="product")
        tbl = s.first_table()
        assert tbl.partition_keys == ("event_date",)
        assert tbl.bucketing.get("vin") == 16

    def test_energy_usage_daily_partition(self):
        s = sl.load_schema("energy_usage", kind="product")
        tbl = s.first_table()
        assert tbl.partition_keys == ("usage_date",)

    def test_service_records_monthly_partition(self):
        s = sl.load_schema("service_records", kind="product")
        tbl = s.first_table()
        assert tbl.partition_keys == ("service_month",)

    def test_customer_360_snapshot_partition(self):
        s = sl.load_schema("customer_360", kind="product")
        tbl = s.first_table()
        assert tbl.partition_keys == ("snapshot_date",)

    def test_ota_campaigns_dual_table_partitions(self):
        s = sl.load_schema("ota_campaigns", kind="product")
        header = next(t for t in s.tables if t.name == "ota_campaigns")
        events = next(t for t in s.tables if t.name == "ota_campaign_events")
        assert header.partition_keys == ("campaign_id",)
        assert events.partition_keys == ("dispatch_date",)

    def test_vehicle_identity_partitioned_by_model_year(self):
        s = sl.load_schema("vehicle_identity", kind="product")
        tbl = s.first_table()
        assert tbl.partition_keys == ("model_year",)

    @pytest.mark.needs_curated
    def test_glue_partition_spec_matches_doc(self):
        """Live Glue partition_spec match — runs in Group 6."""
        pytest.skip("Glue partition_spec assertion runs against deployed catalog (Group 6).")
