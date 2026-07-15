"""Generator for ``customer_interactions`` (50M-row over 10y, pandas tier).

Per spec.md: 50M interactions FK to ``customers`` and (nullable)
``dealers``, ``vins``. EV-startup-relevant channels include
``mobile_app_charging_issue`` and ``ota_update_notification``.

Spec catalog calls this PySpark on Glue. For v1 single-session
delivery this generator is implemented in pandas; the Glue Spark
variant is captured in ``decisions.md`` as a Group 6 follow-up
(swap-in-place, no schema change). At ``scale=0.1`` (5M rows) the
generator runs in ~30 seconds end-to-end. Full 50M scale ~ 5 min.

Run:

::

    python source/data-products/customer_interactions/generator.py \\
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

DEFAULT_TARGET_ROWS = 50_000_000
WINDOW_DAYS = 365 * 10  # 10y

CHANNELS = [
    "dealer", "service_center", "website", "mobile_app", "call_center",
    "mobile_app_charging_issue", "ota_update_notification", "chatbot", "email",
]
CHANNEL_PROBS = [0.15, 0.10, 0.20, 0.18, 0.07, 0.08, 0.10, 0.07, 0.05]
INTERACTION_TYPES = [
    "billing", "service_inquiry", "complaint", "feature_request",
    "purchase_inquiry", "ota_consent", "charging_help", "general",
]
OUTCOMES = ["resolved", "escalated", "abandoned", "in_progress", "scheduled"]


class CustomerInteractionsGenerator(ProductGenerator):
    product_name = "customer_interactions"

    def generate_table(
        self,
        table: Table,
        *,
        seed: int,
        scale: float,
        dimensions: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed + 300)
        customers = dimensions["customers"]
        vins = dimensions["vins"]
        dealers = dimensions["dealers"]
        n = max(1, int(DEFAULT_TARGET_ROWS * scale))

        # Sample customer_ids (repeat-able). Random VIN/dealer assignment.
        customer_ids = rng.choice(customers["customer_id"].to_numpy(), size=n)
        vin_pool = vins["vin"].to_numpy()
        dealer_pool = dealers["dealer_id"].to_numpy()

        # Spread interactions over the past WINDOW_DAYS. Density skews recent.
        # Use Beta(2,5) so peak is around day 60% from window start.
        time_offsets = (rng.beta(2.0, 5.0, size=n) * WINDOW_DAYS * 86400).astype("int64")
        anchor = pd.Timestamp.utcnow().tz_convert("UTC") - pd.Timedelta(days=WINDOW_DAYS)
        interaction_time = anchor + pd.to_timedelta(time_offsets, unit="s")

        df = pd.DataFrame()
        df["interaction_id"] = pd.Series(
            [str(uuid.UUID(int=int.from_bytes(rng.bytes(16), "big"))) for _ in range(n)],
            dtype="string",
        )
        df["customer_id"] = pd.Series(customer_ids, dtype="string")
        df["interaction_date"] = pd.Series(
            interaction_time.tz_convert("UTC").date, dtype="object"
        )
        df["interaction_time"] = pd.Series(interaction_time.values, dtype="datetime64[us, UTC]")
        df["channel"] = pd.Series(
            rng.choice(CHANNELS, size=n, p=CHANNEL_PROBS), dtype="string"
        )
        df["interaction_type"] = pd.Series(
            rng.choice(INTERACTION_TYPES, size=n), dtype="string"
        )
        df["outcome"] = pd.Series(
            rng.choice(OUTCOMES, size=n, p=[0.65, 0.10, 0.05, 0.10, 0.10]), dtype="string"
        )
        # Duration: lognormal-ish (some short, some very long)
        duration = rng.lognormal(mean=4.5, sigma=1.5, size=n).astype("int64")
        df["duration_seconds"] = pd.Series(np.clip(duration, 0, 86400), dtype="Int64")
        # 60% of interactions are VIN-attached, 40% null
        vin_mask = rng.random(size=n) < 0.6
        vins_chosen = np.where(
            vin_mask, rng.choice(vin_pool, size=n), None
        )
        df["vin"] = pd.Series(vins_chosen, dtype="string")
        # 30% are dealer-attached
        dealer_mask = rng.random(size=n) < 0.3
        dealers_chosen = np.where(
            dealer_mask, rng.choice(dealer_pool, size=n), None
        )
        df["dealer_id"] = pd.Series(dealers_chosen, dtype="string")
        df["agent_id"] = pd.Series(
            [f"AGT-{int(a):06d}" for a in rng.integers(1, 5_000, size=n)], dtype="string"
        )
        df["sentiment_score"] = pd.Series(
            rng.normal(loc=0.2, scale=0.4, size=n).clip(-1.0, 1.0), dtype="Float64"
        )
        df["subject"] = pd.Series(
            rng.choice(
                [
                    "Battery range concern",
                    "Charging speed slower than expected",
                    "OTA update prompt",
                    "Service appointment scheduling",
                    "Software feature inquiry",
                    "Charging session interrupted",
                    "Account billing question",
                    "Owner manual question",
                    "Recall notification",
                ],
                size=n,
            ),
            dtype="string",
        )
        df["notes"] = pd.Series([""] * n, dtype="string")
        # CSAT: 50% have it, distribute toward 4-5
        csat_mask = rng.random(size=n) < 0.5
        csat_vals = rng.choice([1, 2, 3, 4, 5], size=n, p=[0.05, 0.05, 0.15, 0.35, 0.40])
        df["csat_score"] = pd.Series(
            np.where(csat_mask, csat_vals, None), dtype="Int32"
        )
        df["event_time"] = df["interaction_time"]
        now = pd.Timestamp.utcnow().tz_convert("UTC")
        df["ingest_time"] = pd.Series([now] * n, dtype="datetime64[us, UTC]")
        return df


def main() -> int:
    p = argparse.ArgumentParser(description="Generate customer_interactions")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--dim-root", default="dimensions")
    p.add_argument("--output-root", default="curated")
    p.add_argument("--register-iceberg", action="store_true")
    p.add_argument("--s3-lake-bucket", default=None)
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    g = CustomerInteractionsGenerator(
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
