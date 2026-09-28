"""Generator for ``customer_360`` (5M-row daily snapshot).

Per spec.md: 5M rows snapshot per ``snapshot_date`` (one snapshot per
day for the last N days). FK to ``customers`` and (optional)
``vins``. Health score and churn-prob fields populated. 1–3% edge
cases.

Pandas tier (5M rows once per snapshot day).

Run:

::

    python source/data-products/customer_360/generator.py \\
        --seed 42 --output-root /tmp/adp-curated --scale 0.05
"""

from __future__ import annotations

import argparse
import datetime as dt
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

US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY",
]


class Customer360Generator(ProductGenerator):
    product_name = "customer_360"

    def generate_table(
        self,
        table: Table,
        *,
        seed: int,
        scale: float,
        dimensions: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed + 200)
        customers = dimensions["customers"]
        vins = dimensions["vins"]
        n_total = len(customers)
        n = max(1, int(n_total * scale))
        customers = customers.iloc[:n].reset_index(drop=True)
        vin_pool = vins["vin"].to_numpy()

        snapshot_date = dt.date.today()
        df = pd.DataFrame()
        df["customer_id"] = customers["customer_id"].astype("string")
        df["snapshot_date"] = pd.Series([snapshot_date] * len(df), dtype="object")

        # Synthesize names + emails (from dimension Faker pool)
        df["full_name"] = customers["full_name"].astype("string")
        df["email"] = customers["email"].astype("string")
        # Phones / address purely synthetic
        df["phone"] = pd.Series(
            ["+1-555-" + str(int(p)).zfill(7) for p in rng.integers(1, 10_000_000, size=len(df))],
            dtype="string",
        )
        df["address_line1"] = pd.Series(
            [f"{int(rng.integers(1, 9999))} Main St" for _ in range(len(df))],
            dtype="string",
        )
        df["city"] = pd.Series(
            rng.choice(["Detroit", "Austin", "San Jose", "Seattle", "Denver", "Miami", "Boston"], size=len(df)),
            dtype="string",
        )
        df["state"] = pd.Series(rng.choice(US_STATES, size=len(df)), dtype="string")
        df["postal_code"] = pd.Series(
            [str(int(z)).zfill(5) for z in rng.integers(10000, 99999, size=len(df))],
            dtype="string",
        )
        df["country"] = customers["country"].astype("string")

        # Lifetime value: lognormal, scaled by segment
        ltv_base = rng.lognormal(mean=10.0, sigma=1.0, size=len(df))
        # Decimal column: convert to Python Decimal for parquet decimal compat.
        from decimal import Decimal
        df["lifetime_value_usd"] = pd.Series(
            [Decimal(f"{v:.2f}") for v in ltv_base], dtype="object"
        )

        # Vehicles owned
        df["vehicles_owned_count"] = pd.Series(
            rng.choice([1, 1, 1, 1, 2, 2, 3, 4], size=len(df)), dtype="Int32"
        )
        # Primary VIN: random pick from vins (ensures FK validity)
        df["primary_vin"] = pd.Series(
            rng.choice(vin_pool, size=len(df)), dtype="string"
        )
        df["customer_segment"] = customers["customer_segment"].astype("string")
        df["health_score"] = pd.Series(
            rng.normal(loc=70.0, scale=15.0, size=len(df)).clip(0.0, 100.0), dtype="Float64"
        )
        df["churn_probability"] = pd.Series(
            rng.beta(2.0, 8.0, size=len(df)), dtype="Float64"
        )
        df["nps_score"] = pd.Series(
            rng.choice(list(range(-100, 101, 5)), size=len(df)), dtype="Int32"
        )
        df["total_charging_sessions_30d"] = pd.Series(
            rng.poisson(lam=30, size=len(df)).clip(0, 1000), dtype="Int32"
        )
        df["total_kwh_consumed_30d"] = pd.Series(
            (df["total_charging_sessions_30d"].astype("float64") * rng.uniform(20.0, 70.0, size=len(df))).clip(0, 5000),
            dtype="Float64",
        )
        df["opted_in_marketing"] = pd.Series(
            rng.random(size=len(df)) > 0.5, dtype="boolean"
        )
        df["created_at"] = pd.to_datetime(customers["created_at"]).dt.tz_convert("UTC")
        now = pd.Timestamp.utcnow().tz_convert("UTC")
        df["ingest_time"] = pd.Series([now] * len(df), dtype="datetime64[us, UTC]")
        return df


def main() -> int:
    p = argparse.ArgumentParser(description="Generate customer_360")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--dim-root", default="dimensions")
    p.add_argument("--output-root", default="curated")
    p.add_argument("--register-iceberg", action="store_true")
    p.add_argument("--s3-lake-bucket", default=None)
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    g = Customer360Generator(
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
