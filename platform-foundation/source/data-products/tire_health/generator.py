"""Generator for ``tire_health`` (per-VIN per-tire daily aggregate, pandas tier).

Per decisions.md (a)(b)(e):
- Grain: (vin, tire_position, event_date) daily aggregate, directly joinable to
  vehicle_telemetry_aggregated on (vin, event_date).
- Supervised labels: needs_replacement (bool), wear_category (ok/monitor/replace)
  derived from tread_depth_mm thresholds.
- Wear model: tread depth = monotonic fn(cumulative_distance) + noise.
  Starts at 7–9 mm for new tyres. Two worn sub-cohorts represent vehicles already
  into their tyre lifecycle:
    - monitor cohort (20%): start at 2.5–4.5 mm → transitions into monitor zone
    - critical cohort (10%): start at 0.5–2.5 mm → at or near replace threshold
  Decays roughly 0.5–1.0 mm per 10,000 km depending on tyre position (rears wear
  faster on FWD, fronts wear faster on RWD).
- Tyre positions: FL, FR, RL, RR — 4 rows per VIN per day.
- Pressure: base 32 PSI with Gaussian noise; slow-leak anomalies injected at 5%.
- Temperature: ambient + driving-speed proxy + noise; no PII.
- Default scale produces ~60 days × VIN-pool × 4 positions.

Label distribution at default seed (scale=1.0, WINDOW_DAYS=60):
  ~70% ok / ~20% monitor / ~10% replace — all three supervised classes present.
  The worn cohort (WORN_COHORT_FRACTION = 0.25) seeds tyres at 2.5–4.5 mm so
  that transitions into monitor and replace occur within the 60-day window.

Thresholds (from decisions.md + tech.md §4.6):
  needs_replacement = True  when tread_depth_mm < 2.0
  wear_category     = 'replace'  when tread_depth_mm < 2.0
  wear_category     = 'monitor'  when 2.0 <= tread_depth_mm < 4.0
  wear_category     = 'ok'       when tread_depth_mm >= 4.0

FK contract: every vin value is drawn from dimensions["vins"]["vin"].
orphan_fk rate: 0.0% (enforced by drawing only from the VIN pool).

Run::

    python source/data-products/tire_health/generator.py \\
        --seed 42 --output-root /tmp/adp-curated --scale 0.1
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

_LIB = Path(__file__).resolve().parents[3] / "source" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from product_generator import ProductGenerator  # noqa: E402
from schema_loader import Table  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default: 60-day rolling window, 4 positions → ~240 rows per VIN.
# Full-quota scale=1.0 generates for all VINs in the dimension.
WINDOW_DAYS = 60

TIRE_POSITIONS = ["FL", "FR", "RL", "RR"]

# Tread depth thresholds (mm)
REPLACE_THRESHOLD_MM = 2.0
MONITOR_THRESHOLD_MM = 4.0

# Starting tread depth range (mm) — new tyre 7–9 mm
TREAD_START_MIN_MM = 7.0
TREAD_START_MAX_MM = 9.0

# Worn cohort: fraction of (vin, position) pairs that start with worn tread,
# representing vehicles 8–18 months into their tyre lifecycle at install time.
# Two sub-cohorts produce the full label distribution within the 60-day window:
#   - WORN_COHORT_FRACTION_MONITOR (20%): start at 2.5–4.5 mm → transitions into monitor
#   - WORN_COHORT_FRACTION_REPLACE (10%): start at 0.5–2.5 mm → transitions into / is already replace
# Together they produce the target distribution: ~70% ok / ~20% monitor / ~10% replace.
WORN_COHORT_FRACTION_MONITOR = 0.20
WORN_COHORT_FRACTION_REPLACE = 0.10
WORN_TREAD_START_MIN_MM = 2.5
WORN_TREAD_START_MAX_MM = 4.5
CRITICAL_TREAD_START_MIN_MM = 0.5   # at or near replace threshold (2.0 mm)
CRITICAL_TREAD_START_MAX_MM = 2.5   # just below monitor → into replace zone

# Wear rate variability per position (mm per km, before scaling by position):
# Rear tyres on FWD cars wear faster; fronts on RWD wear faster.
# Base: ~0.05–0.10 mm per 1,000 km for "normal" driving.
WEAR_RATE_BASE_PER_KM = 0.00007  # mm per km (= 0.07 mm / 1000 km)

# Slow-leak anomaly injection rate (5% of VIN-position pairs)
SLOW_LEAK_RATE = 0.05

# Base tyre pressure (PSI)
PRESSURE_BASE_PSI = 32.0
PRESSURE_NOISE_STD = 0.8
TEMP_AMBIENT_C = 15.0
TEMP_NOISE_STD = 5.0


def _stable_seed(seed: int, vin: str, pos: str, day_offset: int) -> int:
    """Return a stable, cross-session-reproducible integer seed for a single row.

    Uses SHA-256 (truncated to 4 bytes) instead of Python's built-in ``hash()``
    which is salted by PYTHONHASHSEED and NOT stable across interpreter sessions.
    The resulting value is always in [0, 2**31 - 1] for compatibility with
    ``np.random.default_rng``.
    """
    key = f"{seed}:{vin}:{pos}:{day_offset}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:4], byteorder="big") & 0x7FFFFFFF


class TireHealthGenerator(ProductGenerator):
    """Generates per-VIN per-tire per-day tire health aggregates.

    Deterministic (seeded RNG), within-quota (pandas tier,
    follows existing service_records conventions).

    Label distribution at default seed:
        ~70% ok / ~20% monitor / ~10% replace.
    Achieved by two worn sub-cohorts:
      - monitor cohort (20% of pairs): start at 2.5–4.5 mm → monitor zone within window
      - critical cohort (10% of pairs): start at 0.5–2.5 mm → replace zone immediately/within window
    Cohort assignment uses a stable SHA-256 hash of (seed, vin, position), so the
    same pairs are always in the same cohort regardless of iteration order or Python
    PYTHONHASHSEED setting.
    """

    product_name = "tire_health"

    def generate_table(
        self,
        table: Table,
        *,
        seed: int,
        scale: float,
        dimensions: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed + 700)

        vins_df = dimensions["vins"]
        vin_pool = vins_df["vin"].to_numpy()

        # Apply scale: take a slice of the VIN pool (deterministic selection).
        n_vins = max(1, int(len(vin_pool) * scale))
        # Deterministic subset — same seed always picks the same VINs.
        vin_idx = rng.choice(len(vin_pool), size=n_vins, replace=False)
        vin_idx.sort()
        selected_vins = vin_pool[vin_idx]

        # Build the date range: WINDOW_DAYS ending today-1.
        today = dt.date.today()
        start_date = today - dt.timedelta(days=WINDOW_DAYS)
        dates = [start_date + dt.timedelta(days=i) for i in range(WINDOW_DAYS)]

        # Per VIN × per position: assign a starting tread depth and wear rate.
        n_pairs = n_vins * len(TIRE_POSITIONS)

        # Worn-cohort assignment: deterministically flag pairs as pre-worn based on
        # each pair's own stable hash, so cohort assignment is byte-identical across
        # runs and independent of iteration order.
        # Two sub-cohorts:
        #   hash_val < WORN_COHORT_FRACTION_REPLACE                          → critical (0.5–2.5 mm)
        #   WORN_COHORT_FRACTION_REPLACE <= hash_val < (REPLACE + MONITOR)   → monitor-worn (2.5–4.5 mm)
        #   otherwise                                                         → new (7.0–9.0 mm)
        cohort_fraction_replace = WORN_COHORT_FRACTION_REPLACE
        cohort_fraction_monitor = WORN_COHORT_FRACTION_MONITOR

        cohort_vals = np.array(
            [
                int.from_bytes(
                    hashlib.sha256(f"{seed}:worn:{v}:{p}".encode()).digest()[:4],
                    byteorder="big",
                )
                / 0xFFFFFFFF
                for v in selected_vins
                for p in TIRE_POSITIONS
            ]
        )
        # True where pair is in the critical (replace-zone) sub-cohort
        critical_flags = cohort_vals < cohort_fraction_replace
        # True where pair is in the monitor-worn sub-cohort
        monitor_flags = (cohort_vals >= cohort_fraction_replace) & (
            cohort_vals < (cohort_fraction_replace + cohort_fraction_monitor)
        )

        # Starting tread: critical cohort [0.5, 2.5] mm, monitor cohort [2.5, 4.5] mm, rest [7.0, 9.0] mm.
        tread_starts_normal = rng.uniform(TREAD_START_MIN_MM, TREAD_START_MAX_MM, size=n_pairs)
        tread_starts_monitor = rng.uniform(WORN_TREAD_START_MIN_MM, WORN_TREAD_START_MAX_MM, size=n_pairs)
        tread_starts_critical = rng.uniform(CRITICAL_TREAD_START_MIN_MM, CRITICAL_TREAD_START_MAX_MM, size=n_pairs)
        tread_starts = np.where(critical_flags, tread_starts_critical,
                                np.where(monitor_flags, tread_starts_monitor, tread_starts_normal))

        # Position wear multipliers: RL/RR wear ~1.15× faster on the default FWD model;
        # FL/FR wear at 1.0× baseline. Per-VIN noise factor ±20%.
        position_mults = np.tile([1.0, 1.0, 1.15, 1.15], n_vins)  # FL, FR, RL, RR order
        per_pair_noise = rng.uniform(0.80, 1.20, size=n_pairs)
        wear_per_km = WEAR_RATE_BASE_PER_KM * position_mults * per_pair_noise  # mm / km

        # Slow-leak flags: ~5% of VIN-position pairs get a leaking tyre.
        slow_leak_mask = rng.random(size=n_pairs) < SLOW_LEAK_RATE

        # Build records list.
        records = []

        for pair_idx, (vin, pos) in enumerate(
            (v, p) for v in selected_vins for p in TIRE_POSITIONS
        ):
            tread = tread_starts[pair_idx]
            wear_rate = wear_per_km[pair_idx]
            is_leaking = bool(slow_leak_mask[pair_idx])

            cumulative_km = 0.0

            for day_offset, date in enumerate(dates):
                # Daily distance: gamma-distributed km, ~50 km/day mean.
                # Use a stable per-row seed (SHA-256 based, not hash()) for
                # cross-session reproducibility (PYTHONHASHSEED independence).
                day_seed = _stable_seed(seed, vin, pos, day_offset)
                day_rng = np.random.default_rng(day_seed)

                daily_km = float(day_rng.gamma(shape=3.0, scale=17.0))
                cumulative_km += daily_km

                # Tread depth: monotonically decreasing fn of cumulative_km + small noise.
                daily_wear = wear_rate * daily_km
                noise = float(day_rng.normal(0.0, 0.001))
                tread = max(0.0, tread - daily_wear + noise)

                # Wear rate in mm per 1,000 km (avoid divide-by-zero on first day).
                if daily_km > 0:
                    wear_rate_1k = float(daily_wear / daily_km * 1000)
                else:
                    wear_rate_1k = None

                # Pressure: base + Gaussian noise + slow-leak drift.
                pressure_base = PRESSURE_BASE_PSI
                if is_leaking:
                    # 0.3–1.2 PSI drop per day (matches PM's synthetic schema §1.8)
                    leak_rate = float(day_rng.uniform(0.3, 1.2))
                    pressure_base -= leak_rate * (day_offset + 1)
                    pressure_base = max(5.0, pressure_base)
                pressure_avg = float(day_rng.normal(pressure_base, PRESSURE_NOISE_STD))
                pressure_avg = max(5.0, pressure_avg)
                pressure_min = pressure_avg - float(abs(day_rng.normal(0.5, 0.3)))
                pressure_min = max(0.0, pressure_min)
                pressure_max = pressure_avg + float(abs(day_rng.normal(0.5, 0.3)))

                # Temperature: ambient + heat from driving + noise.
                temp_avg = TEMP_AMBIENT_C + (daily_km * 0.05) + float(day_rng.normal(0.0, TEMP_NOISE_STD))
                temp_max = temp_avg + float(abs(day_rng.normal(8.0, 3.0)))

                # Derived labels.
                needs_replacement = bool(tread < REPLACE_THRESHOLD_MM)
                if tread < REPLACE_THRESHOLD_MM:
                    wear_category = "replace"
                elif tread < MONITOR_THRESHOLD_MM:
                    wear_category = "monitor"
                else:
                    wear_category = "ok"

                event_time = pd.Timestamp(date, tz="UTC")
                now_ts = pd.Timestamp.utcnow().tz_convert("UTC")

                records.append(
                    {
                        "vin": vin,
                        "tire_position": pos,
                        "event_date": date,
                        "tread_depth_mm": round(tread, 4),
                        "pressure_psi_avg": round(pressure_avg, 3),
                        "pressure_psi_min": round(pressure_min, 3),
                        "pressure_psi_max": round(pressure_max, 3),
                        "temp_c_avg": round(temp_avg, 3),
                        "temp_c_max": round(temp_max, 3),
                        "distance_km": round(daily_km, 3),
                        "wear_rate_mm_per_1k_km": round(wear_rate_1k, 6) if wear_rate_1k is not None else None,
                        "needs_replacement": needs_replacement,
                        "wear_category": wear_category,
                        "event_time": event_time,
                        "ingest_time": now_ts,
                    }
                )

        df = pd.DataFrame(records)
        # Enforce dtypes to match schema expectations.
        df["vin"] = df["vin"].astype("string")
        df["tire_position"] = df["tire_position"].astype("string")
        df["event_date"] = pd.to_datetime(df["event_date"]).dt.date
        df["tread_depth_mm"] = df["tread_depth_mm"].astype("Float64")
        df["pressure_psi_avg"] = df["pressure_psi_avg"].astype("Float64")
        df["pressure_psi_min"] = df["pressure_psi_min"].astype("Float64")
        df["pressure_psi_max"] = df["pressure_psi_max"].astype("Float64")
        df["temp_c_avg"] = df["temp_c_avg"].astype("Float64")
        df["temp_c_max"] = df["temp_c_max"].astype("Float64")
        df["distance_km"] = df["distance_km"].astype("Float64")
        df["wear_rate_mm_per_1k_km"] = df["wear_rate_mm_per_1k_km"].astype("Float64")
        df["needs_replacement"] = df["needs_replacement"].astype("boolean")
        df["wear_category"] = df["wear_category"].astype("string")
        df["event_time"] = pd.to_datetime(df["event_time"], utc=True)
        df["ingest_time"] = pd.to_datetime(df["ingest_time"], utc=True)
        return df


def main() -> int:
    p = argparse.ArgumentParser(description="Generate tire_health data product")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--scale", type=float, default=1.0,
                   help="Fraction of the VIN pool to generate (0.0–1.0). Default 1.0 (all VINs).")
    p.add_argument("--dim-root", default="dimensions")
    p.add_argument("--output-root", default="curated")
    p.add_argument("--register-iceberg", action="store_true")
    p.add_argument("--s3-lake-bucket", default=None)
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    g = TireHealthGenerator(
        seed=args.seed,
        scale=args.scale,
        output_root=args.output_root,
        region=args.region,
    )
    bucket = args.s3_lake_bucket
    if bucket is None and args.output_root.startswith("s3://"):
        bucket = args.output_root.replace("s3://", "").split("/", 1)[0]
    summary = g.run(
        dim_root=Path(args.dim_root),
        register_iceberg=args.register_iceberg,
        s3_lake_bucket=bucket,
    )
    import json
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
