#!/usr/bin/env python3
"""seed_parts_interchange.py — Seed adp_parts_domain / parts_interchange product.

Target: ~200 interchange records exhibiting all three relationship types:
  1. supersession  — part A superseded by part B
  2. oe_cross      — OE part number cross-reference
  3. aftermarket_equivalent — aftermarket alternative

Required structural invariants (per T3.6):
  a) At least one 3-deep supersession chain:
     DMS-P0001-STD  →  DMS-P0001-PRO  →  DMS-P0001-PREMIUM
     (superseded → supersedes → supersedes)

  b) At least one 1-primary-to-N fanout:
     DMS-P0003-STD  →  {DMS-P0003-PRO, DMS-P0003-OEM, DMS-P0003-ECO}
     (same primary_part_number, multiple replacement_part_numbers)

  c) At least one OE cross-reference and aftermarket equivalent
     per warranty-relevant DTC family:
       P0420 — catalytic converter / oxygen sensor (DMS-PT-007, DMS-PT-006)
       P0300 — ignition coil / crankshaft sensor (DMS-PT-008, DMS-PT-047)
       C0035 — ABS wheel speed sensor / ABS module (DMS-PT-011, DMS-PT-052)
       U0100 — CAN module / gateway module (DMS-PT-012, DMS-PT-055)
       P0171 — fuel injector / MAF sensor (DMS-PT-009, DMS-PT-010)
       B0001 — clock spring / airbag module (DMS-PT-013, DMS-PT-053)

LICENSING INVARIANT (Auto Care Technology License Agreement, rev. 2025-02-28):
  All part numbers are in the DMS-* synthetic namespace.  No real Auto Care
  Brand Table BrandAAIAID, PCdb PartTerminologyID, VCdb VehicleID, Qdb QualifierID,
  or PAdb AttributeID is referenced.

Per ADP spec Decision 3: access_channel='franchise' ONLY in v1.

IDEMPOTENCY CONTRACT: PK = (primary_part_number, replacement_part_number).
A second run produces zero net writes.

Usage:
  python3 seed_parts_interchange.py [--dry-run] [--fixture-dir PATH] [--verbose]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ACCESS_CHANNEL = "franchise"
TENANT_ID = "dms-reference"

# Relationship types per the schema
SUPERSESSION = "supersession"
OE_CROSS = "oe_cross"
AFTERMARKET = "aftermarket_equivalent"


def _rec(
    primary: str,
    replacement: str,
    rel_type: str,
    notes: str | None = None,
) -> dict[str, Any]:
    """Build a single interchange record."""
    return {
        "primary_part_number": primary,
        "replacement_part_number": replacement,
        "relationship_type": rel_type,
        "notes": notes,
        "access_channel": ACCESS_CHANNEL,
        "tenant_id": TENANT_ID,
    }


def _generate_interchange() -> list[dict[str, Any]]:
    """Generate ~200 interchange records covering all required structural patterns."""
    records: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # BLOCK A — 3-deep supersession chain (fulfils requirement a)
    #
    # Oil Filter (DMS-PT-001):
    #   DMS-P0001-STD  is superseded by  DMS-P0001-PRO
    #   DMS-P0001-PRO  is superseded by  DMS-P0001-PREMIUM
    # This gives a 3-node chain: STD → PRO → PREMIUM
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0001-STD",     "DMS-P0001-PRO",     SUPERSESSION,
             "Oil filter supersession chain step 1: STD → PRO (capacity upgrade)"),
        _rec("DMS-P0001-PRO",     "DMS-P0001-PREMIUM",  SUPERSESSION,
             "Oil filter supersession chain step 2: PRO → PREMIUM (synthetic media upgrade)"),
    ]

    # Air Filter chain (DMS-PT-002) — additional supersession demonstration
    records += [
        _rec("DMS-P0007-STD",     "DMS-P0007-PRO",     SUPERSESSION,
             "Air filter supersession: STD → PRO (extended service life)"),
        _rec("DMS-P0007-PRO",     "DMS-P0007-PREMIUM",  SUPERSESSION,
             "Air filter supersession: PRO → PREMIUM (OE-matched high-flow)"),
    ]

    # ------------------------------------------------------------------
    # BLOCK B — 1-primary-to-N fanout (fulfils requirement b)
    #
    # Brake Pad Set front (DMS-PT-003, idx=13 STD):
    #   DMS-P0013-STD  →  DMS-P0013-PRO   (ceramic upgrade)
    #   DMS-P0013-STD  →  DMS-P0013-OEM   (OE match)
    #   DMS-P0013-STD  →  DMS-P0013-ECO   (economy budget)
    # Same primary_part_number, three replacement alternatives.
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0013-STD",     "DMS-P0013-PRO",     SUPERSESSION,
             "Brake pad fanout 1: STD → PRO (ceramic premium formulation)"),
        _rec("DMS-P0013-STD",     "DMS-P0013-OEM",     OE_CROSS,
             "Brake pad fanout 2: STD → OEM (original equipment cross-reference)"),
        _rec("DMS-P0013-STD",     "DMS-P0013-ECO",     AFTERMARKET,
             "Brake pad fanout 3: STD → ECO (economy aftermarket alternative)"),
    ]

    # ------------------------------------------------------------------
    # BLOCK C — DTC P0420 (Catalyst System Efficiency Below Threshold)
    # Parts: Catalytic converter (DMS-PT-007), Oxygen sensor upstream (DMS-PT-006)
    # DMS-PT-007: term_index=6 (0-based), STD idx=6*6+1=37, PRO=38, OEM=39
    # DMS-PT-006: term_index=5 (0-based), STD idx=5*6+1=31, PRO=32
    # ------------------------------------------------------------------
    records += [
        # OE cross-reference: catalytic converter
        _rec("DMS-P0037-STD",     "DMS-P0037-OEM",     OE_CROSS,
             "P0420: Catalytic converter OE cross-reference (DMS-PT-007)"),
        # Aftermarket equivalent: catalytic converter
        _rec("DMS-P0037-STD",     "DMS-P0037-ECO",     AFTERMARKET,
             "P0420: Catalytic converter aftermarket alternative (DMS-PT-007)"),
        # OE cross-reference: upstream O2 sensor
        _rec("DMS-P0031-STD",     "DMS-P0031-OEM",     OE_CROSS,
             "P0420: Oxygen sensor upstream OE cross-reference (DMS-PT-006)"),
        # Aftermarket equivalent: upstream O2 sensor
        _rec("DMS-P0031-STD",     "DMS-P0031-ECO",     AFTERMARKET,
             "P0420: Oxygen sensor upstream aftermarket alternative (DMS-PT-006)"),
        # Supersession: old O2 sensor → new wideband type
        _rec("DMS-P0031-XL",      "DMS-P0031-STD",     SUPERSESSION,
             "P0420: Oxygen sensor supersession — narrow-band → wideband type"),
    ]

    # ------------------------------------------------------------------
    # BLOCK D — DTC P0300 (Random/Multiple Cylinder Misfire)
    # Parts: Ignition coil (DMS-PT-008), Crankshaft position sensor (DMS-PT-047)
    # DMS-PT-008: term_index=7 (0-based), STD idx=7*6+1=43, PRO=44, OEM=45
    # DMS-PT-047: term_index=46 (0-based), STD idx=46*6+1=277, PRO=278, OEM=279
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0043-STD",     "DMS-P0043-OEM",     OE_CROSS,
             "P0300: Ignition coil OE cross-reference (DMS-PT-008)"),
        _rec("DMS-P0043-STD",     "DMS-P0043-ECO",     AFTERMARKET,
             "P0300: Ignition coil aftermarket alternative (DMS-PT-008)"),
        _rec("DMS-P0043-PRO",     "DMS-P0043-OEM",     OE_CROSS,
             "P0300: High-performance ignition coil OE cross-reference"),
        _rec("DMS-P0277-STD",     "DMS-P0277-OEM",     OE_CROSS,
             "P0300: Crankshaft position sensor OE cross-reference (DMS-PT-047)"),
        _rec("DMS-P0277-STD",     "DMS-P0277-ECO",     AFTERMARKET,
             "P0300: Crankshaft position sensor aftermarket alternative (DMS-PT-047)"),
        # Supersession within ignition coil
        _rec("DMS-P0043-XL",      "DMS-P0043-STD",     SUPERSESSION,
             "P0300: Ignition coil supersession — legacy single-spark → dual-spark"),
    ]

    # ------------------------------------------------------------------
    # BLOCK E — DTC C0035 (Left Front Wheel Speed Circuit Malfunction)
    # Parts: ABS wheel speed sensor (DMS-PT-011), ABS control module (DMS-PT-052)
    # DMS-PT-011: term_index=10, STD idx=10*6+1=61, PRO=62, OEM=63
    # DMS-PT-052: term_index=51, STD idx=51*6+1=307, PRO=308
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0061-STD",     "DMS-P0061-OEM",     OE_CROSS,
             "C0035: ABS wheel speed sensor OE cross-reference (DMS-PT-011)"),
        _rec("DMS-P0061-STD",     "DMS-P0061-ECO",     AFTERMARKET,
             "C0035: ABS wheel speed sensor aftermarket alternative (DMS-PT-011)"),
        _rec("DMS-P0307-STD",     "DMS-P0307-OEM",     OE_CROSS,
             "C0035: ABS control module OE cross-reference (DMS-PT-052)"),
        _rec("DMS-P0307-STD",     "DMS-P0307-PRO",     AFTERMARKET,
             "C0035: ABS control module remanufactured aftermarket alternative"),
        # Supersession for ABS sensor — passive → active type
        _rec("DMS-P0061-XL",      "DMS-P0061-STD",     SUPERSESSION,
             "C0035: ABS sensor supersession — passive reluctor → active Hall-effect"),
    ]

    # ------------------------------------------------------------------
    # BLOCK F — DTC U0100 (Lost Communication with ECM/PCM)
    # Parts: CAN bus module (DMS-PT-012), CAN gateway module (DMS-PT-055)
    # DMS-PT-012: term_index=11, STD idx=11*6+1=67, PRO=68, OEM=69
    # DMS-PT-055: term_index=54, STD idx=54*6+1=325, PRO=326, OEM=327
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0067-STD",     "DMS-P0067-OEM",     OE_CROSS,
             "U0100: CAN bus module OE cross-reference (DMS-PT-012)"),
        _rec("DMS-P0067-STD",     "DMS-P0067-ECO",     AFTERMARKET,
             "U0100: CAN bus module aftermarket remanufactured alternative"),
        _rec("DMS-P0325-STD",     "DMS-P0325-OEM",     OE_CROSS,
             "U0100: CAN gateway module OE cross-reference (DMS-PT-055)"),
        _rec("DMS-P0325-STD",     "DMS-P0325-ECO",     AFTERMARKET,
             "U0100: CAN gateway module aftermarket alternative"),
        # Supersession: single-network CAN → multi-network gateway
        _rec("DMS-P0067-XL",      "DMS-P0325-STD",     SUPERSESSION,
             "U0100: CAN module superseded by multi-network gateway (protocol upgrade)"),
    ]

    # ------------------------------------------------------------------
    # BLOCK G — DTC P0171 (System Too Lean — Bank 1)
    # Parts: Fuel injector (DMS-PT-009), MAF sensor (DMS-PT-010)
    # DMS-PT-009: term_index=8, STD idx=8*6+1=49, PRO=50, OEM=51
    # DMS-PT-010: term_index=9, STD idx=9*6+1=55, PRO=56, OEM=57
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0049-STD",     "DMS-P0049-OEM",     OE_CROSS,
             "P0171: Fuel injector OE cross-reference (DMS-PT-009)"),
        _rec("DMS-P0049-STD",     "DMS-P0049-ECO",     AFTERMARKET,
             "P0171: Fuel injector remanufactured aftermarket alternative"),
        _rec("DMS-P0049-PRO",     "DMS-P0049-OEM",     OE_CROSS,
             "P0171: High-flow fuel injector OE cross-reference"),
        _rec("DMS-P0055-STD",     "DMS-P0055-OEM",     OE_CROSS,
             "P0171: MAF sensor OE cross-reference (DMS-PT-010)"),
        _rec("DMS-P0055-STD",     "DMS-P0055-ECO",     AFTERMARKET,
             "P0171: MAF sensor aftermarket alternative"),
        # Supersession: hot-film MAF → hot-wire MAF
        _rec("DMS-P0055-XL",      "DMS-P0055-STD",     SUPERSESSION,
             "P0171: MAF sensor supersession — hot-film → hot-wire element"),
    ]

    # ------------------------------------------------------------------
    # BLOCK H — DTC B0001 (Driver Airbag Squib 1 Circuit Open)
    # Parts: SRS clock spring (DMS-PT-013), SRS airbag module (DMS-PT-053)
    # DMS-PT-013: term_index=12, STD idx=12*6+1=73, PRO=74, OEM=75
    # DMS-PT-053: term_index=52, STD idx=52*6+1=313, PRO=314, OEM=315
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0073-STD",     "DMS-P0073-OEM",     OE_CROSS,
             "B0001: SRS clock spring OE cross-reference (DMS-PT-013)"),
        _rec("DMS-P0073-STD",     "DMS-P0073-ECO",     AFTERMARKET,
             "B0001: SRS clock spring aftermarket alternative"),
        _rec("DMS-P0313-STD",     "DMS-P0313-OEM",     OE_CROSS,
             "B0001: Driver airbag module OE cross-reference (DMS-PT-053)"),
        _rec("DMS-P0313-STD",     "DMS-P0313-PRO",     AFTERMARKET,
             "B0001: Driver airbag module remanufactured alternative (Azide-free propellant)"),
        # Supersession: 4-pin clock spring → 6-pin with horn contact
        _rec("DMS-P0073-XL",      "DMS-P0073-STD",     SUPERSESSION,
             "B0001: Clock spring supersession — 4-pin → 6-pin (added cruise + audio)"),
    ]

    # ------------------------------------------------------------------
    # BLOCK I — Brake system (DMS-PT-003 to DMS-PT-004)
    # Additional supersession + cross-references
    # DMS-PT-004 Brake Rotor: term_index=3, STD idx=3*6+1=19, PRO=20, OEM=21
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0019-STD",     "DMS-P0019-OEM",     OE_CROSS,
             "Brake rotor OE cross-reference (DMS-PT-004)"),
        _rec("DMS-P0019-STD",     "DMS-P0019-PRO",     SUPERSESSION,
             "Brake rotor supersession: standard → cross-drilled performance variant"),
        _rec("DMS-P0019-PRO",     "DMS-P0019-PREMIUM",  SUPERSESSION,
             "Brake rotor supersession: cross-drilled → slotted-and-drilled premium"),
        _rec("DMS-P0013-OEM",     "DMS-P0013-PREMIUM",  SUPERSESSION,
             "Brake pad OE matched superseded by premium ceramic formulation"),
    ]

    # ------------------------------------------------------------------
    # BLOCK J — Spark plug (DMS-PT-005)
    # term_index=4, STD idx=4*6+1=25, PRO=26, OEM=27, ECO=28, XL=29
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0025-STD",     "DMS-P0025-OEM",     OE_CROSS,
             "Spark plug OE cross-reference (DMS-PT-005)"),
        _rec("DMS-P0025-STD",     "DMS-P0025-PRO",     SUPERSESSION,
             "Spark plug supersession: copper → iridium extended life"),
        _rec("DMS-P0025-PRO",     "DMS-P0025-PREMIUM",  SUPERSESSION,
             "Spark plug supersession: single iridium → double iridium"),
        _rec("DMS-P0025-STD",     "DMS-P0025-ECO",     AFTERMARKET,
             "Spark plug aftermarket alternative: budget copper tip"),
    ]

    # ------------------------------------------------------------------
    # BLOCK K — Additional supersessions across major parts
    # ------------------------------------------------------------------
    # Strut (DMS-PT-020): term_index=19, STD idx=19*6+1=115
    records += [
        _rec("DMS-P0115-STD",     "DMS-P0115-OEM",     OE_CROSS,
             "Strut assembly OE cross-reference (DMS-PT-020)"),
        _rec("DMS-P0115-STD",     "DMS-P0115-PRO",     SUPERSESSION,
             "Strut assembly supersession: standard → sport-tuned valving"),
        _rec("DMS-P0115-STD",     "DMS-P0115-ECO",     AFTERMARKET,
             "Strut assembly aftermarket economy alternative"),
    ]
    # Control arm (DMS-PT-022): term_index=21, STD idx=21*6+1=127
    records += [
        _rec("DMS-P0127-STD",     "DMS-P0127-OEM",     OE_CROSS,
             "Control arm OE cross-reference (DMS-PT-022)"),
        _rec("DMS-P0127-STD",     "DMS-P0127-PRO",     AFTERMARKET,
             "Control arm heavy-duty aftermarket alternative"),
    ]
    # Fuel pump (DMS-PT-027): term_index=26, STD idx=26*6+1=157
    records += [
        _rec("DMS-P0157-STD",     "DMS-P0157-OEM",     OE_CROSS,
             "Fuel pump assembly OE cross-reference (DMS-PT-027)"),
        _rec("DMS-P0157-STD",     "DMS-P0157-PRO",     SUPERSESSION,
             "Fuel pump supersession: 90 L/h → 120 L/h high-flow"),
        _rec("DMS-P0157-STD",     "DMS-P0157-ECO",     AFTERMARKET,
             "Fuel pump aftermarket alternative"),
    ]
    # Alternator (DMS-PT-028): term_index=27, STD idx=27*6+1=163
    records += [
        _rec("DMS-P0163-STD",     "DMS-P0163-OEM",     OE_CROSS,
             "Alternator OE cross-reference (DMS-PT-028)"),
        _rec("DMS-P0163-STD",     "DMS-P0163-PRO",     SUPERSESSION,
             "Alternator supersession: 120A → 140A (improved electrical load capacity)"),
    ]
    # Thermostat (DMS-PT-037): term_index=36, STD idx=36*6+1=217
    records += [
        _rec("DMS-P0217-STD",     "DMS-P0217-OEM",     OE_CROSS,
             "Thermostat OE cross-reference (DMS-PT-037)"),
        _rec("DMS-P0217-STD",     "DMS-P0217-ECO",     AFTERMARKET,
             "Thermostat aftermarket alternative"),
    ]
    # Water pump (DMS-PT-038): term_index=37, STD idx=37*6+1=223
    records += [
        _rec("DMS-P0223-STD",     "DMS-P0223-OEM",     OE_CROSS,
             "Water pump OE cross-reference (DMS-PT-038)"),
        _rec("DMS-P0223-STD",     "DMS-P0223-PRO",     SUPERSESSION,
             "Water pump supersession: plastic impeller → metal impeller variant"),
    ]
    # Timing belt kit (DMS-PT-025): term_index=24, STD idx=24*6+1=145
    records += [
        _rec("DMS-P0145-STD",     "DMS-P0145-OEM",     OE_CROSS,
             "Timing belt kit OE cross-reference (DMS-PT-025)"),
        _rec("DMS-P0145-STD",     "DMS-P0145-PRO",     SUPERSESSION,
             "Timing belt kit supersession: includes balance shaft belt"),
        _rec("DMS-P0145-STD",     "DMS-P0145-ECO",     AFTERMARKET,
             "Timing belt kit economy alternative"),
    ]

    # ------------------------------------------------------------------
    # BLOCK L — Hub bearing (DMS-PT-056): term_index=55, STD idx=55*6+1=331
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0331-STD",     "DMS-P0331-OEM",     OE_CROSS,
             "Hub bearing assembly OE cross-reference (DMS-PT-056)"),
        _rec("DMS-P0331-STD",     "DMS-P0331-PRO",     SUPERSESSION,
             "Hub bearing supersession: Gen2 → Gen3 integrated ABS ring"),
        _rec("DMS-P0331-STD",     "DMS-P0331-ECO",     AFTERMARKET,
             "Hub bearing aftermarket alternative"),
    ]

    # ------------------------------------------------------------------
    # BLOCK M — PCM/ECM (DMS-PT-050): term_index=49, STD idx=49*6+1=295
    # ------------------------------------------------------------------
    records += [
        _rec("DMS-P0295-STD",     "DMS-P0295-OEM",     OE_CROSS,
             "PCM OE cross-reference (DMS-PT-050)"),
        _rec("DMS-P0295-STD",     "DMS-P0295-PRO",     SUPERSESSION,
             "PCM supersession: updated calibration, revised fuel trim tables"),
    ]

    # ------------------------------------------------------------------
    # BLOCK N — Additional part-to-part OE cross-references and supersessions
    # to reach the ~200 record target.
    # We add more supersession chains, OE-cross, and aftermarket records
    # across the remaining terminology categories.
    # ------------------------------------------------------------------
    extra_parts_for_oe = [
        # (part_STD, part_OEM, part_ECO, part_PRO, description_prefix)
        ("DMS-P0049-SM",  "DMS-P0049-OEM",  "DMS-P0049-ECO",  "DMS-P0049-PRO",  "Fuel injector compact"),
        ("DMS-P0055-SM",  "DMS-P0055-OEM",  "DMS-P0055-ECO",  "DMS-P0055-PRO",  "MAF sensor compact"),
        ("DMS-P0067-PRO", "DMS-P0067-OEM",  "DMS-P0067-ECO",  "DMS-P0067-XL",   "CAN module heavy-duty"),
        ("DMS-P0073-PRO", "DMS-P0073-OEM",  "DMS-P0073-ECO",  "DMS-P0073-XL",   "Clock spring heavy-duty"),
        ("DMS-P0019-OEM", "DMS-P0019-PREMIUM","DMS-P0019-ECO", "DMS-P0019-XL",   "Brake rotor premium"),
        ("DMS-P0127-OEM", "DMS-P0127-PRO",  "DMS-P0127-ECO",  "DMS-P0127-XL",   "Control arm OE"),
        ("DMS-P0157-OEM", "DMS-P0157-PRO",  "DMS-P0157-ECO",  "DMS-P0157-XL",   "Fuel pump OE"),
        ("DMS-P0331-OEM", "DMS-P0331-PRO",  "DMS-P0331-ECO",  "DMS-P0331-XL",   "Hub bearing OE"),
        ("DMS-P0115-OEM", "DMS-P0115-PRO",  "DMS-P0115-ECO",  "DMS-P0115-XL",   "Strut OE"),
        ("DMS-P0277-PRO", "DMS-P0277-OEM",  "DMS-P0277-ECO",  "DMS-P0277-XL",   "Crank sensor heavy-duty"),
        ("DMS-P0295-PRO", "DMS-P0295-OEM",  "DMS-P0295-ECO",  "DMS-P0295-XL",   "PCM heavy-duty"),
        ("DMS-P0043-XL",  "DMS-P0043-OEM",  "DMS-P0043-ECO",  "DMS-P0043-PREMIUM","Ignition coil extended"),
        ("DMS-P0037-PRO", "DMS-P0037-OEM",  "DMS-P0037-ECO",  "DMS-P0037-PREMIUM","Catalytic converter premium"),
        ("DMS-P0031-PRO", "DMS-P0031-OEM",  "DMS-P0031-ECO",  "DMS-P0031-PREMIUM","O2 sensor premium"),
        ("DMS-P0061-PRO", "DMS-P0061-OEM",  "DMS-P0061-ECO",  "DMS-P0061-PREMIUM","ABS sensor premium"),
        ("DMS-P0313-OEM", "DMS-P0313-PRO",  "DMS-P0313-ECO",  "DMS-P0313-PREMIUM","Airbag module OE"),
        ("DMS-P0307-PRO", "DMS-P0307-OEM",  "DMS-P0307-ECO",  "DMS-P0307-PREMIUM","ABS module premium"),
        ("DMS-P0325-PRO", "DMS-P0325-OEM",  "DMS-P0325-ECO",  "DMS-P0325-PREMIUM","Gateway module premium"),
    ]

    for std, oem, eco, pro, prefix in extra_parts_for_oe:
        # Each block adds 2 records: OE cross + aftermarket
        records.append(_rec(std, oem, OE_CROSS, f"{prefix}: OE cross-reference"))
        records.append(_rec(std, eco, AFTERMARKET, f"{prefix}: aftermarket alternative"))
    additional_supersessions = [
        ("DMS-P0007-PREMIUM", "DMS-P0007-OEM",   "Air filter: premium superseded by current OEM spec"),
        ("DMS-P0025-PREMIUM", "DMS-P0025-OEM",   "Spark plug: double-iridium cross with OEM"),
        ("DMS-P0037-PREMIUM", "DMS-P0037-OEM",   "Cat converter: premium ↔ OEM cross-reference"),
        ("DMS-P0031-PREMIUM", "DMS-P0031-OEM",   "O2 sensor: premium ↔ OEM cross-reference"),
        ("DMS-P0043-PREMIUM", "DMS-P0043-OEM",   "Ignition coil: premium ↔ OEM cross-reference"),
        ("DMS-P0061-PREMIUM", "DMS-P0061-OEM",   "ABS sensor: premium ↔ OEM cross-reference"),
        ("DMS-P0073-PREMIUM", "DMS-P0073-OEM",   "Clock spring: premium ↔ OEM"),
        ("DMS-P0145-OEM",     "DMS-P0145-PRO",   "Timing belt kit: OEM ↔ Pro cross-reference"),
        ("DMS-P0163-OEM",     "DMS-P0163-PRO",   "Alternator: OEM ↔ heavy-duty cross"),
        ("DMS-P0217-OEM",     "DMS-P0217-PRO",   "Thermostat: OEM ↔ sport rating"),
        ("DMS-P0223-OEM",     "DMS-P0223-PRO",   "Water pump: OEM ↔ high-flow"),
        ("DMS-P0295-ECO",     "DMS-P0295-OEM",   "PCM: economy cross to OEM spec"),
        ("DMS-P0307-ECO",     "DMS-P0307-OEM",   "ABS module: economy cross to OEM"),
        ("DMS-P0313-ECO",     "DMS-P0313-OEM",   "Airbag module: economy cross to OEM"),
        ("DMS-P0019-ECO",     "DMS-P0019-STD",   "Brake rotor: economy superseded by standard"),
        ("DMS-P0013-ECO",     "DMS-P0013-STD",   "Brake pad: economy superseded by standard ceramic"),
        ("DMS-P0049-ECO",     "DMS-P0049-STD",   "Fuel injector: economy superseded by standard"),
        ("DMS-P0055-ECO",     "DMS-P0055-STD",   "MAF sensor: economy superseded by standard"),
        ("DMS-P0067-ECO",     "DMS-P0067-STD",   "CAN module: economy superseded by standard"),
        ("DMS-P0277-ECO",     "DMS-P0277-STD",   "Crank sensor: economy superseded by standard"),
        ("DMS-P0025-ECO",     "DMS-P0025-STD",   "Spark plug: economy copper superseded by iridium"),
        ("DMS-P0007-ECO",     "DMS-P0007-STD",   "Air filter: economy superseded by standard"),
        ("DMS-P0001-ECO",     "DMS-P0001-STD",   "Oil filter: economy superseded by standard"),
        ("DMS-P0115-ECO",     "DMS-P0115-STD",   "Strut: economy superseded by standard"),
        ("DMS-P0331-ECO",     "DMS-P0331-STD",   "Hub bearing: economy superseded by standard"),
        ("DMS-P0127-ECO",     "DMS-P0127-STD",   "Control arm: economy superseded by standard"),
        ("DMS-P0157-ECO",     "DMS-P0157-STD",   "Fuel pump: economy superseded by standard"),
        ("DMS-P0163-ECO",     "DMS-P0163-STD",   "Alternator: economy superseded by standard"),
        # Additional cross-references to reach 200+ records
        ("DMS-P0079-STD",     "DMS-P0079-OEM",   "TPS: OE cross-reference (DMS-PT-014)"),
        ("DMS-P0079-STD",     "DMS-P0079-ECO",   "TPS: aftermarket alternative"),
        ("DMS-P0085-STD",     "DMS-P0085-OEM",   "MAP sensor: OE cross-reference (DMS-PT-015)"),
        ("DMS-P0085-STD",     "DMS-P0085-ECO",   "MAP sensor: aftermarket alternative"),
        ("DMS-P0091-STD",     "DMS-P0091-OEM",   "Coolant temp sensor: OE cross-reference (DMS-PT-016)"),
        ("DMS-P0091-STD",     "DMS-P0091-ECO",   "Coolant temp sensor: aftermarket alternative"),
        ("DMS-P0097-STD",     "DMS-P0097-OEM",   "VVT solenoid: OE cross-reference (DMS-PT-017)"),
        ("DMS-P0097-STD",     "DMS-P0097-ECO",   "VVT solenoid: aftermarket alternative"),
        ("DMS-P0097-PRO",     "DMS-P0097-STD",   "VVT solenoid: PRO supersedes STD (updated flow rate)"),
        ("DMS-P0103-STD",     "DMS-P0103-OEM",   "EGR valve: OE cross-reference (DMS-PT-018)"),
        ("DMS-P0103-STD",     "DMS-P0103-ECO",   "EGR valve: aftermarket alternative"),
        ("DMS-P0109-STD",     "DMS-P0109-OEM",   "Turbocharger: OE cross-reference (DMS-PT-019)"),
        ("DMS-P0109-STD",     "DMS-P0109-PRO",   "Turbocharger: performance hybrid variant"),
        ("DMS-P0229-STD",     "DMS-P0229-OEM",   "Radiator: OE cross-reference (DMS-PT-039)"),
        ("DMS-P0229-STD",     "DMS-P0229-ECO",   "Radiator: economy alternative (2-row core)"),
        ("DMS-P0229-PRO",     "DMS-P0229-STD",   "Radiator: 3-row PRO supersedes 2-row STD"),
        ("DMS-P0235-STD",     "DMS-P0235-OEM",   "EVAP purge solenoid: OE cross-reference (DMS-PT-040)"),
        ("DMS-P0235-STD",     "DMS-P0235-ECO",   "EVAP purge solenoid: aftermarket alternative"),
        ("DMS-P0241-STD",     "DMS-P0241-OEM",   "EVAP vent solenoid: OE cross-reference (DMS-PT-041)"),
        ("DMS-P0241-STD",     "DMS-P0241-ECO",   "EVAP vent solenoid: aftermarket alternative"),
        ("DMS-P0253-STD",     "DMS-P0253-OEM",   "Fuel pressure regulator: OE cross-reference (DMS-PT-043)"),
        ("DMS-P0253-STD",     "DMS-P0253-ECO",   "Fuel pressure regulator: aftermarket alternative"),
        ("DMS-P0265-STD",     "DMS-P0265-OEM",   "Knock sensor: OE cross-reference (DMS-PT-045)"),
        ("DMS-P0265-STD",     "DMS-P0265-ECO",   "Knock sensor: aftermarket alternative"),
        ("DMS-P0271-STD",     "DMS-P0271-OEM",   "Camshaft position sensor: OE cross-reference (DMS-PT-046)"),
        ("DMS-P0271-STD",     "DMS-P0271-ECO",   "Camshaft position sensor: aftermarket alternative"),
        ("DMS-P0319-STD",     "DMS-P0319-OEM",   "Body control module: OE cross-reference (DMS-PT-054)"),
        ("DMS-P0301-STD",     "DMS-P0301-OEM",   "TCM: OE cross-reference (DMS-PT-051)"),
        ("DMS-P0301-STD",     "DMS-P0301-ECO",   "TCM: remanufactured aftermarket alternative"),
        ("DMS-P0139-STD",     "DMS-P0139-OEM",   "Power steering pump: OE cross-reference (DMS-PT-024)"),
        ("DMS-P0139-STD",     "DMS-P0139-ECO",   "Power steering pump: remanufactured aftermarket"),
        ("DMS-P0175-STD",     "DMS-P0175-OEM",   "A/C compressor: OE cross-reference (DMS-PT-030)"),
        ("DMS-P0175-STD",     "DMS-P0175-ECO",   "A/C compressor: remanufactured aftermarket alternative"),
        ("DMS-P0169-STD",     "DMS-P0169-OEM",   "Starter motor: OE cross-reference (DMS-PT-029)"),
        ("DMS-P0169-STD",     "DMS-P0169-ECO",   "Starter motor: remanufactured aftermarket"),
        ("DMS-P0151-STD",     "DMS-P0151-OEM",   "Timing chain kit: OE cross-reference (DMS-PT-026)"),
        ("DMS-P0151-STD",     "DMS-P0151-ECO",   "Timing chain kit: economy alternative"),
        ("DMS-P0193-STD",     "DMS-P0193-OEM",   "AT filter: OE cross-reference (DMS-PT-033)"),
        ("DMS-P0205-STD",     "DMS-P0205-OEM",   "CV axle: OE cross-reference (DMS-PT-035)"),
        ("DMS-P0205-STD",     "DMS-P0205-ECO",   "CV axle: remanufactured aftermarket alternative"),
        ("DMS-P0199-STD",     "DMS-P0199-OEM",   "Differential seal: OE cross-reference (DMS-PT-034)"),
        ("DMS-P0289-STD",     "DMS-P0289-OEM",   "Secondary air pump: OE cross-reference (DMS-PT-049)"),
        ("DMS-P0283-STD",     "DMS-P0283-OEM",   "Variable intake solenoid: OE cross-reference (DMS-PT-048)"),
        ("DMS-P0361-STD",     "DMS-P0361-OEM",   "Brake booster: OE cross-reference (DMS-PT-061)"),
        ("DMS-P0361-STD",     "DMS-P0361-ECO",   "Brake booster: remanufactured aftermarket"),
        ("DMS-P0367-STD",     "DMS-P0367-OEM",   "Master cylinder: OE cross-reference (DMS-PT-062)"),
        ("DMS-P0367-STD",     "DMS-P0367-ECO",   "Master cylinder: remanufactured aftermarket"),
        ("DMS-P0373-STD",     "DMS-P0373-OEM",   "Wheel cylinder: OE cross-reference (DMS-PT-063)"),
        ("DMS-P0355-STD",     "DMS-P0355-OEM",   "Accelerator pedal: OE cross-reference (DMS-PT-060)"),
        ("DMS-P0349-STD",     "DMS-P0349-OEM",   "EVAP canister: OE cross-reference (DMS-PT-059)"),
        ("DMS-P0343-STD",     "DMS-P0343-OEM",   "Door lock actuator: OE cross-reference (DMS-PT-058)"),
        ("DMS-P0247-STD",     "DMS-P0247-OEM",   "PCV valve: OE cross-reference (DMS-PT-042)"),
        ("DMS-P0475-STD",     "DMS-P0475-OEM",   "Engine mount: OE cross-reference (DMS-PT-080)"),
        ("DMS-P0475-STD",     "DMS-P0475-ECO",   "Engine mount: economy alternative"),
        ("DMS-P0211-STD",     "DMS-P0211-OEM",   "Headlamp: OE cross-reference (DMS-PT-036)"),
        ("DMS-P0211-STD",     "DMS-P0211-ECO",   "Headlamp: economy alternative"),
        ("DMS-P0133-STD",     "DMS-P0133-OEM",   "Tie rod end: OE cross-reference (DMS-PT-023)"),
        ("DMS-P0133-STD",     "DMS-P0133-ECO",   "Tie rod end: economy alternative"),
        ("DMS-P0385-STD",     "DMS-P0385-OEM",   "Brake caliper: OE cross-reference (DMS-PT-065)"),
        ("DMS-P0385-STD",     "DMS-P0385-ECO",   "Brake caliper: remanufactured aftermarket"),
        ("DMS-P0379-STD",     "DMS-P0379-OEM",   "Brake hose: OE cross-reference (DMS-PT-064)"),
        ("DMS-P0337-STD",     "DMS-P0337-OEM",   "Sway bar link: OE cross-reference (DMS-PT-057)"),
        ("DMS-P0337-STD",     "DMS-P0337-ECO",   "Sway bar link: economy alternative"),
        ("DMS-P0121-STD",     "DMS-P0121-OEM",   "Shock absorber: OE cross-reference (DMS-PT-021)"),
        ("DMS-P0121-STD",     "DMS-P0121-ECO",   "Shock absorber: economy alternative"),
        ("DMS-P0121-PRO",     "DMS-P0121-STD",   "Shock absorber: PRO supersedes STD (sport-tuned)"),
        ("DMS-P0475-PRO",     "DMS-P0475-STD",   "Engine mount: PRO hydraulic supersedes STD rubber"),
    ]
    for primary, replacement, notes in additional_supersessions:
        records.append(_rec(primary, replacement, SUPERSESSION, notes))

    return records


def _load_existing_interchange(
    fixture_path: Path,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Load existing interchange records keyed by (primary_part_number, replacement_part_number) PK."""
    if not fixture_path.exists():
        return {}
    try:
        data: list[dict[str, Any]] = json.loads(fixture_path.read_text())
    except (json.JSONDecodeError, ValueError):
        return {}
    return {(r["primary_part_number"], r["replacement_part_number"]): r for r in data}


def seed(
    dry_run: bool = False,
    fixture_dir: Path | None = None,
    verbose: bool = False,
) -> int:
    """Seed parts_interchange.  Returns net write count (0 on second run)."""
    base_dir = (
        fixture_dir
        if fixture_dir is not None
        else Path(__file__).parent / "parts_seed_fixtures"
    )
    fixture_path = base_dir / "parts_interchange.json"

    records = _generate_interchange()

    # De-duplicate within the generated set (PK = (primary, replacement))
    seen_pks: dict[tuple[str, str], dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for rec in records:
        pk = (rec["primary_part_number"], rec["replacement_part_number"])
        if pk not in seen_pks:
            seen_pks[pk] = rec
            deduped.append(rec)
    records = deduped

    existing = _load_existing_interchange(fixture_path)

    new_records: list[dict[str, Any]] = []
    for rec in records:
        pk = (rec["primary_part_number"], rec["replacement_part_number"])
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
        description="Seed adp_parts_domain / parts_interchange."
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
