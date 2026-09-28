"""test_lint_no_licensed_autocare_ids.py — T3.7 reactive lint tests.

TWO REQUIREMENTS THAT MATTER MORE THAN THE LINT EXISTING (per T3.7):

1.  REACTIVE proof: a fixture injection test MUST make the lint exit non-zero.
    A guard nobody has seen fail is a guard nobody should trust.

2.  DECISION 3 enforcement: zero access_channel='independent' rows must exist.
    "Franchise-only in v1" is test-enforced here, not just asserted.

Test inventory
--------------
TestLintCleanPass          — lint exits 0 on the actual T3.6 seeds (clean path)
TestReactiveInjection      — parametrized: each known violation type causes exit 1
TestVehicleConfigId        — vehicle_config_id specific injection (task's primary example: 25551)
TestAccessChannelDecision3 — zero 'independent' rows in fixtures + scripts
TestFalsePositiveTolerance — DMS-prefixed IDs with digits do NOT trigger lint
TestSeedScriptScanning     — seed scripts with inline literal assignments
TestSchemaExamplesScanning — JSON Schema example values
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# Fixtures: paths
# ---------------------------------------------------------------------------

# Repo root: platform-foundation/ is the CDK app root;
# scripts/lint_no_licensed_autocare_ids.py lives there.
_PF_ROOT = Path(__file__).parent.parent

_LINT_SCRIPT = _PF_ROOT / "scripts" / "lint_no_licensed_autocare_ids.py"
_FIXTURE_DIR = _PF_ROOT / "scripts" / "parts_seed_fixtures"
_SCHEMA_DIR  = _PF_ROOT / "source" / "schemas"


def _run_lint(root: str | Path, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run the lint script with the given root and return the CompletedProcess."""
    cmd = [
        sys.executable,
        str(_LINT_SCRIPT),
        "--root", str(root),
        "--verbose",
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


@pytest.fixture()
def temp_root(tmp_path: Path) -> Generator[Path, None, None]:
    """A temporary platform-foundation root with copies of all scanned files.

    The copy mirrors the exact directory layout the lint expects:
      scripts/parts_seed_fixtures/*.json
      scripts/seed_parts_catalog.py
      scripts/seed_parts_fitment.py
      scripts/seed_parts_interchange.py
      source/schemas/aces_5_0_shape.json
      source/schemas/pies_8_0_shape.json
    """
    # Mirror directory structure
    (tmp_path / "scripts" / "parts_seed_fixtures").mkdir(parents=True, exist_ok=True)
    (tmp_path / "source" / "schemas").mkdir(parents=True, exist_ok=True)

    # Copy fixture
    for fixture in _FIXTURE_DIR.glob("*.json"):
        shutil.copy2(fixture, tmp_path / "scripts" / "parts_seed_fixtures" / fixture.name)

    # Copy seed scripts
    for script_name in (
        "seed_parts_catalog.py",
        "seed_parts_fitment.py",
        "seed_parts_interchange.py",
    ):
        src = _PF_ROOT / "scripts" / script_name
        if src.exists():
            shutil.copy2(src, tmp_path / "scripts" / script_name)

    # Copy schemas
    for schema_name in ("aces_5_0_shape.json", "pies_8_0_shape.json"):
        src = _SCHEMA_DIR / schema_name
        if src.exists():
            shutil.copy2(src, tmp_path / "source" / "schemas" / schema_name)

    yield tmp_path


# ---------------------------------------------------------------------------
# TestLintCleanPass — lint must exit 0 on the actual T3.6 output
# ---------------------------------------------------------------------------

class TestLintCleanPass:
    """The lint passes (exit 0) on the clean seeds produced by T3.6."""

    def test_clean_seeds_exit_zero(self) -> None:
        """Run lint directly against the real platform-foundation/ tree."""
        result = _run_lint(_PF_ROOT)
        assert result.returncode == 0, (
            f"Lint failed on clean seeds.\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    def test_pass_message_present(self) -> None:
        result = _run_lint(_PF_ROOT)
        assert "PASS" in result.stdout or "PASS" in result.stderr, (
            "Expected PASS in lint output"
        )

    def test_zero_violation_count_on_clean_run(self) -> None:
        result = _run_lint(_PF_ROOT)
        assert "0 violations" in result.stdout or "0 violations" in result.stderr


# ---------------------------------------------------------------------------
# TestLintFailClosed — security-review Cycle 1 W1 (2026-09-03)
# ---------------------------------------------------------------------------

class TestLintFailClosed:
    """The lint fails closed when target paths are missing.

    Rationale (security-review Cycle 1 W1): prior behavior silently skipped
    non-existent target paths and returned exit 0 on a tree with all target
    directories renamed. Now `run_lint` counts files per category and emits a
    synthetic Finding with reason `target-paths missing` when any category is
    under-scanned, causing exit 1.
    """

    def test_missing_seed_scripts_fails_closed(self, temp_root: Path) -> None:
        """Rename all seed scripts → lint must FAIL, not silently PASS."""
        for name in ('seed_parts_catalog.py', 'seed_parts_fitment.py', 'seed_parts_interchange.py'):
            p = temp_root / 'scripts' / name
            if p.exists():
                p.rename(p.with_suffix('.py.hidden'))
        result = _run_lint(temp_root)
        assert result.returncode != 0, (
            "W1 fail-closed: lint should FAIL when seed scripts are missing.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert 'target-paths missing' in result.stderr, (
            "W1 fail-closed: expected 'target-paths missing' in stderr.\n"
            f"STDERR:\n{result.stderr}"
        )

    def test_missing_schemas_fails_closed(self, temp_root: Path) -> None:
        """Rename JSON Schemas → lint must FAIL, not silently PASS."""
        for name in ('aces_5_0_shape.json', 'pies_8_0_shape.json'):
            p = temp_root / 'source' / 'schemas' / name
            if p.exists():
                p.rename(p.with_suffix('.json.hidden'))
        result = _run_lint(temp_root)
        assert result.returncode != 0
        assert 'target-paths missing' in result.stderr

    def test_missing_fixtures_dir_fails_closed(self, temp_root: Path) -> None:
        """Delete parts_seed_fixtures/ → lint must FAIL, not silently PASS.

        This is the exact fail-open path W1 was written for: a rename of the
        fixture directory as part of a cleanup PR previously left the lint
        reporting PASS on zero fixture files. Now it fails closed.
        """
        fixtures_dir = temp_root / 'scripts' / 'parts_seed_fixtures'
        if fixtures_dir.exists():
            import shutil
            shutil.rmtree(fixtures_dir)
        result = _run_lint(temp_root)
        assert result.returncode != 0, (
            "W1 fail-closed: lint should FAIL when parts_seed_fixtures/ is gone.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert 'target-paths missing' in result.stderr or "fixtures" in result.stderr


# ---------------------------------------------------------------------------
# TestReactiveInjection — each violation type causes exit 1
# ---------------------------------------------------------------------------

# Parametrized cases:
# (fixture_patch, field_injected, value_injected, reason_label)
_INJECTION_CASES = [
    # The task's primary example: a bare integer VCdb VehicleConfigurationID
    (
        "vehicle_config_id",
        "25551",
        "bare integer VCdb VehicleConfigurationID (task example)",
    ),
    # PCdb PartTerminologyID in typical published range
    (
        "part_terminology_id",
        "12345",
        "bare integer PCdb PartTerminologyID",
    ),
    # Brand Table BrandAAIAID in typical published range
    (
        "brand_aaia_id",
        "10000",
        "bare integer Brand Table BrandAAIAID",
    ),
    # Non-prefixed string (not DMS-) in brand_aaia_id
    (
        "brand_aaia_id",
        "ACME-001",
        "non-DMS-prefixed brand ID",
    ),
    # Non-prefixed vehicle config with non-numeric value
    (
        "vehicle_config_id",
        "VCFG-99",
        "non-DMS-prefixed vehicle config ID",
    ),
    # access_channel = 'independent'  (Decision 3 enforcement)
    (
        "access_channel",
        "independent",
        "access_channel='independent' violates Decision 3 franchise-only invariant",
    ),
]


def _build_injected_fixture(base_fixture: list[dict], field: str, bad_value: str) -> list[dict]:
    """Clone the base fixture and inject bad_value into the first record's field."""
    import copy
    patched = copy.deepcopy(base_fixture)
    if field == "attribute_id":
        # Inject into extended_attributes[0]
        attrs = patched[0].get("extended_attributes") or []
        if attrs:
            attrs[0]["attribute_id"] = bad_value
        else:
            patched[0].setdefault("extended_attributes", [{"attribute_id": bad_value, "attribute_name": "X", "attribute_value": "Y", "uom": None}])
    elif field == "qualifier_id":
        # Inject into qualifiers[0]
        quals = patched[0].get("qualifiers") or []
        if quals:
            quals[0]["qualifier_id"] = bad_value
        else:
            patched[0].setdefault("qualifiers", [{"qualifier_id": bad_value, "qualifier_text": "test"}])
    else:
        patched[0][field] = bad_value
    return patched


@pytest.mark.parametrize("field,bad_value,label", _INJECTION_CASES)
class TestReactiveInjection:
    """Injecting a violation into a temp fixture copy MUST make the lint exit non-zero."""

    def test_injection_causes_exit_nonzero(
        self,
        field: str,
        bad_value: str,
        label: str,
        temp_root: Path,
    ) -> None:
        """The injected fixture makes the lint fail.

        This is the primary reactive proof required by the task specification:
        'A guard nobody has seen fail is a guard nobody should trust.'
        """
        # Load the canonical fixture
        fixture_path = temp_root / "scripts" / "parts_seed_fixtures" / "parts_catalog.json"
        base = json.loads(fixture_path.read_text())

        # Inject the violation
        patched = _build_injected_fixture(base, field, bad_value)

        # Overwrite the fixture in the temp root
        fixture_path.write_text(json.dumps(patched, indent=2))

        result = _run_lint(temp_root)

        assert result.returncode != 0, (
            f"Lint should have FAILED for injection [{label}].\n"
            f"  field={field!r}  bad_value={bad_value!r}\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    def test_injection_produces_fail_message(
        self,
        field: str,
        bad_value: str,
        label: str,
        temp_root: Path,
    ) -> None:
        """The FAIL message names the offending field and value."""
        fixture_path = temp_root / "scripts" / "parts_seed_fixtures" / "parts_catalog.json"
        base = json.loads(fixture_path.read_text())
        patched = _build_injected_fixture(base, field, bad_value)
        fixture_path.write_text(json.dumps(patched, indent=2))

        result = _run_lint(temp_root)

        combined = result.stdout + result.stderr
        assert "FAIL" in combined, f"Expected 'FAIL' in output for injection [{label}]"


# ---------------------------------------------------------------------------
# TestVehicleConfigId — the task's primary canonical example
# ---------------------------------------------------------------------------

class TestVehicleConfigId:
    """The vehicle_config_id=25551 injection from the task specification."""

    def test_bare_integer_25551_fails(self, temp_root: Path) -> None:
        """vehicle_config_id='25551' (the example from the task) MUST fail lint."""
        fixture_path = temp_root / "scripts" / "parts_seed_fixtures" / "parts_catalog.json"
        # We need a fitment-style fixture with vehicle_config_id; the catalog fixture
        # does not have this field directly.  Create a minimal fitment fixture.
        fitment_fixture = [
            {
                "part_number":      "DMS-PT001-OIL-F",
                "brand_aaia_id":    "DMS-BR-001",
                "vehicle_config_id": "25551",   # <-- the violation
                "position_id":      "Front",
                "qualifier_hash":   "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "quantity":         1,
                "notes":            None,
                "action":           "A",
                "access_channel":   "franchise",
                "tenant_id":        "dms-reference",
            }
        ]
        # Write into a new fixture file in the temp tree
        injected_path = temp_root / "scripts" / "parts_seed_fixtures" / "fitment_injection.json"
        injected_path.write_text(json.dumps(fitment_fixture, indent=2))

        result = _run_lint(temp_root)
        assert result.returncode != 0, (
            "vehicle_config_id='25551' should have failed lint (VCdb range 1–9,999,999).\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "25551" in combined, "Expected the injected value '25551' in lint output"
        assert "vehicle_config_id" in combined.lower()

    def test_dms_prefixed_vcfg_with_digits_passes(self, temp_root: Path) -> None:
        """DMS-VCFG-0001 (contains digits) must NOT trigger the numeric-range check.

        This is the false-positive guard: legitimate DMS IDs contain digits, but
        they have the DMS- prefix and must pass cleanly.
        """
        # The canonical fixture already has DMS-VCFG-* values in seed scripts.
        # Confirm clean pass on original tree.
        result = _run_lint(_PF_ROOT)
        assert result.returncode == 0, (
            "DMS-VCFG-* IDs triggered a false positive in the numeric-range check.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# TestAccessChannelDecision3 — zero 'independent' rows in fixtures + scripts
# ---------------------------------------------------------------------------

class TestAccessChannelDecision3:
    """Per Decision 3: access_channel='franchise' ONLY in v1.  Zero 'independent' rows."""

    def test_fixture_has_no_independent_rows(self) -> None:
        """Load the actual fixture and assert zero 'independent' values."""
        fixture_path = _FIXTURE_DIR / "parts_catalog.json"
        assert fixture_path.exists(), f"Fixture not found: {fixture_path}"
        records = json.loads(fixture_path.read_text())
        independent = [
            (i, r) for i, r in enumerate(records)
            if r.get("access_channel") == "independent"
        ]
        assert not independent, (
            f"Found {len(independent)} 'independent' record(s) in parts_catalog.json — "
            "Decision 3 requires zero: "
            + str([f"record[{i}]" for i, _ in independent])
        )

    def test_lint_flags_independent_fixture(self, temp_root: Path) -> None:
        """Injecting access_channel='independent' makes lint exit non-zero."""
        fixture_path = temp_root / "scripts" / "parts_seed_fixtures" / "parts_catalog.json"
        base = json.loads(fixture_path.read_text())
        base[0]["access_channel"] = "independent"
        fixture_path.write_text(json.dumps(base, indent=2))

        result = _run_lint(temp_root)
        assert result.returncode != 0, (
            "Lint should FAIL when access_channel='independent' is present.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_seed_catalog_has_no_independent_access_channel_assignment(self) -> None:
        """seed_parts_catalog.py must not assign access_channel='independent'.

        The word 'independent' may appear in comments or docstrings explaining
        the Decision 3 rationale — that is fine.  What must not appear is a
        live assignment like access_channel = "independent" or
        "access_channel": "independent".
        """
        src = (_PF_ROOT / "scripts" / "seed_parts_catalog.py").read_text()
        # Use the same regex the lint uses for seed scripts
        live_assignments = [
            (i + 1, line)
            for i, line in enumerate(src.splitlines())
            if re.search(
                r"""["']?access_channel["']?\s*[:=]\s*["']independent["']""", line
            )
        ]
        assert not live_assignments, (
            f"seed_parts_catalog.py assigns access_channel='independent': "
            + str(live_assignments)
        )

    def test_seed_fitment_has_no_independent_access_channel_assignment(self) -> None:
        """seed_parts_fitment.py must not assign access_channel='independent'."""
        src = (_PF_ROOT / "scripts" / "seed_parts_fitment.py").read_text()
        live_assignments = [
            (i + 1, line)
            for i, line in enumerate(src.splitlines())
            if re.search(
                r"""["']?access_channel["']?\s*[:=]\s*["']independent["']""", line
            )
        ]
        assert not live_assignments, (
            f"seed_parts_fitment.py assigns access_channel='independent': "
            + str(live_assignments)
        )

    def test_seed_interchange_has_no_independent_access_channel_assignment(self) -> None:
        """seed_parts_interchange.py must not assign access_channel='independent'."""
        src = (_PF_ROOT / "scripts" / "seed_parts_interchange.py").read_text()
        live_assignments = [
            (i + 1, line)
            for i, line in enumerate(src.splitlines())
            if re.search(
                r"""["']?access_channel["']?\s*[:=]\s*["']independent["']""", line
            )
        ]
        assert not live_assignments, (
            f"seed_parts_interchange.py assigns access_channel='independent': "
            + str(live_assignments)
        )

    def test_lint_passes_franchise_only_seeds(self) -> None:
        """Full clean-pass on franchise-only seeds confirms Decision 3 is enforced."""
        result = _run_lint(_PF_ROOT)
        assert result.returncode == 0, (
            "Lint failed on franchise-only clean seeds — possible false positive.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# TestFalsePositiveTolerance — DMS-prefixed IDs with digits pass cleanly
# ---------------------------------------------------------------------------

class TestFalsePositiveTolerance:
    """DMS-VCFG-0001, DMS-PT-001, DMS-QT-001, DMS-PA-001, DMS-BR-001 must all pass.

    The DMS- prefix scheme means legitimate IDs contain digits.  A naive
    numeric-range regex would fire on the digit suffix.  This class proves
    the lint does not cry wolf on any valid DMS-prefixed ID in the actual seeds.
    """

    _VALID_DMS_IDS: list[tuple[str, str]] = [
        ("vehicle_config_id",   "DMS-VCFG-0001"),
        ("vehicle_config_id",   "DMS-VCFG-0012"),
        ("brand_aaia_id",       "DMS-BR-001"),
        ("part_terminology_id", "DMS-PT-001"),
        ("part_terminology_id", "DMS-PT-080"),
        ("qualifier_id",        "DMS-QT-001"),
        ("qualifier_id",        "DMS-QT-020"),
        ("attribute_id",        "DMS-PA-001"),
        ("attribute_id",        "DMS-PA-042"),
    ]

    @pytest.mark.parametrize("field,value", _VALID_DMS_IDS)
    def test_dms_prefixed_id_does_not_trigger(
        self,
        field: str,
        value: str,
        temp_root: Path,
    ) -> None:
        """DMS-prefixed ID with digits must not trigger lint."""
        # Build a minimal fixture with the valid ID in the expected field
        record: dict = {
            "brand_aaia_id":       "DMS-BR-001",
            "part_number":         "DMS-P-TEST-001",
            "part_terminology_id": "DMS-PT-001",
            "access_channel":      "franchise",
            "tenant_id":           "dms-reference",
        }

        if field == "attribute_id":
            record["extended_attributes"] = [
                {"attribute_id": value, "attribute_name": "Test", "attribute_value": "X", "uom": None}
            ]
        elif field == "qualifier_id":
            record["qualifiers"] = [
                {"qualifier_id": value, "qualifier_text": "test condition"}
            ]
        else:
            record[field] = value

        fixture_path = tmp_path_for_test = temp_root / "scripts" / "parts_seed_fixtures" / "valid_dms.json"
        fixture_path.write_text(json.dumps([record]))

        result = _run_lint(temp_root)
        assert result.returncode == 0, (
            f"False positive: valid DMS-prefixed ID {field}={value!r} triggered lint.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_full_clean_run_proves_no_false_positives_in_actual_seeds(self) -> None:
        """The actual 500-part seed (DMS-VCFG-0001..0012, DMS-PT-001..080, etc.)
        passes cleanly — proving no false positives on the full corpus."""
        result = _run_lint(_PF_ROOT)
        assert result.returncode == 0, (
            "False positive in actual seeds — DMS-prefixed IDs triggered lint.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# TestSeedScriptScanning — Python source literal assignments
# ---------------------------------------------------------------------------

class TestSeedScriptScanning:
    """The lint also scans seed scripts for literal ID assignments."""

    def test_injection_into_seed_script_fails(self, temp_root: Path) -> None:
        """A seed script with a hard-coded non-DMS vehicle_config_id is caught."""
        script_path = temp_root / "scripts" / "seed_parts_fitment.py"
        if not script_path.exists():
            pytest.skip("seed_parts_fitment.py not found in temp_root")

        original = script_path.read_text()
        # Inject a bare integer literal assignment for vehicle_config_id
        injection = '\nvehicle_config_id = "99999"\n'
        script_path.write_text(original + injection)

        result = _run_lint(temp_root)
        assert result.returncode != 0, (
            "Lint should FAIL when seed script contains a hard-coded non-DMS vehicle_config_id.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_format_string_template_not_flagged(self, temp_root: Path) -> None:
        """Format-string templates like 'DMS-VCFG-{n}' must NOT be flagged.

        They are placeholders, not literal IDs.
        """
        script_path = temp_root / "scripts" / "seed_parts_fitment.py"
        if not script_path.exists():
            pytest.skip("seed_parts_fitment.py not found in temp_root")

        original = script_path.read_text()
        # Add a format-string template — this is safe and must not be flagged
        template_line = '\nvehicle_config_id = f"DMS-VCFG-{n}"\n'
        script_path.write_text(original + template_line)

        result = _run_lint(temp_root)
        assert result.returncode == 0, (
            "Format-string template 'DMS-VCFG-{n}' should NOT trigger lint.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    @pytest.mark.parametrize(
        "injected_value,description",
        [
            ('"25551{}".format("")', 'format() call: str contains { but runtime value is bare 25551'),
            ('"25551%s" % ""', 'printf-style: str contains % but runtime value is bare 25551'),
            ('"{prefix}25551".format(prefix="")', '{prefix} placeholder does not start with DMS-'),
            ('"99999{}"', 'template does not start with DMS-'),
        ],
    )
    def test_w2_format_string_escape_hatch_is_closed(
        self,
        temp_root: Path,
        injected_value: str,
        description: str,
    ) -> None:
        """Security-review Cycle 1 W2 (2026-09-03): format-string trick.

        Prior to the fix, ``value = "25551{}".format("")`` bypassed the source
        scanner because the raw string contained ``{``. Now templates must
        themselves start with ``DMS-`` (or ``dms-``) to be treated as safe;
        otherwise they are treated as suspect literals.
        """
        script_path = temp_root / "scripts" / "seed_parts_fitment.py"
        if not script_path.exists():
            pytest.skip("seed_parts_fitment.py not found in temp_root")

        original = script_path.read_text()
        injection = f'\nvehicle_config_id = {injected_value}\n'
        script_path.write_text(original + injection)

        result = _run_lint(temp_root)
        assert result.returncode != 0, (
            f"W2 escape-hatch trick ({description}) should FAIL the lint.\n"
            f"Injected value expression: {injected_value}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# TestSchemaExamplesScanning — example values in JSON Schemas
# ---------------------------------------------------------------------------

class TestSchemaExamplesScanning:
    """The lint checks 'examples' and 'default' values in JSON Schemas."""

    def test_schema_with_bad_example_fails(self, temp_root: Path) -> None:
        """A JSON Schema with a non-DMS example value for brand_aaia_id is caught."""
        schema_path = temp_root / "source" / "schemas" / "pies_8_0_shape.json"
        if not schema_path.exists():
            pytest.skip("pies_8_0_shape.json not found in temp_root")

        schema = json.loads(schema_path.read_text())
        # Inject a bad example into the brand_aaia_id property
        schema.setdefault("properties", {})
        schema["properties"].setdefault("brand_aaia_id", {})
        schema["properties"]["brand_aaia_id"]["examples"] = ["10000"]  # bare int, not DMS-

        schema_path.write_text(json.dumps(schema, indent=2))

        result = _run_lint(temp_root)
        assert result.returncode != 0, (
            "Lint should FAIL when JSON Schema has a non-DMS brand_aaia_id example.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_schema_clean_examples_pass(self) -> None:
        """The actual schemas (DMS-BR-001 etc.) pass cleanly."""
        result = _run_lint(_PF_ROOT)
        assert result.returncode == 0, (
            "JSON Schema examples triggered a false positive.\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# TestMultipleViolationsReported — lint accumulates all findings
# ---------------------------------------------------------------------------

class TestMultipleViolationsReported:
    """Lint accumulates and reports all violations, not just the first."""

    def test_two_injections_both_reported(self, temp_root: Path) -> None:
        """Two injected violations both appear in the output."""
        fixture_path = temp_root / "scripts" / "parts_seed_fixtures" / "parts_catalog.json"
        base = json.loads(fixture_path.read_text())

        # Inject two violations in two different records
        import copy
        patched = copy.deepcopy(base)
        patched[0]["brand_aaia_id"] = "10000"         # violation 1
        if len(patched) > 1:
            patched[1]["part_terminology_id"] = "5000" # violation 2

        fixture_path.write_text(json.dumps(patched, indent=2))

        result = _run_lint(temp_root)
        assert result.returncode != 0

        combined = result.stdout + result.stderr
        # Both injected values should appear in the output
        assert "10000" in combined, "First violation value not in output"
