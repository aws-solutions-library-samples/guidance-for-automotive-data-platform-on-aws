"""Generator for ``charging_sessions`` (20M rows over 3y).

Per spec.md "Schemas for the three new EV-Operations products":
~70% home (L1/L2), ~25% public DC fast, ~5% destination L2.
Session duration correlates with station_type. 1–3% edge-case
injection including realistic interrupt scenarios.

FKs: vins, customers (nullable; ~10% guest sessions), charging_stations.

Pandas tier per spec. 20M rows ≈ 5-7 min wall clock at full scale.
Configurable via ``--scale``.

Run::

    python source/data-products/charging_sessions/generator.py \\
        --seed 42 --output-root /tmp/adp-curated --scale 0.05
"""

from __future__ import annotations

import argparse
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

_LIB = Path(__file__).resolve().parents[3] / "source" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from product_generator import ProductGenerator  # noqa: E402
from schema_loader import Table  # noqa: E402

DEFAULT_TARGET_ROWS = 20_000_000
WINDOW_DAYS = 365 * 3

# station_type → typical duration range (seconds), avg power kw, kWh delivered
STATION_PROFILES = {
    "home_l1": {"duration": (8 * 3600, 14 * 3600), "power": (1.4, 2.4), "kwh": (10, 25)},
    "home_l2": {"duration": (4 * 3600, 8 * 3600), "power": (7.0, 11.5), "kwh": (30, 80)},
    "public_dc_fast": {"duration": (15 * 60, 60 * 60), "power": (50, 250), "kwh": (20, 80)},
    "destination_l2": {"duration": (2 * 3600, 6 * 3600), "power": (7.0, 11.5), "kwh": (15, 50)},
}
NETWORK_BY_STATION_PREFIX = {
    "TS": "Tesla Supercharger",
    "EA": "Electrify America",
    "EVGO": "EVgo",
    "CP": "ChargePoint",
    "HOME": "home",
    "DEST": "destination",
}
CONNECTOR_BY_NETWORK = {
    "Tesla Supercharger": "NACS",
    "Electrify America": "CCS1",
    "EVgo": "CCS1",
    "ChargePoint": "J1772",
    "home": "J1772",
    "destination": "J1772",
}
INTERRUPT_REASONS = ["user_unplug", "station_fault", "vehicle_fault", "network_drop"]
INTERRUPT_PROBS = [0.55, 0.20, 0.15, 0.10]


class ChargingSessionsGenerator(ProductGenerator):
    product_name = "charging_sessions"

    def generate_table(
        self,
        table: Table,
        *,
        seed: int,
        scale: float,
        dimensions: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed + 500)
        vins = dimensions["vins"]
        customers = dimensions["customers"]
        stations = dimensions["charging_stations"]
        n = max(1, int(DEFAULT_TARGET_ROWS * scale))

        vin_pool = vins["vin"].to_numpy()
        customer_pool = customers["customer_id"].to_numpy()

        # Defensive: every charging session row references a station
        # via station_type bucketing. If the dimensions DataFrame is
        # ever materialized without ``station_type`` (e.g., a future
        # schema change drops the column or a malformed seed), fail
        # loudly here rather than KeyError mid-loop on row sampling.
        if "station_type" not in stations.columns:
            raise KeyError(
                "charging_stations dimension is missing required column "
                "'station_type'. Schema drift suspected — verify "
                "scripts/seed_charging_stations.py and "
                "source/data-products/charging_stations/schema.yaml."
            )

        # Bucket stations by station_type so we can sample by realism distribution.
        st_by_type: dict[str, np.ndarray] = {}
        for stype in STATION_PROFILES:
            mask = stations["station_type"].to_numpy() == stype
            st_by_type[stype] = stations.loc[mask, "station_id"].to_numpy()

        # Realistic mix per spec: 70% home (L1+L2), 25% public DC, 5% destination L2.
        # Within "home", split L2/L1 ~ 80/20.
        type_choices = rng.choice(
            ["home_l1", "home_l2", "public_dc_fast", "destination_l2"],
            size=n,
            p=[0.14, 0.56, 0.25, 0.05],
        )

        # Pre-sample station_id per row honoring station_type buckets
        station_ids = np.empty(n, dtype=object)
        for stype in STATION_PROFILES:
            mask = type_choices == stype
            count = int(mask.sum())
            pool = st_by_type[stype]
            if count == 0 or len(pool) == 0:
                continue
            station_ids[mask] = rng.choice(pool, size=count)

        df = pd.DataFrame()
        df["session_id"] = pd.Series(
            [str(uuid.UUID(int=int.from_bytes(rng.bytes(16), "big"))) for _ in range(n)],
            dtype="string",
        )
        df["vin"] = pd.Series(rng.choice(vin_pool, size=n), dtype="string")
        # customer_id null for ~10% of public sessions
        cust_mask = (rng.random(size=n) < 0.90) | (
            np.isin(type_choices, ["home_l1", "home_l2"])
        )
        df["customer_id"] = pd.Series(
            np.where(cust_mask, rng.choice(customer_pool, size=n), None),
            dtype="string",
        )

        # Time spread: WINDOW_DAYS, recency-skewed
        time_offsets = (rng.beta(2.0, 3.0, size=n) * WINDOW_DAYS * 86400).astype("int64")
        anchor = pd.Timestamp.utcnow().tz_convert("UTC") - pd.Timedelta(days=WINDOW_DAYS)
        start_time = anchor + pd.to_timedelta(time_offsets, unit="s")

        durations = np.empty(n, dtype="int64")
        kwh = np.empty(n, dtype="float64")
        avg_power = np.empty(n, dtype="float64")
        peak_power = np.empty(n, dtype="float64")
        connector = np.empty(n, dtype=object)
        provider = np.empty(n, dtype=object)
        for stype in STATION_PROFILES:
            mask = type_choices == stype
            count = int(mask.sum())
            if count == 0:
                continue
            prof = STATION_PROFILES[stype]
            durations[mask] = rng.integers(prof["duration"][0], prof["duration"][1], size=count)
            kwh[mask] = rng.uniform(prof["kwh"][0], prof["kwh"][1], size=count)
            avg_power[mask] = rng.uniform(prof["power"][0], prof["power"][1], size=count)
            peak_power[mask] = avg_power[mask] * rng.uniform(1.05, 1.5, size=count)

        # Resolve provider/connector from station prefix.
        # Per 2026-06-02 fix (within-quota-seed spec, decisions.md "STOP at
        # Group 2"): preserve None values rather than coercing to the
        # literal string 'None'. Home-charging rows leave ``station_ids[i]``
        # as ``None`` (the per-stype loop above only fills indices for
        # public/destination stations; home_l1/home_l2 are not in
        # STATION_PROFILES). Bare ``str(s)`` produced 2.8M orphan
        # station_ids (14% of rows) under the integrity-test contract.
        st_arr = np.array(
            [str(s) if s is not None else None for s in station_ids],
            dtype=object,
        )
        for i in range(n):
            if st_arr[i] is None or pd.isna(st_arr[i]):
                provider[i] = None
                connector[i] = "J1772"
                continue
            parts = st_arr[i].split("-")
            if len(parts) >= 2:
                pfx = parts[1]
                provider[i] = NETWORK_BY_STATION_PREFIX.get(pfx, "unknown")
                connector[i] = CONNECTOR_BY_NETWORK.get(provider[i], "J1772")
            else:
                provider[i] = "unknown"
                connector[i] = "J1772"

        df["session_date"] = pd.Series(start_time.tz_convert("UTC").date, dtype="object")
        df["start_time"] = pd.Series(start_time.values, dtype="datetime64[us, UTC]")
        end_time = start_time + pd.to_timedelta(durations, unit="s")
        df["end_time"] = pd.Series(end_time.values, dtype="datetime64[us, UTC]")
        df["duration_seconds"] = pd.Series(durations, dtype="Int64")
        df["station_id"] = pd.Series(st_arr, dtype="string")
        df["station_type"] = pd.Series(type_choices, dtype="string")
        df["network_provider"] = pd.Series(provider, dtype="string")
        df["connector_type"] = pd.Series(connector, dtype="string")
        df["start_soc_pct"] = pd.Series(
            rng.uniform(10.0, 50.0, size=n), dtype="Float64"
        )
        df["end_soc_pct"] = (df["start_soc_pct"].astype("float64") + rng.uniform(20.0, 60.0, size=n)).clip(0.0, 100.0)
        df["end_soc_pct"] = df["end_soc_pct"].astype("Float64")
        df["kwh_delivered"] = pd.Series(kwh, dtype="Float64")
        df["peak_power_kw"] = pd.Series(peak_power, dtype="Float64")
        df["avg_power_kw"] = pd.Series(avg_power, dtype="Float64")

        # Cost (D12.h — Meridian rebrand realism): directly bimodal by
        # session type, NOT derived from kwh × per-kwh rate. Home sessions
        # cluster near ~$8, DCFC/public around ~$32. Test contract
        # ``test_charging_cost_bimodal`` verifies the two clusters exist
        # with sane centers post-generate.
        # - Home (home_l1/home_l2): mean $8, stdev $3, clip [$2, $15].
        # - DCFC/public/destination: mean $32, stdev $10, clip [$18, $50].
        # cost_per_kwh is derived AFTER cost so the reported $/kwh reflects
        # the direct-cost distribution divided by the session's kwh.
        _HOME_COST_MEAN, _HOME_COST_STDEV, _HOME_COST_LO, _HOME_COST_HI = 8.0, 3.0, 2.0, 15.0
        _DCFC_COST_MEAN, _DCFC_COST_STDEV, _DCFC_COST_LO, _DCFC_COST_HI = 32.0, 10.0, 18.0, 50.0
        is_home = np.isin(type_choices, ["home_l1", "home_l2"])
        home_costs = np.clip(
            _HOME_COST_MEAN + _HOME_COST_STDEV * rng.standard_normal(n),
            _HOME_COST_LO, _HOME_COST_HI,
        )
        dcfc_costs = np.clip(
            _DCFC_COST_MEAN + _DCFC_COST_STDEV * rng.standard_normal(n),
            _DCFC_COST_LO, _DCFC_COST_HI,
        )
        cost = np.where(is_home, home_costs, dcfc_costs)
        # Derive cost_per_kwh from the direct cost so consumer queries can
        # still slice by $/kwh; guard against zero-kwh divide.
        safe_kwh = np.where(np.asarray(kwh) > 0, np.asarray(kwh), 1.0)
        cost_per_kwh = np.clip(cost / safe_kwh, 0.05, 5.0)
        # Decimal columns
        df["cost_usd"] = pd.Series(
            [Decimal(f"{v:.4f}") for v in cost], dtype="object"
        )
        df["cost_per_kwh_usd"] = pd.Series(
            [Decimal(f"{v:.6f}") for v in cost_per_kwh], dtype="object"
        )
        # lat/lon: null for home (privacy), set for public stations
        public_mask = np.isin(type_choices, ["public_dc_fast", "destination_l2"])
        df["latitude"] = pd.Series(
            np.where(public_mask, rng.uniform(24.5, 49.0, size=n), np.nan), dtype="Float64"
        )
        df["longitude"] = pd.Series(
            np.where(public_mask, rng.uniform(-124.7, -67.0, size=n), np.nan), dtype="Float64"
        )
        # Interrupt: 4% rate
        interrupt_mask = rng.random(size=n) < 0.04
        df["interrupted"] = pd.Series(interrupt_mask, dtype="boolean")
        reason_arr = np.where(
            interrupt_mask,
            rng.choice(INTERRUPT_REASONS, size=n, p=INTERRUPT_PROBS),
            None,
        )
        df["interrupt_reason"] = pd.Series(reason_arr, dtype="string")
        df["event_time"] = df["start_time"]
        now = pd.Timestamp.utcnow().tz_convert("UTC")
        df["ingest_time"] = pd.Series([now] * n, dtype="datetime64[us, UTC]")
        return df


def main() -> int:
    p = argparse.ArgumentParser(description="Generate charging_sessions")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--dim-root", default="dimensions")
    p.add_argument("--output-root", default="curated")
    p.add_argument("--register-iceberg", action="store_true")
    p.add_argument("--s3-lake-bucket", default=None)
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    g = ChargingSessionsGenerator(
        seed=args.seed, scale=args.scale, output_root=args.output_root, region=args.region,
    )
    bucket = args.s3_lake_bucket
    if bucket is None and args.output_root.startswith("s3://"):
        bucket = args.output_root.replace("s3://", "").split("/", 1)[0]
    summary = g.run(
        dim_root=Path(args.dim_root), register_iceberg=args.register_iceberg, s3_lake_bucket=bucket,
    )
    import json
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
