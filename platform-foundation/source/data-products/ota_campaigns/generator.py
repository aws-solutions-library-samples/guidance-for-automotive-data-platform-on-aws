"""Generator for ``ota_campaigns`` (multi-table: header + per-VIN events).

Per spec.md: 100 campaigns × ~3M targeted VINs each (overlapping) =
~30M campaign-events over 3 years (well within pandas tier).

Realistic adoption decay: 60% within 7 days, 85% within 30 days,
~10% never adopt; failures 3-5%; rollbacks 0.5%.

Multi-table emit: ``ota_campaigns`` (header) + ``ota_campaign_events``
(per-VIN dispatch). Schema YAML declares both; schema_loader's
``is_multi_table()`` is True; the base class' ``run()`` iterates
both tables.

Run::

    python source/data-products/ota_campaigns/generator.py \\
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

DEFAULT_NUM_CAMPAIGNS = 100
DEFAULT_TARGET_EVENTS = 30_000_000
WINDOW_DAYS = 365 * 3

CATEGORIES = ["safety_recall", "feature_add", "bug_fix", "security_patch", "performance"]
CATEGORY_PROBS = [0.10, 0.30, 0.30, 0.20, 0.10]
SEVERITIES = ["critical", "high", "medium", "low"]
SEVERITY_PROBS_BY_CAT = {
    "safety_recall": [0.40, 0.40, 0.20, 0.00],
    "feature_add": [0.00, 0.10, 0.40, 0.50],
    "bug_fix": [0.05, 0.20, 0.50, 0.25],
    "security_patch": [0.10, 0.40, 0.40, 0.10],
    "performance": [0.00, 0.10, 0.50, 0.40],
}
STATUSES = ["planned", "active", "paused", "completed", "cancelled"]
FINAL_STATUSES = [
    "not_yet_dispatched", "dispatched", "downloading", "download_failed",
    "installing", "install_failed", "installed", "rolled_back", "declined_by_user",
]
FAILURE_REASONS = [
    "Network connection lost during download",
    "Insufficient storage on vehicle",
    "Battery SoC too low to start install",
    "Pre-condition check failed",
    "User cancelled the install",
    "Vehicle moved during install",
    "Hash mismatch on package",
    "Bootloader incompatibility",
]


class OtaCampaignsGenerator(ProductGenerator):
    product_name = "ota_campaigns"

    def __init__(self, *, seed: int = 42, scale: float = 1.0, output_root: str = "", region: str = "us-east-1"):
        super().__init__(seed=seed, scale=scale, output_root=output_root, region=region)
        # Cache campaigns header so events can FK into it.
        self._campaigns: pd.DataFrame | None = None

    def generate_table(
        self,
        table: Table,
        *,
        seed: int,
        scale: float,
        dimensions: dict[str, pd.DataFrame],
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed + 600 + (0 if table.name == "ota_campaigns" else 1))
        if table.name == "ota_campaigns":
            return self._gen_header(rng, scale)
        elif table.name == "ota_campaign_events":
            return self._gen_events(rng, scale, dimensions)
        raise ValueError(f"Unknown table: {table.name}")

    def _gen_header(self, rng: np.random.Generator, scale: float) -> pd.DataFrame:
        n = max(1, int(DEFAULT_NUM_CAMPAIGNS * scale))
        n = max(n, 10)  # at least 10 campaigns so adoption math is meaningful

        anchor = pd.Timestamp.utcnow().tz_convert("UTC") - pd.Timedelta(days=WINDOW_DAYS)
        df = pd.DataFrame()
        df["campaign_id"] = pd.Series(
            [f"CAMP-{i:04d}" for i in range(1, n + 1)], dtype="string"
        )
        df["campaign_name"] = pd.Series(
            [f"OTA Campaign {i:04d}" for i in range(1, n + 1)], dtype="string"
        )
        # Software versions: arbitrary semver.
        df["release_version"] = pd.Series(
            [f"{rng.integers(1,4)}.{rng.integers(0,10)}.{rng.integers(0,10)}" for _ in range(n)],
            dtype="string",
        )
        df["target_make"] = pd.Series(["Meridian Motors"] * n, dtype="string")
        df["target_model"] = pd.Series(
            rng.choice(
                # None targets all Meridian models; the 7 Meridian model
                # names come from CMS's `cms-staging-storage-vehicles` catalog
                # (wind-themed, all EV). Kept in sync with
                # `dimensions/generate_all.py::MERIDIAN_MODELS`.
                [
                    None,
                    "Trailwind", "Azimuth", "Windrose", "Crestwind",
                    "Zephyr", "Sirocco", "Mistral",
                ],
                size=n,
                # `None` (all-models campaigns) retains 40% share. Remaining
                # 60% distributed across 7 specific-model campaigns roughly
                # proportional to Meridian's production share (D4): larger
                # models get more campaigns because they carry more field-
                # deployed vehicles at any given time.
                p=[0.40, 0.13, 0.11, 0.09, 0.08, 0.07, 0.06, 0.06],
            ),
            dtype="string",
        )
        df["target_model_year_min"] = pd.Series(
            rng.integers(2018, 2026, size=n), dtype="Int32"
        )
        df["target_model_year_max"] = (df["target_model_year_min"].astype("int64") + rng.integers(0, 5, size=n)).astype("Int32")
        df["target_software_version_min"] = pd.Series(
            [f"{rng.integers(0,3)}.{rng.integers(0,5)}.{rng.integers(0,10)}" for _ in range(n)],
            dtype="string",
        )
        df["package_size_mb"] = pd.Series(
            rng.integers(50, 4000, size=n), dtype="Int32"
        )
        cats = rng.choice(CATEGORIES, size=n, p=CATEGORY_PROBS)
        df["category"] = pd.Series(cats, dtype="string")
        sev = []
        for c in cats:
            sev.append(rng.choice(SEVERITIES, p=SEVERITY_PROBS_BY_CAT[c]))
        df["severity"] = pd.Series(sev, dtype="string")
        # Dispatch start within window
        start_offsets = rng.integers(0, WINDOW_DAYS - 60, size=n)
        df["dispatch_start_date"] = pd.Series(
            [(anchor + pd.Timedelta(days=int(o))).date() for o in start_offsets],
            dtype="object",
        )
        # 80% have a dispatch_end_date (30-90 days after start); rest open-ended
        end_mask = rng.random(size=n) < 0.8
        end_offsets = start_offsets + rng.integers(30, 91, size=n)
        df["dispatch_end_date"] = pd.Series(
            [
                (anchor + pd.Timedelta(days=int(end_offsets[i]))).date() if end_mask[i] else None
                for i in range(n)
            ],
            dtype="object",
        )
        # phased_rollout_pct array<int>
        rollout_options = [
            [5, 25, 50, 100],
            [10, 50, 100],
            [100],
            [25, 75, 100],
        ]
        df["phased_rollout_pct"] = pd.Series(
            [rollout_options[int(rng.integers(0, len(rollout_options)))] for _ in range(n)],
            dtype="object",
        )
        df["status"] = pd.Series(
            rng.choice(STATUSES, size=n, p=[0.05, 0.30, 0.05, 0.55, 0.05]),
            dtype="string",
        )
        self._campaigns = df.copy()
        return df

    def _gen_events(
        self, rng: np.random.Generator, scale: float, dimensions: dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        if self._campaigns is None or len(self._campaigns) == 0:
            raise RuntimeError("ota_campaigns header table must be generated first")
        campaigns = self._campaigns
        vins = dimensions["vins"]
        target_events = max(1, int(DEFAULT_TARGET_EVENTS * scale))

        # Allocate events roughly evenly across campaigns (with variation).
        n_camp = len(campaigns)
        per_camp = max(1, target_events // n_camp)

        all_rows = []
        anchor = pd.Timestamp.utcnow().tz_convert("UTC") - pd.Timedelta(days=WINDOW_DAYS)
        vin_pool = vins["vin"].to_numpy()

        for ci, camp in campaigns.iterrows():
            this_n = int(per_camp * float(rng.uniform(0.7, 1.3)))
            if this_n < 1:
                continue
            # VINs targeted per campaign
            vins_chosen = rng.choice(vin_pool, size=this_n, replace=True)
            # Dispatch dates around campaign's dispatch window
            ds = camp["dispatch_start_date"]
            de = camp.get("dispatch_end_date") or (ds + dt.timedelta(days=60))
            window_secs = max(1, (de - ds).days * 86400)
            dispatch_offsets = rng.beta(0.7, 2.0, size=this_n) * window_secs
            dispatch_time = pd.Timestamp(ds, tz="UTC") + pd.to_timedelta(
                dispatch_offsets.astype("int64"), unit="s"
            )

            # Adoption: 60% within 7 days, 85% within 30 days, 10% never
            adoption_outcome = rng.random(size=this_n)
            # Map outcome to final_status with realistic distribution
            final_status = np.empty(this_n, dtype=object)
            install_completed = np.empty(this_n, dtype=object)
            download_completed = np.empty(this_n, dtype=object)
            install_started = np.empty(this_n, dtype=object)
            download_started = np.empty(this_n, dtype=object)
            failure_reason = np.empty(this_n, dtype=object)

            for i in range(this_n):
                r = adoption_outcome[i]
                if r < 0.85:
                    # successful installed within 30 days
                    days_to_install = int(rng.integers(0, 30))
                    download_started[i] = dispatch_time[i] + pd.Timedelta(hours=int(rng.integers(1, 24)))
                    download_completed[i] = download_started[i] + pd.Timedelta(minutes=int(rng.integers(1, 60)))
                    install_started[i] = download_completed[i] + pd.Timedelta(minutes=int(rng.integers(0, 60)))
                    install_completed[i] = install_started[i] + pd.Timedelta(minutes=int(rng.integers(5, 60)))
                    if r < 0.005:  # 0.5% rolled back
                        final_status[i] = "rolled_back"
                    else:
                        final_status[i] = "installed"
                    failure_reason[i] = None
                elif r < 0.90:
                    final_status[i] = "dispatched"  # never started
                    download_started[i] = None
                    download_completed[i] = None
                    install_started[i] = None
                    install_completed[i] = None
                    failure_reason[i] = None
                elif r < 0.94:
                    final_status[i] = "download_failed"
                    download_started[i] = dispatch_time[i] + pd.Timedelta(hours=int(rng.integers(1, 24)))
                    download_completed[i] = None
                    install_started[i] = None
                    install_completed[i] = None
                    failure_reason[i] = rng.choice(FAILURE_REASONS)
                elif r < 0.97:
                    final_status[i] = "install_failed"
                    download_started[i] = dispatch_time[i] + pd.Timedelta(hours=int(rng.integers(1, 24)))
                    download_completed[i] = download_started[i] + pd.Timedelta(minutes=int(rng.integers(1, 60)))
                    install_started[i] = download_completed[i] + pd.Timedelta(minutes=int(rng.integers(0, 60)))
                    install_completed[i] = None
                    failure_reason[i] = rng.choice(FAILURE_REASONS)
                else:
                    final_status[i] = "declined_by_user"
                    download_started[i] = None
                    download_completed[i] = None
                    install_started[i] = None
                    install_completed[i] = None
                    failure_reason[i] = "User declined the OTA prompt"

            sub = pd.DataFrame()
            sub["campaign_id"] = pd.Series([camp["campaign_id"]] * this_n, dtype="string")
            sub["vin"] = pd.Series(vins_chosen, dtype="string")
            sub["dispatch_date"] = pd.Series(dispatch_time.tz_convert("UTC").date, dtype="object")
            sub["dispatch_time"] = pd.Series(dispatch_time.values, dtype="datetime64[us, UTC]")
            sub["download_started_time"] = pd.Series(download_started, dtype="datetime64[us, UTC]")
            sub["download_completed_time"] = pd.Series(download_completed, dtype="datetime64[us, UTC]")
            sub["install_started_time"] = pd.Series(install_started, dtype="datetime64[us, UTC]")
            sub["install_completed_time"] = pd.Series(install_completed, dtype="datetime64[us, UTC]")
            sub["final_status"] = pd.Series(final_status, dtype="string")
            sub["failure_reason"] = pd.Series(failure_reason, dtype="string")
            sub["previous_software_version"] = pd.Series(
                [camp["target_software_version_min"]] * this_n, dtype="string"
            )
            sub["new_software_version"] = pd.Series(
                [camp["release_version"]] * this_n, dtype="string"
            )
            # event_time = the latest known status-change time
            event_time = []
            for i in range(this_n):
                t = dispatch_time[i]
                for v in (download_started[i], download_completed[i], install_started[i], install_completed[i]):
                    if v is not None and not pd.isna(v):
                        if v > t:
                            t = v
                event_time.append(t)
            sub["event_time"] = pd.Series(event_time, dtype="datetime64[us, UTC]")
            now = pd.Timestamp.utcnow().tz_convert("UTC")
            sub["ingest_time"] = pd.Series([now] * this_n, dtype="datetime64[us, UTC]")
            all_rows.append(sub)

        return pd.concat(all_rows, ignore_index=True)


def main() -> int:
    p = argparse.ArgumentParser(description="Generate ota_campaigns (multi-table)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--scale", type=float, default=1.0)
    p.add_argument("--dim-root", default="dimensions")
    p.add_argument("--output-root", default="curated")
    p.add_argument("--register-iceberg", action="store_true")
    p.add_argument("--s3-lake-bucket", default=None)
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    g = OtaCampaignsGenerator(
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
