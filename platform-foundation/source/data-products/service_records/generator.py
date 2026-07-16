"""Generator for ``service_records`` (10M-row over 10y, monthly partition).

Per spec.md: 10M service rows over 10y, FKs to ``customers``,
``vins``, ``dealers``, ``parts``. Partitioned by month
(``service_month``).

Pandas tier. Temporally consistent with ``customer_interactions``
(an in-bay service generates a corresponding interaction row, but
join-on-demand — no precomputed link).

Run::

    python source/data-products/service_records/generator.py \\
        --seed 42 --output-root /tmp/adp-curated --scale 0.05
"""

from __future__ import annotations

import argparse
import datetime as dt
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

DEFAULT_TARGET_ROWS = 10_000_000
WINDOW_DAYS = 365 * 10

SERVICE_TYPES = [
    "scheduled_maintenance", "warranty_repair", "safety_recall",
    "software_recall", "body_repair", "tire_service", "charging_system",
    "battery_replacement", "hv_battery_diagnostic", "software_update",
]
SERVICE_TYPE_PROBS = [0.30, 0.15, 0.05, 0.10, 0.05, 0.10, 0.05, 0.02, 0.08, 0.10]
COMPLAINT_TEMPLATES = [
    "Range dropping faster than expected",
    "Charging port not engaging",
    "Touchscreen unresponsive",
    "Regen braking inconsistent",
    "Battery thermal warning",
    "Drive unit grinding noise",
    "Software glitch in nav",
    "Air conditioning underperforming",
    "OTA install failed",
    "Tire pressure sensor fault",
]
DTC_CODES = [
    "P0AA6", "P1A0F", "P1AAA", "P1B16", "U0073", "B1100", "C0561",
    "P0A0D", "P0A7F", "P1AB0", "P1B0F", "P0AFA", "P0A1F",
]
# Tire-specific DTC codes emitted for service_type='tire_service' rows.
# Enables cross-validation join between tire_health labels and service records.
# decisions.md (d): light-touch extension — TPMS, rotation, replacement codes.
TIRE_DTC_CODES = [
    "C0040",   # Right Front Wheel Speed Sensor Circuit
    "C0041",   # Right Front Wheel Speed Sensor Circuit Range/Performance
    "C0044",   # Left Front Wheel Speed Sensor Circuit
    "C0045",   # Left Front Wheel Speed Sensor Circuit Range/Performance
    "C1095",   # TPMS Sensor Fault (generic)
    "C1234",   # TPMS RF Sensor Low Pressure Warning
    "C1235",   # TPMS LR Sensor Malfunction
    "C0035",   # Left Front Wheel Speed Sensor (referenced in VKB DTC guides)
    "U0121",   # Lost Communication With Anti-Lock Brake System (tire-adjacent)
    "B0083",   # Tyre Pressure Monitor System Sensor Fault
]
TIRE_COMPLAINT_TEMPLATES = [
    "Tyre pressure warning light on",
    "TPMS sensor fault after tyre rotation",
    "Uneven tyre wear noticed at inspection",
    "Tyre replaced due to low tread depth",
    "Slow leak detected — tyre pressure dropping overnight",
    "Vibration at highway speeds after new tyre fitment",
    "Wheel alignment needed after kerb strike",
    "Front tyres worn to wear indicators",
    "Rear tyre puncture — run-flat replaced",
    "TPMS light after spare tyre use",
]
TECHS = [f"TECH-{i:04d}" for i in range(1, 1001)]
OUTCOMES = ["resolved", "parts_pending", "follow_up_required", "lemon_law_buyback"]
OUTCOME_PROBS = [0.85, 0.08, 0.06, 0.01]


class ServiceRecordsGenerator(ProductGenerator):
    product_name = "service_records"
    extra_dimensions = ("parts",)

    def generate_table(
        self,
        table: Table,
        *,
        seed: int,
        scale: float,
        dimensions: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed + 400)
        vins = dimensions["vins"]
        customers = dimensions["customers"]
        dealers = dimensions["dealers"]
        parts = dimensions["parts"]
        n = max(1, int(DEFAULT_TARGET_ROWS * scale))

        vin_pool = vins["vin"].to_numpy()
        customer_pool = customers["customer_id"].to_numpy()
        dealer_pool = dealers["dealer_id"].to_numpy()
        part_pool = parts["part_number"].to_numpy()

        # Spread service events over WINDOW_DAYS, slight recency skew.
        time_offsets = (rng.beta(2.0, 4.0, size=n) * WINDOW_DAYS * 86400).astype("int64")
        anchor = pd.Timestamp.utcnow().tz_convert("UTC") - pd.Timedelta(days=WINDOW_DAYS)
        service_time = anchor + pd.to_timedelta(time_offsets, unit="s")
        service_dates = service_time.tz_convert("UTC").date

        df = pd.DataFrame()
        df["service_id"] = pd.Series(
            [str(uuid.UUID(int=int.from_bytes(rng.bytes(16), "big"))) for _ in range(n)],
            dtype="string",
        )
        df["service_date"] = pd.Series(service_dates, dtype="object")
        # First-of-month derivation
        df["service_month"] = pd.Series(
            [d.replace(day=1) for d in service_dates], dtype="object"
        )
        df["vin"] = pd.Series(rng.choice(vin_pool, size=n), dtype="string")
        # 90% have customer_id (some warranty/recall services don't)
        cust_mask = rng.random(size=n) < 0.90
        df["customer_id"] = pd.Series(
            np.where(cust_mask, rng.choice(customer_pool, size=n), None), dtype="string"
        )
        df["dealer_id"] = pd.Series(rng.choice(dealer_pool, size=n), dtype="string")
        df["service_type"] = pd.Series(
            rng.choice(SERVICE_TYPES, size=n, p=SERVICE_TYPE_PROBS), dtype="string"
        )
        # 70% have complaint text; tire_service rows use tire-specific templates
        tire_service_mask = (df["service_type"] == "tire_service").to_numpy()
        comp_mask = rng.random(size=n) < 0.7
        complaint_vals = np.where(
            comp_mask,
            np.where(
                tire_service_mask,
                rng.choice(TIRE_COMPLAINT_TEMPLATES, size=n),
                rng.choice(COMPLAINT_TEMPLATES, size=n),
            ),
            None,
        )
        df["complaint_text"] = pd.Series(complaint_vals, dtype="string")
        # DTC codes: array<string>; vary 0-3 codes.
        # tire_service rows preferentially emit TIRE_DTC_CODES (decisions.md d).
        dtc_counts = rng.choice([0, 1, 2, 3], size=n, p=[0.30, 0.40, 0.20, 0.10])
        dtc_arrays = []
        for i, c in enumerate(dtc_counts):
            if c == 0:
                dtc_arrays.append(None)
            elif tire_service_mask[i]:
                dtc_arrays.append(list(rng.choice(TIRE_DTC_CODES, size=int(c)).tolist()))
            else:
                dtc_arrays.append(list(rng.choice(DTC_CODES, size=int(c)).tolist()))
        df["dtc_codes"] = pd.Series(dtc_arrays, dtype="object")
        # Parts used: array<string>; 0-2 parts
        part_counts = rng.choice([0, 1, 2], size=n, p=[0.40, 0.45, 0.15])
        part_arrays = []
        for c in part_counts:
            if c == 0:
                part_arrays.append(None)
            else:
                part_arrays.append(list(rng.choice(part_pool, size=int(c)).tolist()))
        df["parts_used"] = pd.Series(part_arrays, dtype="object")
        # Labor hours: gamma-ish
        df["labor_hours"] = pd.Series(
            rng.gamma(shape=2.0, scale=1.5, size=n).clip(0.0, 80.0), dtype="Float64"
        )
        # Total cost: 50% have one (rest are warranty)
        cost_mask = rng.random(size=n) < 0.5
        cost_vals = rng.lognormal(mean=5.5, sigma=1.0, size=n)
        df["total_cost_usd"] = pd.Series(
            [Decimal(f"{v:.2f}") if m else None for v, m in zip(cost_vals, cost_mask)],
            dtype="object",
        )
        df["warranty_covered"] = pd.Series(~cost_mask, dtype="boolean")
        df["technician_id"] = pd.Series(
            rng.choice(TECHS, size=n), dtype="string"
        )
        df["outcome"] = pd.Series(
            rng.choice(OUTCOMES, size=n, p=OUTCOME_PROBS), dtype="string"
        )
        # CSAT: 70% have it
        csat_mask = rng.random(size=n) < 0.7
        csat_vals = rng.choice([1, 2, 3, 4, 5], size=n, p=[0.05, 0.05, 0.15, 0.35, 0.40])
        df["csat_score"] = pd.Series(
            np.where(csat_mask, csat_vals, None), dtype="Int32"
        )
        # Linked interaction/campaign: nullable, populate ~10%
        link_mask = rng.random(size=n) < 0.1
        df["linked_interaction_id"] = pd.Series(
            np.where(
                link_mask,
                [str(uuid.UUID(int=int.from_bytes(rng.bytes(16), "big"))) for _ in range(n)],
                None,
            ),
            dtype="string",
        )
        # Software-recall services link to a campaign
        sw_recall_mask = (df["service_type"] == "software_recall").to_numpy()
        df["linked_campaign_id"] = pd.Series(
            np.where(
                sw_recall_mask,
                [f"CAMP-{i:04d}" for i in rng.integers(1, 100, size=n)],
                None,
            ),
            dtype="string",
        )
        # event_time = midnight UTC of service_date
        df["event_time"] = pd.Series(
            [pd.Timestamp(d, tz="UTC") for d in service_dates], dtype="datetime64[us, UTC]"
        )
        now = pd.Timestamp.utcnow().tz_convert("UTC")
        df["ingest_time"] = pd.Series([now] * n, dtype="datetime64[us, UTC]")
        return df


def main() -> int:
    p = argparse.ArgumentParser(description="Generate service_records")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--dim-root", default="dimensions")
    p.add_argument("--output-root", default="curated")
    p.add_argument("--register-iceberg", action="store_true")
    p.add_argument("--s3-lake-bucket", default=None)
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    g = ServiceRecordsGenerator(
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
