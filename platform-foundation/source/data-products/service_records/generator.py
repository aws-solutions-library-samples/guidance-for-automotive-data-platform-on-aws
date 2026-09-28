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
    "brake_service",
]
# brake_service share 0.05 taken entirely from scheduled_maintenance (0.30 → 0.25).
# The other nine shares are unchanged so tire_service and hv_battery_diagnostic
# volumes seen by downstream consumers remain stable (spec § D3).
SERVICE_TYPE_PROBS = [0.25, 0.15, 0.05, 0.10, 0.05, 0.10, 0.05, 0.02, 0.08, 0.10, 0.05]

assert len(SERVICE_TYPES) == len(SERVICE_TYPE_PROBS), (
    f"SERVICE_TYPES has {len(SERVICE_TYPES)} entries but "
    f"SERVICE_TYPE_PROBS has {len(SERVICE_TYPE_PROBS)}; "
    "update both lists together"
)
assert abs(sum(SERVICE_TYPE_PROBS) - 1.0) < 1e-9, (
    f"SERVICE_TYPE_PROBS sums to {sum(SERVICE_TYPE_PROBS):.10f}, not 1.0; "
    "a future edit has introduced probability drift"
)
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
# Brake-specific DTC codes emitted for service_type='brake_service' rows.
# C0161 is mandatory — dtc-C0161.md is a deployed Bedrock KB guide (spec § D2),
# giving brake rows the same KB-join property TIRE_DTC_CODES was built for.
# U0121 (ABS communication loss) deliberately remains in TIRE_DTC_CODES; it is
# NOT duplicated here to avoid perturbing the tire cross-validation join (spec § D2).
# Brake DTC codes emitted for service_type='brake_service' rows.
#
# Descriptions below are aligned to ADP's OWN vehicle_knowledge_base definitions
# where one exists, because the VKB is what a consuming agent grounds on — a
# comment here that disagrees with the KB would mislead a reader of the public
# mirror. Only the two [KB] codes have a guide; the other eight are realistic
# brake/ABS codes with no KB entry, so a consuming agent can report them but
# cannot explain them. Tracked as a follow-on rather than silently implied.
#
# Manufacturer context is noted where a code is not SAE J2012 generic, since
# several C0xxx codes are reused with different meanings across OEMs.
BRAKE_DTC_CODES = [
    # [KB] vehicle_knowledge_base: "Brake System Pressure Circuit", severity P0,
    # remedy "Critical brake pressure loss detected. Pull over immediately."
    # That P0 phrasing is a safety property: per ~/.kiro/steering/agentic-tiers.md
    # a consuming agent must narrate it verbatim and may not soften it.
    "C0161",
    # [KB] vehicle_knowledge_base: "Right Front Wheel Speed Sensor Circuit", P1.
    # Also present in TIRE_DTC_CODES — genuinely shared brake/ABS/tyre surface.
    "C0040",
    "C0110",   # Antilock Brake System Motor Circuit (GM-family C-code)
    "C0200",   # Wheel Speed Sensor Circuit — Toyota/Lexus manufacturer-specific;
               # overlaps C0040's fault area under a different OEM numbering
    "C0210",   # Rear Right Wheel Speed Sensor Circuit (GM-family)
    "C0265",   # EBCM Relay Circuit (GM-family)
    "C0266",   # EBCM Relay Circuit Open (GM-family)
    "C0300",   # Rear Wheel Speed Sensor Circuit (GM-family)
    "U0415",   # Invalid Data Received From Anti-Lock Brake System Control Module
               # (SAE J1979/J2012 network code)
    "B2477",   # Module Configuration Failure — Ford-family body code; commonly
               # observed on the ABS module. NOT brake-booster-specific.
]
# EV-appropriate brake complaint templates, mirroring TIRE_COMPLAINT_TEMPLATES shape.
# Content covers the failure modes documented in spec § Design "Brake content shape":
# fluid service, pedal feel, regen-to-friction handoff, caliper/rotor corrosion,
# parking brake, ABS, fluid moisture, and pad wear.
BRAKE_COMPLAINT_TEMPLATES = [
    "Brake fluid service due at inspection interval",
    "Soft pedal — longer travel than usual before vehicle slows",
    "Brake squeal after vehicle parked overnight in damp conditions",
    "Regen-to-friction handoff feels rough at low speed",
    "Caliper sticking — uneven pad wear noted at inspection",
    "Rotor surface corrosion observed at front axle",
    "Parking brake warning light on — cable tension fault",
    "ABS warning light illuminated — module communication fault",
    "Brake fluid moisture content above service threshold",
    "Front pad wear at minimum — replacement recommended",
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

        # Spread service events over WINDOW_DAYS. Beta(2,4) peaks at 0.25 of the
        # window (~7.5 years ago), producing historically-concentrated coverage
        # with sparse recency. This is the correct base distribution; the cohort
        # supplement (generate_supplement) adds dense trailing-36-month coverage
        # for cohort VINs using a separate RNG.
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
        brake_service_mask = (df["service_type"] == "brake_service").to_numpy()
        comp_mask = rng.random(size=n) < 0.7
        complaint_vals = np.where(
            comp_mask,
            np.where(
                tire_service_mask,
                rng.choice(TIRE_COMPLAINT_TEMPLATES, size=n),
                np.where(
                    brake_service_mask,
                    rng.choice(BRAKE_COMPLAINT_TEMPLATES, size=n),
                    rng.choice(COMPLAINT_TEMPLATES, size=n),
                ),
            ),
            None,
        )
        df["complaint_text"] = pd.Series(complaint_vals, dtype="string")
        # DTC codes: array<string>; vary 0-3 codes.
        # tire_service rows preferentially emit TIRE_DTC_CODES (decisions.md d).
        # brake_service rows preferentially emit BRAKE_DTC_CODES (spec § D2).
        dtc_counts = rng.choice([0, 1, 2, 3], size=n, p=[0.30, 0.40, 0.20, 0.10])
        dtc_arrays = []
        for i, c in enumerate(dtc_counts):
            if c == 0:
                dtc_arrays.append(None)
            elif tire_service_mask[i]:
                dtc_arrays.append(list(rng.choice(TIRE_DTC_CODES, size=int(c)).tolist()))
            elif brake_service_mask[i]:
                dtc_arrays.append(list(rng.choice(BRAKE_DTC_CODES, size=int(c)).tolist()))
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
        # Total cost: 50% have one (rest are warranty).
        # D12.h — Meridian rebrand realism: right-skewed lognormal with
        # median ~$180 / mean ~$400 / clip $30-$5000. Params derived from
        # target moments:
        #   median = e^μ = 180  →  μ = ln(180) ≈ 5.193
        #   mean   = e^(μ + σ²/2) = 400  →  σ² = 2·ln(400/180) ≈ 1.598  →  σ ≈ 1.264
        # Clip low ($30 = the cost floor for even a routine tire rotation)
        # and high ($5000 = major powertrain job cap). Test contract
        # ``test_service_cost_right_skewed`` verifies sample skewness > 1.0.
        _LOGNORMAL_MU, _LOGNORMAL_SIGMA = 5.193, 1.264
        _SVC_COST_LO, _SVC_COST_HI = 30.0, 5000.0
        cost_mask = rng.random(size=n) < 0.5
        cost_vals = np.clip(
            rng.lognormal(mean=_LOGNORMAL_MU, sigma=_LOGNORMAL_SIGMA, size=n),
            _SVC_COST_LO, _SVC_COST_HI,
        )
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


def generate_supplement(
    *,
    cohort_vins: list[str],
    seed: int,
    product_salt: int = 901,
    output_root: str = "curated",
    region: str = "us-east-1",
    dimensions: dict,
) -> "pd.DataFrame":
    """Generate a dense trailing-36-month supplement for cohort VINs.

    Uses a separate RNG ``np.random.default_rng([seed, product_salt])``
    so it has zero interaction with the base generator's stream
    (``np.random.default_rng(seed + 400)``).  The base ``generate_table``
    path is NOT touched; non-cohort rows are byte-identical whether or not
    this function is called (R5 guarantee).

    Parameters
    ----------
    cohort_vins:
        The 100,013-VIN list (or a smaller sample for tests).
    seed:
        Base seed (42).
    product_salt:
        Domain-separation salt; default 901 for service_records.
    output_root:
        Passed through for callers that write the result (not used here).
    region:
        AWS region string (not used inside this function; present for
        interface parity with generate_table callers).
    dimensions:
        Dimension DataFrames; must include ``vins``, ``customers``,
        ``dealers``, ``parts``.  The ``vins`` DataFrame may optionally
        carry a ``model_year`` column; if present it is used to key the
        cost-growth rate on vehicle age (spec D6 S12, older vehicles →
        higher growth) rather than on VIN list position.

    Returns
    -------
    pd.DataFrame
        Supplement rows in the same schema as generate_table's output.
        The caller is responsible for writing them alongside the base
        output before publishing.
    """
    import uuid as _uuid
    from decimal import Decimal

    rng = np.random.default_rng([seed, product_salt])

    n = len(cohort_vins) * 40  # ~40 events per cohort VIN → ~34 distinct months

    # Time window: trailing 1080 days (36 months)
    SUPPLEMENT_WINDOW_DAYS = 36 * 30  # 1080 days
    anchor = pd.Timestamp.utcnow().tz_convert("UTC") - pd.Timedelta(days=SUPPLEMENT_WINDOW_DAYS)

    # Beta(3, 1.5) peaks at 0.57 of window (~21 months ago): mild recency
    # presence without extreme-end sparsity.
    time_offsets = (rng.beta(3.0, 1.5, size=n) * SUPPLEMENT_WINDOW_DAYS * 86400).astype("int64")
    service_time = anchor + pd.to_timedelta(time_offsets, unit="s")
    # Vectorised date extraction (S14: avoid per-row Python loops).
    # service_time is a DatetimeIndex with tz=UTC; .date returns array of Python date objects.
    service_dates = service_time.tz_convert("UTC").date

    # Month-in-window index (0–35), used for the cost-growth multiplier.
    # Vectorised: compute as integer number of 30-day intervals from anchor.
    anchor_date = anchor.date()
    month_in_window = np.clip(
        np.array([(d - anchor_date).days // 30 for d in service_dates], dtype=int),
        0, 35,
    )

    # VIN assignment: round-robin across cohort VINs so distribution is uniform.
    cohort_arr = np.array(cohort_vins, dtype=object)
    row_vin_idx = np.arange(n) % len(cohort_vins)
    row_vins = cohort_arr[row_vin_idx]

    # VIN age factor ∈ [0, 1]: keyed on model_year when available (S12).
    # 0 = newest vehicle (model_year max, e.g. 2026 → low growth rate),
    # 1 = oldest vehicle (model_year min, e.g. 2022 → high growth rate).
    # Fall back to list position when model_year is absent (synthetic test dims).
    vins_dim = dimensions["vins"]
    if "model_year" in vins_dim.columns:
        vin_to_my = dict(zip(vins_dim["vin"], vins_dim["model_year"].astype(int)))
        my_min = min(vin_to_my.values())
        my_max = max(vin_to_my.values())
        my_range = max(my_max - my_min, 1)
        # Map VIN idx → model_year → age_factor (1.0 for oldest, 0.0 for newest).
        per_cohort_factor = np.array(
            [(my_max - vin_to_my.get(v, my_max)) / my_range for v in cohort_vins],
            dtype=float,
        )
    else:
        # No model_year column (synthetic test dimensions): use list position.
        per_cohort_factor = np.arange(len(cohort_vins), dtype=float) / max(len(cohort_vins) - 1, 1)

    vin_age_factor = per_cohort_factor[row_vin_idx]

    # Growth rate per VIN: 1.5%/month (youngest) → 10.0%/month (oldest).
    # Calibrated on the FI spine (all 36 months, maintenance 0 where no paid
    # service exists).  With seed=42 / salt=901 / 1,000-VIN sample:
    #   sell_recommended ≈ 8.8%  → within spec R3 band [0%, 10%]
    #   sell_soon        ≈ 5.8%  → within spec R3 band [5%, 15%]
    #   healthy k 13-36  ≈ 21.7% → within spec R3 band [20%, 30%]
    # (Previous constants 0.010–0.040 were calibrated against cost-only months
    # and gave < 1% on the full FI spine — see review.md Cycle 1 Critical C8.)
    _GROWTH_MIN = 0.015   # lowest-ordinal / newest VIN
    _GROWTH_MAX = 0.100   # highest-ordinal / oldest VIN
    growth_rate = _GROWTH_MIN + (_GROWTH_MAX - _GROWTH_MIN) * vin_age_factor

    # Cost-growth multiplier: starts at 1.0, rises over 36 months.
    cost_multiplier = 1.0 + growth_rate * month_in_window

    customers = dimensions["customers"]
    dealers = dimensions["dealers"]
    parts = dimensions["parts"]

    customer_pool = customers["customer_id"].to_numpy()
    dealer_pool = dealers["dealer_id"].to_numpy()
    part_pool = parts["part_number"].to_numpy()

    df = pd.DataFrame()
    # Vectorised UUID generation (S14): use rng.integers to produce two 64-bit
    # halves and combine, avoiding a per-row Python loop over rng.bytes(16).
    hi = rng.integers(0, 2**63, size=n, dtype=np.uint64)
    lo = rng.integers(0, 2**63, size=n, dtype=np.uint64)
    df["service_id"] = pd.Series(
        [str(_uuid.UUID(int=(int(h) << 64) | int(l))) for h, l in zip(hi, lo)],
        dtype="string",
    )
    df["service_date"] = pd.Series(service_dates, dtype="object")
    # Vectorised first-of-month derivation (S14).
    df["service_month"] = pd.Series(
        [d.replace(day=1) for d in service_dates], dtype="object"
    )
    df["vin"] = pd.Series(row_vins, dtype="string")

    cust_mask = rng.random(size=n) < 0.90
    df["customer_id"] = pd.Series(
        np.where(cust_mask, rng.choice(customer_pool, size=n), None), dtype="string"
    )
    df["dealer_id"] = pd.Series(rng.choice(dealer_pool, size=n), dtype="string")
    df["service_type"] = pd.Series(
        rng.choice(SERVICE_TYPES, size=n, p=SERVICE_TYPE_PROBS), dtype="string"
    )

    tire_service_mask = (df["service_type"] == "tire_service").to_numpy()
    brake_service_mask = (df["service_type"] == "brake_service").to_numpy()
    comp_mask = rng.random(size=n) < 0.7
    complaint_vals = np.where(
        comp_mask,
        np.where(
            tire_service_mask,
            rng.choice(TIRE_COMPLAINT_TEMPLATES, size=n),
            np.where(
                brake_service_mask,
                rng.choice(BRAKE_COMPLAINT_TEMPLATES, size=n),
                rng.choice(COMPLAINT_TEMPLATES, size=n),
            ),
        ),
        None,
    )
    df["complaint_text"] = pd.Series(complaint_vals, dtype="string")

    dtc_counts = rng.choice([0, 1, 2, 3], size=n, p=[0.30, 0.40, 0.20, 0.10])
    dtc_arrays = []
    for i, c in enumerate(dtc_counts):
        if c == 0:
            dtc_arrays.append(None)
        elif tire_service_mask[i]:
            dtc_arrays.append(list(rng.choice(TIRE_DTC_CODES, size=int(c)).tolist()))
        elif brake_service_mask[i]:
            dtc_arrays.append(list(rng.choice(BRAKE_DTC_CODES, size=int(c)).tolist()))
        else:
            dtc_arrays.append(list(rng.choice(DTC_CODES, size=int(c)).tolist()))
    df["dtc_codes"] = pd.Series(dtc_arrays, dtype="object")

    part_counts = rng.choice([0, 1, 2], size=n, p=[0.40, 0.45, 0.15])
    part_arrays = []
    for c in part_counts:
        if c == 0:
            part_arrays.append(None)
        else:
            part_arrays.append(list(rng.choice(part_pool, size=int(c)).tolist()))
    df["parts_used"] = pd.Series(part_arrays, dtype="object")

    df["labor_hours"] = pd.Series(
        rng.gamma(shape=2.0, scale=1.5, size=n).clip(0.0, 80.0), dtype="Float64"
    )

    # 50% of rows are warranty-covered (NULL cost), matching the base rate.
    # Cost-growth multiplier is applied only to non-NULL (non-warranty) rows.
    # The effective growth rate seen by the FI linear fit is growth_rate × 0.5
    # because warranty months contribute $0, flattening the slope.
    # The growth constants (0.015–0.100/month) are calibrated to deliver the
    # R3 bucket distribution after this 50% halving, measured on the full 36-month
    # FI spine (all months present, maintenance 0 where no paid service exists).
    #
    # Supplement cost distribution: lognormal with moderate median.
    # μ=3.5 → median ~$33, mean ~$90 per non-warranty event.
    # Monthly sum ≈ 1.1 events/month × 0.5 paid × $90 × growth_multiplier.
    # At month 35, oldest VINs: $90 × (1 + 0.10×35) = ~$405 per event → monthly
    # totals above $500 for high-growth VINs within H=36 months.
    # (Previous μ=3.3 gave < 1% crossovers on the FI spine; see review.md C8.)
    _SUPP_LOGNORMAL_MU, _SUPP_LOGNORMAL_SIGMA = 3.5, 1.264
    _SVC_COST_LO, _SVC_COST_HI = 30.0, 5000.0
    cost_mask = rng.random(size=n) < 0.5
    raw_costs = np.clip(
        rng.lognormal(mean=_SUPP_LOGNORMAL_MU, sigma=_SUPP_LOGNORMAL_SIGMA, size=n),
        _SVC_COST_LO, _SVC_COST_HI,
    )
    # Apply cost-growth multiplier to non-warranty rows.
    grown_costs = np.clip(raw_costs * cost_multiplier, _SVC_COST_LO, _SVC_COST_HI * 2)
    df["total_cost_usd"] = pd.Series(
        [Decimal(f"{v:.2f}") if m else None for v, m in zip(grown_costs, cost_mask)],
        dtype="object",
    )
    df["warranty_covered"] = pd.Series(~cost_mask, dtype="boolean")

    df["technician_id"] = pd.Series(rng.choice(TECHS, size=n), dtype="string")
    df["outcome"] = pd.Series(rng.choice(OUTCOMES, size=n, p=OUTCOME_PROBS), dtype="string")

    csat_mask = rng.random(size=n) < 0.7
    csat_vals = rng.choice([1, 2, 3, 4, 5], size=n, p=[0.05, 0.05, 0.15, 0.35, 0.40])
    df["csat_score"] = pd.Series(
        np.where(csat_mask, csat_vals, None), dtype="Int32"
    )

    link_mask = rng.random(size=n) < 0.1
    # Vectorised UUID generation for linked_interaction_id (S14).
    hi2 = rng.integers(0, 2**63, size=n, dtype=np.uint64)
    lo2 = rng.integers(0, 2**63, size=n, dtype=np.uint64)
    link_ids = np.array(
        [str(_uuid.UUID(int=(int(h) << 64) | int(l))) for h, l in zip(hi2, lo2)],
        dtype=object,
    )
    df["linked_interaction_id"] = pd.Series(
        np.where(link_mask, link_ids, None),
        dtype="string",
    )
    sw_recall_mask = (df["service_type"] == "software_recall").to_numpy()
    df["linked_campaign_id"] = pd.Series(
        np.where(
            sw_recall_mask,
            [f"CAMP-{i:04d}" for i in rng.integers(1, 100, size=n)],
            None,
        ),
        dtype="string",
    )

    # Vectorised timestamp construction from pre-computed date objects (S14).
    df["event_time"] = pd.to_datetime(
        pd.Series(service_dates, dtype="object")
    ).dt.tz_localize("UTC").astype("datetime64[us, UTC]")
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
    p.add_argument(
        "--cohort-vins",
        default=None,
        help="Path to newline-delimited VIN list; activates supplement run "
             "after generate_table() completes.",
    )
    p.add_argument(
        "--supplement-salt",
        type=int,
        default=901,
        help="Supplement RNG salt; default 901 for service_records.",
    )
    p.add_argument(
        "--supplement-only",
        action="store_true",
        default=False,
        help=(
            "Generate ONLY the supplement (part-supp-{salt}.parquet files per "
            "service_month= partition). Requires --cohort-vins. Skips base "
            "generation entirely — no data.parquet is written and no base row "
            "is touched. This is the safe publish path for an additive cohort "
            "supplement when the base is already on S3."
        ),
    )
    args = p.parse_args()

    if args.supplement_only and not args.cohort_vins:
        print(
            "ERROR: --supplement-only requires --cohort-vins (path to newline-delimited VIN list).",
            file=sys.stderr,
        )
        return 1

    g = ServiceRecordsGenerator(
        seed=args.seed, scale=args.scale, output_root=args.output_root, region=args.region,
    )
    bucket = args.s3_lake_bucket
    if bucket is None and args.output_root.startswith("s3://"):
        bucket = args.output_root.replace("s3://", "").split("/", 1)[0]

    if args.supplement_only:
        # Supplement-only mode: skip base generation entirely.  Only part-supp-*
        # files are written.  The caller is responsible for uploading them to S3
        # and then calling publish_product.py --register-only (which runs MSCK
        # REPAIR on the raw layer to discover both data.parquet and part-supp-*
        # files, then rebuilds the Iceberg table from all of them).
        summary: dict = {}
    else:
        summary = g.run(
        dim_root=Path(args.dim_root), register_iceberg=args.register_iceberg, s3_lake_bucket=bucket,
    )

    # Supplement run — separate RNG, cohort VINs only, trailing 36 months.
    if args.cohort_vins:
        cohort_path = Path(args.cohort_vins)
        # C6: the cohort is the energy_usage pool (first 100,000 VINs by ordinal_index)
        # PLUS the 13 out-of-pool CMS-overlap VINs from the file.  Load the pool
        # from the dimensions instead of treating the file as the entire cohort.
        extra_vins = [v.strip() for v in cohort_path.read_text().splitlines() if v.strip()]
        dims = g.load_dimensions(Path(args.dim_root), ["vins", "customers", "dealers", "parts"])
        # Pool = first 100,000 VINs by vin string order (matching energy_usage
        # _load_vin_pool which uses orderBy("vin"), NOT ordinal_index).
        # Using vin string sort ensures the 13 out-of-pool CMS VINs are truly
        # outside the pool and the cohort is exactly 100,013 VINs.
        vins_dim = dims["vins"]
        pool_vins = (
            vins_dim.sort_values("vin")
            .head(100_000)["vin"]
            .tolist()
        )
        # Union: pool + the 13 out-of-pool VINs (deduplication preserves order).
        seen: set[str] = set(pool_vins)
        cohort_vins_list = pool_vins + [v for v in extra_vins if v not in seen]
        print(
            f"[service_records] cohort: {len(cohort_vins_list):,} VINs "
            f"({len(pool_vins):,} pool + {len(extra_vins):,} extra)"
        )
        supp_df = generate_supplement(
            cohort_vins=cohort_vins_list,
            seed=args.seed,
            product_salt=args.supplement_salt,
            output_root=args.output_root,
            region=args.region,
            dimensions=dims,
        )
        # C5 (F2.2 step-back): write supplement rows into service_month= partition
        # directories using the file name part-supp-{salt}.parquet — NEVER
        # data.parquet, which would overwrite the base rows.  This makes the
        # supplement additive: publish_product.py's MSCK REPAIR picks up every
        # *.parquet file in the partition directory, and the subsequent Iceberg
        # INSERT INTO SELECT reads all of them.  Re-runs overwrite the same
        # part-supp-{salt}.parquet object (idempotent), so base rows are never
        # touched.  No .vintage-meta.json sidecar is written for supplement
        # files; the base sidecar's row count remains accurate for the base alone,
        # and the supplement is not included in the manifest.
        try:
            import pyarrow as _pa
            import pyarrow.parquet as _pq
        except ImportError:
            print("[service_records] pyarrow not available — install with pip install pyarrow", file=sys.stderr)
            return 1

        # Build pyarrow schema from schema_loader Table (same as product_generator.py).
        tbl = g.schema.first_table()
        _fields = []
        _TYPE_MAP = {
            "string": _pa.string(), "int": _pa.int32(), "bigint": _pa.int64(),
            "double": _pa.float64(), "boolean": _pa.bool_(),
            "timestamp": _pa.timestamp("us", tz="UTC"), "date": _pa.date32(),
            "array<string>": _pa.list_(_pa.string()), "array<int>": _pa.list_(_pa.int32()),
        }
        for col in tbl.columns:
            if col.type == "decimal":
                assert col.decimal_precision is not None and col.decimal_scale is not None
                ty: "_pa.DataType" = _pa.decimal128(col.decimal_precision, col.decimal_scale)
            else:
                ty = _TYPE_MAP[col.type]
            _fields.append(_pa.field(col.name, ty, nullable=col.nullable))
        _pa_schema = _pa.schema(_fields)

        tbl_dir = Path(args.output_root) / "service_records" / "service_records"
        tbl_dir.mkdir(parents=True, exist_ok=True)
        supp_file_name = f"part-supp-{args.supplement_salt}.parquet"
        written_partitions: list[str] = []
        for part_value, part_df in supp_df.groupby("service_month", dropna=False):
            part_str = "__null__" if pd.isna(part_value) else str(part_value)
            part_dir = tbl_dir / f"service_month={part_str}"
            part_dir.mkdir(parents=True, exist_ok=True)
            out_path = part_dir / supp_file_name
            try:
                _arrow_tbl = _pa.Table.from_pandas(part_df, schema=_pa_schema, preserve_index=False)
            except Exception:
                _arrow_tbl = _pa.Table.from_pandas(part_df, preserve_index=False)
            _pq.write_table(_arrow_tbl, out_path, compression="zstd")
            written_partitions.append(str(part_dir))
        print(
            f"[service_records] supplement rows: {len(supp_df):,} written to "
            f"{tbl_dir} in {len(written_partitions)} partitions "
            f"as {supp_file_name} (never data.parquet)"
        )

    import json
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
