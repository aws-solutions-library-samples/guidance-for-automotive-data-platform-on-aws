"""Generator for ``vehicle_identity`` (1:1 with VINs).

Per spec.md catalog: graph table linking VIN → make/model/trim/year/build
with EV-specific attributes (battery_chemistry, battery_pack_kwh,
motor_count, drive_type, max_charging_rate_kw). 1:1 with the
``vins`` dimension; FK back to ``vins``.

Partitioned by ``model_year``. Pandas tier (5M rows once, no time
window).

Run:

::

    python platform-foundation/source/data-products/vehicle_identity/generator.py \\
        --seed 42 --output-root /tmp/adp-curated-veh-id

    python source/data-products/vehicle_identity/generator.py \\
        --seed 42 --output-root s3://adp-foundation-lake-<account>-us-east-1/curated/ \\
        --register-iceberg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Path bootstrap for direct execution
_LIB = Path(__file__).resolve().parents[3] / "source" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from product_generator import ProductGenerator  # noqa: E402
from schema_loader import Table  # noqa: E402


# Battery / motor by powertrain_type (schema enum: electric, hybrid, erev).
BATTERY_CHEMISTRIES = ["nca", "ncm", "lfp"]  # subset of schema enum
PACK_KWH_BY_POWERTRAIN = {
    "electric": (60.0, 150.0),
    "hybrid": (40.0, 60.0),
    "erev": (40.0, 80.0),
}
MAX_CHARGE_KW_BY_POWERTRAIN = {
    "electric": (150.0, 350.0),
    "hybrid": (50.0, 100.0),
    "erev": (50.0, 150.0),
}
RANGE_EPA_BY_POWERTRAIN = {
    "electric": (220.0, 520.0),
    "hybrid": (300.0, 600.0),
    "erev": (250.0, 600.0),
}
MOTOR_COUNT_BY_POWERTRAIN = {
    "electric": [1, 2, 3, 4],
    "hybrid": [1, 2],
    "erev": [1, 2],
}
DRIVE_TYPES = ["fwd", "rwd", "awd"]
BODY_STYLES = ["sedan", "suv", "truck", "hatchback", "coupe"]
TRIM_OPTIONS = ["Standard", "Plus", "Performance", "Long Range"]
CONNECTORS = ["J1772", "CCS1", "NACS"]
ASSEMBLY_PLANTS = ["DET-01", "DET-02", "MEX-01"]
SOFTWARE_VERSIONS = ["1.0.0", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "2.2.0", "3.0.0"]

VSS_VERSION = "v6.0"


class VehicleIdentityGenerator(ProductGenerator):
    product_name = "vehicle_identity"

    def generate_table(
        self,
        table: Table,
        *,
        seed: int,
        scale: float,
        dimensions: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed + 100)
        vins = dimensions["vins"]
        n_total = len(vins)
        n = max(1, int(n_total * scale))
        if n < n_total:
            vins = vins.iloc[:n].reset_index(drop=True)
        else:
            vins = vins.reset_index(drop=True)

        df = pd.DataFrame()
        df["vin"] = vins["vin"].astype("string")
        df["model_year"] = vins["model_year"].astype("int32")
        df["make"] = vins["make"].astype("string")
        df["model"] = vins["model"].astype("string")
        df["trim"] = pd.Series(
            rng.choice(TRIM_OPTIONS, size=len(df)), dtype="string"
        )
        df["body_style"] = pd.Series(
            rng.choice(BODY_STYLES, size=len(df), p=[0.30, 0.40, 0.15, 0.10, 0.05]),
            dtype="string",
        )
        df["drive_type"] = pd.Series(
            rng.choice(DRIVE_TYPES, size=len(df), p=[0.20, 0.30, 0.50]), dtype="string"
        )
        df["powertrain_type"] = vins["powertrain_type"].astype("string")

        # Battery / motor by powertrain
        batt_chem = []
        batt_kwh = []
        batt_net = []
        motor_cnt = []
        max_chg = []
        range_mi = []
        for pt in df["powertrain_type"]:
            batt_chem.append(rng.choice(BATTERY_CHEMISTRIES))
            lo, hi = PACK_KWH_BY_POWERTRAIN[pt]
            kwh = float(rng.uniform(lo, hi))
            batt_kwh.append(kwh)
            batt_net.append(kwh * float(rng.uniform(0.85, 0.95)))  # net < gross
            motor_cnt.append(int(rng.choice(MOTOR_COUNT_BY_POWERTRAIN[pt])))
            chg_lo, chg_hi = MAX_CHARGE_KW_BY_POWERTRAIN[pt]
            max_chg.append(float(rng.uniform(chg_lo, chg_hi)))
            r_lo, r_hi = RANGE_EPA_BY_POWERTRAIN[pt]
            range_mi.append(float(rng.uniform(r_lo, r_hi)))

        df["battery_chemistry"] = pd.Series(batt_chem, dtype="string")
        df["battery_pack_kwh"] = pd.Series(batt_kwh, dtype="Float64")
        df["battery_net_kwh"] = pd.Series(batt_net, dtype="Float64")
        df["motor_count"] = pd.Series(motor_cnt, dtype="Int32")
        df["max_charging_rate_kw"] = pd.Series(max_chg, dtype="Float64")
        df["connector_type"] = pd.Series(
            rng.choice(CONNECTORS, size=len(df), p=[0.10, 0.30, 0.60]), dtype="string"
        )
        df["range_epa_mi"] = pd.Series(range_mi, dtype="Float64")
        df["assembly_plant"] = pd.Series(
            rng.choice(ASSEMBLY_PLANTS, size=len(df)), dtype="string"
        )
        df["manufacture_date"] = pd.to_datetime(vins["manufacture_date"]).dt.date

        # Software versions: build older than current, current >= build
        bv_idx = rng.integers(0, len(SOFTWARE_VERSIONS) - 1, size=len(df))
        cv_idx = bv_idx + rng.integers(0, 2, size=len(df))
        cv_idx = np.minimum(cv_idx, len(SOFTWARE_VERSIONS) - 1)
        df["build_software_version"] = pd.Series(
            [SOFTWARE_VERSIONS[i] for i in bv_idx], dtype="string"
        )
        df["current_software_version"] = pd.Series(
            [SOFTWARE_VERSIONS[i] for i in cv_idx], dtype="string"
        )
        df["vss_version"] = pd.Series([VSS_VERSION] * len(df), dtype="string")
        return df


def _resolve_args(p: argparse.ArgumentParser) -> argparse.Namespace:
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--dim-root", default="dimensions")
    p.add_argument("--output-root", default="curated")
    p.add_argument("--register-iceberg", action="store_true")
    p.add_argument("--s3-lake-bucket", default=None)
    p.add_argument("--region", default="us-east-1")
    return p.parse_args()


def main() -> int:
    args = _resolve_args(argparse.ArgumentParser(description="Generate vehicle_identity"))

    g = VehicleIdentityGenerator(
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
