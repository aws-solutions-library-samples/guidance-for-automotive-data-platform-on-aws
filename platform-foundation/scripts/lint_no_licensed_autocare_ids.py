#!/usr/bin/env python3
"""lint_no_licensed_autocare_ids.py — T3.7 Licensing safeguard.

This is a LICENSING safeguard, not a schema validator.

Purpose
-------
Scan the seed fixtures, the three seed scripts, and the two JSON Schemas
under platform-foundation/ and FAIL (exit non-zero) on any value that:

  (a) Is present in a field where a licensed Auto Care ID is expected
      (vehicle_config_id, brand_aaia_id, part_terminology_id, qualifier_id,
      attribute_id) but does NOT start with the mandatory DMS- prefix.

  (b) Matches a known Auto Care numeric-ID range pattern:
        • VCdb VehicleID / VehicleConfigurationID  — bare integers 1–9999999
        • PCdb PartTerminologyID                   — bare integers 1–999999
        • Qdb QualifierID                          — bare integers 1–9999
        • PAdb AttributeID                         — bare integers 1–9999
        • Brand Table BrandAAIAID                  — bare integers 1–99999

  (c) Has access_channel != 'franchise'.  v1 is franchise-only per ADP spec
      Decision 3 (2026-08-27).  Zero 'independent' rows must exist.

False-positive discipline
-------------------------
Legitimate DMS-prefixed IDs contain digits (DMS-VCFG-0001, DMS-PT-001, …).
A naive "digits-only" check would fire on those.  This lint therefore checks
each ID field individually:

  1. First asserts the DMS- prefix is present.  If it is, the value is
     syntactically safe and no numeric-range check is performed.

  2. If the DMS- prefix is absent, the value is checked against each Auto
     Care numeric range.  Only purely numeric strings (no hyphens or letters)
     are flagged by the range patterns, so schema-structural strings like
     "Front Left" or "EA" are never flagged.

The numeric-range checks are CONSERVATIVE (not generous):
  • They flag only bare integer strings inside the known published ranges.
  • They err toward flagging for human review over silently passing.

Do NOT weaken this by adding an allowlist for a suspicious ID — that is
precisely how VCdb data would end up shipped.  User sign-off is required.

Scope
-----
Scanned paths (relative to --root, defaulting to platform-foundation/):
  scripts/parts_seed_fixtures/*.json  — fixture JSON arrays
  scripts/seed_parts_catalog.py
  scripts/seed_parts_fitment.py
  scripts/seed_parts_interchange.py
  source/schemas/aces_5_0_shape.json
  source/schemas/pies_8_0_shape.json

Usage
-----
  # Clean run (exits 0):
  python3 scripts/lint_no_licensed_autocare_ids.py --root platform-foundation/

  # With verbose output:
  python3 scripts/lint_no_licensed_autocare_ids.py --root platform-foundation/ --verbose

  # Inject a violation and see it fail:
  python3 scripts/lint_no_licensed_autocare_ids.py \
      --root /tmp/injected/ --verbose

Exit codes
----------
  0 — no violations found
  1 — one or more violations found (printed to stderr)
  2 — argument / file-not-found error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# ID field names that must carry a DMS- prefix in fixture/seed data.
# Keys: JSON field name.  Values: short description for error messages.
# ---------------------------------------------------------------------------
_LICENSED_ID_FIELDS: dict[str, str] = {
    "vehicle_config_id":     "VCdb VehicleConfigurationID",
    "engine_base_id":        "VCdb EngineBaseID",
    "brand_aaia_id":         "Brand Table BrandAAIAID",
    "part_terminology_id":   "PCdb PartTerminologyID",
    "qualifier_id":          "Qdb QualifierID",
    "attribute_id":          "PAdb AttributeID",
}

# ---------------------------------------------------------------------------
# Known published Auto Care numeric-ID ranges.
# These are conservative floor-to-ceiling windows based on publicly known
# range conventions.  Any purely numeric string in these windows, found in
# a licensed-ID field, is flagged for human review.
# DMS-prefixed values are never matched by these patterns because the match
# requires an all-digit string.
# ---------------------------------------------------------------------------
_AUTOCARE_NUMERIC_RANGES: list[tuple[str, int, int, str]] = [
    # (field_keyword, min_inclusive, max_inclusive, label)
    # VCdb VehicleID / VehicleConfigurationID (published range: 1–~9,000,000)
    ("vehicle_config_id",   1, 9_999_999, "VCdb VehicleConfigurationID"),
    ("engine_base_id",      1, 9_999_999, "VCdb EngineBaseID"),
    # PCdb PartTerminologyID (published range: 1–~90,000 as of 2025)
    ("part_terminology_id", 1,   999_999, "PCdb PartTerminologyID"),
    # Qdb QualifierID (published range: 1–~3,000 as of 2025)
    ("qualifier_id",        1,     9_999, "Qdb QualifierID"),
    # PAdb AttributeID (published range: 1–~2,000 as of 2025)
    ("attribute_id",        1,     9_999, "PAdb AttributeID"),
    # Brand Table BrandAAIAID (published range: 1–~60,000 as of 2025)
    ("brand_aaia_id",       1,    99_999, "Brand Table BrandAAIAID"),
]

# Pattern: bare integer (no letters, no hyphens, no spaces).
_BARE_INT_RE = re.compile(r"^\d+$")

# ---------------------------------------------------------------------------
# Seed-script field references: strings inside the seed Python sources that
# hard-code a literal value for a licensed-ID field.
# These regexes match assignment patterns like:
#   vehicle_config_id = "12345"
#   "brand_aaia_id": "DMS-BR-001",
# We scan for lines that contain a licensed-ID field key followed by a
# quoted value that lacks the DMS- prefix.
# ---------------------------------------------------------------------------
_SEED_FIELD_ASSIGN_RE = re.compile(
    r"""["']?(?P<field>vehicle_config_id|brand_aaia_id|part_terminology_id|"""
    r"""qualifier_id|attribute_id|engine_base_id)["']?\s*[:=]\s*["'](?P<value>[^"']+)["']""",
)

# access_channel value that is forbidden in v1 fixtures.
_FORBIDDEN_ACCESS_CHANNEL = "independent"


# ---------------------------------------------------------------------------
# Finding dataclass (plain namedtuple-style class for Python 3.6 compat)
# ---------------------------------------------------------------------------
class Finding:
    """A lint violation."""

    __slots__ = ("path", "location", "field", "value", "reason")

    def __init__(
        self,
        path: str,
        location: str,
        field: str,
        value: str,
        reason: str,
    ) -> None:
        self.path = path
        self.location = location
        self.field = field
        self.value = value
        self.reason = reason

    def __str__(self) -> str:
        return (
            f"  [{self.path}] {self.location}\n"
            f"    field={self.field!r}  value={self.value!r}\n"
            f"    reason: {self.reason}"
        )


# ---------------------------------------------------------------------------
# Value checking
# ---------------------------------------------------------------------------

def _check_id_value(
    field: str, value: Any, path: str, location: str
) -> list[Finding]:
    """Check a single ID-typed field value.  Returns 0 or 1 Finding."""
    if not isinstance(value, str) or not value:
        # null / None is allowed (optional fields); non-string is ignored
        return []

    # Presence check: must start with "DMS-"
    if not value.startswith("DMS-"):
        # Secondary check: is it in a known numeric range?
        reason = f"missing DMS- prefix on {_LICENSED_ID_FIELDS.get(field, field)}"
        if _BARE_INT_RE.match(value):
            int_val = int(value)
            for key, lo, hi, label in _AUTOCARE_NUMERIC_RANGES:
                if key == field and lo <= int_val <= hi:
                    reason = (
                        f"bare integer {int_val} falls in the {label} "
                        f"numeric range ({lo}–{hi}) — potential licensed ID"
                    )
                    break
        return [Finding(path=path, location=location, field=field, value=value, reason=reason)]

    return []


def _check_access_channel(
    value: Any, path: str, location: str
) -> list[Finding]:
    """Flag any access_channel != 'franchise'."""
    if not isinstance(value, str):
        return []
    if value == _FORBIDDEN_ACCESS_CHANNEL:
        return [Finding(
            path=path,
            location=location,
            field="access_channel",
            value=value,
            reason=(
                "v1 is franchise-only (ADP spec Decision 3, 2026-08-27); "
                "zero 'independent' rows must exist — per T3.7 the 'franchise-only' "
                "invariant is test-enforced here rather than asserted"
            ),
        )]
    return []


# ---------------------------------------------------------------------------
# JSON fixture scanning
# ---------------------------------------------------------------------------

def _scan_json_record(
    record: dict, path: str, record_index: int
) -> list[Finding]:
    """Scan a single JSON record (dict) for violations."""
    findings: list[Finding] = []
    location = f"record[{record_index}]"

    for field in _LICENSED_ID_FIELDS:
        if field in record:
            findings.extend(_check_id_value(field, record[field], path, location))

    # Check extended_attributes array for attribute_id
    ext_attrs = record.get("extended_attributes")
    if isinstance(ext_attrs, list):
        for i, attr in enumerate(ext_attrs):
            if isinstance(attr, dict) and "attribute_id" in attr:
                sub_loc = f"record[{record_index}].extended_attributes[{i}]"
                findings.extend(
                    _check_id_value("attribute_id", attr["attribute_id"], path, sub_loc)
                )

    # Check qualifiers array for qualifier_id
    qualifiers = record.get("qualifiers")
    if isinstance(qualifiers, list):
        for i, qual in enumerate(qualifiers):
            if isinstance(qual, dict) and "qualifier_id" in qual:
                sub_loc = f"record[{record_index}].qualifiers[{i}]"
                findings.extend(
                    _check_id_value("qualifier_id", qual["qualifier_id"], path, sub_loc)
                )

    # access_channel check
    if "access_channel" in record:
        findings.extend(
            _check_access_channel(record["access_channel"], path, location)
        )

    return findings


def scan_fixture_file(fixture_path: Path) -> list[Finding]:
    """Scan a JSON fixture file (expected: array of records)."""
    try:
        text = fixture_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # A malformed fixture is suspicious — flag it
        return [Finding(
            path=str(fixture_path),
            location="(file)",
            field="(parse)",
            value="",
            reason=f"JSON parse error: {exc}",
        )]

    findings: list[Finding] = []
    if isinstance(data, list):
        for i, record in enumerate(data):
            if isinstance(record, dict):
                findings.extend(_scan_json_record(record, str(fixture_path), i))
    elif isinstance(data, dict):
        # Single-object fixture
        findings.extend(_scan_json_record(data, str(fixture_path), 0))

    return findings


def scan_schema_file(schema_path: Path) -> list[Finding]:
    """Scan a JSON Schema file for literal example values that would violate the invariant.

    JSON Schema files legitimately name the licensed field keys (in 'description',
    'properties', etc.) — that is expected and correct.  We only flag `examples`
    values and `default` values, which could inadvertently embed real IDs.
    """
    try:
        text = schema_path.read_text(encoding="utf-8")
        schema = json.loads(text)
    except json.JSONDecodeError as exc:
        return [Finding(
            path=str(schema_path),
            location="(file)",
            field="(parse)",
            value="",
            reason=f"JSON parse error: {exc}",
        )]

    findings: list[Finding] = []

    def _walk_schema(node: Any, json_path: str) -> None:
        if isinstance(node, dict):
            # Check 'examples' arrays under licensed-ID property definitions
            # The property key in the parent is the field name; we detect it via
            # context passed as json_path.
            examples = node.get("examples")
            default = node.get("default")

            # Infer the field name from the json_path tail
            path_parts = json_path.rstrip("]").split(".")
            tail = path_parts[-1] if path_parts else ""
            # Strip array index if present
            if tail.endswith("]"):
                tail = tail[:tail.index("[")]

            if tail in _LICENSED_ID_FIELDS:
                if isinstance(examples, list):
                    for ex in examples:
                        findings.extend(
                            _check_id_value(tail, ex, str(schema_path), f"{json_path}.examples")
                        )
                if default is not None:
                    findings.extend(
                        _check_id_value(tail, default, str(schema_path), f"{json_path}.default")
                    )

            for k, v in node.items():
                _walk_schema(v, f"{json_path}.{k}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                _walk_schema(item, f"{json_path}[{i}]")

    _walk_schema(schema, "$")
    return findings


# ---------------------------------------------------------------------------
# Seed-script (Python source) scanning
# ---------------------------------------------------------------------------
#
# The seed scripts are Python source files, not JSON.  We look for literal
# string assignments to licensed-ID fields via the regex above.
#
# We deliberately do NOT parse Python AST here — the regex is conservative
# (matches only the exact field-name-colon/equals-quote-value pattern) and
# avoids flagging comments or docstrings.  A false negative (missing a
# well-disguised literal) is less harmful than a false positive that causes
# the lint to be ignored.

def scan_seed_script(script_path: Path) -> list[Finding]:
    """Scan a Python seed script for literal licensed-ID field assignments."""
    try:
        lines = script_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [Finding(
            path=str(script_path),
            location="(file)",
            field="(read)",
            value="",
            reason=f"Cannot read file: {exc}",
        )]

    findings: list[Finding] = []
    for lineno, line in enumerate(lines, start=1):
        # Skip pure comments (lines beginning with optional whitespace then #)
        stripped = line.strip()
        if stripped.startswith("#"):
            continue

        for m in _SEED_FIELD_ASSIGN_RE.finditer(line):
            field = m.group("field")
            value = m.group("value")

            # Ignore if the value is a format-string placeholder (e.g., {n},
            # DMS-VCFG-{n}) — these are template strings, not literal IDs.
            # SECURITY (W2, 2026-09-03): the template escape MUST require the
            # value to start with 'DMS-' or 'dms-'; otherwise a template like
            # `"25551{}"` (which at runtime yields the literal `25551`) would
            # bypass the source scanner. Tightened per security-review Cycle 1.
            if ("{" in value or "%" in value) and (
                value.startswith("DMS-") or value.startswith("dms-")
            ):
                continue

            # Ignore known constant names (uppercase identifiers) and f-string
            # fragments — these are variable references, not literal values.
            # A value containing only uppercase letters + underscores is a
            # Python identifier (constant reference), not a literal ID.
            if re.fullmatch(r"[A-Z_][A-Z0-9_]*", value):
                continue

            findings.extend(
                _check_id_value(field, value, str(script_path), f"line {lineno}")
            )

    # Also check for any 'independent' access_channel literal in the scripts
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Look for: access_channel = 'independent' or "access_channel": "independent"
        if re.search(
            r"""["']?access_channel["']?\s*[:=]\s*["']independent["']""", line
        ):
            findings.append(Finding(
                path=str(script_path),
                location=f"line {lineno}",
                field="access_channel",
                value="independent",
                reason=(
                    "v1 is franchise-only (ADP spec Decision 3, 2026-08-27); "
                    "'independent' must not appear as a literal value in seed scripts"
                ),
            ))

    return findings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _collect_target_paths(root: Path) -> dict[str, list[Path]]:
    """Return the paths to scan, keyed by category."""
    return {
        "fixtures":     sorted((root / "scripts" / "parts_seed_fixtures").glob("*.json")),
        "seed_scripts": [
            root / "scripts" / "seed_parts_catalog.py",
            root / "scripts" / "seed_parts_fitment.py",
            root / "scripts" / "seed_parts_interchange.py",
        ],
        "schemas":      [
            root / "source" / "schemas" / "aces_5_0_shape.json",
            root / "source" / "schemas" / "pies_8_0_shape.json",
        ],
    }


def run_lint(root: Path, verbose: bool = False) -> list[Finding]:
    """Run all lint checks and return the full findings list.

    SECURITY (W1, 2026-09-03): fails **closed** if any of the expected target
    categories is under-scanned. Prevents the "rename the fixtures directory,
    lint reports PASS on zero files" fail-open scenario documented in
    ``security-review.md`` Cycle 1 W1. Missing paths are reported to stderr
    with a distinct "target-paths missing" reason regardless of ``--verbose``.
    """
    targets = _collect_target_paths(root)
    all_findings: list[Finding] = []
    files_checked = 0
    files_by_category: dict[str, int] = {"fixtures": 0, "seed_scripts": 0, "schemas": 0}
    missing_paths: list[Path] = []

    # --- Fixtures ---
    for path in targets["fixtures"]:
        if not path.exists():
            print(
                f"lint_no_licensed_autocare_ids: target-paths missing — fixture {path} not found",
                file=sys.stderr,
            )
            missing_paths.append(path)
            continue
        if verbose:
            print(f"  [scan] fixture  {path.relative_to(root)}", file=sys.stderr)
        findings = scan_fixture_file(path)
        all_findings.extend(findings)
        files_checked += 1
        files_by_category["fixtures"] += 1

    # --- Seed scripts ---
    for path in targets["seed_scripts"]:
        if not path.exists():
            print(
                f"lint_no_licensed_autocare_ids: target-paths missing — seed script {path} not found",
                file=sys.stderr,
            )
            missing_paths.append(path)
            continue
        if verbose:
            print(f"  [scan] script   {path.relative_to(root)}", file=sys.stderr)
        findings = scan_seed_script(path)
        all_findings.extend(findings)
        files_checked += 1
        files_by_category["seed_scripts"] += 1

    # --- JSON Schemas ---
    for path in targets["schemas"]:
        if not path.exists():
            print(
                f"lint_no_licensed_autocare_ids: target-paths missing — schema {path} not found",
                file=sys.stderr,
            )
            missing_paths.append(path)
            continue
        if verbose:
            print(f"  [scan] schema   {path.relative_to(root)}", file=sys.stderr)
        findings = scan_schema_file(path)
        all_findings.extend(findings)
        files_checked += 1
        files_by_category["schemas"] += 1

    # --- Fail-closed minimum-coverage check (W1) ---
    # Expected minima:
    #   fixtures:     >= 1  (at least one product's committed fixture)
    #   seed_scripts: == 3  (catalog, fitment, interchange)
    #   schemas:      == 2  (ACES 5.0, PIES 8.0)
    # A rename or deletion of any target directory would previously have
    # returned exit 0 with zero files scanned; now it emits a synthetic
    # Finding that surfaces at lint fail-time.
    _expected = {"fixtures": 1, "seed_scripts": 3, "schemas": 2}
    for category, expected in _expected.items():
        got = files_by_category[category]
        if got < expected:
            all_findings.append(Finding(
                path=str(root),
                location=f"category '{category}'",
                field="(coverage)",
                value=f"{got}/{expected}",
                reason=(
                    f"target-paths missing: expected >= {expected} '{category}' "
                    f"file(s), scanned {got}. Fixing this failure requires either "
                    f"(a) restoring the missing paths OR (b) getting user sign-off "
                    f"to reduce the expected minimum in scripts/lint_no_licensed_autocare_ids.py. "
                    f"Missing paths (this run): "
                    + (", ".join(str(p) for p in missing_paths) if missing_paths else "(none)")
                ),
            ))
    if verbose:
        print(f"\n  Files checked: {files_checked} "
              f"(fixtures={files_by_category['fixtures']}, "
              f"seed_scripts={files_by_category['seed_scripts']}, "
              f"schemas={files_by_category['schemas']})", file=sys.stderr)
        if missing_paths:
            print(f"  Missing: {len(missing_paths)}", file=sys.stderr)

    return all_findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="T3.7 licensing lint — no licensed Auto Care IDs in parts seed",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        default=str(Path(__file__).parent.parent),
        help="Platform-foundation root directory (default: parent of scripts/)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print each scanned file to stderr",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root {root} is not a directory", file=sys.stderr)
        return 2

    if args.verbose:
        print(f"\nLint root: {root}", file=sys.stderr)

    findings = run_lint(root, verbose=args.verbose)

    if not findings:
        print(
            f"lint_no_licensed_autocare_ids: PASS — 0 violations found in {root}",
            file=sys.stderr,
        )
        return 0

    print(
        f"\nlint_no_licensed_autocare_ids: FAIL — {len(findings)} violation(s) found:\n",
        file=sys.stderr,
    )
    for finding in findings:
        print(str(finding), file=sys.stderr)
        print("", file=sys.stderr)

    print(
        "Do NOT weaken this check by adding an allowlist without user sign-off.\n"
        "Allowlisting a licensed range is precisely how VCdb data would end up shipped.\n"
        "See ADP spec 2026-08-26-adp-dealer-domain § Constraints.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
