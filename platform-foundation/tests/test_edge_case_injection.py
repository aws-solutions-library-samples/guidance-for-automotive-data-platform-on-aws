"""Edge-case injection rate tests (per `docs/tech.md` "Edge-Case Taxonomy").

The six injection codes — ``missing_required``, ``late_arrival``,
``schema_drift``, ``bad_pii``, ``orphan_fk`` (counter-example, target
0%), ``outlier_value`` — each have target ranges per product. These
tests load curated parquet, count rows matching the detector for each
code, and assert rates are within the documented bounds.

Pre-Group-3 these tests skip with clear reasons.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import schema_loader as sl  # noqa: E402


# Aggregate edge-case rate per product (PRD: 1-3% of records carry ≥1 code).
EDGE_AGGREGATE_LO = 0.01
EDGE_AGGREGATE_HI = 0.03

# Per-code target ranges (from docs/tech.md).
PER_CODE_RATES = {
    "missing_required": (0.005, 0.010),
    "late_arrival": (0.003, 0.007),
    "schema_drift": (0.002, 0.005),
    "bad_pii": (0.001, 0.003),
    "orphan_fk": (0.000, 0.000),  # counter-example: production = 0
    "outlier_value": (0.002, 0.006),
}


# --- Schema-only checks ------------------------------------------------------


def test_six_codes_documented_only():
    """No 7th code should be silently introduced."""
    assert set(PER_CODE_RATES.keys()) == {
        "missing_required",
        "late_arrival",
        "schema_drift",
        "bad_pii",
        "orphan_fk",
        "outlier_value",
    }


def test_orphan_fk_target_rate_is_zero():
    lo, hi = PER_CODE_RATES["orphan_fk"]
    assert lo == hi == 0.0, "orphan_fk target rate MUST be 0% (counter-example)"


def test_some_columns_are_edge_case_eligible(product_names):
    """Every fact-table product must declare at least 1 edge_case_eligible column,
    so generators can place injections somewhere safe."""
    for product in product_names:
        if product == "vehicle_knowledge_base":
            continue  # documents-format; injections handled differently
        s = sl.load_schema(product, kind="product")
        eligible = [
            c.name
            for tbl in s.tables
            for c in tbl.columns
            if c.edge_case_eligible
        ]
        assert eligible, (
            f"{product}: no columns flagged edge_case_eligible — generator has no place "
            f"to inject missing_required / outlier_value cleanly"
        )


# --- Functional check: outlier_value Int64 dtype coercion --------------------
def test_outlier_value_preserves_int64_dtype():
    """Regression: ``EdgeCaseInjector.outlier_value`` must coerce float
    multiplier output to int when the target column dtype is Int32/Int64-backed.

    Bug surfaced 2026-05-29 during Group 3 smoke runs: assigning a float
    (e.g. ``86400.0 * 7.3``) to a pandas ``Int64`` column via ``df.iat[]``
    raised ``TypeError`` because the integer extension dtype rejects floats.

    Fix lives in ``source/lib/product_generator.py`` (``EdgeCaseInjector.apply``,
    ``outlier_value`` branch).
    """
    import pandas as pd

    from product_generator import EdgeCaseInjector  # noqa: E402

    # Build a synthetic single-column Table: 'duration_seconds' bigint,
    # edge_case_eligible, range=[0, 86400] — same shape as
    # customer_interactions.duration_seconds (a real column hit by the bug).
    col = sl.Column(
        name="duration_seconds",
        type="bigint",
        nullable=True,
        edge_case_eligible=True,
        range=(0.0, 86400.0),
    )
    table = sl.Table(
        name="t",
        storage_format="iceberg",
        columns=(col,),
    )

    # Force a high outlier_value rate so the branch fires deterministically.
    n = 500
    rates = {
        "missing_required": 0.0,
        "late_arrival": 0.0,
        "schema_drift": 0.0,
        "bad_pii": 0.0,
        "orphan_fk": 0.0,
        "outlier_value": 0.20,  # 100 cells out of 500
    }

    df = pd.DataFrame(
        {"duration_seconds": pd.Series([100] * n, dtype="Int64")}
    )

    injector = EdgeCaseInjector(seed=42, table=table, rates=rates)
    out = injector.apply(df)

    # 1. dtype is preserved — no silent upcast to float64 / object.
    assert str(out["duration_seconds"].dtype) == "Int64", (
        f"expected Int64 after outlier injection, got {out['duration_seconds'].dtype}"
    )

    # 2. expected number of cells were perturbed.
    assert injector.summary["outlier_value"] == int(n * rates["outlier_value"])

    # 3. perturbed cells are above 5x of hi (within the 5-10x band).
    hi = 86400
    perturbed = out["duration_seconds"][out["duration_seconds"] > hi * 5]
    assert len(perturbed) > 0, "no outlier values landed above 5x hi"


# --- C3 regression: bad_pii MUST NOT corrupt FK columns ---------------------
#
# Cycle 3 surfaced the bad_pii × orphan_fk semantic overlap: the prior
# implementation corrupted ``vin`` / ``customer_id`` (FK columns) and folded
# bad_pii into orphan_fk, breaking spec Constraint #5 ("zero orphan FKs
# across products") and Constraint #6 (``orphan_fk`` target = 0%, counter-
# example). Fix Group C re-targets ``bad_pii`` to columns flagged
# ``pii_drift_target: true`` in the schema YAML — by convention non-FK PII
# text columns (e.g., ``customer_360.email``,
# ``customer_interactions.notes``, ``service_records.complaint_text``).
# These tests guard the new contract.

# Regex from docs/data-contracts.md row 1 (VIN / ISO 3779).
_VIN_REGEX = r"^[A-HJ-NPR-Z0-9]{17}$"
# Regex from customer_360/schema.yaml customer_id pattern.
_CUSTOMER_ID_REGEX = r"^CUST-[0-9A-F]{8}$"


def test_bad_pii_does_not_corrupt_fk_columns_when_drift_target_present():
    """When the table declares both an FK column and a ``pii_drift_target``
    non-FK column, the bad_pii branch MUST corrupt only the drift target —
    the FK column must remain regex-conforming for every row.
    """
    import re

    import pandas as pd

    from product_generator import EdgeCaseInjector  # noqa: E402

    # Synthetic table mirroring customer_360's relevant shape:
    # - ``customer_id``: FK PII column (must NOT be corrupted)
    # - ``vin``: FK column (must NOT be corrupted)
    # - ``email``: non-FK PII column tagged pii_drift_target (corruption target)
    customer_id_col = sl.Column(
        name="customer_id",
        type="string",
        nullable=False,
        pii=True,
        pii_drift_target=False,  # FK — must be excluded
        pattern=_CUSTOMER_ID_REGEX,
    )
    vin_col = sl.Column(
        name="vin",
        type="string",
        nullable=True,
        pii=False,
        pii_drift_target=False,  # FK — must be excluded
        pattern=_VIN_REGEX,
    )
    email_col = sl.Column(
        name="email",
        type="string",
        nullable=True,
        pii=True,
        pii_drift_target=True,  # the only legitimate corruption target
    )
    table = sl.Table(
        name="t",
        storage_format="iceberg",
        columns=(customer_id_col, vin_col, email_col),
    )

    n = 500
    rates = {
        "missing_required": 0.0,
        "late_arrival": 0.0,
        "schema_drift": 0.0,
        "bad_pii": 0.20,  # 100 cells out of 500 — fires deterministically
        "orphan_fk": 0.0,
        "outlier_value": 0.0,
    }

    df = pd.DataFrame(
        {
            "customer_id": pd.Series(
                [f"CUST-{i:08X}" for i in range(n)], dtype="string"
            ),
            "vin": pd.Series(
                # All-uppercase, 17 chars, regex-conforming.
                [f"1FA{i:014X}"[:17] for i in range(n)], dtype="string"
            ),
            "email": pd.Series(
                [f"user{i}@example.com" for i in range(n)], dtype="string"
            ),
        }
    )

    injector = EdgeCaseInjector(seed=42, table=table, rates=rates)
    out = injector.apply(df)

    # 1. bad_pii fired the expected number of times.
    assert injector.summary["bad_pii"] == int(n * rates["bad_pii"])

    # 2. Every customer_id still matches the data-contracts regex —
    #    proving the FK column was NOT touched.
    cust_pat = re.compile(_CUSTOMER_ID_REGEX)
    bad_cust = [v for v in out["customer_id"].dropna() if not cust_pat.match(v)]
    assert not bad_cust, (
        f"bad_pii corrupted FK column customer_id — {len(bad_cust)} "
        f"non-conforming values: {bad_cust[:3]!r} (this folds bad_pii into "
        f"orphan_fk and breaks spec Constraints #5 + #6)"
    )

    # 3. Every vin still matches the data-contracts regex — same proof for vin.
    vin_pat = re.compile(_VIN_REGEX)
    bad_vin = [v for v in out["vin"].dropna() if not vin_pat.match(v)]
    assert not bad_vin, (
        f"bad_pii corrupted FK column vin — {len(bad_vin)} non-conforming "
        f"values (this folds bad_pii into orphan_fk and breaks Constraints "
        f"#5 + #6)"
    )

    # 4. The email column DID get corrupted (lowercase 'i' inserted at char 2)
    #    — at least one cell now contains the corruption marker.
    corrupted_emails = [v for v in out["email"].dropna() if v[1:2] == "i"]
    assert corrupted_emails, (
        "bad_pii did not corrupt the pii_drift_target email column — "
        "the branch is no longer firing on the legitimate target"
    )


def test_bad_pii_is_no_op_when_no_drift_target_column():
    """When the table declares zero ``pii_drift_target`` columns (mirroring
    ``vehicle_telemetry_aggregated`` / ``energy_usage`` shape — VIN is the
    only PII candidate and it's the FK), bad_pii MUST report 0
    perturbations and the FK column MUST be byte-identical to the input.
    """
    import pandas as pd

    from product_generator import EdgeCaseInjector  # noqa: E402

    # Synthetic table mirroring telemetry/energy_usage shape:
    # only an FK column, no pii_drift_target column.
    vin_col = sl.Column(
        name="vin",
        type="string",
        nullable=False,
        pii=False,
        pii_drift_target=False,
        pattern=_VIN_REGEX,
    )
    table = sl.Table(
        name="t",
        storage_format="iceberg",
        columns=(vin_col,),
    )

    n = 500
    rates = {
        "missing_required": 0.0,
        "late_arrival": 0.0,
        "schema_drift": 0.0,
        "bad_pii": 0.20,  # 100 cells if a target existed — but there's none.
        "orphan_fk": 0.0,
        "outlier_value": 0.0,
    }

    original_vins = [f"1FA{i:014X}"[:17] for i in range(n)]
    df = pd.DataFrame({"vin": pd.Series(original_vins, dtype="string")})

    injector = EdgeCaseInjector(seed=42, table=table, rates=rates)
    out = injector.apply(df)

    # 1. bad_pii reports ZERO perturbations — structural-zero contract.
    assert injector.summary["bad_pii"] == 0, (
        f"bad_pii fired {injector.summary['bad_pii']} times on a table with "
        f"no pii_drift_target column — must be 0 (structural-zero contract)"
    )

    # 2. VIN column is byte-identical to the input — proves no FK corruption.
    assert list(out["vin"]) == original_vins, (
        "bad_pii corrupted vin even though no pii_drift_target column was "
        "declared — FK column must be untouched"
    )


# --- Per-product rate assertions (skipped pre-Group-3) -----------------------


@pytest.mark.needs_curated
@pytest.mark.parametrize(
    "product_name",
    [
        "vehicle_telemetry_aggregated",
        "charging_sessions",
        "energy_usage",
        "ota_campaigns",
        "customer_interactions",
        "service_records",
        "customer_360",
        "vehicle_identity",
    ],
)
def test_aggregate_edge_rate_per_product(curated_root, product_name):
    p = curated_root / product_name
    if not p.exists() or not any(p.iterdir()):
        pytest.skip(f"{product_name} not generated yet")
    pytest.skip(
        "Aggregate-rate detector implemented as part of Group 3 generator + "
        "Group 6 distribution profiler. Placeholder asserts call shape."
    )


@pytest.mark.needs_curated
@pytest.mark.parametrize("code,bounds", list(PER_CODE_RATES.items()))
def test_per_code_rate_in_bounds(curated_root, code, bounds):
    if not (curated_root.exists() and any(curated_root.iterdir())):
        pytest.skip("curated/ not populated")
    pytest.skip(f"Per-code detector for {code} implemented in Group 3.")
