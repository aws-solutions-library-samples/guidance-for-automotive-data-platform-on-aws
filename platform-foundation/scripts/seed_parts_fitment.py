#!/usr/bin/env python3
"""seed_parts_fitment.py — Seed adp_parts_domain / parts_fitment product.

Target: ~1,200 fitment records across the twelve DMS-brand vehicle configurations.

LICENSING INVARIANT (Auto Care Technology License Agreement, rev. 2025-02-28):
  VCdb, PCdb, Qdb, PAdb and the Brand Table are subscription-based licensed
  property.  All vehicle_config_id values use the DMS-VCFG-* synthetic namespace;
  no VCdb VehicleID or VehicleConfigurationID is referenced.  All qualifier_id
  values use the DMS-QT-* namespace; no Qdb QualifierID is referenced.

Per ADP spec Decision 3: access_channel='franchise' ONLY in v1.

IDEMPOTENCY CONTRACT: PK = (part_number, vehicle_config_id, position_id, qualifier_hash).
A second run produces zero net writes.

Usage:
  python3 seed_parts_fitment.py [--dry-run] [--fixture-dir PATH] [--verbose]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ACCESS_CHANNEL = "franchise"
BRAND_ID = "DMS-BR-001"
TENANT_ID = "dms-reference"


# ---------------------------------------------------------------------------
# Twelve DMS-brand vehicle configurations (DMS-VCFG-* namespace)
# (year, make, model, submodel, engine_base_id, vcfg_id)
# make/model use the invented portfolio brand — never a real vehicle marque.
# ---------------------------------------------------------------------------
_VEHICLE_CONFIGS: list[dict[str, Any]] = [
    {"vehicle_config_id": "DMS-VCFG-0001", "vehicle_year": 2022, "vehicle_make": "Meridian",
     "vehicle_model": "Apex", "vehicle_submodel": "Sedan", "engine_base_id": "DMS-ENG-001"},
    {"vehicle_config_id": "DMS-VCFG-0002", "vehicle_year": 2022, "vehicle_make": "Meridian",
     "vehicle_model": "Apex", "vehicle_submodel": "Coupe", "engine_base_id": "DMS-ENG-001"},
    {"vehicle_config_id": "DMS-VCFG-0003", "vehicle_year": 2023, "vehicle_make": "Meridian",
     "vehicle_model": "Apex", "vehicle_submodel": "Sedan", "engine_base_id": "DMS-ENG-002"},
    {"vehicle_config_id": "DMS-VCFG-0004", "vehicle_year": 2021, "vehicle_make": "Meridian",
     "vehicle_model": "Traverse", "vehicle_submodel": "SUV", "engine_base_id": "DMS-ENG-003"},
    {"vehicle_config_id": "DMS-VCFG-0005", "vehicle_year": 2022, "vehicle_make": "Meridian",
     "vehicle_model": "Traverse", "vehicle_submodel": "SUV", "engine_base_id": "DMS-ENG-003"},
    {"vehicle_config_id": "DMS-VCFG-0006", "vehicle_year": 2023, "vehicle_make": "Meridian",
     "vehicle_model": "Traverse", "vehicle_submodel": "SUV AWD", "engine_base_id": "DMS-ENG-004"},
    {"vehicle_config_id": "DMS-VCFG-0007", "vehicle_year": 2021, "vehicle_make": "Meridian",
     "vehicle_model": "Valor", "vehicle_submodel": "Pickup 4x2", "engine_base_id": "DMS-ENG-005"},
    {"vehicle_config_id": "DMS-VCFG-0008", "vehicle_year": 2022, "vehicle_make": "Meridian",
     "vehicle_model": "Valor", "vehicle_submodel": "Pickup 4x4", "engine_base_id": "DMS-ENG-005"},
    {"vehicle_config_id": "DMS-VCFG-0009", "vehicle_year": 2023, "vehicle_make": "Meridian",
     "vehicle_model": "Valor", "vehicle_submodel": "Pickup 4x4 HD", "engine_base_id": "DMS-ENG-006"},
    {"vehicle_config_id": "DMS-VCFG-0010", "vehicle_year": 2022, "vehicle_make": "Meridian",
     "vehicle_model": "Zephyr", "vehicle_submodel": "Electric Sedan", "engine_base_id": "DMS-ENG-007"},
    {"vehicle_config_id": "DMS-VCFG-0011", "vehicle_year": 2023, "vehicle_make": "Meridian",
     "vehicle_model": "Zephyr", "vehicle_submodel": "Electric SUV", "engine_base_id": "DMS-ENG-007"},
    {"vehicle_config_id": "DMS-VCFG-0012", "vehicle_year": 2021, "vehicle_make": "Meridian",
     "vehicle_model": "Pinnacle", "vehicle_submodel": "Luxury Sedan", "engine_base_id": "DMS-ENG-008"},
]

# Positions for fitment records
_POSITIONS: list[str] = [
    "Front", "Rear", "Left Front", "Right Front", "Left Rear", "Right Rear",
    "Upper", "Lower", "Upstream", "Downstream", "Bank 1", "Bank 2",
    "All", "Center", "Inner", "Outer",
]

# Qualifiers: (qualifier_id, qualifier_text)
_QUALIFIERS: list[tuple[str, str]] = [
    ("DMS-QT-001", "with Turbo"),
    ("DMS-QT-002", "without Turbo"),
    ("DMS-QT-003", "FWD only"),
    ("DMS-QT-004", "AWD only"),
    ("DMS-QT-005", "Automatic Transmission"),
    ("DMS-QT-006", "Manual Transmission"),
    ("DMS-QT-007", "with Sport Package"),
    ("DMS-QT-008", "with Tow Package"),
    ("DMS-QT-009", "DOHC"),
    ("DMS-QT-010", "SOHC"),
    ("DMS-QT-011", "Gasoline Engine"),
    ("DMS-QT-012", "Diesel Engine"),
    ("DMS-QT-013", "High Altitude"),
    ("DMS-QT-014", "Standard Output"),
    ("DMS-QT-015", "High Output"),
    ("DMS-QT-016", "without TPMS"),
    ("DMS-QT-017", "with TPMS"),
    ("DMS-QT-018", "Base Trim"),
    ("DMS-QT-019", "Sport Trim"),
    ("DMS-QT-020", "Luxury Trim"),
]


def _qualifier_hash(qualifiers: list[tuple[str, str]]) -> str:
    """Compute SHA-256 over sorted qualifier text values.

    Empty qualifier set hashes to SHA-256 of empty string per schema description.
    """
    texts = sorted(q[1] for q in qualifiers)
    payload = "\n".join(texts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# Terminology IDs relevant for fitment (must be a subset of seed_parts_catalog.py)
# 103 entries × 12 vehicle configs = 1236 records (before PK de-dup) > 1200
_FITMENT_TERMINOLOGIES: list[tuple[str, str, str]] = [
    # (part_terminology_id, part_number_template, position)
    ("DMS-PT-001", "DMS-P0001-STD", "All"),
    ("DMS-PT-001", "DMS-P0002-PRO", "All"),
    ("DMS-PT-002", "DMS-P0007-STD", "All"),
    ("DMS-PT-002", "DMS-P0008-PRO", "All"),
    ("DMS-PT-003", "DMS-P0013-STD", "Front"),
    ("DMS-PT-003", "DMS-P0014-PRO", "Rear"),
    ("DMS-PT-003", "DMS-P0015-OEM", "Left Front"),
    ("DMS-PT-003", "DMS-P0016-OEM", "Right Front"),
    ("DMS-PT-004", "DMS-P0019-STD", "Left Front"),
    ("DMS-PT-004", "DMS-P0020-PRO", "Right Front"),
    ("DMS-PT-004", "DMS-P0019-OEM", "Left Rear"),
    ("DMS-PT-004", "DMS-P0020-OEM", "Right Rear"),
    ("DMS-PT-005", "DMS-P0025-STD", "All"),
    ("DMS-PT-005", "DMS-P0026-PRO", "All"),
    ("DMS-PT-006", "DMS-P0031-STD", "Upstream"),
    ("DMS-PT-006", "DMS-P0032-PRO", "Downstream"),
    ("DMS-PT-006", "DMS-P0033-OEM", "Bank 1"),
    ("DMS-PT-006", "DMS-P0034-OEM", "Bank 2"),
    ("DMS-PT-007", "DMS-P0037-STD", "All"),
    ("DMS-PT-007", "DMS-P0038-PRO", "All"),
    ("DMS-PT-008", "DMS-P0043-STD", "All"),
    ("DMS-PT-008", "DMS-P0044-PRO", "All"),
    ("DMS-PT-009", "DMS-P0049-STD", "All"),
    ("DMS-PT-009", "DMS-P0050-PRO", "All"),
    ("DMS-PT-010", "DMS-P0055-STD", "All"),
    ("DMS-PT-010", "DMS-P0056-PRO", "All"),
    ("DMS-PT-011", "DMS-P0061-STD", "Left Front"),
    ("DMS-PT-011", "DMS-P0062-PRO", "Right Front"),
    ("DMS-PT-011", "DMS-P0061-OEM", "Left Rear"),
    ("DMS-PT-011", "DMS-P0062-OEM", "Right Rear"),
    ("DMS-PT-012", "DMS-P0067-STD", "All"),
    ("DMS-PT-013", "DMS-P0073-STD", "All"),
    ("DMS-PT-014", "DMS-P0079-STD", "All"),
    ("DMS-PT-015", "DMS-P0085-STD", "All"),
    ("DMS-PT-016", "DMS-P0091-STD", "All"),
    ("DMS-PT-017", "DMS-P0097-STD", "All"),
    ("DMS-PT-017", "DMS-P0098-PRO", "All"),
    ("DMS-PT-018", "DMS-P0103-STD", "All"),
    ("DMS-PT-019", "DMS-P0109-STD", "All"),
    ("DMS-PT-020", "DMS-P0115-STD", "Left Front"),
    ("DMS-PT-020", "DMS-P0116-PRO", "Right Front"),
    ("DMS-PT-020", "DMS-P0117-OEM", "Left Front"),
    ("DMS-PT-020", "DMS-P0118-OEM", "Right Front"),
    ("DMS-PT-021", "DMS-P0121-STD", "Left Rear"),
    ("DMS-PT-021", "DMS-P0122-PRO", "Right Rear"),
    ("DMS-PT-022", "DMS-P0127-STD", "Left Front"),
    ("DMS-PT-022", "DMS-P0128-PRO", "Right Front"),
    ("DMS-PT-022", "DMS-P0127-OEM", "Left Rear"),
    ("DMS-PT-022", "DMS-P0128-OEM", "Right Rear"),
    ("DMS-PT-023", "DMS-P0133-STD", "Left Front"),
    ("DMS-PT-023", "DMS-P0134-PRO", "Right Front"),
    ("DMS-PT-024", "DMS-P0139-STD", "All"),
    ("DMS-PT-025", "DMS-P0145-STD", "All"),
    ("DMS-PT-026", "DMS-P0151-STD", "All"),
    ("DMS-PT-027", "DMS-P0157-STD", "All"),
    ("DMS-PT-028", "DMS-P0163-STD", "All"),
    ("DMS-PT-029", "DMS-P0169-STD", "All"),
    ("DMS-PT-030", "DMS-P0175-STD", "All"),
    ("DMS-PT-031", "DMS-P0181-STD", "Front"),
    ("DMS-PT-031", "DMS-P0181-OEM", "Rear"),
    ("DMS-PT-032", "DMS-P0187-STD", "All"),
    ("DMS-PT-033", "DMS-P0193-STD", "All"),
    ("DMS-PT-034", "DMS-P0199-STD", "Rear"),
    ("DMS-PT-035", "DMS-P0205-STD", "Left Front"),
    ("DMS-PT-035", "DMS-P0206-PRO", "Right Front"),
    ("DMS-PT-035", "DMS-P0205-OEM", "Left Rear"),
    ("DMS-PT-035", "DMS-P0206-OEM", "Right Rear"),
    ("DMS-PT-036", "DMS-P0211-STD", "Left Front"),
    ("DMS-PT-036", "DMS-P0212-PRO", "Right Front"),
    ("DMS-PT-037", "DMS-P0217-STD", "All"),
    ("DMS-PT-037", "DMS-P0218-PRO", "All"),
    ("DMS-PT-038", "DMS-P0223-STD", "All"),
    ("DMS-PT-039", "DMS-P0229-STD", "All"),
    ("DMS-PT-040", "DMS-P0235-STD", "All"),
    ("DMS-PT-041", "DMS-P0241-STD", "All"),
    ("DMS-PT-042", "DMS-P0247-STD", "All"),
    ("DMS-PT-043", "DMS-P0253-STD", "All"),
    ("DMS-PT-044", "DMS-P0259-STD", "All"),
    ("DMS-PT-045", "DMS-P0265-STD", "All"),
    ("DMS-PT-046", "DMS-P0271-STD", "All"),
    ("DMS-PT-047", "DMS-P0277-STD", "All"),
    ("DMS-PT-048", "DMS-P0283-STD", "All"),
    ("DMS-PT-049", "DMS-P0289-STD", "All"),
    ("DMS-PT-050", "DMS-P0295-STD", "All"),
    ("DMS-PT-051", "DMS-P0301-STD", "All"),
    ("DMS-PT-052", "DMS-P0307-STD", "All"),
    ("DMS-PT-053", "DMS-P0313-STD", "All"),
    ("DMS-PT-054", "DMS-P0319-STD", "All"),
    ("DMS-PT-055", "DMS-P0325-STD", "All"),
    ("DMS-PT-056", "DMS-P0331-STD", "Left Front"),
    ("DMS-PT-056", "DMS-P0332-PRO", "Right Front"),
    ("DMS-PT-056", "DMS-P0331-OEM", "Left Rear"),
    ("DMS-PT-056", "DMS-P0332-OEM", "Right Rear"),
    ("DMS-PT-057", "DMS-P0337-STD", "Left Front"),
    ("DMS-PT-057", "DMS-P0338-PRO", "Right Front"),
    ("DMS-PT-057", "DMS-P0337-OEM", "Left Rear"),
    ("DMS-PT-057", "DMS-P0338-OEM", "Right Rear"),
    ("DMS-PT-058", "DMS-P0343-STD", "Left Front"),
    ("DMS-PT-058", "DMS-P0344-PRO", "Right Front"),
    ("DMS-PT-059", "DMS-P0349-STD", "All"),
    ("DMS-PT-060", "DMS-P0355-STD", "All"),
    ("DMS-PT-061", "DMS-P0361-STD", "All"),
    ("DMS-PT-062", "DMS-P0367-STD", "All"),
    ("DMS-PT-063", "DMS-P0373-STD", "Left Rear"),
    ("DMS-PT-063", "DMS-P0374-PRO", "Right Rear"),
    ("DMS-PT-064", "DMS-P0379-STD", "Left Front"),
    ("DMS-PT-064", "DMS-P0380-PRO", "Right Front"),
    ("DMS-PT-065", "DMS-P0385-STD", "Left Front"),
    ("DMS-PT-065", "DMS-P0386-PRO", "Right Front"),
    ("DMS-PT-065", "DMS-P0385-OEM", "Left Rear"),
    ("DMS-PT-065", "DMS-P0386-OEM", "Right Rear"),
    ("DMS-PT-080", "DMS-P0475-STD", "Left Front"),
    ("DMS-PT-080", "DMS-P0476-PRO", "Right Rear"),
]

# Qualifier sets for each vehicle config variant
_CONFIG_QUALIFIER_MAP: dict[str, list[tuple[str, str]]] = {
    "DMS-VCFG-0001": [("DMS-QT-002", "without Turbo"), ("DMS-QT-003", "FWD only"), ("DMS-QT-005", "Automatic Transmission")],
    "DMS-VCFG-0002": [("DMS-QT-001", "with Turbo"), ("DMS-QT-003", "FWD only"), ("DMS-QT-006", "Manual Transmission")],
    "DMS-VCFG-0003": [("DMS-QT-001", "with Turbo"), ("DMS-QT-003", "FWD only"), ("DMS-QT-005", "Automatic Transmission")],
    "DMS-VCFG-0004": [("DMS-QT-002", "without Turbo"), ("DMS-QT-003", "FWD only"), ("DMS-QT-005", "Automatic Transmission")],
    "DMS-VCFG-0005": [("DMS-QT-001", "with Turbo"), ("DMS-QT-003", "FWD only"), ("DMS-QT-005", "Automatic Transmission")],
    "DMS-VCFG-0006": [("DMS-QT-001", "with Turbo"), ("DMS-QT-004", "AWD only"), ("DMS-QT-005", "Automatic Transmission")],
    "DMS-VCFG-0007": [("DMS-QT-002", "without Turbo"), ("DMS-QT-003", "FWD only"), ("DMS-QT-006", "Manual Transmission")],
    "DMS-VCFG-0008": [("DMS-QT-001", "with Turbo"), ("DMS-QT-004", "AWD only"), ("DMS-QT-005", "Automatic Transmission"), ("DMS-QT-008", "with Tow Package")],
    "DMS-VCFG-0009": [("DMS-QT-001", "with Turbo"), ("DMS-QT-004", "AWD only"), ("DMS-QT-005", "Automatic Transmission"), ("DMS-QT-008", "with Tow Package"), ("DMS-QT-015", "High Output")],
    "DMS-VCFG-0010": [],  # Electric — no combustion qualifiers
    "DMS-VCFG-0011": [("DMS-QT-004", "AWD only")],
    "DMS-VCFG-0012": [("DMS-QT-001", "with Turbo"), ("DMS-QT-004", "AWD only"), ("DMS-QT-005", "Automatic Transmission"), ("DMS-QT-020", "Luxury Trim")],
}


def generate_fitment() -> list[dict[str, Any]]:
    """Generate ~1,200 fitment records across 12 vehicle configurations."""
    records: list[dict[str, Any]] = []
    seen_pks: set[tuple[str, str, str, str]] = set()

    # Enumerate vehicle configs × fitment terminologies/positions
    for vcfg in _VEHICLE_CONFIGS:
        vcfg_id = vcfg["vehicle_config_id"]
        qualifiers = _CONFIG_QUALIFIER_MAP.get(vcfg_id, [])
        q_hash = _qualifier_hash(qualifiers)

        for term_id, part_number, position in _FITMENT_TERMINOLOGIES:
            pk = (part_number, vcfg_id, position, q_hash)
            if pk in seen_pks:
                continue
            seen_pks.add(pk)

            record: dict[str, Any] = {
                "part_number": part_number,
                "brand_aaia_id": BRAND_ID,
                "vehicle_config_id": vcfg_id,
                "vehicle_year": vcfg["vehicle_year"],
                "vehicle_make": vcfg["vehicle_make"],
                "vehicle_model": vcfg["vehicle_model"],
                "vehicle_submodel": vcfg["vehicle_submodel"],
                "engine_base_id": vcfg["engine_base_id"],
                "position_id": position,
                "qualifier_hash": q_hash,
                "qualifiers": [
                    {"qualifier_id": qid, "qualifier_text": qtxt}
                    for qid, qtxt in qualifiers
                ] if qualifiers else None,
                "quantity": 1,
                "notes": None,
                "part_type_id": term_id,
                "mfr_label": None,
                "action": "A",
                "access_channel": ACCESS_CHANNEL,
                "tenant_id": TENANT_ID,
            }
            records.append(record)

    return records


def _load_existing_fitment(fixture_path: Path) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    """Load existing fitment records keyed by composite PK."""
    if not fixture_path.exists():
        return {}
    try:
        data: list[dict[str, Any]] = json.loads(fixture_path.read_text())
    except (json.JSONDecodeError, ValueError):
        return {}
    return {
        (r["part_number"], r["vehicle_config_id"], r["position_id"], r["qualifier_hash"]): r
        for r in data
    }


def seed(
    dry_run: bool = False,
    fixture_dir: Path | None = None,
    verbose: bool = False,
) -> int:
    """Seed parts_fitment.  Returns net write count (0 on second run)."""
    base_dir = (
        fixture_dir
        if fixture_dir is not None
        else Path(__file__).parent / "parts_seed_fixtures"
    )
    fixture_path = base_dir / "parts_fitment.json"

    records = generate_fitment()
    existing = _load_existing_fitment(fixture_path)

    new_records: list[dict[str, Any]] = []
    for rec in records:
        pk = (rec["part_number"], rec["vehicle_config_id"], rec["position_id"], rec["qualifier_hash"])
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

    return len(new_records)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed adp_parts_domain / parts_fitment (ACES 5.0 shaped)."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fixture-dir", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
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
