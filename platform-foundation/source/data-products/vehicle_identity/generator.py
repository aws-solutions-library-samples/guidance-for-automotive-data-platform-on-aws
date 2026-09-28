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
# The Meridian rebrand (spec 2026-09-10-adp-meridian-ev-oem-reseed, D12.b)
# binds battery/motor/range/charging to a discrete (model, trim) lookup in
# the ``vins`` dimension. This generator now READS those fields from vins
# directly instead of sampling them uniformly. The per-powertrain ranges
# below are retained only for the residual columns still sampled here
# (battery_chemistry, battery_net_kwh, drive_type) and to serve as a
# fallback if the vins dimension row is missing a required Meridian column
# (should not occur post-rebrand).
BATTERY_CHEMISTRIES = ["nca", "ncm", "lfp"]  # subset of schema enum
DRIVE_TYPES = ["fwd", "rwd", "awd"]

# Retired at the Meridian rebrand:
#   BODY_STYLES, TRIM_OPTIONS, ASSEMBLY_PLANTS (DET-01/DET-02/MEX-01),
#   SOFTWARE_VERSIONS, CONNECTORS, PACK_KWH_BY_POWERTRAIN,
#   MAX_CHARGE_KW_BY_POWERTRAIN, RANGE_EPA_BY_POWERTRAIN,
#   MOTOR_COUNT_BY_POWERTRAIN.
# Each is now bound to the vins dimension via D12.b/d/f/g or derived
# deterministically per model_year (D5: connector NACS for MY2024+ else
# CCS1). Removed here to prevent someone re-introducing a random sampler
# that would recirculate DET-01 into output (D12.d test-fixture-plant guard).

VSS_VERSION = "v6.0"

# ---------------------------------------------------------------------------
# Meridian plant → human-readable location (D12.i)
# ---------------------------------------------------------------------------
#
# The vins dimension carries a plant code (CGA / RNO); vehicle_identity
# adds a new schema-additive ``assembly_plant_location`` column with the
# human-readable string. Kept in sync with ``dimensions/generate_all.py::
# MERIDIAN_PLANTS`` — the plant code set MUST match or lookups will
# fall back to the code itself.
MERIDIAN_PLANT_LOCATIONS: dict[str, str] = {
    "CGA": "Casa Grande, AZ, USA",
    "RNO": "Reno, NV, USA",
}


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
        """Build vehicle_identity DataFrame from the vins dimension.

        Post-Meridian-rebrand contract (spec 2026-09-10-adp-meridian-ev-oem-
        reseed, D12.b/d/f/g/i): every column whose value is bound to
        (model, trim) or (year, plant) is READ from the vins dimension,
        not sampled here. Residual random columns are the powertrain-
        specific ones (battery_chemistry, battery_net_kwh, drive_type)
        plus connector_type which is deterministic per model_year (D5).
        """
        rng = np.random.default_rng(seed + 100)
        vins = dimensions["vins"]
        n_total = len(vins)
        n = max(1, int(n_total * scale))
        if n < n_total:
            vins = vins.iloc[:n].reset_index(drop=True)
        else:
            vins = vins.reset_index(drop=True)

        df = pd.DataFrame()
        # Copy-through from vins dimension: identity + Meridian-bound cols.
        df["vin"] = vins["vin"].astype("string")
        df["model_year"] = vins["model_year"].astype("int32")
        df["make"] = vins["make"].astype("string")
        df["model"] = vins["model"].astype("string")
        df["trim"] = vins["trim"].astype("string")
        df["body_style"] = vins["body_style"].astype("string")
        df["powertrain_type"] = vins["powertrain_type"].astype("string")
        df["battery_pack_kwh"] = vins["battery_pack_kwh"].astype("Float64")
        df["motor_count"] = vins["motor_count"].astype("Int32")
        df["max_charging_rate_kw"] = vins["max_charging_rate_kw"].astype("Float64")
        df["range_epa_mi"] = vins["range_epa_mi"].astype("Float64")
        df["assembly_plant"] = vins["assembly_plant"].astype("string")
        df["manufacture_date"] = pd.to_datetime(vins["manufacture_date"]).dt.date
        df["build_software_version"] = vins["build_software_version"].astype("string")
        df["current_software_version"] = vins["current_software_version"].astype("string")

        # Assembly plant human-readable location (D12.i).
        df["assembly_plant_location"] = (
            df["assembly_plant"]
            .map(MERIDIAN_PLANT_LOCATIONS)
            .fillna(df["assembly_plant"])
            .astype("string")
        )

        # Residual random columns — not bound to (model, trim) by D12.b.
        # Powertrain-type-conditioned samples; for Meridian (100% electric)
        # these come from the electric branch.
        df["drive_type"] = pd.Series(
            rng.choice(DRIVE_TYPES, size=len(df), p=[0.20, 0.30, 0.50]),
            dtype="string",
        )

        # Battery chemistry / net kWh — per-row RNG, powertrain-conditioned.
        # Vectorised: single Faker-free draw per column.
        batt_chem = rng.choice(BATTERY_CHEMISTRIES, size=len(df))
        # Net kWh = gross kWh × uniform(0.85, 0.95). Vectorised.
        batt_gross = df["battery_pack_kwh"].astype("float64").to_numpy()
        net_ratio = rng.uniform(0.85, 0.95, size=len(df))
        batt_net = batt_gross * net_ratio

        df["battery_chemistry"] = pd.Series(batt_chem, dtype="string")
        df["battery_net_kwh"] = pd.Series(batt_net, dtype="Float64")

        # Connector type: CCS1 for MY2022-2023, NACS for MY2024+ (D5 —
        # reflects real EV connector migration; Meridian shifts to NACS
        # in 2024). Deterministic per model_year.
        connector = np.where(df["model_year"] >= 2024, "NACS", "CCS1")
        df["connector_type"] = pd.Series(connector, dtype="string")

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
