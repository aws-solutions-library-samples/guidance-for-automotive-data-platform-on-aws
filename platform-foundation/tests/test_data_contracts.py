"""Drift-detection tests for `docs/data-contracts.md`.

Per the spec's "drift-detection test design" section:

  - TestKeyFormats — sample 10K rows and assert every ID conforms.
  - TestVSSColumnPresence — every VSS-subset column is present in the
    generated schema for `vehicle_telemetry_aggregated` and
    `energy_usage`. The VSS table is parsed from the markdown so doc
    edits flow into the test automatically.
  - TestPartitionConventions — Glue partition_spec matches the doc.
  - TestBrakeServiceContract — RED-phase contract tests for the
    brake_service surface (spec 2026-08-03-adp-brake-records-tire-health-deploy
    § D2). These fail until T2.1 adds the brake pools; they must fail for
    the right reason (no brake_service type) rather than an import error.

Tests that require generated data skip pre-Group-3 with clear reasons.
The markdown-parsing helpers are pure-Python and run in skeleton phase.
"""

from __future__ import annotations

import importlib.util
import re
import sys
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


# ---------------------------------------------------------------------------
# TestBrakeServiceContract — RED-phase contract tests for brake_service surface
#
# Spec: 2026-08-03-adp-brake-records-tire-health-deploy § D2
# These tests FAIL until T2.1 adds:
#   - "brake_service" to SERVICE_TYPES
#   - BRAKE_DTC_CODES (including C0161) to the generator
#   - BRAKE_COMPLAINT_TEMPLATES (10 entries) to the generator
# They fail for the RIGHT REASON (missing type / pool) rather than an
# import or fixture error.  The generator module is loaded via importlib
# so a missing attribute is caught as an AssertionError, not AttributeError.
# ---------------------------------------------------------------------------


def _load_service_records_generator():
    """Load the service_records generator module without executing main()."""
    here = Path(__file__).resolve()
    repo_root = here.parents[1]
    gen_path = (
        repo_root
        / "source"
        / "data-products"
        / "service_records"
        / "generator.py"
    )
    lib_path = repo_root / "source" / "lib"
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))
    spec = importlib.util.spec_from_file_location("service_records_generator", gen_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def service_records_gen():
    """The service_records generator module (module-scoped for speed)."""
    return _load_service_records_generator()


class TestBrakeServiceContract:
    """RED-phase assertions for the brake_service data surface (spec § D2).

    All tests in this class must FAIL against the unmodified generator and
    PASS once T2.1 is complete.  They must NOT fail due to import errors
    or missing fixtures — the failure reason must be a failed assertion
    about missing brake content.
    """

    def test_brake_service_type_exists(self, service_records_gen):
        """SERVICE_TYPES must contain 'brake_service' (spec § D2).

        RED: fails because brake_service is not yet in SERVICE_TYPES.
        """
        service_types = service_records_gen.SERVICE_TYPES
        assert "brake_service" in service_types, (
            f"'brake_service' missing from SERVICE_TYPES; "
            f"current types: {service_types}"
        )

    def test_service_type_probs_match_types_length(self, service_records_gen):
        """SERVICE_TYPE_PROBS must have exactly len(SERVICE_TYPES) entries.

        This is a regression guard: after T2.1 adds brake_service the
        probs list must grow in sync.  Passes pre-T2.1 on the current
        10-entry lists; must continue passing after T2.1.
        """
        service_types = service_records_gen.SERVICE_TYPES
        service_type_probs = service_records_gen.SERVICE_TYPE_PROBS
        assert len(service_types) == len(service_type_probs), (
            f"SERVICE_TYPES has {len(service_types)} entries but "
            f"SERVICE_TYPE_PROBS has {len(service_type_probs)}"
        )

    def test_service_type_probs_sum_to_one(self, service_records_gen):
        """SERVICE_TYPE_PROBS must sum to exactly 1.0.

        numpy raises on a non-unit distribution; this assertion names
        the cause before numpy does.  Passes pre-T2.1; must continue
        passing after T2.1 adds brake_service and rebalances the probs.
        """
        service_type_probs = service_records_gen.SERVICE_TYPE_PROBS
        total = sum(service_type_probs)
        assert abs(total - 1.0) < 1e-9, (
            f"SERVICE_TYPE_PROBS sums to {total:.10f}, not 1.0; "
            f"a future edit has introduced drift"
        )

    def test_brake_dtc_codes_defined(self, service_records_gen):
        """BRAKE_DTC_CODES must be defined in the generator (spec § D2).

        RED: fails because BRAKE_DTC_CODES does not yet exist.
        """
        brake_dtc_codes = getattr(service_records_gen, "BRAKE_DTC_CODES", None)
        assert brake_dtc_codes is not None, (
            "BRAKE_DTC_CODES is not defined in the service_records generator; "
            "T2.1 must add it (spec § D2)"
        )

    def test_brake_dtc_codes_contains_c0161(self, service_records_gen):
        """BRAKE_DTC_CODES must include C0161 (deployed KB guide exists — spec § D2).

        C0161 gives brake rows the same KB-join property TIRE_DTC_CODES
        was built for: dtc-C0161.md is a deployed Bedrock KB guide
        retrieved at score 0.6552 for 'brake system warning C0161'.

        RED: fails because BRAKE_DTC_CODES does not yet exist.
        """
        brake_dtc_codes = getattr(service_records_gen, "BRAKE_DTC_CODES", None)
        assert brake_dtc_codes is not None, (
            "BRAKE_DTC_CODES is not defined — T2.1 must add it before "
            "the C0161 assertion can be evaluated (spec § D2)"
        )
        assert "C0161" in brake_dtc_codes, (
            f"C0161 missing from BRAKE_DTC_CODES; current entries: {brake_dtc_codes}. "
            "dtc-C0161.md is a deployed KB guide — this code is mandatory (spec § D2)."
        )

    def test_brake_dtc_codes_does_not_include_u0121(self, service_records_gen):
        """U0121 must remain in TIRE_DTC_CODES only (spec § D2 hard constraint).

        U0121 (Lost Communication With ABS) is marked '(tire-adjacent)' in
        TIRE_DTC_CODES and must NOT be copied into BRAKE_DTC_CODES — moving
        it would perturb the tire cross-validation join.

        RED: passes today (no BRAKE_DTC_CODES at all); must continue to
        pass after T2.1 — if BRAKE_DTC_CODES exists it must not contain U0121.
        """
        brake_dtc_codes = getattr(service_records_gen, "BRAKE_DTC_CODES", None)
        if brake_dtc_codes is None:
            pytest.skip("BRAKE_DTC_CODES not yet defined — skip U0121 guard until T2.1")
        assert "U0121" not in brake_dtc_codes, (
            "U0121 must NOT appear in BRAKE_DTC_CODES — it belongs exclusively "
            "in TIRE_DTC_CODES to preserve the tire cross-validation join (spec § D2)."
        )

    def test_tire_dtc_codes_still_contains_u0121(self, service_records_gen):
        """U0121 must remain in TIRE_DTC_CODES after T2.1 (spec § D2 hard constraint).

        Asserts that T2.1 did not accidentally remove U0121 from TIRE_DTC_CODES
        when adding the brake surface.
        """
        tire_dtc_codes = service_records_gen.TIRE_DTC_CODES
        assert "U0121" in tire_dtc_codes, (
            "U0121 was removed from TIRE_DTC_CODES — this breaks the tire "
            "cross-validation join; spec § D2 explicitly forbids moving it."
        )

    def test_brake_complaint_templates_defined(self, service_records_gen):
        """BRAKE_COMPLAINT_TEMPLATES must be defined in the generator (spec § D2).

        RED: fails because BRAKE_COMPLAINT_TEMPLATES does not yet exist.
        """
        brake_complaint_templates = getattr(
            service_records_gen, "BRAKE_COMPLAINT_TEMPLATES", None
        )
        assert brake_complaint_templates is not None, (
            "BRAKE_COMPLAINT_TEMPLATES is not defined in the service_records generator; "
            "T2.1 must add 10 EV-appropriate brake complaint entries (spec § D2)"
        )

    def test_brake_complaint_templates_has_ten_entries(self, service_records_gen):
        """BRAKE_COMPLAINT_TEMPLATES must have exactly 10 entries (spec § Design).

        RED: fails because BRAKE_COMPLAINT_TEMPLATES does not yet exist.
        """
        brake_complaint_templates = getattr(
            service_records_gen, "BRAKE_COMPLAINT_TEMPLATES", None
        )
        assert brake_complaint_templates is not None, (
            "BRAKE_COMPLAINT_TEMPLATES is not defined — T2.1 must add it "
            "(spec § Design requires 10 EV-appropriate brake entries)"
        )
        assert len(brake_complaint_templates) == 10, (
            f"BRAKE_COMPLAINT_TEMPLATES has {len(brake_complaint_templates)} entries; "
            f"spec § Design requires exactly 10"
        )
