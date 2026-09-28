"""Unified dimension catalog generator for the ADP foundation.

Generates all 7 dimensions in a deterministic order from a single
seed, writes parquet to local filesystem (dev mode) or S3 (production
mode), and emits ``manifest.json`` per dimension recording the row
count, seed, dimension version, and SHA-256 over the parquet bytes.

The ``vins`` dimension is the Meridian Motors EV catalog (post-rebrand
from Acme Motors, 2026-09-10 — spec
``.kiro/specs/2026-09-10-adp-meridian-ev-oem-reseed/``). The vin pool is
an organic production ramp of 4,734,904 vehicles across five model years
(2022-2026), two assembly plants (Casa Grande, AZ; Reno, NV), seven
wind-themed models, three trim configurations each, and enforces
model-year introduction gating, ISO 3779 check digits, weekday-only
manufacture dates, plant holiday shutdowns, and a monotone software
version rollout curve.

The first 21 rows of the vin pool are the CMS staging demo fleet fetched
at seed time from ``cms-staging-storage-vehicles`` via
``lib/cms_demo_vins.py``. Ordinals 21..4,734,903 are procedurally
generated. The seed fails closed if the CMS DDB fetch returns zero rows
or errors — see spec D2 + R4.

Deterministic guarantees
------------------------
- Same seed + same dimension YAML schemas + same CMS DDB state →
  byte-identical parquet.
- Generation order is fixed: dealers → suppliers → parts → vins →
  customers → time_calendar → charging_stations. Order matters because
  parts has an FK to suppliers.
- NumPy uses ``numpy.random.default_rng(seed + offset)`` per dimension
  so RNG streams stay independent across dimensions.

Outputs
-------
For each dimension D (e.g., ``vins``), the generator writes:

::

    <output_root>/<D>/data.parquet
    <output_root>/<D>/manifest.json

Where ``<output_root>`` is either a local filesystem path or an
``s3://...`` URL.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import string
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from faker import Faker

# Path bootstrap so the local ``lib`` package (cms_demo_vins) resolves when
# this module is run directly OR imported from the tests dir.
_SOURCE = Path(__file__).resolve().parents[1]  # platform-foundation/source
if str(_SOURCE) not in sys.path:
    sys.path.insert(0, str(_SOURCE))

# ---------------------------------------------------------------------------
# Version + top-level scale
# ---------------------------------------------------------------------------

# Bumped 2.0.0 at the Meridian rebrand (spec 2026-09-10-adp-meridian-ev-oem-reseed).
# 1.x = Acme Motors, 5M-VIN round pool. 2.x = Meridian Motors, 4,734,904-VIN
# organic ramp. The bump is stamped on every row + manifest so downstream
# consumers can tell which vintage they're reading.
DIMENSION_VERSION = "2.0.0"

# Anchor date for time_calendar (10-year window 2020-01-01 → 2029-12-31).
TIME_ANCHOR = datetime.date(2020, 1, 1)
TIME_DAYS = 365 * 10 + 3  # 3 leap days in the 2020-2030 window

# Total Meridian VIN pool per D1 organic ramp. Sums per-year values below.
_MERIDIAN_TOTAL_VINS = 4_734_904

SCALE = {
    "vins": _MERIDIAN_TOTAL_VINS,
    "customers": 5_000_000,
    "dealers": 200,
    "suppliers": 500,
    "parts": 50_000,
    "time_calendar": TIME_DAYS,
    "charging_stations": 50_000,
}

# ---------------------------------------------------------------------------
# VIN encoding + alphabets
# ---------------------------------------------------------------------------

# ISO 3779 VIN alphabet — 33 chars, excluding I, O, Q.
VIN_ALPHABET = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"
# Full A-Z + 0-9 alphabet used for parts numbers (no ISO 3779 constraint there).
ALNUM_UPPER = string.ascii_uppercase + string.digits

# Meridian Motors synthetic World Manufacturer Identifier (WMI). Not
# assigned to any real OEM by SAE — appropriate for synthetic demo data.
# Replaces the retired ``ACME_WMI = "1FA"`` which collided with a real Ford
# WMI (portfolio hygiene fix bundled into the rebrand).
MERIDIAN_WMI = "MRD"

# ---------------------------------------------------------------------------
# Meridian model catalog (D4)
# ---------------------------------------------------------------------------
#
# Tuple shape: (model, powertrain_type, share_of_production, first_year,
#               base_battery_kwh, base_range_epa_mi).
#
# All 7 models are ``electric`` per D5 (Meridian is a pure BEV OEM). Shares
# are the target long-run distribution; per-year renormalization (D12.a)
# handles introduction-year gating so a 2022 vehicle can only sample from
# {Trailwind, Azimuth} etc.
#
# The model names come from CMS's existing Meridian catalog in
# ``cms-staging-storage-vehicles`` (wind-themed): 7 models, all BEVs.
# ADP does not invent Meridian models — CMS is the authoritative source.
MERIDIAN_MODELS: list[tuple[str, str, float, int, float, float]] = [
    # model,       powertrain,  share, first_yr, base_kwh, base_range_mi
    ("Trailwind", "electric", 0.27, 2022, 100.0, 350.0),
    ("Azimuth",   "electric", 0.21, 2022, 118.0, 400.0),
    ("Windrose",  "electric", 0.17, 2023, 100.0, 330.0),
    ("Crestwind", "electric", 0.13, 2023, 118.0, 390.0),
    ("Zephyr",    "electric", 0.11, 2024,  90.0, 300.0),
    ("Sirocco",   "electric", 0.07, 2024,  75.0, 260.0),
    ("Mistral",   "electric", 0.04, 2025, 130.0, 450.0),
]

# ---------------------------------------------------------------------------
# Meridian trim configurations (D12.b)
# ---------------------------------------------------------------------------
#
# For each (model, trim) pair the tuple is (battery_kwh, motor_count,
# range_epa_mi, max_charging_rate_kw). Every battery_pack_kwh, motor_count,
# range_epa_mi, and max_charging_rate_kw value in the output MUST come from
# this table — NOT from uniform Faker samples. Test
# ``test_battery_kwh_is_discrete`` asserts on the closure of the kWh column
# to the set of values here. Test
# ``test_trim_config_binds_battery_motor_range`` asserts the per-cell binding
# holds exactly.
#
# Verbatim from ``test_meridian_reseed.py::_TRIM_CONFIGS``. If either side
# changes, they must change together — the spec is the source of truth.
MERIDIAN_TRIMS: dict[tuple[str, str], tuple[float, int, float, float]] = {
    ("Trailwind", "Standard"):    (100.0, 2, 350.0, 250.0),
    ("Trailwind", "Plus"):        (118.0, 3, 400.0, 300.0),
    ("Trailwind", "Performance"): (118.0, 4, 380.0, 350.0),
    ("Azimuth", "Standard"):      (118.0, 2, 400.0, 300.0),
    ("Azimuth", "Plus"):          (118.0, 3, 450.0, 300.0),
    ("Azimuth", "Performance"):   (118.0, 4, 425.0, 350.0),
    ("Windrose", "Standard"):     (100.0, 2, 320.0, 250.0),
    ("Windrose", "Plus"):         (118.0, 2, 380.0, 300.0),
    ("Windrose", "Performance"):  (118.0, 3, 360.0, 350.0),
    ("Crestwind", "Standard"):    ( 75.0, 2, 280.0, 200.0),
    ("Crestwind", "Plus"):        (100.0, 2, 340.0, 250.0),
    ("Crestwind", "Performance"): (100.0, 3, 320.0, 300.0),
    ("Zephyr", "Standard"):       ( 90.0, 2, 300.0, 250.0),
    ("Zephyr", "Plus"):           (100.0, 3, 350.0, 300.0),
    ("Zephyr", "Performance"):    (100.0, 4, 320.0, 350.0),
    ("Sirocco", "Standard"):      (100.0, 2, 250.0, 200.0),
    ("Sirocco", "Plus"):          (118.0, 3, 290.0, 250.0),
    ("Sirocco", "Performance"):   (130.0, 4, 270.0, 300.0),
    ("Mistral", "Standard"):      (130.0, 3, 450.0, 350.0),
    ("Mistral", "Plus"):          (130.0, 4, 480.0, 350.0),
    ("Mistral", "Performance"):   (150.0, 4, 500.0, 350.0),
}

# Trim distribution (D12.b): Standard-heavy, moderate Plus, small
# Performance. Same shape for every model. Test
# ``test_trim_distribution_skew`` asserts each share is within ±2% of these.
_TRIM_NAMES: tuple[str, ...] = ("Standard", "Plus", "Performance")
_TRIM_SHARES: tuple[float, ...] = (0.45, 0.35, 0.20)

# ---------------------------------------------------------------------------
# Meridian assembly plants (D12.d)
# ---------------------------------------------------------------------------
#
# Two US EV manufacturing plants. Casa Grande, AZ (`CGA`) is the primary
# plant, opened Sep 2022 alongside the model launch. Reno, NV (`RNO`)
# opens Apr 2024 as second-plant capacity expansion.
#
# Tuple shape: (plant_code, open_date, human_readable_location).
# The human-readable location is what ``vehicle_identity`` writes to its
# new ``assembly_plant_location`` column per D12.i.
MERIDIAN_PLANTS: list[tuple[str, datetime.date, str]] = [
    ("CGA", datetime.date(2022, 9, 1), "Casa Grande, AZ, USA"),
    ("RNO", datetime.date(2024, 4, 1), "Reno, NV, USA"),
]
_PLANT_OPEN_DATE: dict[str, datetime.date] = {p[0]: p[1] for p in MERIDIAN_PLANTS}
_PLANT_LOCATION: dict[str, str] = {p[0]: p[2] for p in MERIDIAN_PLANTS}

# ---------------------------------------------------------------------------
# D1 organic ramp — per-year and per-plant target counts
# ---------------------------------------------------------------------------
#
# Cumulative production through mid-September 2026. Non-round values
# (245,913 not 250,000; 4,734,904 not 5,000,000) so the dataset scans as
# real-OEM-output rather than a corporate target. Total exactly matches
# ``_MERIDIAN_TOTAL_VINS``; sanity-checked at import time.
_YEAR_VIN_COUNTS: dict[int, int] = {
    2022: 245_913,   # Q3-Q4 launch, single plant (CGA), 2 models
    2023: 897_441,   # first full year, ramp on 4 models
    2024: 1_383_776, # Q2 second plant (RNO) opens, 6 models
    2025: 1_721_554, # peak dual-plant year, all 7 models
    2026: 486_220,   # partial year through mid-Sep, all 7 models
}
assert sum(_YEAR_VIN_COUNTS.values()) == _MERIDIAN_TOTAL_VINS, (
    "D1 year counts must sum to the total pool size"
)

# Per-year assembly plant volume distribution (D1's plant table). Sums per
# year match _YEAR_VIN_COUNTS. Reno absent in 2022-2023; opens Q2 2024.
_PLANT_DISTRIBUTION_BY_YEAR: dict[int, dict[str, int]] = {
    2022: {"CGA": 245_913, "RNO": 0},
    2023: {"CGA": 897_441, "RNO": 0},
    2024: {"CGA": 968_643, "RNO": 415_133},
    2025: {"CGA": 946_855, "RNO": 774_699},
    2026: {"CGA": 267_421, "RNO": 218_799},
}
for _yr, _plant_dist in _PLANT_DISTRIBUTION_BY_YEAR.items():
    assert sum(_plant_dist.values()) == _YEAR_VIN_COUNTS[_yr], (
        f"plant distribution for year {_yr} must sum to _YEAR_VIN_COUNTS"
    )

# ---------------------------------------------------------------------------
# D12.g — color distribution (weighted, common colors dominate ~60%)
# ---------------------------------------------------------------------------
#
# Test ``test_common_colors_dominate`` asserts (white + black + silver)
# share is 0.60 ± 0.03. Long-tail values sum to make total 1.00.
_COLOR_DISTRIBUTION: tuple[tuple[str, float], ...] = (
    ("white",  0.22),
    ("black",  0.20),
    ("silver", 0.18),  # subtotal common: 0.60
    ("grey",   0.12),
    ("blue",   0.10),
    ("red",    0.08),
    ("green",  0.03),
    ("orange", 0.02),
    ("yellow", 0.02),
    ("purple", 0.02),
    ("beige",  0.01),
)
_COLOR_NAMES: tuple[str, ...] = tuple(c[0] for c in _COLOR_DISTRIBUTION)
_COLOR_PROBS: tuple[float, ...] = tuple(c[1] for c in _COLOR_DISTRIBUTION)
assert abs(sum(_COLOR_PROBS) - 1.0) < 1e-9, "color probabilities must sum to 1"

# ---------------------------------------------------------------------------
# D12.g — body style per model (FIXED, not per-VIN sampled)
# ---------------------------------------------------------------------------
_MERIDIAN_BODY_STYLES: dict[str, str] = {
    "Trailwind": "suv",       # mid-size crossover
    "Azimuth":   "sedan",     # premium sedan
    "Windrose":  "suv",       # family SUV
    "Crestwind": "hatchback", # compact crossover
    "Zephyr":    "coupe",     # sport coupe
    "Sirocco":   "truck",     # pickup, work-fleet
    "Mistral":   "sedan",     # halo flagship sedan
}

# ---------------------------------------------------------------------------
# D12.f — software version rollout milestones
# ---------------------------------------------------------------------------
#
# ``build_software_version`` = the version installed at the plant when the
# VIN was manufactured. Monotone non-decreasing over calendar time within
# each plant (test ``test_build_software_version_monotone_per_plant``).
# Quarterly minor bumps; major bumps at Q1 2024 (2.0.0) and Q3 2025 (3.0.0).
#
# Look up by finding the last milestone <= manufacture_date. If no milestone
# is <= the date (i.e., date is pre-plant-open), the plant open date is
# guaranteed to be >= 2022-09-01 = the first milestone, so the fallback path
# is unreachable in production data.
_SOFTWARE_VERSION_MILESTONES: tuple[tuple[datetime.date, str], ...] = (
    (datetime.date(2022,  9, 1), "1.0.0"),
    (datetime.date(2022, 12, 1), "1.1.0"),
    (datetime.date(2023,  3, 1), "1.2.0"),
    (datetime.date(2023,  6, 1), "1.3.0"),
    (datetime.date(2023,  9, 1), "1.4.0"),
    (datetime.date(2023, 12, 1), "1.5.0"),
    (datetime.date(2024,  1, 1), "2.0.0"),  # major bump
    (datetime.date(2024,  4, 1), "2.1.0"),
    (datetime.date(2024,  7, 1), "2.2.0"),
    (datetime.date(2024, 10, 1), "2.3.0"),
    (datetime.date(2025,  1, 1), "2.4.0"),
    (datetime.date(2025,  4, 1), "2.5.0"),
    (datetime.date(2025,  7, 1), "3.0.0"),  # major bump
    (datetime.date(2025, 10, 1), "3.1.0"),
    (datetime.date(2026,  1, 1), "3.2.0"),
    (datetime.date(2026,  4, 1), "3.3.0"),
    (datetime.date(2026,  7, 1), "3.4.0"),
)

# ---------------------------------------------------------------------------
# VIN internal encoding tables (D3)
# ---------------------------------------------------------------------------
#
# The 5-char VDS (positions 3-7) encodes model (2) + trim (2) + body (1).
# Position 8 is the ISO 3779 check digit. Position 9 is the SAE J272 model
# year letter. Position 10 is the plant character (first letter of code).
# Positions 11-16 are a 6-char base-33 serial from an ordinal counter.
#
# All 2-char model and trim codes below are ISO 3779 alphabet-safe (no I,
# O, Q). Body chars similarly safe.
_MODEL_CODE: dict[str, str] = {
    "Trailwind": "TW",
    "Azimuth":   "AZ",
    "Windrose":  "WR",
    "Crestwind": "CW",
    "Zephyr":    "ZP",
    "Sirocco":   "SR",
    "Mistral":   "MS",
}
_TRIM_CODE: dict[str, str] = {
    "Standard":    "01",
    "Plus":        "02",
    "Performance": "03",
}
_BODY_STYLE_CHAR: dict[str, str] = {
    "sedan":     "S",
    "suv":       "U",
    "hatchback": "H",
    "coupe":     "C",
    "truck":     "T",
}

# SAE J272 model-year encoding. Standard cycle skips I, O, Q, U, Z, then
# runs 0-9. We only need 2022-2026 for this rebrand; full table pinned so
# the mapping stays authoritative if the spec extends.
_YEAR_LETTER: dict[int, str] = {
    2010: "A", 2011: "B", 2012: "C", 2013: "D", 2014: "E", 2015: "F",
    2016: "G", 2017: "H", 2018: "J", 2019: "K", 2020: "L", 2021: "M",
    2022: "N", 2023: "P", 2024: "R", 2025: "S", 2026: "T",
    2027: "V", 2028: "W", 2029: "X", 2030: "Y",
}

# ISO 3779 letter transliteration (positions 9-16) for check digit
# computation. Digits map to themselves; letters map per the table below.
# I, O, Q are excluded from the alphabet by construction.
_ISO3779_TRANSLIT: dict[str, int] = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5,           "P": 7,
    "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}
# ISO 3779 position weights. Position 8 (0-indexed) — the check digit
# position — has weight 0.
_ISO3779_WEIGHTS: tuple[int, ...] = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)

# ---------------------------------------------------------------------------
# US states (unchanged from pre-rebrand — dealer/station geo dimension)
# ---------------------------------------------------------------------------
US_STATES = [
    "CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI",
    "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MD", "MO", "WI",
    "CO", "MN", "SC", "AL", "LA", "KY", "OR", "OK", "CT", "UT",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_n(n: int, alphabet: str, width: int) -> str:
    """Encode integer ``n`` in base-len(alphabet), zero-padded to ``width`` chars."""
    base = len(alphabet)
    if n < 0:
        raise ValueError("negative ordinal not supported")
    out = ""
    while n > 0:
        n, idx = divmod(n, base)
        out = alphabet[idx] + out
    return out.rjust(width, alphabet[0])


def _customer_id(i: int) -> str:
    return f"CUST-{i:08X}"


def _dealer_id(i: int) -> str:
    return f"DLR-{i:05d}"


def _supplier_id(i: int) -> str:
    return f"SUP-{i:04d}"


def _part_number(i: int) -> str:
    """Encode ordinal i into ``XXXXXXXX-YYYY`` where both halves are base-36."""
    high = (i // (36 * 36 * 36 * 36)) & 0xFFFFFFFF
    low = i & 0xFFFFFFFF
    h = _base_n(high % (36**8), ALNUM_UPPER, width=8)
    ll = _base_n(low % (36**4), ALNUM_UPPER, width=4)
    return f"{h}-{ll}"


def _station_id(network_code: str, i: int) -> str:
    return f"STN-{network_code}-{i:08d}"


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _iso3779_check_digit(vin_partial: str) -> str:
    """Compute the ISO 3779 check digit (position 9 in 1-indexed VIN, index 8 here).

    ``vin_partial`` MUST be 17 characters; the character at position 8 is
    ignored (weight is 0 at that position). Returns a single-character
    string in ``{'0'..'9', 'X'}`` — 'X' when the remainder is 10.

    Kept in sync with ``test_meridian_reseed.py::_iso3779_check_digit`` —
    both implementations MUST agree or D12.c's regression test fails.
    """
    if len(vin_partial) != 17:
        raise ValueError(f"VIN partial must be 17 chars; got {len(vin_partial)}")
    total = 0
    for i, ch in enumerate(vin_partial.upper()):
        if ch.isdigit():
            v = int(ch)
        else:
            v = _ISO3779_TRANSLIT.get(ch, 0)
        total += v * _ISO3779_WEIGHTS[i]
    r = total % 11
    return "X" if r == 10 else str(r)


def _year_letter(year: int) -> str:
    """SAE J272 model-year encoding for VIN position 10."""
    if year not in _YEAR_LETTER:
        raise ValueError(f"model_year {year} not in SAE J272 pinned range")
    return _YEAR_LETTER[year]


# ---------------------------------------------------------------------------
# Valid-manufacture-date pre-computation
# ---------------------------------------------------------------------------


def _valid_manufacture_dates(year: int, plant: str) -> list[datetime.date]:
    """Return sorted list of valid manufacture dates for a (year, plant) bucket.

    Applies D12.e rules:
      * Monday-Friday only (no weekend production).
      * No production in the last week of December (Dec 25-31) — Christmas
        / New Year shutdown.
      * No production in the first week of July (Jul 1-7) — retooling week.

    Plus D12.d plant-open constraint: RNO produces nothing before 2024-04-01.
    """
    if plant not in _PLANT_OPEN_DATE:
        raise ValueError(f"unknown plant {plant!r}")
    open_date = _PLANT_OPEN_DATE[plant]

    # Year window: MY2026 only through 2026-09-15 (mid-September per D1
    # "partial year through mid-Sep"). Other years use the full calendar.
    year_start = datetime.date(year, 1, 1)
    if year == 2026:
        year_end = datetime.date(2026, 9, 15)
    else:
        year_end = datetime.date(year, 12, 31)

    # Effective window respects plant open date.
    window_start = max(year_start, open_date)
    if window_start > year_end:
        return []

    valid: list[datetime.date] = []
    d = window_start
    one_day = datetime.timedelta(days=1)
    while d <= year_end:
        # Weekday only (Monday=0..Friday=4)
        if d.weekday() <= 4:
            # Exclude plant shutdown windows.
            not_dec_shutdown = not (d.month == 12 and d.day >= 25)
            not_jul_retool = not (d.month == 7 and d.day <= 7)
            if not_dec_shutdown and not_jul_retool:
                valid.append(d)
        d += one_day
    return valid


def _software_version_for_date(mfg_date: datetime.date) -> str:
    """Look up ``build_software_version`` by manufacture_date.

    Returns the version of the last milestone with date <= mfg_date. Since
    milestones start at 2022-09-01 and every plant open date is >= 2022-09-01,
    the fallback (first-milestone version) is unreachable for real bucket
    dates — but kept safe against future date shifts.
    """
    chosen = _SOFTWARE_VERSION_MILESTONES[0][1]
    for milestone_date, version in _SOFTWARE_VERSION_MILESTONES:
        if milestone_date <= mfg_date:
            chosen = version
        else:
            break
    return chosen


def _current_software_version(build_version: str, laggard_offset: int) -> str:
    """Compute ``current_software_version`` given ``build`` + laggard offset.

    ``laggard_offset``:
      * 0 → current version is the latest release (no laggard).
      * 1-2 → one or two versions behind latest.

    Real fleets have OTA laggards; test
    ``test_build_software_version_monotone_per_plant`` only asserts
    monotonicity of ``build_software_version`` (not ``current``), so any
    plausible laggard distribution is acceptable here.
    """
    versions = [v for _, v in _SOFTWARE_VERSION_MILESTONES]
    latest = versions[-1]
    if laggard_offset == 0:
        return latest
    # Step back N versions from latest, clamped to at least the build version.
    idx = max(0, len(versions) - 1 - laggard_offset)
    candidate = versions[idx]
    # Guarantee current >= build. Compare by version-index.
    try:
        build_idx = versions.index(build_version)
    except ValueError:
        build_idx = 0
    if idx < build_idx:
        return build_version
    return candidate


# ---------------------------------------------------------------------------
# Bucket planning — allocate procedural rows across (year, plant, model)
# ---------------------------------------------------------------------------


def _split_by_largest_remainder(
    total: int, shares: list[float]
) -> list[int]:
    """Split ``total`` into ``len(shares)`` integers proportional to ``shares``.

    Uses the largest-remainder method — floor each product, then hand out
    the residual rows to buckets with the largest fractional parts. Sum
    of returned integers is exactly ``total``. Deterministic.
    """
    if total == 0:
        return [0] * len(shares)
    s = sum(shares)
    exact = [total * (sh / s) for sh in shares]
    floors = [int(x) for x in exact]
    remainder = total - sum(floors)
    if remainder > 0:
        fractions = [(exact[i] - floors[i], i) for i in range(len(shares))]
        # Sort by fractional part descending, break ties by bucket index
        # ascending — deterministic.
        fractions.sort(key=lambda t: (-t[0], t[1]))
        for k in range(remainder):
            floors[fractions[k][1]] += 1
    return floors


def _plan_procedural_buckets(
    procedural_year_targets: dict[int, dict[str, int]],
) -> list[tuple[int, str, str, int]]:
    """Return list of (year, plant, model, count) buckets.

    ``procedural_year_targets`` is the count remaining after subtracting
    the CMS block, keyed as ``[year][plant] -> count``. Within each
    (year, plant), split ``count`` across eligible models by their D4
    shares, renormalized to sum to 1 over the eligible set. Uses
    largest-remainder rounding so every bucket sums exactly.
    """
    buckets: list[tuple[int, str, str, int]] = []
    for year in sorted(procedural_year_targets):
        for plant in ("CGA", "RNO"):
            plant_count = procedural_year_targets[year].get(plant, 0)
            if plant_count == 0:
                continue
            eligible = [
                (name, share)
                for (name, _pt, share, first_yr, _bk, _br) in MERIDIAN_MODELS
                if first_yr <= year
            ]
            model_names = [name for (name, _) in eligible]
            model_shares = [share for (_, share) in eligible]
            model_counts = _split_by_largest_remainder(plant_count, model_shares)
            for name, mc in zip(model_names, model_counts):
                if mc > 0:
                    buckets.append((year, plant, name, mc))
    return buckets


def _distribute_cms_by_year_plant(
    cms_records: list[dict],
) -> dict[int, dict[str, int]]:
    """Assign each CMS demo row to a (year, plant) cell for accounting.

    CMS rows carry ``year`` and ``model`` (from DDB) but no plant.
    Synthesize the plant per D12.d rules:

      * MY2022 rows → CGA (Reno not open).
      * MY2023 rows → CGA (Reno not open).
      * MY2024 rows → CGA if the (deterministic) synthesized manufacture
        date is < 2024-04-01; else pick per year's plant share.
      * MY2025-2026 rows → per year's plant share.

    In practice the CMS demo fleet is only ~21 rows, and per-year plant
    assignment for these 21 is derived from a deterministic hash of the
    VIN string, not RNG — so re-runs assign identically without needing
    to persist state.
    """
    per: dict[int, dict[str, int]] = {}
    for r in cms_records:
        year = int(r["year"])
        plant = _synthesize_plant_for_cms_row(r)
        per.setdefault(year, {"CGA": 0, "RNO": 0})[plant] += 1
    return per


def _synthesize_plant_for_cms_row(row: dict) -> str:
    """Deterministic plant assignment for a single CMS demo VIN row.

    Rules:
      * MY2022-2023 → CGA (only plant open).
      * MY2024 → CGA if hash(vin) even, else RNO (RNO open Q2 2024;
        manufacture_date synthesized ≥ 2024-04-01 when RNO chosen —
        handled by _synthesize_cms_manufacture_date below).
      * MY2025-2026 → CGA if hash(vin) even, else RNO.

    Hash is a stable Python-level operation on the VIN string
    (``sum(ord(c))`` mod 2) — no reliance on Python's random-seeded
    hash() so this stays deterministic across processes.
    """
    year = int(row["year"])
    if year <= 2023:
        return "CGA"
    vin_char_sum = sum(ord(c) for c in str(row["vin"]))
    return "CGA" if vin_char_sum % 2 == 0 else "RNO"


def _synthesize_cms_manufacture_date(
    row: dict, plant: str
) -> datetime.date:
    """Deterministic manufacture date for a CMS demo row in given (year, plant).

    Picks a valid manufacture date from ``_valid_manufacture_dates(year,
    plant)`` using ``sum(ord(c))`` on the VIN mod len(valid_dates) — same
    determinism model as ``_synthesize_plant_for_cms_row``.
    """
    year = int(row["year"])
    valid = _valid_manufacture_dates(year, plant)
    if not valid:
        raise RuntimeError(
            f"no valid manufacture dates for CMS row {row.get('vin')!r} "
            f"in ({year}, {plant})"
        )
    idx = sum(ord(c) for c in str(row["vin"])) % len(valid)
    return valid[idx]


# ---------------------------------------------------------------------------
# Bucket-level VIN generation (procedural block)
# ---------------------------------------------------------------------------


def _generate_procedural_bucket(
    *,
    year: int,
    plant: str,
    model: str,
    count: int,
    serial_offset: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Generate ``count`` procedural rows for one (year, plant, model) bucket.

    Vectorised where possible. Per-row Python only for VIN string assembly
    + check-digit computation.
    """
    if count == 0:
        return pd.DataFrame()

    # Trim sampling — vectorised, 45/35/20 shares.
    trim_arr = rng.choice(_TRIM_NAMES, size=count, p=_TRIM_SHARES)

    # Trim lookup — pre-compute per-trim attribute arrays for this model.
    trim_kwh = np.empty(count, dtype=np.float64)
    trim_motors = np.empty(count, dtype=np.int32)
    trim_range = np.empty(count, dtype=np.float64)
    trim_chg = np.empty(count, dtype=np.float64)
    for tr in _TRIM_NAMES:
        mask = trim_arr == tr
        if mask.any():
            kwh, motors, range_mi, chg = MERIDIAN_TRIMS[(model, tr)]
            trim_kwh[mask] = kwh
            trim_motors[mask] = motors
            trim_range[mask] = range_mi
            trim_chg[mask] = chg

    # Color — vectorised, per D12.g.
    color_arr = rng.choice(_COLOR_NAMES, size=count, p=_COLOR_PROBS)

    # Manufacture date — sample uniformly from valid dates for (year, plant).
    valid_dates = _valid_manufacture_dates(year, plant)
    if not valid_dates:
        raise RuntimeError(
            f"no valid manufacture dates for procedural bucket "
            f"({year}, {plant}, {model}) — should be impossible"
        )
    date_idx = rng.integers(0, len(valid_dates), size=count)
    mfg_dates = [valid_dates[i] for i in date_idx]

    # Build software version — lookup by manufacture date.
    build_sw = [_software_version_for_date(d) for d in mfg_dates]

    # Current software version — sample laggard offset (0-2 versions
    # behind latest, weighted toward latest).
    laggard_offset = rng.choice([0, 1, 2], size=count, p=[0.85, 0.10, 0.05])
    current_sw = [
        _current_software_version(bv, int(lo))
        for bv, lo in zip(build_sw, laggard_offset)
    ]

    # In-service date — 0-180 days after manufacture.
    in_service_offset = rng.integers(0, 180, size=count)
    in_service_dates = [
        md + datetime.timedelta(days=int(o))
        for md, o in zip(mfg_dates, in_service_offset)
    ]

    # VIN string assembly.
    model_code = _MODEL_CODE[model]
    body_style = _MERIDIAN_BODY_STYLES[model]
    body_char = _BODY_STYLE_CHAR[body_style]
    year_char = _year_letter(year)
    plant_char = plant[0]  # 'C' for CGA, 'R' for RNO

    vins: list[str] = []
    for i in range(count):
        tr = trim_arr[i]
        trim_code = _TRIM_CODE[tr]
        serial = _base_n(serial_offset + i, VIN_ALPHABET, width=6)
        # Assemble with placeholder at check-digit position (position 8);
        # check digit's weight is 0 so placeholder value doesn't affect
        # the computation.
        partial = (
            MERIDIAN_WMI       # positions 0-2
            + model_code       # positions 3-4
            + trim_code        # positions 5-6
            + body_char        # position 7
            + "0"              # position 8 — check digit placeholder
            + year_char        # position 9
            + plant_char       # position 10
            + serial           # positions 11-16
        )
        cd = _iso3779_check_digit(partial)
        vins.append(partial[:8] + cd + partial[9:])

    df = pd.DataFrame(
        {
            "vin": vins,
            "model_year": np.full(count, year, dtype=np.int32),
            "make": np.full(count, "Meridian Motors", dtype=object),
            "model": np.full(count, model, dtype=object),
            "powertrain_type": np.full(count, "electric", dtype=object),
            "manufacture_date": mfg_dates,
            "in_service_date": in_service_dates,
            "assembly_plant": np.full(count, plant, dtype=object),
            "trim": trim_arr,
            "battery_pack_kwh": trim_kwh,
            "motor_count": trim_motors,
            "range_epa_mi": trim_range,
            "max_charging_rate_kw": trim_chg,
            "body_style": np.full(count, body_style, dtype=object),
            "color": color_arr,
            "build_software_version": build_sw,
            "current_software_version": current_sw,
        }
    )
    return df


def _build_cms_block(cms_records: list[dict], rng: np.random.Generator) -> pd.DataFrame:
    """Build the CMS demo block DataFrame from fetched records.

    Fields present in ``cms_records`` (from ``lib.cms_demo_vins``):
    ``vin``, ``model``, ``year``, ``make``, ``vehicleId``. We use
    ``vin`` + ``model`` + ``year`` directly; ``make`` is forced to
    "Meridian Motors" (fetcher already filters make=='Meridian').

    Synthesized deterministically (VIN-string-hash based, NOT rng — so
    repeated seeds produce byte-identical CMS block):
      * ``assembly_plant`` via ``_synthesize_plant_for_cms_row``.
      * ``manufacture_date`` via ``_synthesize_cms_manufacture_date``.
      * ``trim``, ``color``, laggard offset via rng (contributes to
        overall determinism via the seed offset).
    """
    rows: list[dict] = []
    n = len(cms_records)
    trim_arr = rng.choice(_TRIM_NAMES, size=n, p=_TRIM_SHARES)
    color_arr = rng.choice(_COLOR_NAMES, size=n, p=_COLOR_PROBS)
    laggard_offset = rng.choice([0, 1, 2], size=n, p=[0.85, 0.10, 0.05])
    in_service_offset = rng.integers(0, 180, size=n)

    for i, r in enumerate(cms_records):
        vin = str(r["vin"])
        model = str(r.get("model", "Trailwind"))
        year = int(r["year"])
        plant = _synthesize_plant_for_cms_row(r)
        mfg_date = _synthesize_cms_manufacture_date(r, plant)
        body_style = _MERIDIAN_BODY_STYLES.get(model, "suv")
        tr = str(trim_arr[i])
        # Lookup trim attributes. Fallback to (model, "Standard") if
        # (model, tr) is missing — should not happen for the 7 Meridian
        # models × 3 trims all defined in MERIDIAN_TRIMS.
        key = (model, tr)
        if key not in MERIDIAN_TRIMS:
            key = (model, "Standard")
        kwh, motors, range_mi, chg = MERIDIAN_TRIMS.get(
            key, (100.0, 2, 300.0, 250.0)
        )
        build_sw = _software_version_for_date(mfg_date)
        current_sw = _current_software_version(build_sw, int(laggard_offset[i]))
        in_service_date = mfg_date + datetime.timedelta(days=int(in_service_offset[i]))

        rows.append(
            {
                "vin": vin,
                "model_year": year,
                "make": "Meridian Motors",
                "model": model,
                "powertrain_type": "electric",
                "manufacture_date": mfg_date,
                "in_service_date": in_service_date,
                "assembly_plant": plant,
                "trim": tr,
                "battery_pack_kwh": float(kwh),
                "motor_count": int(motors),
                "range_epa_mi": float(range_mi),
                "max_charging_rate_kw": float(chg),
                "body_style": body_style,
                "color": str(color_arr[i]),
                "build_software_version": build_sw,
                "current_software_version": current_sw,
            }
        )
    df = pd.DataFrame(rows)
    # Force column dtypes matching the procedural block for concat compatibility.
    if not df.empty:
        df["model_year"] = df["model_year"].astype(np.int32)
        df["battery_pack_kwh"] = df["battery_pack_kwh"].astype(np.float64)
        df["motor_count"] = df["motor_count"].astype(np.int32)
        df["range_epa_mi"] = df["range_epa_mi"].astype(np.float64)
        df["max_charging_rate_kw"] = df["max_charging_rate_kw"].astype(np.float64)
    return df


# ---------------------------------------------------------------------------
# Per-dimension generators
# ---------------------------------------------------------------------------


def gen_dealers(seed: int) -> pd.DataFrame:
    fake = Faker("en_US")
    fake.seed_instance(seed + 1)
    rng = np.random.default_rng(seed + 1)
    n = SCALE["dealers"]

    types = ["flagship", "urban", "suburban", "rural", "service_only"]
    type_p = [0.05, 0.30, 0.40, 0.20, 0.05]

    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        rows.append(
            {
                "dealer_id": _dealer_id(i),
                "ordinal_index": i,
                "dealer_name": f"{fake.last_name()} Meridian Motors of {fake.city()}",
                "city": fake.city(),
                "state": rng.choice(US_STATES).item(),
                "country": "US",
                "dealer_type": rng.choice(types, p=type_p).item(),
                "opened_date": (
                    TIME_ANCHOR + datetime.timedelta(days=int(rng.integers(0, 1825)))
                ),
                "dimension_version": DIMENSION_VERSION,
            }
        )
    return pd.DataFrame(rows)


def gen_suppliers(seed: int) -> pd.DataFrame:
    fake = Faker("en_US")
    fake.seed_instance(seed + 2)
    rng = np.random.default_rng(seed + 2)
    n = SCALE["suppliers"]

    countries = ["US", "DE", "JP", "KR", "CN", "MX", "TW", "GB"]
    country_p = [0.40, 0.15, 0.15, 0.10, 0.10, 0.05, 0.03, 0.02]
    tiers = ["tier_1", "tier_2", "tier_3"]
    tier_p = [0.20, 0.45, 0.35]
    categories = [
        "battery_cells", "battery_pack", "motor", "power_electronics",
        "body_chassis", "interior", "software", "other",
    ]

    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        rows.append(
            {
                "supplier_id": _supplier_id(i),
                "ordinal_index": i,
                "supplier_name": f"{fake.company()} {fake.company_suffix()}",
                "country": rng.choice(countries, p=country_p).item(),
                "supplier_tier": rng.choice(tiers, p=tier_p).item(),
                "category": rng.choice(categories).item(),
                "dimension_version": DIMENSION_VERSION,
            }
        )
    return pd.DataFrame(rows)


def gen_parts(seed: int, suppliers: pd.DataFrame) -> pd.DataFrame:
    fake = Faker("en_US")
    fake.seed_instance(seed + 3)
    rng = np.random.default_rng(seed + 3)
    n = SCALE["parts"]
    supplier_ids = suppliers["supplier_id"].to_numpy()

    categories = [
        "battery_cell", "battery_module", "battery_pack", "bms",
        "motor", "inverter", "charger_onboard", "dc_dc_converter",
        "body", "chassis", "tire", "brake", "hvac", "infotainment",
        "sensor", "other",
    ]

    rows: list[dict[str, Any]] = []
    for i in range(n):
        sup_idx = i % len(supplier_ids)
        cat = categories[i % len(categories)]
        rows.append(
            {
                "part_number": _part_number(i),
                "ordinal_index": i,
                "supplier_id": str(supplier_ids[sup_idx]),
                "part_name": f"{cat.replace('_', ' ').title()} {i:05d}",
                "part_category": cat,
                "list_price_usd": _round_decimal(
                    float(rng.uniform(5.0, 9_500.0))
                ),
                "dimension_version": DIMENSION_VERSION,
            }
        )
    return pd.DataFrame(rows)


def gen_vins(seed: int) -> pd.DataFrame:
    """Generate the Meridian VIN pool.

    Steps:
      1. Fetch the CMS demo block from ``cms-staging-storage-vehicles``
         (~21 rows). Fail-closed if empty/error.
      2. Assign a (plant, manufacture_date) to each CMS row
         deterministically (VIN-hash based, no RNG dependency).
      3. Subtract the CMS per-(year, plant) counts from the D1 targets
         to compute procedural per-bucket counts.
      4. For each (year, plant), split the count across eligible models
         (D12.a introduction gating) by D4 shares — largest-remainder
         rounding so totals sum exactly.
      5. Generate each (year, plant, model) bucket vectorised.
      6. Concat CMS block + procedural buckets. Add ``ordinal_index`` and
         ``dimension_version`` last so they cover all rows.

    Total row count is exactly ``SCALE["vins"] == 4_734_904``.

    Determinism: seed=42 + same CMS DDB state → byte-identical parquet.
    The CMS fetch is the only source of external non-determinism; the
    generator does not retry.
    """
    # Lazy import so this module remains importable without the ``lib``
    # package on path (tests bootstrap it via a sys.path insertion).
    from lib import cms_demo_vins  # type: ignore[import-not-found]

    rng = np.random.default_rng(seed + 4)

    # Step 1: fetch CMS block.
    cms_records = cms_demo_vins.fetch_meridian_demo_vins()
    n_cms = len(cms_records)
    if n_cms == 0:
        # Defence-in-depth: fetch_meridian_demo_vins already raises on
        # empty; this branch is unreachable but pins the invariant.
        raise RuntimeError(
            "CMS demo VIN fetch returned an empty list — refusing to seed"
        )

    # Step 2 + 3: distribute CMS per (year, plant) and subtract from D1.
    cms_by_year_plant = _distribute_cms_by_year_plant(cms_records)
    procedural_targets: dict[int, dict[str, int]] = {}
    for year, plant_dist_full in _PLANT_DISTRIBUTION_BY_YEAR.items():
        procedural_targets[year] = {}
        cms_year = cms_by_year_plant.get(year, {})
        for plant, plant_full in plant_dist_full.items():
            cms_here = cms_year.get(plant, 0)
            procedural_targets[year][plant] = max(0, plant_full - cms_here)

    # Reconcile: if any (year, plant) went negative (CMS drift exceeded
    # a plant's D1 target), we've clamped to 0 above. Adjust the last
    # non-empty procedural bucket in the SAME year to absorb any deficit
    # so the yearly total matches after adding the CMS-block back.
    # In practice this is unreachable for the 21-row demo fleet.
    for year in procedural_targets:
        expected_proc = _YEAR_VIN_COUNTS[year] - sum(
            cms_by_year_plant.get(year, {}).values()
        )
        actual_proc = sum(procedural_targets[year].values())
        deficit = expected_proc - actual_proc
        if deficit != 0:
            # Add deficit to the plant with the largest bucket (typically
            # CGA in early years, then split by target size).
            plant_biggest = max(
                procedural_targets[year],
                key=lambda p: procedural_targets[year][p],
            )
            procedural_targets[year][plant_biggest] = max(
                0, procedural_targets[year][plant_biggest] + deficit
            )

    # Step 4: plan buckets.
    buckets = _plan_procedural_buckets(procedural_targets)

    # Step 5: generate each bucket.
    frames: list[pd.DataFrame] = []
    # CMS block first — ordinals 0..n_cms-1.
    frames.append(_build_cms_block(cms_records, rng))
    serial_offset = 0
    for year, plant, model, count in buckets:
        # Each bucket's serial numbering is contiguous in the concat order;
        # serial-offset carries across all procedural rows so no VIN
        # repeats within the pool.
        bucket_df = _generate_procedural_bucket(
            year=year,
            plant=plant,
            model=model,
            count=count,
            serial_offset=serial_offset,
            rng=rng,
        )
        frames.append(bucket_df)
        serial_offset += count

    # Step 6: concat + ordinal + version.
    df = pd.concat(frames, ignore_index=True)

    # Final row-count sanity — must be exactly SCALE["vins"] (spec R5).
    if len(df) != SCALE["vins"]:
        raise RuntimeError(
            f"gen_vins produced {len(df):,} rows; expected {SCALE['vins']:,} "
            f"(CMS={n_cms}, procedural={sum(c for _, _, _, c in buckets):,})"
        )

    df["ordinal_index"] = np.arange(len(df), dtype=np.int64)
    df["dimension_version"] = DIMENSION_VERSION
    return df


def gen_customers(seed: int) -> pd.DataFrame:
    fake = Faker("en_US")
    fake.seed_instance(seed + 5)
    rng = np.random.default_rng(seed + 5)
    n = SCALE["customers"]

    countries = ["US", "CA", "MX", "GB", "DE", "FR", "JP"]
    country_p = [0.65, 0.10, 0.05, 0.07, 0.05, 0.05, 0.03]
    segments = ["enthusiast", "family", "fleet", "commercial", "prospect"]
    segment_p = [0.10, 0.55, 0.05, 0.05, 0.25]

    name_pool = [fake.name() for _ in range(100_000)]
    email_pool = [fake.email() for _ in range(100_000)]

    name_idx = rng.integers(0, len(name_pool), size=n)
    email_idx = rng.integers(0, len(email_pool), size=n)

    df = pd.DataFrame(
        {
            "customer_id": [_customer_id(i) for i in range(n)],
            "ordinal_index": np.arange(n, dtype=np.int64),
            "full_name": [name_pool[i] for i in name_idx],
            "email": [email_pool[i] for i in email_idx],
            "country": rng.choice(countries, size=n, p=country_p),
            "customer_segment": rng.choice(segments, size=n, p=segment_p),
        }
    )
    base = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    delta_secs = rng.integers(0, 5 * 365 * 24 * 3600, size=n).astype("int64")
    df["created_at"] = [
        (base + datetime.timedelta(seconds=int(s))) for s in delta_secs
    ]
    df["dimension_version"] = DIMENSION_VERSION
    return df


def gen_time_calendar(seed: int) -> pd.DataFrame:
    n = SCALE["time_calendar"]
    dates = [TIME_ANCHOR + datetime.timedelta(days=i) for i in range(n)]
    df = pd.DataFrame(
        {
            "calendar_date": dates,
            "ordinal_index": np.arange(n, dtype=np.int64),
            "year": [d.year for d in dates],
            "quarter": [(d.month - 1) // 3 + 1 for d in dates],
            "month": [d.month for d in dates],
            "month_name": [d.strftime("%B") for d in dates],
            "week_of_year": [d.isocalendar()[1] for d in dates],
            "day_of_year": [d.timetuple().tm_yday for d in dates],
            "day_of_month": [d.day for d in dates],
            "day_of_week": [d.isoweekday() for d in dates],
            "day_name": [d.strftime("%A") for d in dates],
            "is_weekend": [d.isoweekday() >= 6 for d in dates],
            "is_us_holiday": [_is_us_holiday(d) for d in dates],
            "dimension_version": DIMENSION_VERSION,
        }
    )
    return df


def gen_charging_stations(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 7)
    fake = Faker("en_US")
    fake.seed_instance(seed + 7)

    networks = [
        ("TS", "Tesla Supercharger", "public_dc_fast", ["NACS", "CCS1"], 250.0),
        ("EA", "Electrify America", "public_dc_fast", ["CCS1", "NACS"], 350.0),
        ("EVGO", "EVgo", "public_dc_fast", ["CCS1", "CHAdeMO"], 200.0),
        ("CP", "ChargePoint", "destination_l2", ["J1772", "CCS1"], 11.5),
        ("HOME", "home", "home_l2", ["J1772"], 11.5),
        ("DEST", "destination", "destination_l2", ["J1772"], 11.5),
    ]
    weights = np.array([0.20, 0.20, 0.10, 0.10, 0.30, 0.10])
    n = SCALE["charging_stations"]
    network_idx = rng.choice(len(networks), size=n, p=weights)

    rows: list[dict[str, Any]] = []
    for i, ni in enumerate(network_idx):
        code, provider, station_type, connectors, base_kw = networks[int(ni)]
        is_synthetic_private = code in {"HOME", "DEST"}
        stall_count = 1 if is_synthetic_private else int(rng.integers(2, 16))
        power_kw = float(base_kw * rng.uniform(0.8, 1.2))
        if is_synthetic_private:
            lat = None
            lon = None
            city = None
            state = None
        else:
            lat = float(rng.uniform(24.5, 49.0))
            lon = float(rng.uniform(-124.7, -67.0))
            city = fake.city()
            state = rng.choice(US_STATES).item()
        opened_date = (
            None if is_synthetic_private
            else (TIME_ANCHOR + datetime.timedelta(days=int(rng.integers(0, 1825))))
        )
        rows.append(
            {
                "station_id": _station_id(code, i + 1),
                "ordinal_index": i,
                "network_provider": provider,
                "network_code": code,
                "station_type": station_type,
                "connector_types": connectors,
                "max_power_kw": power_kw,
                "stall_count": stall_count,
                "latitude": lat,
                "longitude": lon,
                "city": city,
                "state": state,
                "country": "US",
                "opened_date": opened_date,
                "dimension_version": DIMENSION_VERSION,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# US holidays (simple set — sufficient for synthetic data narratives)
# ---------------------------------------------------------------------------


def _is_us_holiday(d: datetime.date) -> bool:
    """Return True for fixed-date and the major movable US federal holidays."""
    fixed = {(1, 1), (7, 4), (11, 11), (12, 25)}
    if (d.month, d.day) in fixed:
        return True
    if d.month == 5 and d.weekday() == 0 and d.day > 24:
        return True
    if d.month == 9 and d.weekday() == 0 and d.day <= 7:
        return True
    if d.month == 11 and d.weekday() == 3 and 22 <= d.day <= 28:
        return True
    if d.month == 1 and d.weekday() == 0 and 15 <= d.day <= 21:
        return True
    if d.month == 2 and d.weekday() == 0 and 15 <= d.day <= 21:
        return True
    if d.month == 6 and d.day == 19:
        return True
    if d.month == 10 and d.weekday() == 0 and 8 <= d.day <= 14:
        return True
    return False


def _round_decimal(x: float) -> "Decimal":
    """Round to 2 decimal places and return as Decimal for parquet decimal128."""
    from decimal import Decimal, ROUND_HALF_UP
    return Decimal(str(round(x, 2))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class DimensionSpec:
    name: str
    func: Callable[..., pd.DataFrame]
    deps: tuple[str, ...] = ()


DIMENSION_SPECS: tuple[DimensionSpec, ...] = (
    DimensionSpec("dealers", gen_dealers),
    DimensionSpec("suppliers", gen_suppliers),
    DimensionSpec("parts", gen_parts, deps=("suppliers",)),
    DimensionSpec("vins", gen_vins),
    DimensionSpec("customers", gen_customers),
    DimensionSpec("time_calendar", gen_time_calendar),
    DimensionSpec("charging_stations", gen_charging_stations),
)


def _write_parquet(
    df: pd.DataFrame, path: Path, *, schema: pa.Schema | None = None
) -> bytes:
    """Write df to parquet at ``path`` (creating parents) and return raw bytes for hashing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    buf = pa.BufferOutputStream()
    pq.write_table(
        table,
        buf,
        compression="zstd",
        version="2.6",
        write_statistics=True,
        store_schema=True,
    )
    raw = bytes(buf.getvalue())
    path.write_bytes(raw)
    return raw


def _write_manifest(
    name: str,
    *,
    seed: int,
    rows: int,
    sha: str,
    out_dir: Path,
) -> None:
    manifest = {
        "dimension_name": name,
        "dimension_version": DIMENSION_VERSION,
        "row_count": rows,
        "generator_seed": seed,
        "data_sha256": sha,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


def generate_all(*, seed: int, output_root: Path | str) -> dict[str, dict[str, Any]]:
    """Generate every dimension. Return a manifest summary keyed by dimension name."""
    output = Path(output_root) if not isinstance(output_root, Path) else output_root
    output.mkdir(parents=True, exist_ok=True)

    cache: dict[str, pd.DataFrame] = {}
    summary: dict[str, dict[str, Any]] = {}

    for spec in DIMENSION_SPECS:
        deps_args: list[Any] = []
        for dep in spec.deps:
            if dep not in cache:
                raise RuntimeError(f"dimension '{spec.name}' depends on unbuilt '{dep}'")
            deps_args.append(cache[dep])

        df = spec.func(seed, *deps_args)
        cache[spec.name] = df

        out_dir = output / spec.name
        parquet_path = out_dir / "data.parquet"
        raw = _write_parquet(df, parquet_path)
        sha = _sha256_of_bytes(raw)
        _write_manifest(
            spec.name, seed=seed, rows=len(df), sha=sha, out_dir=out_dir
        )
        summary[spec.name] = {
            "rows": len(df),
            "sha256": sha,
            "path": str(parquet_path.relative_to(output.parent))
            if parquet_path.is_relative_to(output.parent)
            else str(parquet_path),
        }
        print(f"  ✓ {spec.name}: {len(df):,} rows ({sha[:16]}...)", file=sys.stderr)

    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate_dimensions",
        description="Generate the ADP foundation dimension catalog (7 dimensions).",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Deterministic seed (default: 42)"
    )
    parser.add_argument(
        "--output-root",
        default=str(Path(__file__).resolve().parents[2] / "dimensions"),
        help="Output root directory (default: platform-foundation/dimensions/)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run with reduced row counts (1%% of full scale) for fast iteration",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.dry_run:
        for k in list(SCALE.keys()):
            if k == "time_calendar":
                continue
            SCALE[k] = max(200, SCALE[k] // 100)
        print(f"DRY RUN — using reduced scales: {SCALE}", file=sys.stderr)

    print(
        f"Generating 7 dimensions @ seed={args.seed} "
        f"to {args.output_root} ...",
        file=sys.stderr,
    )
    summary = generate_all(seed=args.seed, output_root=args.output_root)
    total_rows = sum(s["rows"] for s in summary.values())
    print(f"Done. Total rows generated: {total_rows:,}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
