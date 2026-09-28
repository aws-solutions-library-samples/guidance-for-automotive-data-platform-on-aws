#!/usr/bin/env python3
"""seed_parts_catalog.py — Seed adp_parts_domain / parts_catalog product.

Target: ~500 unique parts across ~80 PCdb-shaped part-terminology categories.

LICENSING INVARIANT (Auto Care Technology License Agreement, rev. 2025-02-28):
  VCdb, PCdb, Qdb, PAdb and the Brand Table are subscription-based licensed
  property.  This script ships ACES/PIES-conformant *shape* with synthetic values
  only.  Every ID lives in a DMS-prefixed namespace so T3.7 lint can catch any
  violation:
    brand_aaia_id  → DMS-BR-*
    part_terminology_id → DMS-PT-*
    attribute_id   → DMS-PA-*

Per ADP spec Decision 3 (2026-08-27): access_channel='franchise' ONLY in v1.
Zero 'independent' rows.

IDEMPOTENCY CONTRACT (portfolio lesson from agentic-tiers.md):
  A second run must produce zero net writes.  This is proven by an actual
  second run, not by a stub — see tests/test_parts_seed_idempotency.py.

  The fixture store is a JSON file (parts_seed_fixtures/parts_catalog.json).
  The script reads the store, computes the full record set, diffs against what
  is already there by (brand_aaia_id, part_number) PK, and only writes new
  rows.  On the second call from the same run the store is already complete
  and the write count is 0.

Usage:
  python3 seed_parts_catalog.py [--dry-run] [--fixture-dir PATH] [--verbose]

  --dry-run     Print each record to stdout; do NOT write to the fixture store.
  --fixture-dir Override the default fixture directory.
  --verbose     Include summary counts at the end.
"""
from __future__ import annotations

import argparse
import json
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Namespace constants — lint invariant: every ID must start with one of these.
# ---------------------------------------------------------------------------
BRAND_ID = "DMS-BR-001"          # Single synthetic brand for all catalog parts
ACCESS_CHANNEL = "franchise"      # v1 — no 'independent' rows per Decision 3
TENANT_ID = "dms-reference"


# ---------------------------------------------------------------------------
# 80 PCdb-shaped part-terminology categories (synthetic DMS-PT-* IDs)
# Each entry: (DMS-PT-NNN, human-readable name, typical_quantity, uom)
# ---------------------------------------------------------------------------
_TERMINOLOGY: list[tuple[str, str, int, str]] = [
    ("DMS-PT-001", "Oil Filter", 1, "EA"),
    ("DMS-PT-002", "Air Filter", 1, "EA"),
    ("DMS-PT-003", "Brake Pad Set", 1, "PR"),
    ("DMS-PT-004", "Brake Rotor", 2, "EA"),
    ("DMS-PT-005", "Spark Plug", 4, "EA"),
    ("DMS-PT-006", "Oxygen Sensor", 1, "EA"),
    ("DMS-PT-007", "Catalytic Converter", 1, "EA"),
    ("DMS-PT-008", "Ignition Coil", 1, "EA"),
    ("DMS-PT-009", "Fuel Injector", 1, "EA"),
    ("DMS-PT-010", "Mass Air Flow Sensor", 1, "EA"),
    ("DMS-PT-011", "ABS Wheel Speed Sensor", 1, "EA"),
    ("DMS-PT-012", "CAN Bus Module", 1, "EA"),
    ("DMS-PT-013", "SRS Clock Spring", 1, "EA"),
    ("DMS-PT-014", "Throttle Position Sensor", 1, "EA"),
    ("DMS-PT-015", "Manifold Absolute Pressure Sensor", 1, "EA"),
    ("DMS-PT-016", "Engine Coolant Temperature Sensor", 1, "EA"),
    ("DMS-PT-017", "Variable Valve Timing Solenoid", 1, "EA"),
    ("DMS-PT-018", "EGR Valve", 1, "EA"),
    ("DMS-PT-019", "Turbocharger", 1, "EA"),
    ("DMS-PT-020", "Strut Assembly", 1, "EA"),
    ("DMS-PT-021", "Shock Absorber", 1, "EA"),
    ("DMS-PT-022", "Control Arm", 1, "EA"),
    ("DMS-PT-023", "Tie Rod End", 1, "EA"),
    ("DMS-PT-024", "Power Steering Pump", 1, "EA"),
    ("DMS-PT-025", "Timing Belt Kit", 1, "KT"),
    ("DMS-PT-026", "Timing Chain Kit", 1, "KT"),
    ("DMS-PT-027", "Fuel Pump", 1, "EA"),
    ("DMS-PT-028", "Alternator", 1, "EA"),
    ("DMS-PT-029", "Starter Motor", 1, "EA"),
    ("DMS-PT-030", "A/C Compressor", 1, "EA"),
    ("DMS-PT-031", "Wiper Blade", 2, "EA"),
    ("DMS-PT-032", "Cabin Air Filter", 1, "EA"),
    ("DMS-PT-033", "Automatic Transmission Filter", 1, "KT"),
    ("DMS-PT-034", "Differential Seal", 1, "EA"),
    ("DMS-PT-035", "CV Axle Shaft", 1, "EA"),
    ("DMS-PT-036", "Headlamp Assembly", 1, "EA"),
    ("DMS-PT-037", "Engine Thermostat", 1, "EA"),
    ("DMS-PT-038", "Water Pump", 1, "EA"),
    ("DMS-PT-039", "Radiator", 1, "EA"),
    ("DMS-PT-040", "EVAP Purge Solenoid Valve", 1, "EA"),
    ("DMS-PT-041", "EVAP Vent Solenoid Valve", 1, "EA"),
    ("DMS-PT-042", "PCV Valve", 1, "EA"),
    ("DMS-PT-043", "Fuel Pressure Regulator", 1, "EA"),
    ("DMS-PT-044", "Idle Air Control Valve", 1, "EA"),
    ("DMS-PT-045", "Knock Sensor", 1, "EA"),
    ("DMS-PT-046", "Camshaft Position Sensor", 1, "EA"),
    ("DMS-PT-047", "Crankshaft Position Sensor", 1, "EA"),
    ("DMS-PT-048", "Variable Intake Manifold Solenoid", 1, "EA"),
    ("DMS-PT-049", "Secondary Air Injection Pump", 1, "EA"),
    ("DMS-PT-050", "Powertrain Control Module", 1, "EA"),
    ("DMS-PT-051", "Transmission Control Module", 1, "EA"),
    ("DMS-PT-052", "ABS Control Module", 1, "EA"),
    ("DMS-PT-053", "SRS Airbag Module", 1, "EA"),
    ("DMS-PT-054", "Body Control Module", 1, "EA"),
    ("DMS-PT-055", "CAN Gateway Module", 1, "EA"),
    ("DMS-PT-056", "Wheel Hub Bearing Assembly", 1, "EA"),
    ("DMS-PT-057", "Sway Bar Link", 1, "EA"),
    ("DMS-PT-058", "Door Lock Actuator", 1, "EA"),
    ("DMS-PT-059", "EVAP Charcoal Canister", 1, "EA"),
    ("DMS-PT-060", "Accelerator Pedal Position Sensor", 1, "EA"),
    ("DMS-PT-061", "Brake Booster", 1, "EA"),
    ("DMS-PT-062", "Brake Master Cylinder", 1, "EA"),
    ("DMS-PT-063", "Wheel Cylinder", 2, "EA"),
    ("DMS-PT-064", "Brake Hose", 1, "EA"),
    ("DMS-PT-065", "Brake Caliper", 1, "EA"),
    ("DMS-PT-066", "Power Window Motor", 1, "EA"),
    ("DMS-PT-067", "HVAC Blower Motor", 1, "EA"),
    ("DMS-PT-068", "Transmission Shift Solenoid", 1, "KT"),
    ("DMS-PT-069", "Oil Pressure Switch", 1, "EA"),
    ("DMS-PT-070", "Engine Oil Cooler", 1, "EA"),
    ("DMS-PT-071", "Intake Manifold", 1, "EA"),
    ("DMS-PT-072", "Exhaust Manifold", 1, "EA"),
    ("DMS-PT-073", "Oil Pan", 1, "EA"),
    ("DMS-PT-074", "Valve Cover Gasket", 1, "KT"),
    ("DMS-PT-075", "Head Gasket", 1, "EA"),
    ("DMS-PT-076", "Piston Ring Set", 4, "KT"),
    ("DMS-PT-077", "Crankshaft Main Bearing Set", 1, "KT"),
    ("DMS-PT-078", "Connecting Rod Bearing Set", 1, "KT"),
    ("DMS-PT-079", "Transmission Mount", 1, "EA"),
    ("DMS-PT-080", "Engine Mount", 1, "EA"),
]

# Part SKU suffixes generate variation within each terminology category.
# Combined with the 80 terminologies, this yields >= 500 unique SKUs.
_SKU_VARIANTS: list[tuple[str, str, str]] = [
    # (suffix, description_qualifier, attribute_note)
    ("STD", "Standard replacement. OE-equivalent specification.", "Standard"),
    ("PRO", "Heavy-duty professional grade. Extended service life.", "Heavy-Duty"),
    ("OEM", "OE-matched specification. Sourced from original equipment supplier.", "OE-Match"),
    ("ECO", "Economy grade. Short-interval replacement or lower-demand applications.", "Economy"),
    ("XL", "Extended-length or oversize application variant.", "Extended"),
    ("SM", "Compact or short-dimension application variant.", "Compact"),
]

# Attributes used across SKU variants — DMS-PA-* namespace
_ATTR_GRADE = "DMS-PA-100"
_ATTR_VARIANT = "DMS-PA-101"

# Hazard codes assigned to specific terminology IDs
_HAZMAT: dict[str, str] = {
    "DMS-PT-027": "FL",   # fuel pump
    "DMS-PT-043": "FL",   # fuel pressure regulator
    "DMS-PT-053": "EX",   # airbag module
}


def _make_part(
    term_id: str,
    term_name: str,
    qty: int,
    uom: str,
    suffix: str,
    desc_qual: str,
    attr_note: str,
    idx: int,
) -> dict[str, Any]:
    """Build a single parts_catalog record conforming to pies_8_0_shape.json."""
    part_number = f"DMS-P{idx:04d}-{suffix}"
    description = f"{term_name}. {desc_qual}"

    # Supersession pointer for PRO variant: points at STD of same terminology
    superseded = None
    if suffix == "PRO" and term_id in _HAZMAT:
        pass  # no auto-supersession for hazmat parts
    elif suffix == "XL":
        # XL supersedes the STD variant  (same term, idx-1)
        std_idx = idx - 4  # STD is 4 variants back in ordering
        if std_idx > 0:
            superseded = f"DMS-P{std_idx:04d}-STD"

    return {
        "brand_aaia_id": BRAND_ID,
        "part_number": part_number,
        "part_terminology_id": term_id,
        "part_terminology_name": term_name,
        "description": description,
        "quantity_per_application": qty,
        "upc": None,
        "hazardous_material_code": _HAZMAT.get(term_id),
        "country_of_origin": "US",
        "package_unit_of_measure": uom,
        "package_quantity": 1,
        "package_weight": round(0.1 + idx * 0.01, 2),
        "package_height": 5.0,
        "package_width": 10.0,
        "package_length": 15.0,
        "superseded_part_number": superseded,
        "extended_attributes": [
            {
                "attribute_id": _ATTR_GRADE,
                "attribute_name": "Grade",
                "attribute_value": attr_note,
                "uom": None,
            },
            {
                "attribute_id": _ATTR_VARIANT,
                "attribute_name": "Variant",
                "attribute_value": suffix,
                "uom": None,
            },
        ],
        "digital_assets": None,
        "access_channel": ACCESS_CHANNEL,
        "tenant_id": TENANT_ID,
    }


def generate_catalog() -> list[dict[str, Any]]:
    """Generate ~500 parts catalog records across ~80 terminology categories."""
    records: list[dict[str, Any]] = []
    # We generate len(_TERMINOLOGY) * len(_SKU_VARIANTS) = 80 * 6 = 480 records
    # plus 20 extra single-SKU parts from the first 20 terminologies = 500 total
    idx = 1
    for term_id, term_name, qty, uom in _TERMINOLOGY:
        for suffix, desc_qual, attr_note in _SKU_VARIANTS:
            records.append(
                _make_part(term_id, term_name, qty, uom, suffix, desc_qual, attr_note, idx)
            )
            idx += 1

    # Add 20 additional "-PREMIUM" variants from the first 20 terminologies
    # to push total >= 500
    for term_id, term_name, qty, uom in _TERMINOLOGY[:20]:
        records.append(
            _make_part(
                term_id,
                term_name,
                qty,
                uom,
                "PREMIUM",
                "Premium specification. Advanced materials and tighter tolerances.",
                "Premium",
                idx,
            )
        )
        idx += 1

    return records


def _load_existing(fixture_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Load existing catalog records keyed by (brand_aaia_id, part_number) PK."""
    if not fixture_path.exists():
        return {}
    try:
        data: list[dict[str, Any]] = json.loads(fixture_path.read_text())
    except (json.JSONDecodeError, ValueError):
        return {}
    return {(r["brand_aaia_id"], r["part_number"]): r for r in data}


def seed(
    dry_run: bool = False,
    fixture_dir: Path | None = None,
    verbose: bool = False,
) -> int:
    """Seed parts_catalog.  Returns net write count (0 on second run).

    This is the callable entry-point used by idempotency tests.
    """
    base_dir = (
        fixture_dir
        if fixture_dir is not None
        else Path(__file__).parent / "parts_seed_fixtures"
    )
    fixture_path = base_dir / "parts_catalog.json"

    records = generate_catalog()
    existing = _load_existing(fixture_path)

    new_records: list[dict[str, Any]] = []
    for rec in records:
        pk = (rec["brand_aaia_id"], rec["part_number"])
        if pk not in existing:
            new_records.append(rec)

    if dry_run:
        for rec in records:
            print(json.dumps(rec))
        if verbose:
            print(
                f"# dry-run: {len(records)} records total, "
                f"{len(new_records)} net new, "
                f"{len(existing)} already present",
                file=sys.stderr,
            )
        return len(new_records)

    if new_records:
        # Merge: existing (preserving order) + new
        all_records = list(existing.values()) + new_records
        base_dir.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(
            json.dumps(all_records, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if verbose:
        print(
            f"# seed: {len(records)} records total, "
            f"{len(new_records)} written, "
            f"{len(existing)} already present",
            file=sys.stderr,
        )

    return len(new_records)  # 0 on second run — idempotency contract


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed adp_parts_domain / parts_catalog (PIES 8.0 shaped)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print records to stdout without writing to the fixture store.",
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=None,
        help="Override fixture directory (default: scripts/parts_seed_fixtures/).",
    )
    parser.add_argument("--verbose", action="store_true", help="Print summary counts.")
    args = parser.parse_args()

    net_writes = seed(
        dry_run=args.dry_run,
        fixture_dir=args.fixture_dir,
        verbose=args.verbose,
    )
    if not args.dry_run and args.verbose:
        print(f"Net writes: {net_writes}")


if __name__ == "__main__":
    main()
