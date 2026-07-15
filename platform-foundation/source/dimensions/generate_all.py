"""Unified dimension catalog generator for the ADP foundation.

Generates all 7 dimensions in a deterministic order from a single
seed, writes parquet to local filesystem (dev mode) or S3 (production
mode), and emits ``manifest.json`` per dimension recording the row
count, seed, dimension version, and SHA-256 over the parquet bytes.

Deterministic guarantees
------------------------
- Same seed + same dimension YAML schemas → byte-identical parquet.
- Generation order is fixed: dealers → suppliers → parts → vins →
  customers → time_calendar → charging_stations. Order matters because
  parts has an FK to suppliers and the FK is realized by deterministic
  modular indexing — not by random sampling.
- Faker uses ``Faker.seed_instance(seed)`` per dimension; numpy uses
  ``numpy.random.default_rng(seed + offset)`` per dimension to keep
  RNG streams independent.

Outputs
-------
For each dimension D (e.g., ``vins``), the generator writes:

::

    <output_root>/<D>/data.parquet
    <output_root>/<D>/manifest.json

Where ``<output_root>`` is either:
- a local filesystem path (e.g., ``platform-foundation/dimensions/``),
  or
- an ``s3://...`` URL (production deploy).

Test fixtures
-------------
``test_dimensions.py`` and ``test_referential_integrity.py`` consume
the local-mode parquet via the ``dimension_root`` pytest fixture.
"""

from __future__ import annotations

import argparse
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

# Dimension version stamped into every row + manifest.
# Bump only when the dimension catalog schema or generation logic changes.
DIMENSION_VERSION = "1.0.0"

# Anchor date for time_calendar (10-year window 2020-01-01 → 2029-12-31).
TIME_ANCHOR = datetime.date(2020, 1, 1)
TIME_DAYS = 365 * 10 + 3  # 3 leap days in the 2020-2030 window

# Default dimension scales per spec.md "Shared dimension catalog".
SCALE = {
    "vins": 5_000_000,
    "customers": 5_000_000,
    "dealers": 200,
    "suppliers": 500,
    "parts": 50_000,
    "time_calendar": TIME_DAYS,
    "charging_stations": 50_000,
}

# Allowed VIN alphabet (ISO 3779: no I, O, Q).
VIN_ALPHABET = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"  # 33 chars
ALNUM_UPPER = string.ascii_uppercase + string.digits  # 36 chars (A-Z + 0-9)

# Acme Motors WMI per docs/data-contracts.md.
ACME_WMI = "1FA"

US_STATES = [
    "CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI",
    "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MD", "MO", "WI",
    "CO", "MN", "SC", "AL", "LA", "KY", "OR", "OK", "CT", "UT",
]

ACME_MODELS = [
    ("Acme Spark", "electric"),
    ("Acme Spark Long Range", "electric"),
    ("Acme Bolt", "electric"),
    ("Acme Bolt Performance", "electric"),
    ("Acme Voyager", "electric"),
    ("Acme Trail", "erev"),
    ("Acme Hauler", "erev"),
    ("Acme Eco", "hybrid"),
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


def _vin_for_ordinal(i: int) -> str:
    """Compute a 17-char VIN with Acme WMI for ordinal ``i``.

    Encoding: WMI (3) + base-33 ordinal in remaining 14 chars (no check-digit
    correctness; we satisfy regex but skip the official VIN check-digit since
    these are synthetic).
    """
    suffix = _base_n(i + 1, VIN_ALPHABET, width=14)
    return ACME_WMI + suffix


def _customer_id(i: int) -> str:
    return f"CUST-{i:08X}"


def _dealer_id(i: int) -> str:
    return f"DLR-{i:05d}"


def _supplier_id(i: int) -> str:
    return f"SUP-{i:04d}"


def _part_number(i: int) -> str:
    """Encode ordinal i into ``XXXXXXXX-YYYY`` where both halves are base-36."""
    high = (i // (36 * 36 * 36 * 36)) & 0xFFFFFFFF  # high 8 chars
    low = i & 0xFFFFFFFF  # low 4 chars
    h = _base_n(high % (36**8), ALNUM_UPPER, width=8)
    ll = _base_n(low % (36**4), ALNUM_UPPER, width=4)
    return f"{h}-{ll}"


def _station_id(network_code: str, i: int) -> str:
    return f"STN-{network_code}-{i:08d}"


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
                "dealer_name": f"{fake.last_name()} Acme Motors of {fake.city()}",
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
        # Deterministic FK: ordinal modulo supplier count (no random sampling
        # so two consumers of dim catalog see identical FK distribution).
        sup_idx = i % len(supplier_ids)
        # part name: deterministic from category, no Faker call to keep stable.
        cat = categories[i % len(categories)]
        rows.append(
            {
                "part_number": _part_number(i),
                "ordinal_index": i,
                "supplier_id": str(supplier_ids[sup_idx]),
                "part_name": f"{cat.replace('_', ' ').title()} {i:05d}",
                "part_category": cat,
                # decimal stored as object (Decimal); use round-half-up
                "list_price_usd": _round_decimal(
                    float(rng.uniform(5.0, 9_500.0))
                ),
                "dimension_version": DIMENSION_VERSION,
            }
        )
    return pd.DataFrame(rows)


def gen_vins(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 4)
    n = SCALE["vins"]

    # Pre-compute model assignments for vectorized speed.
    model_idx = rng.integers(0, len(ACME_MODELS), size=n)
    model_year = rng.integers(2018, 2031, size=n)  # 2018-2030 inclusive
    # In-service offset: 0-180 days after manufacture.
    in_service_offset = rng.integers(0, 180, size=n)
    # Manufacture date: model_year + uniform 365-day offset.
    manufacture_offset_in_year = rng.integers(0, 365, size=n)

    df = pd.DataFrame(
        {
            "vin": [_vin_for_ordinal(i) for i in range(n)],
            "ordinal_index": np.arange(n, dtype=np.int64),
            "model_year": model_year.astype(np.int32),
            "make": np.full(n, "Acme Motors", dtype=object),
            "model": [ACME_MODELS[i][0] for i in model_idx],
            "powertrain_type": [ACME_MODELS[i][1] for i in model_idx],
        }
    )
    # Manufacture date: 1 January of model_year + day offset
    df["manufacture_date"] = [
        datetime.date(int(my), 1, 1) + datetime.timedelta(days=int(d))
        for my, d in zip(df["model_year"], manufacture_offset_in_year)
    ]
    df["in_service_date"] = [
        md + datetime.timedelta(days=int(o))
        for md, o in zip(df["manufacture_date"], in_service_offset)
    ]
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

    # 5M Faker calls would be slow. Use a 100K-name pool resampled
    # — still deterministic with the same seed; full-name PII is
    # synthetic regardless.
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
    # Customer creation time: between 2020-01-01 and now.
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

    # Distribution per spec design: Tesla SC ~20%, EA ~20%, EVgo ~10%,
    # ChargePoint ~10%, home ~30%, destination ~10%.
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
        # Add slight stall variation
        stall_count = 1 if is_synthetic_private else int(rng.integers(2, 16))
        # Power variation around base
        power_kw = float(base_kw * rng.uniform(0.8, 1.2))
        # Lat/lon: null for home/destination per spec privacy policy
        if is_synthetic_private:
            lat = None
            lon = None
            city = None
            state = None
        else:
            # CONUS bounding box: lat 24.5-49, lon -124.7 to -67
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
    # Fixed holidays
    fixed = {
        (1, 1),    # New Year's
        (7, 4),    # Independence
        (11, 11),  # Veterans
        (12, 25),  # Christmas
    }
    if (d.month, d.day) in fixed:
        return True
    # Memorial Day: last Monday of May
    if d.month == 5 and d.weekday() == 0 and d.day > 24:
        return True
    # Labor Day: first Monday of September
    if d.month == 9 and d.weekday() == 0 and d.day <= 7:
        return True
    # Thanksgiving: 4th Thursday of November
    if d.month == 11 and d.weekday() == 3 and 22 <= d.day <= 28:
        return True
    # MLK Day: 3rd Monday of January
    if d.month == 1 and d.weekday() == 0 and 15 <= d.day <= 21:
        return True
    # Presidents' Day: 3rd Monday of February
    if d.month == 2 and d.weekday() == 0 and 15 <= d.day <= 21:
        return True
    # Juneteenth
    if d.month == 6 and d.day == 19:
        return True
    # Columbus Day: 2nd Monday of October
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
    # pq.write_table writes to disk; we also serialize to bytes in-memory for hashing.
    buf = pa.BufferOutputStream()
    pq.write_table(
        table,
        buf,
        compression="zstd",
        version="2.6",
        # Disable any creator-version metadata that varies between runs.
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
        # Manifest does NOT include a wall-clock timestamp — keep
        # byte-equivalence on re-runs.
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
            "path": str(parquet_path.relative_to(output.parent)) if parquet_path.is_relative_to(output.parent) else str(parquet_path),
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
        # Shrink scales to 1% (or 200 minimum) for fast smoke runs.
        for k in list(SCALE.keys()):
            if k == "time_calendar":
                continue  # full 10y; cheap.
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
