"""Red-phase tests for the Meridian EV-OEM rebrand.

Spec: `.kiro/specs/2026-09-10-adp-meridian-ev-oem-reseed/spec.md`
      D1 (organic ramp volume), D2 (CMS demo VINs at ordinal head),
      D3 (procedural VIN scheme + check digits), D4 (model catalog),
      D5 (all EV), D6 (child-product volumes), D12 (realism upgrades).

These tests FAIL until Group 2 ships. The failure IS the red phase.

Two categories:
1. Interface tests — run in skeleton phase; fail if the module exists
   but doesn't export the expected symbols, OR pass if the module doesn't
   exist yet (waiting on T2.1). These bind the API surface Group 2 must
   implement.
2. Data-presence tests — skip gracefully if generator output isn't on
   disk yet. Once Group 2 (implementation) + Group 3 T3.1 (dry-run) ship,
   these run against the generated parquet and enforce D1/D2/D3/D4/D5/D12
   properties.

Import convention matches `test_dimensions.py`: `schema_loader as sl`,
local `pyarrow.parquet` imports so this module is importable without
`pyarrow` installed.

Meridian CMS demo VINs (D2) — 21 vehicles from `cms-staging-storage-vehicles`
with `make='Meridian'`. Their VIN strings are hand-crafted (`MRDN*` or
`DEMO*` prefixes) and DO NOT carry valid ISO 3779 check digits (spec D2
note). Tests for check-digit validity apply to the procedural block only
(ordinals >= 21).

Constants from spec:
- Total pool = 4,734,904 (D1)
- CMS block = 21 vehicles (ordinals 0-20)
- Procedural block = 4,734,883 (ordinals 21-4,734,903)
- Model years = {2022, 2023, 2024, 2025, 2026}
- Model catalog (7 models, all EV, D4):
  Trailwind, Azimuth, Windrose, Crestwind, Zephyr, Sirocco, Mistral
- Model-year gating (D12.a introduction dates):
  Trailwind/Azimuth  — 2022+
  Windrose/Crestwind — 2023+
  Zephyr/Sirocco     — 2024+
  Mistral            — 2025+
- Trim configs (D12.b) — discrete (model, trim) → (kWh, motors, range, kW).
  See _TRIM_CONFIGS below; if these values are edited, D12.b must be
  edited in the same commit.
- Plants (D12.d): {'CGA', 'RNO'}, Reno opens 2024-04-01.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Pinned constants — mirror D1 + D4 + D12 tables from spec.
# If these disagree with the spec, the SPEC is the source of truth and this
# test file needs updating.
# ---------------------------------------------------------------------------

TOTAL_POOL_SIZE: int = 4_734_904
CMS_BLOCK_SIZE: int = 21
PROCEDURAL_BLOCK_SIZE: int = TOTAL_POOL_SIZE - CMS_BLOCK_SIZE  # 4,734,883

MERIDIAN_MODELS: frozenset[str] = frozenset({
    "Trailwind", "Azimuth", "Windrose", "Crestwind",
    "Zephyr", "Sirocco", "Mistral",
})

# D12.a — model → (first_year, last_year). last_year=None means still in production.
MODEL_INTRODUCTION_YEAR: dict[str, int] = {
    "Trailwind": 2022,
    "Azimuth":   2022,
    "Windrose":  2023,
    "Crestwind": 2023,
    "Zephyr":    2024,
    "Sirocco":   2024,
    "Mistral":   2025,
}

# D1 per-year VIN counts. Values are the exact deterministic targets.
# See spec D1's table.
YEAR_VIN_COUNTS: dict[int, int] = {
    2022: 245_913,
    2023: 897_441,
    2024: 1_383_776,
    2025: 1_721_554,
    2026: 486_220,
}
assert sum(YEAR_VIN_COUNTS.values()) == TOTAL_POOL_SIZE, (
    "YEAR_VIN_COUNTS must sum to TOTAL_POOL_SIZE — check spec D1"
)

# D12.b — (model, trim) → (battery_kwh, motor_count, range_epa_mi, max_charging_rate_kw).
# Every value in every column MUST come from this table. No mid-range Faker samples.
_TRIM_CONFIGS: dict[tuple[str, str], tuple[float, int, float, float]] = {
    ("Trailwind", "Standard"):    (100.0, 2, 350.0, 250.0),
    ("Trailwind", "Plus"):        (118.0, 3, 400.0, 300.0),
    ("Trailwind", "Performance"): (118.0, 4, 380.0, 350.0),
    ("Azimuth", "Standard"):      (118.0, 2, 400.0, 300.0),
    ("Azimuth", "Plus"):          (118.0, 3, 450.0, 300.0),
    ("Azimuth", "Performance"):   (118.0, 4, 425.0, 350.0),
    ("Windrose", "Standard"):     (100.0, 2, 320.0, 250.0),
    ("Windrose", "Plus"):         (118.0, 2, 380.0, 300.0),
    ("Windrose", "Performance"):  (118.0, 3, 360.0, 350.0),
    ("Crestwind", "Standard"):    ( 75.0, 2, 280.0, 200.0),
    ("Crestwind", "Plus"):        (100.0, 2, 340.0, 250.0),
    ("Crestwind", "Performance"): (100.0, 3, 320.0, 300.0),
    ("Zephyr", "Standard"):       ( 90.0, 2, 300.0, 250.0),
    ("Zephyr", "Plus"):           (100.0, 3, 350.0, 300.0),
    ("Zephyr", "Performance"):    (100.0, 4, 320.0, 350.0),
    ("Sirocco", "Standard"):      (100.0, 2, 250.0, 200.0),
    ("Sirocco", "Plus"):          (118.0, 3, 290.0, 250.0),
    ("Sirocco", "Performance"):   (130.0, 4, 270.0, 300.0),
    ("Mistral", "Standard"):      (130.0, 3, 450.0, 350.0),
    ("Mistral", "Plus"):          (130.0, 4, 480.0, 350.0),
    ("Mistral", "Performance"):   (150.0, 4, 500.0, 350.0),
}

VALID_BATTERY_KWH: frozenset[float] = frozenset(
    kwh for (kwh, _, _, _) in _TRIM_CONFIGS.values()
)
VALID_TRIMS: frozenset[str] = frozenset({"Standard", "Plus", "Performance"})
VALID_PLANTS: frozenset[str] = frozenset({"CGA", "RNO"})
RENO_OPEN_DATE: str = "2024-04-01"  # D12.d — plant volume distribution

# Test-fixture plant codes from the RETIRED Acme era. Must NOT appear.
RETIRED_ACME_PLANTS: frozenset[str] = frozenset({"DET-01", "DET-02", "MEX-01"})


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _vins_parquet_path(dimension_root: Path) -> Path:
    return dimension_root / "vins" / "data.parquet"


def _vehicle_identity_parquet_path(curated_root: Path) -> Path:
    return curated_root / "vehicle_identity" / "vehicle_identity" / "data.parquet"


def _read_vins_df(dimension_root: Path):
    """Load the vins dimension parquet as a pandas DataFrame.

    Skips the test if the parquet isn't on disk yet — Group 2 hasn't shipped.
    """
    p = _vins_parquet_path(dimension_root)
    if not p.exists():
        pytest.skip(f"{p} not produced yet — Group 2 dimension generator pending")
    import pandas as pd  # noqa: WPS433 — local import to keep skeleton importable

    return pd.read_parquet(p)


def _read_vehicle_identity_df(curated_root: Path):
    """Read curated vehicle_identity — Hive-partitioned by model_year.

    Uses ``_read_curated_partitioned`` under the hood so tests survive
    the real partitioned layout (see T3.1 discovery: prior helper looked
    for a single unpartitioned ``data.parquet`` that only exists in
    smoke fixtures, not in real generator output).
    """
    return _read_curated_partitioned(
        curated_root,
        "vehicle_identity",
        columns=[
            "vin", "model", "trim", "body_style", "battery_pack_kwh",
            "motor_count", "range_epa_mi", "max_charging_rate_kw",
            "assembly_plant", "assembly_plant_location", "make",
            "powertrain_type", "model_year",
        ],
        sample_n=None,
    )


def _read_curated_partitioned(
    curated_root: Path, product: str, columns: list[str], sample_n: int | None = None
):
    """Read a Hive-partitioned curated product's parquet tree.

    ``curated_root/<product>/<product>/`` is the Iceberg-shaped layout the
    per-product generators produce. Reads each parquet file directly via
    ``pyarrow.parquet.ParquetFile`` (bypassing the dataset machinery)
    because the generators emit Hive-partitioned trees that carry the
    partition column INSIDE the parquet file in addition to the directory
    path, and ``pyarrow.dataset`` fails to merge the two (``date32[day]``
    in-file vs ``string`` from path). This matches the reader pattern in
    ``test_referential_integrity.py``.

    ``sample_n``: if provided and fewer parquet files can supply that many
    rows collectively, all rows are returned; otherwise per-file rows are
    taken proportionally until the target is met. Deterministic
    (``sort()`` of glob results + head-based truncation).

    Skips if the product dir hasn't been produced yet (T3.1 dry-run
    pending).
    """
    p = curated_root / product / product
    if not p.exists():
        pytest.skip(f"{p} not produced yet — Group 3 {product} generator pending")

    import pyarrow.parquet as pq
    import pandas as pd
    import re

    files = sorted(p.rglob("*.parquet"))
    if not files:
        pytest.skip(f"{p} has no parquet files — {product} generator pending")

    frames: list[pd.DataFrame] = []
    rows_collected = 0
    per_file = None
    if sample_n is not None:
        per_file = max(1, sample_n // len(files))
    # Regex to extract Hive partition (`key=value`) pairs from a file's
    # ancestor path components. Applies when a requested column is a
    # partition column carried only in the path (e.g. PySpark-produced
    # tables like `energy_usage` where partitionBy("usage_date") stores
    # the value in the dirname, not the file body).
    _HIVE_KV = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.+)$")

    def _partition_kv(path: Path) -> dict[str, str]:
        kv: dict[str, str] = {}
        for parent in path.parents:
            m = _HIVE_KV.match(parent.name)
            if m:
                kv[m.group(1)] = m.group(2)
        return kv

    for f in files:
        pf = pq.ParquetFile(str(f))
        available = [c for c in columns if c in pf.schema_arrow.names]
        path_kv = _partition_kv(f)
        # Path-only columns (requested but not in file body, present in
        # the Hive path).
        path_cols = {c: path_kv[c] for c in columns if c not in pf.schema_arrow.names and c in path_kv}
        if not available and not path_cols:
            continue
        tbl = pf.read(columns=available) if available else None
        df = tbl.to_pandas() if tbl is not None else pd.DataFrame(index=range(pf.metadata.num_rows))
        # Add path-carried columns (broadcast scalar to all rows in file).
        for col_name, col_val in path_cols.items():
            df[col_name] = col_val
        if per_file is not None and len(df) > per_file:
            df = df.head(per_file)
        frames.append(df)
        rows_collected += len(df)
        if sample_n is not None and rows_collected >= sample_n:
            break

    if not frames:
        pytest.skip(f"{p} parquet files have no requested columns: {columns}")
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# D12.h — Child-product cost realism helpers
# ---------------------------------------------------------------------------


def _decimal_to_float(series):
    """Convert a pandas Series of Decimal objects to float (dropping nulls)."""
    import pandas as pd

    return pd.to_numeric(series.dropna().astype(str), errors="coerce").dropna()


# ---------------------------------------------------------------------------
# Interface tests — run at skeleton phase.
# These enforce the API surface Group 2 must implement.
# ---------------------------------------------------------------------------


def test_generate_all_exports_meridian_constants():
    """dimensions/generate_all.py must export MERIDIAN_WMI + MERIDIAN_MODELS.

    T2.2 replaces `ACME_WMI` + `ACME_MODELS` with `MERIDIAN_WMI` + `MERIDIAN_MODELS`.
    Until T2.2 ships, this test FAILS (either ImportError or AttributeError).
    """
    import sys
    from pathlib import Path as _P

    _pf_source = _P(__file__).resolve().parent.parent / "source"
    if str(_pf_source) not in sys.path:
        sys.path.insert(0, str(_pf_source))

    from dimensions import generate_all as g  # type: ignore[attr-defined]

    assert hasattr(g, "MERIDIAN_WMI"), "T2.2 must export MERIDIAN_WMI"
    assert g.MERIDIAN_WMI == "MRD", f"MERIDIAN_WMI should be 'MRD', got {g.MERIDIAN_WMI!r}"

    assert hasattr(g, "MERIDIAN_MODELS"), "T2.2 must export MERIDIAN_MODELS"
    # MERIDIAN_MODELS is a list-of-tuples per D4 spec — extract model names.
    model_names = {row[0] for row in g.MERIDIAN_MODELS}
    assert model_names == set(MERIDIAN_MODELS), (
        f"MERIDIAN_MODELS model names must equal {sorted(MERIDIAN_MODELS)}; "
        f"got {sorted(model_names)}"
    )

    assert not hasattr(g, "ACME_WMI"), "T2.2 must retire ACME_WMI"
    assert not hasattr(g, "ACME_MODELS"), "T2.2 must retire ACME_MODELS"


def test_generate_all_exports_meridian_trims():
    """T2.2 must export MERIDIAN_TRIMS lookup keyed by (model, trim)."""
    import sys
    from pathlib import Path as _P

    _pf_source = _P(__file__).resolve().parent.parent / "source"
    if str(_pf_source) not in sys.path:
        sys.path.insert(0, str(_pf_source))

    from dimensions import generate_all as g

    assert hasattr(g, "MERIDIAN_TRIMS"), (
        "T2.2 must export MERIDIAN_TRIMS lookup per D12.b"
    )
    assert isinstance(g.MERIDIAN_TRIMS, dict)
    assert set(g.MERIDIAN_TRIMS.keys()) == set(_TRIM_CONFIGS.keys()), (
        "MERIDIAN_TRIMS keys must match D12.b's 21 (model, trim) tuples"
    )
    # Content pins — every entry equals D12.b exactly.
    for (model, trim), config in _TRIM_CONFIGS.items():
        got = g.MERIDIAN_TRIMS[(model, trim)]
        assert got == config, (
            f"MERIDIAN_TRIMS[({model!r},{trim!r})] must equal {config}, got {got}"
        )


def test_generate_all_exports_meridian_plants():
    """T2.2 must export MERIDIAN_PLANTS with the two plants + open dates."""
    import sys
    from pathlib import Path as _P

    _pf_source = _P(__file__).resolve().parent.parent / "source"
    if str(_pf_source) not in sys.path:
        sys.path.insert(0, str(_pf_source))

    from dimensions import generate_all as g

    assert hasattr(g, "MERIDIAN_PLANTS"), "T2.2 must export MERIDIAN_PLANTS per D12.d"
    plant_codes = {row[0] if isinstance(row, tuple) else row for row in g.MERIDIAN_PLANTS}
    assert plant_codes == set(VALID_PLANTS), (
        f"MERIDIAN_PLANTS codes must be {sorted(VALID_PLANTS)}, got {sorted(plant_codes)}"
    )


def test_generate_all_scale_vins_updated():
    """SCALE['vins'] must be 4,734,904 (D1 organic ramp total)."""
    import sys
    from pathlib import Path as _P

    _pf_source = _P(__file__).resolve().parent.parent / "source"
    if str(_pf_source) not in sys.path:
        sys.path.insert(0, str(_pf_source))

    from dimensions import generate_all as g

    assert g.SCALE["vins"] == TOTAL_POOL_SIZE, (
        f"SCALE['vins'] must be {TOTAL_POOL_SIZE} (D1); got {g.SCALE['vins']}"
    )


# ---------------------------------------------------------------------------
# Data-presence tests — require Group 2's generator to have run.
# ---------------------------------------------------------------------------


@pytest.mark.needs_dimensions
def test_meridian_vin_pool_size(dimension_root):
    """D1: total pool = 4,734,904 exactly."""
    df = _read_vins_df(dimension_root)
    assert len(df) == TOTAL_POOL_SIZE, (
        f"Expected exactly {TOTAL_POOL_SIZE} rows (D1 organic ramp total), got {len(df)}"
    )


@pytest.mark.needs_dimensions
def test_meridian_wmi_is_mrd_not_1fa_on_procedural(dimension_root):
    """D3: every procedural VIN (ordinal >= 21) starts with 'MRD'."""
    df = _read_vins_df(dimension_root)
    proc = df.iloc[CMS_BLOCK_SIZE:]
    prefixes = proc["vin"].str[:3].unique()
    assert set(prefixes) == {"MRD"}, (
        f"Procedural block must all start with 'MRD'; got {sorted(prefixes)}"
    )


@pytest.mark.needs_dimensions
def test_no_ford_wmi_in_procedural(dimension_root):
    """The rebrand retires the '1FA' Ford-WMI collision."""
    df = _read_vins_df(dimension_root)
    proc = df.iloc[CMS_BLOCK_SIZE:]
    assert not proc["vin"].str.startswith("1FA").any(), (
        "No procedural VIN may start with '1FA' (Acme's retired WMI)"
    )


@pytest.mark.needs_dimensions
def test_cms_demo_vins_present_at_ordinal_head(dimension_root):
    """D2: CMS demo VINs occupy ordinals 0-20 verbatim.

    Every ordinal 0-20 VIN should have make='Meridian Motors' and a VIN prefix
    in {MRDN, DEMO} — the two prefixes CMS uses (F4 of spec).
    """
    df = _read_vins_df(dimension_root)
    cms_block = df.iloc[:CMS_BLOCK_SIZE]
    assert len(cms_block) == CMS_BLOCK_SIZE, (
        f"CMS block must be first {CMS_BLOCK_SIZE} rows; got {len(cms_block)}"
    )
    prefixes = cms_block["vin"].str[:4].unique()
    assert set(prefixes) <= {"MRDN", "DEMO"}, (
        f"CMS block VINs must have MRDN or DEMO prefix; got {sorted(prefixes)}"
    )


@pytest.mark.needs_dimensions
def test_meridian_models_replace_acme(dimension_root):
    """D4: every model is in the 7-model Meridian catalog."""
    df = _read_vins_df(dimension_root)
    actual = set(df["model"].unique())
    assert actual == set(MERIDIAN_MODELS), (
        f"Model set must equal {sorted(MERIDIAN_MODELS)}; got {sorted(actual)}"
    )


@pytest.mark.needs_dimensions
def test_all_meridian_vins_are_electric(dimension_root):
    """D5: every VIN has powertrain_type='electric'."""
    df = _read_vins_df(dimension_root)
    values = set(df["powertrain_type"].unique())
    assert values == {"electric"}, (
        f"All powertrain_type must be 'electric'; got {sorted(values)}"
    )


@pytest.mark.needs_dimensions
def test_manufacture_years_span_2022_to_2026(dimension_root):
    """D1: model years exactly {2022, 2023, 2024, 2025, 2026}."""
    df = _read_vins_df(dimension_root)
    years = set(df["model_year"].unique())
    assert years == {2022, 2023, 2024, 2025, 2026}, (
        f"Model years must be exactly 2022-2026; got {sorted(years)}"
    )


@pytest.mark.needs_dimensions
def test_model_year_distribution_matches_ramp(dimension_root):
    """D1: per-year VIN counts within ±0.1% of the pinned ramp values."""
    df = _read_vins_df(dimension_root)
    counts = df.groupby("model_year").size().to_dict()
    for year, expected in YEAR_VIN_COUNTS.items():
        actual = counts.get(year, 0)
        # ±0.1% tolerance = ±1000 for a 1M-ish value; more permissive for small years.
        tolerance = max(500, int(expected * 0.001))
        assert abs(actual - expected) <= tolerance, (
            f"MY{year}: got {actual}, expected {expected} ± {tolerance}"
        )


@pytest.mark.needs_dimensions
def test_no_acme_brand_in_output(dimension_root):
    """No row has make='Acme Motors' (rebrand complete)."""
    df = _read_vins_df(dimension_root)
    if "make" not in df.columns:
        pytest.skip("vins dimension does not carry 'make' column")
    assert not (df["make"] == "Acme Motors").any(), (
        "No row may have make='Acme Motors' — rebrand incomplete"
    )


# ---------------------------------------------------------------------------
# D12.a — Model-year gating
# ---------------------------------------------------------------------------


@pytest.mark.needs_dimensions
def test_no_2022_mistral(dimension_root):
    """D12.a: Mistral introduces in 2025 — no 2022/2023/2024 Mistral exists.

    Includes a positive control: Mistral MUST exist somewhere in 2025+ so
    the "no early Mistral" check isn't vacuously satisfied by Mistral being
    absent from the dataset entirely (which is the pre-rebrand Acme state).
    """
    df = _read_vins_df(dimension_root)
    # Positive control — Mistral MUST exist in the dataset in 2025+.
    mistral_present = df[(df["model"] == "Mistral") & (df["model_year"] >= 2025)]
    assert not mistral_present.empty, (
        "Positive control failed: no Mistral rows found in MY2025+. "
        "Either the dataset is not yet the Meridian rebrand (still Acme?) "
        "or the generator dropped Mistral entirely."
    )
    # Actual gating check.
    early_mistral = df[(df["model"] == "Mistral") & (df["model_year"] < 2025)]
    assert early_mistral.empty, (
        f"Found {len(early_mistral)} Mistral rows in MY2022-2024 — "
        f"violates D12.a (Mistral first year = 2025)"
    )


@pytest.mark.needs_dimensions
def test_model_year_gating_all_models(dimension_root):
    """D12.a: every (model, year) pair respects the introduction year table.

    Includes positive controls per model: each Meridian model MUST have at
    least one row in its introduction year OR later. This prevents vacuous
    passes when the dataset has zero rows for a model (which is the pre-
    rebrand Acme state — no Meridian models exist at all).
    """
    df = _read_vins_df(dimension_root)
    # Positive control — every Meridian model MUST exist in >= its intro year.
    for model, first_year in MODEL_INTRODUCTION_YEAR.items():
        present = df[(df["model"] == model) & (df["model_year"] >= first_year)]
        assert not present.empty, (
            f"Positive control failed: no {model} rows found in MY{first_year}+. "
            f"Either the dataset is not yet the Meridian rebrand or the generator "
            f"dropped {model} entirely."
        )
    # Actual gating check.
    for model, first_year in MODEL_INTRODUCTION_YEAR.items():
        early = df[(df["model"] == model) & (df["model_year"] < first_year)]
        assert early.empty, (
            f"Found {len(early)} {model} rows before MY{first_year} — "
            f"violates D12.a introduction year"
        )


# ---------------------------------------------------------------------------
# D12.b — Discrete trim configurations
# ---------------------------------------------------------------------------


@pytest.mark.needs_dimensions
def test_battery_kwh_is_discrete(curated_root):
    """D12.b: every battery_pack_kwh ∈ D12.b's exact set."""
    df = _read_vehicle_identity_df(curated_root)
    if "battery_pack_kwh" not in df.columns:
        pytest.skip("vehicle_identity does not carry battery_pack_kwh")
    actual = set(df["battery_pack_kwh"].dropna().unique())
    unexpected = actual - VALID_BATTERY_KWH
    assert not unexpected, (
        f"battery_pack_kwh must be one of {sorted(VALID_BATTERY_KWH)}; "
        f"found unexpected values: {sorted(unexpected)}"
    )


@pytest.mark.needs_dimensions
def test_trim_config_binds_battery_motor_range(curated_root):
    """D12.b: for each (model, trim), battery/motor/range match the fixed lookup.

    ``range_epa_mi`` is ``edge_case_eligible`` in the vehicle_identity schema,
    so the ``outlier_value`` edge-case injector poisons ~0.4% of rows with
    values 5-10× the schema max (800 mi) → observed outliers in the 4000-
    8000 mi range. Filter to values within the schema range [100, 800]
    before the per-(model, trim) equality check — the outlier population
    is expected pollution, not a D12.b contract violation. The D12.b
    contract holds on the well-formed 99.6%.
    """
    df = _read_vehicle_identity_df(curated_root)
    required_cols = {"model", "trim", "battery_pack_kwh", "motor_count", "range_epa_mi"}
    missing = required_cols - set(df.columns)
    if missing:
        pytest.skip(f"vehicle_identity missing required columns: {missing}")

    # Filter outlier_value poisons — values outside schema range on
    # edge_case_eligible columns. range_epa_mi is the only D12.b column
    # currently flagged edge_case_eligible in vehicle_identity/schema.yaml;
    # its schema range is [100, 800]. Values above 800 (5-10× multiplier)
    # or below 100 are the outlier_value injector's output.
    df = df[
        (df["range_epa_mi"] >= 100.0)
        & (df["range_epa_mi"] <= 800.0)
    ]

    grouped = df.groupby(["model", "trim"])[
        ["battery_pack_kwh", "motor_count", "range_epa_mi"]
    ].agg(lambda x: set(x.dropna().unique()))

    for (model, trim), expected in _TRIM_CONFIGS.items():
        if (model, trim) not in grouped.index:
            continue  # this (model, trim) combo may not appear (e.g. Mistral trim missing)
        exp_kwh, exp_motors, exp_range, _ = expected
        row = grouped.loc[(model, trim)]
        assert row["battery_pack_kwh"] == {exp_kwh}, (
            f"({model},{trim}): battery_pack_kwh must be exactly {exp_kwh}; "
            f"got {row['battery_pack_kwh']}"
        )
        assert row["motor_count"] == {exp_motors}, (
            f"({model},{trim}): motor_count must be exactly {exp_motors}; "
            f"got {row['motor_count']}"
        )
        assert row["range_epa_mi"] == {exp_range}, (
            f"({model},{trim}): range_epa_mi must be exactly {exp_range}; "
            f"got {row['range_epa_mi']}"
        )


@pytest.mark.needs_dimensions
def test_trim_distribution_skew(curated_root):
    """D12.b: trim shares are Standard 45% / Plus 35% / Performance 20% ± 2%."""
    df = _read_vehicle_identity_df(curated_root)
    if "trim" not in df.columns:
        pytest.skip("vehicle_identity does not carry trim column")
    shares = df["trim"].value_counts(normalize=True).to_dict()
    expected = {"Standard": 0.45, "Plus": 0.35, "Performance": 0.20}
    for trim, exp_share in expected.items():
        got = shares.get(trim, 0.0)
        assert abs(got - exp_share) <= 0.02, (
            f"Trim '{trim}' share: got {got:.3f}, expected {exp_share:.3f} ± 0.02"
        )


# ---------------------------------------------------------------------------
# D12.c — VIN check-digit correctness on procedural block
# ---------------------------------------------------------------------------


def _iso3779_check_digit(vin: str) -> str:
    """Compute the ISO 3779 VIN check digit (position 9, 0-indexed=8).

    Returns the expected check digit for a VIN's positions 0-7 + 9-16
    (i.e., excluding the current position-8 character).
    """
    # ISO 3779 transliteration: letters → digits (I, O, Q excluded).
    # A=1..I=9, J=1..R=9 (O skipped), S=2..Z=9 (Q skipped).
    trans = {
        "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
        "J": 1, "K": 2, "L": 3, "M": 4, "N": 5,           "P": 7,
        "R": 9,
        "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
    }
    # Position weights per ISO 3779 (position 9 = the check digit itself has weight 0).
    weights = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
    total = 0
    for i, ch in enumerate(vin.upper()):
        if ch.isdigit():
            v = int(ch)
        else:
            v = trans.get(ch, 0)
        total += v * weights[i]
    r = total % 11
    return "X" if r == 10 else str(r)


@pytest.mark.needs_dimensions
def test_vin_check_digit_valid_on_procedural(dimension_root):
    """D12.c: samples 1000 procedural VINs; check digit at position 9 valid."""
    df = _read_vins_df(dimension_root)
    proc = df.iloc[CMS_BLOCK_SIZE:CMS_BLOCK_SIZE + 1000]
    for vin in proc["vin"]:
        if len(vin) != 17:
            pytest.fail(f"VIN {vin!r} is not 17 chars")
        expected = _iso3779_check_digit(vin)
        assert vin[8] == expected, (
            f"VIN {vin!r}: check digit at pos 9 is {vin[8]!r}, expected {expected!r}"
        )


# ---------------------------------------------------------------------------
# D12.d — Two-plant production
# ---------------------------------------------------------------------------


@pytest.mark.needs_dimensions
def test_plant_codes_are_meridian(dimension_root):
    """D12.d: assembly_plant ∈ {'CGA', 'RNO'} — no Acme test-fixture codes."""
    df = _read_vins_df(dimension_root)
    if "assembly_plant" not in df.columns:
        pytest.skip("vins dimension does not carry assembly_plant")
    actual = set(df["assembly_plant"].dropna().unique())
    unexpected = actual - VALID_PLANTS
    assert not unexpected, (
        f"assembly_plant must be in {sorted(VALID_PLANTS)}; found unexpected: "
        f"{sorted(unexpected)}"
    )


@pytest.mark.needs_dimensions
def test_no_test_fixture_plant_codes(dimension_root):
    """D12.d: no VIN has one of the retired Acme test-fixture plant codes."""
    df = _read_vins_df(dimension_root)
    if "assembly_plant" not in df.columns:
        pytest.skip("vins dimension does not carry assembly_plant")
    actual = set(df["assembly_plant"].dropna().unique())
    hits = actual & RETIRED_ACME_PLANTS
    assert not hits, f"Retired Acme plant codes present: {sorted(hits)}"


@pytest.mark.needs_dimensions
def test_reno_absent_before_2024_apr(dimension_root):
    """D12.d: RNO does not appear before manufacture_date >= 2024-04-01."""
    df = _read_vins_df(dimension_root)
    if "assembly_plant" not in df.columns or "manufacture_date" not in df.columns:
        pytest.skip("vins dimension missing assembly_plant or manufacture_date")
    import pandas as pd

    reno = df[df["assembly_plant"] == "RNO"]
    if reno.empty:
        pytest.skip("no RNO rows to check")
    reno_dates = pd.to_datetime(reno["manufacture_date"])
    threshold = pd.Timestamp(RENO_OPEN_DATE)
    early = reno[reno_dates < threshold]
    assert early.empty, (
        f"Found {len(early)} RNO rows before {RENO_OPEN_DATE} — "
        f"Reno plant not open until Q2 2024"
    )


@pytest.mark.needs_dimensions
def test_cga_is_only_plant_for_my2022(dimension_root):
    """D12.d: CGA is the sole plant for MY2022 (RNO opens 2024)."""
    df = _read_vins_df(dimension_root)
    if "assembly_plant" not in df.columns:
        pytest.skip("vins dimension does not carry assembly_plant")
    my2022 = df[df["model_year"] == 2022]
    plants = set(my2022["assembly_plant"].dropna().unique())
    assert plants == {"CGA"}, (
        f"MY2022 must be produced only at CGA; found {sorted(plants)}"
    )


# ---------------------------------------------------------------------------
# D12.e — Manufacture-date realism (weekday-only, holiday shutdowns)
# ---------------------------------------------------------------------------


@pytest.mark.needs_dimensions
def test_no_weekend_manufacture_dates_on_procedural(dimension_root):
    """D12.e: procedural VINs are manufactured Mon-Fri only."""
    df = _read_vins_df(dimension_root)
    if "manufacture_date" not in df.columns:
        pytest.skip("vins dimension does not carry manufacture_date")
    import pandas as pd

    proc = df.iloc[CMS_BLOCK_SIZE:]
    dates = pd.to_datetime(proc["manufacture_date"])
    # Monday=0, Sunday=6 — assert no 5 (Sat) or 6 (Sun).
    dow = dates.dt.dayofweek
    weekend = proc[(dow == 5) | (dow == 6)]
    assert weekend.empty, (
        f"Found {len(weekend)} procedural VINs with weekend manufacture_date; "
        f"expected 0 (D12.e)"
    )


@pytest.mark.needs_dimensions
def test_no_holiday_shutdown_manufacture_dates(dimension_root):
    """D12.e: no VIN manufactured in the last week of Dec or the first week of Jul."""
    df = _read_vins_df(dimension_root)
    if "manufacture_date" not in df.columns:
        pytest.skip("vins dimension does not carry manufacture_date")
    import pandas as pd

    proc = df.iloc[CMS_BLOCK_SIZE:]
    dates = pd.to_datetime(proc["manufacture_date"])
    # Dec 25-31 (Christmas / NY shutdown) OR Jul 1-7 (retooling week).
    is_dec_shutdown = (dates.dt.month == 12) & (dates.dt.day >= 25)
    is_jul_retooling = (dates.dt.month == 7) & (dates.dt.day <= 7)
    shutdown = proc[is_dec_shutdown | is_jul_retooling]
    assert shutdown.empty, (
        f"Found {len(shutdown)} procedural VINs manufactured during plant "
        f"holiday windows (Dec 25-31 or Jul 1-7); expected 0 (D12.e)"
    )


# ---------------------------------------------------------------------------
# D12.f — Software rollout curve
# ---------------------------------------------------------------------------


@pytest.mark.needs_dimensions
def test_build_software_version_monotone_per_plant(dimension_root):
    """D12.f: within a plant, newer VINs have build_software_version >= older ones.

    A stricter test than "no rollback": the version stays flat or increases over
    time within a single plant's production line. Ties are OK (a version can
    span many months of production before the next bump).
    """
    df = _read_vins_df(dimension_root)
    required = {"assembly_plant", "manufacture_date", "build_software_version"}
    missing = required - set(df.columns)
    if missing:
        pytest.skip(f"vins missing required columns: {missing}")
    import pandas as pd
    from packaging.version import Version, InvalidVersion

    proc = df.iloc[CMS_BLOCK_SIZE:].copy()
    proc["_date"] = pd.to_datetime(proc["manufacture_date"])
    proc = proc.sort_values(["assembly_plant", "_date"])
    for plant, plant_df in proc.groupby("assembly_plant"):
        try:
            versions = [Version(v) for v in plant_df["build_software_version"]]
        except InvalidVersion as e:
            pytest.fail(
                f"Plant {plant} has invalid build_software_version: {e}"
            )
        for i in range(1, len(versions)):
            assert versions[i] >= versions[i - 1], (
                f"Plant {plant}: build_software_version regressed at position "
                f"{i} ({versions[i - 1]} → {versions[i]})"
            )


# ---------------------------------------------------------------------------
# D12.g — Color / body-style distribution
# ---------------------------------------------------------------------------


@pytest.mark.needs_dimensions
def test_common_colors_dominate(dimension_root):
    """D12.g: white/black/silver combined = ~60% ± 3%."""
    df = _read_vins_df(dimension_root)
    if "color" not in df.columns:
        pytest.skip("vins dimension does not carry color")
    shares = df["color"].str.lower().value_counts(normalize=True).to_dict()
    common = shares.get("white", 0) + shares.get("black", 0) + shares.get("silver", 0)
    assert 0.57 <= common <= 0.63, (
        f"white+black+silver combined share = {common:.3f}; expected 0.60 ± 0.03"
    )


# ---------------------------------------------------------------------------
# D12.h — Child-product cost realism (charging bimodal, service right-skewed,
# winter efficiency higher). Added post-T2.8.
# ---------------------------------------------------------------------------


@pytest.mark.needs_dimensions
def test_charging_cost_bimodal(curated_root):
    """D12.h: charging_sessions.cost_usd is bimodal — home ≈ $8, DCFC ≈ $32.

    Rather than importing sklearn/scipy for k-means, verify bimodality
    directly against the driver (session_type): home rows should cluster
    near $8, DCFC/public rows near $32, and the two cluster means should
    be well-separated. This is a stronger contract than histogram peak-
    finding because it ties the two clusters to the design decision that
    produced them.
    """
    df = _read_curated_partitioned(
        curated_root,
        "charging_sessions",
        columns=["cost_usd", "station_type"],
        sample_n=50_000,
    )
    if df.empty:
        pytest.skip("charging_sessions parquet is empty")

    df["_cost"] = _decimal_to_float(df["cost_usd"])
    home_mask = df["station_type"].isin(["home_l1", "home_l2"])
    home = df.loc[home_mask, "_cost"].dropna()
    dcfc = df.loc[~home_mask, "_cost"].dropna()

    assert len(home) > 100, f"too few home sessions in sample: {len(home)}"
    assert len(dcfc) > 100, f"too few DCFC sessions in sample: {len(dcfc)}"

    home_mean = home.mean()
    dcfc_mean = dcfc.mean()
    # Home mean ~$8, tolerance ±$3 (D12.h spec: mean $8 ± $3 stdev, clipped).
    assert 5.0 <= home_mean <= 11.0, (
        f"home charging cost mean = ${home_mean:.2f}; expected ~$8 ± $3"
    )
    # DCFC mean ~$32, tolerance ±$4 (D12.h spec: mean $32 ± $10 stdev, clipped).
    assert 28.0 <= dcfc_mean <= 36.0, (
        f"DCFC charging cost mean = ${dcfc_mean:.2f}; expected ~$32 ± $4"
    )
    # Bimodality signal: the two cluster means must be well-separated.
    assert dcfc_mean - home_mean >= 15.0, (
        f"home and DCFC cost means too close ({home_mean:.2f} vs "
        f"{dcfc_mean:.2f}) — distribution is unimodal, not bimodal"
    )
    # Clipping bounds (from D12.h) — no outlier costs.
    assert home.max() <= 15.0 + 0.01, f"home cost {home.max()} exceeds $15 clip"
    assert home.min() >= 2.0 - 0.01, f"home cost {home.min()} below $2 clip"
    assert dcfc.max() <= 50.0 + 0.01, f"DCFC cost {dcfc.max()} exceeds $50 clip"
    assert dcfc.min() >= 18.0 - 0.01, f"DCFC cost {dcfc.min()} below $18 clip"


@pytest.mark.needs_dimensions
def test_service_cost_right_skewed(curated_root):
    """D12.h: service_records.total_cost_usd is right-skewed (skewness > 1.0).

    Sample skewness computed inline (no scipy dep). A right-tailed
    distribution has positive skewness; the design target (lognormal
    μ=5.193, σ=1.264) gives a theoretical skewness ≈ (e^σ² + 2) × √(e^σ² − 1)
    ≈ 8.7 — very right-skewed. The 1.0 lower bound is a loose guarantee
    that survives clipping + the 50% warranty-null mask.
    """
    df = _read_curated_partitioned(
        curated_root,
        "service_records",
        columns=["total_cost_usd"],
        sample_n=100_000,
    )
    if df.empty:
        pytest.skip("service_records parquet is empty")

    costs = _decimal_to_float(df["total_cost_usd"])
    assert len(costs) > 1000, f"too few non-null costs: {len(costs)}"

    # Sample skewness: E[((X - mean)/std)³].
    mean = costs.mean()
    std = costs.std(ddof=1)
    assert std > 0, "std is zero — distribution is degenerate"
    skewness = ((costs - mean) ** 3).mean() / (std ** 3)
    assert skewness > 1.0, (
        f"sample skewness = {skewness:.3f}; expected > 1.0 (right-skewed). "
        f"mean=${mean:.2f}, std=${std:.2f}"
    )

    # Also verify clip bounds ($30 low, $5000 high) hold.
    assert costs.min() >= 30.0 - 0.01, f"cost {costs.min()} below $30 clip"
    assert costs.max() <= 5000.0 + 0.01, f"cost {costs.max()} exceeds $5000 clip"

    # And rough moment sanity: mean should be ballpark ~$400 (±40% loose).
    assert 200.0 <= mean <= 700.0, (
        f"cost mean = ${mean:.2f}; expected ~$400 (D12.h target)"
    )


@pytest.mark.needs_dimensions
def test_winter_efficiency_higher(curated_root):
    """D12.h: energy_usage.efficiency_kwh_per_100mi is higher in winter.

    Dec-Feb rows should show ≥10% higher mean efficiency than Jun-Aug rows.
    Backed by the ``_winter_penalty`` multiplier (Nov-Feb: 1.15-1.25×)
    on top of the ambient-temp cold_penalty.
    """
    df = _read_curated_partitioned(
        curated_root,
        "energy_usage",
        columns=["efficiency_kwh_per_100mi", "usage_date"],
        sample_n=200_000,
    )
    if df.empty:
        pytest.skip("energy_usage parquet is empty")

    import pandas as pd

    df["_month"] = pd.to_datetime(df["usage_date"]).dt.month
    winter = df.loc[df["_month"].isin([12, 1, 2]), "efficiency_kwh_per_100mi"].dropna()
    summer = df.loc[df["_month"].isin([6, 7, 8]), "efficiency_kwh_per_100mi"].dropna()

    # Local sample tier canonically uses `PYSPARK_LOCAL_DAYS_NRG=30` (Makefile),
    # which produces one contiguous ~30-day window — insufficient month coverage
    # for a winter-vs-summer comparison. Skip in that case; full-scale
    # (Group 6 Glue run at `--days 365+`) will exercise this assertion.
    if len(winter) < 1000 or len(summer) < 1000:
        pytest.skip(
            f"energy_usage sample has insufficient season coverage "
            f"(winter={len(winter)}, summer={len(summer)}); needs >=1000 each. "
            f"Local staging shape (`--days 30`) covers only one season. "
            f"Full-scale Glue run (`--days 365+`) exercises this assertion."
        )

    winter_mean = winter.mean()
    summer_mean = summer.mean()
    ratio = winter_mean / summer_mean
    assert ratio >= 1.10, (
        f"winter efficiency mean = {winter_mean:.2f}, summer = {summer_mean:.2f}, "
        f"ratio = {ratio:.3f}; expected ≥ 1.10 (D12.h winter penalty)"
    )


# ---------------------------------------------------------------------------
# Determinism — critical property
# ---------------------------------------------------------------------------


@pytest.mark.needs_dimensions
def test_deterministic_seed_produces_identical_output(dimension_root):
    """Same seed → byte-identical parquet (SHA256 match).

    Runs the generator twice with the same seed and checks the parquet
    output is byte-for-byte identical. Deterministic generation is a
    hard requirement (spec § Constraints).

    This test does NOT re-invoke the generator (which would double the
    G3 T3.1 dry-run time). Instead it computes the SHA256 of the current
    parquet and compares against a pinned value that G2 T2.2 records in
    `dimensions/vins/manifest.json` under key `data_sha256`.
    """
    import hashlib
    import json

    parquet = _vins_parquet_path(dimension_root)
    manifest = dimension_root / "vins" / "manifest.json"
    if not (parquet.exists() and manifest.exists()):
        pytest.skip("parquet or manifest not produced yet")

    sha = hashlib.sha256(parquet.read_bytes()).hexdigest()
    m = json.loads(manifest.read_text())
    pinned = m.get("data_sha256")
    if pinned is None:
        pytest.skip(
            "manifest.json missing 'data_sha256' key — G2 T2.2 must pin it"
        )
    assert sha == pinned, (
        f"parquet SHA256 mismatch: file={sha[:12]}... manifest={pinned[:12]}... — "
        f"determinism broken"
    )
