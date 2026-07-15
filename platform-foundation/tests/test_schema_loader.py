"""Tests for the schema loader (`platform-foundation/source/lib/schema_loader.py`).

These tests run without any AWS access — pure-Python validation of
YAML parsing, dataclass construction, and DDL/dtype generation.
They are GREEN as soon as Group 1 task 6 lands (the loader and its
schema YAMLs).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import schema_loader as sl  # noqa: E402  (added to sys.path by conftest)


@pytest.fixture(scope="module")
def all_product_schemas(product_names) -> dict[str, sl.Schema]:
    return {name: sl.load_schema(name, kind="product") for name in product_names}


@pytest.fixture(scope="module")
def all_dimension_schemas(dimension_names) -> dict[str, sl.Schema]:
    return {name: sl.load_schema(name, kind="dimension") for name in dimension_names}


# --- Discovery & validate-all ------------------------------------------------


def test_discover_finds_nine_products():
    paths = sl.discover_schemas(kind="product")
    assert len(paths) == 9, f"Expected 9 product schemas, found {len(paths)}"


def test_discover_finds_seven_dimensions():
    paths = sl.discover_schemas(kind="dimension")
    assert len(paths) == 7, f"Expected 7 dimension schemas, found {len(paths)}"


def test_validate_all_clean():
    ok, errors = sl.validate_all()
    assert errors == [], f"Validation errors: {errors}"
    assert ok == 16


# --- Per-product round-trip --------------------------------------------------


@pytest.mark.parametrize(
    "product_name",
    [
        "vehicle_telemetry_aggregated",
        "vehicle_identity",
        "charging_sessions",
        "energy_usage",
        "ota_campaigns",
        "customer_360",
        "customer_interactions",
        "service_records",
        "vehicle_knowledge_base",
    ],
)
def test_product_loads_and_has_columns(product_name):
    s = sl.load_schema(product_name, kind="product")
    assert s.kind == "product"
    assert s.name == product_name
    assert s.tables, f"{product_name} has no tables"
    for tbl in s.tables:
        assert tbl.columns, f"{product_name}.{tbl.name} has no columns"


# --- Multi-table OTA ---------------------------------------------------------


def test_ota_campaigns_has_two_tables():
    s = sl.load_schema("ota_campaigns", kind="product")
    assert s.is_multi_table() is True
    names = {t.name for t in s.tables}
    assert names == {"ota_campaigns", "ota_campaign_events"}


def test_ota_campaign_events_fk_references_ota_campaigns():
    s = sl.load_schema("ota_campaigns", kind="product")
    events = next(t for t in s.tables if t.name == "ota_campaign_events")
    fks = {fk.references_table for fk in events.foreign_keys}
    assert "ota_campaigns" in fks
    assert "vins" in fks


# --- Iceberg DDL generation --------------------------------------------------


def test_iceberg_ddl_is_well_formed_for_charging_sessions():
    s = sl.load_schema("charging_sessions", kind="product")
    tbl = s.first_table()
    ddl = tbl.iceberg_ddl(
        database=s.iceberg_database(),
        location="s3://adp-foundation-lake-000000000000-us-east-1/curated/charging_sessions/",
    )
    assert "CREATE TABLE adp_charging_sessions.charging_sessions" in ddl
    # Identifiers are backtick-quoted and NOT NULL is intentionally NOT emitted
    # (schema_loader.iceberg_ddl_fragment: Athena/Glue-catalog Iceberg treats
    # every column as nullable; the `nullable: false` YAML stays a
    # YAML/generator-level assertion). See schema_loader.py:153-171.
    assert "`session_id` string" in ddl
    assert "`vin` string" in ddl
    # Bucketing on vin — count 16 — should appear in the partition clause.
    assert "bucket(16, vin)" in ddl
    assert "PARTITIONED BY (session_date" in ddl
    assert "'table_type' = 'ICEBERG'" in ddl


def test_iceberg_ddl_decimal_precision_scale():
    s = sl.load_schema("charging_sessions", kind="product")
    tbl = s.first_table()
    ddl = tbl.iceberg_ddl(
        database=s.iceberg_database(),
        location="s3://adp-foundation-lake-000000000000-us-east-1/curated/charging_sessions/",
    )
    # Backtick-quoted identifiers (see note in the well-formed test above).
    assert "`cost_usd` decimal(10,4)" in ddl
    assert "`cost_per_kwh_usd` decimal(10,6)" in ddl


def test_iceberg_ddl_rejects_documents_storage_format():
    s = sl.load_schema("vehicle_knowledge_base", kind="product")
    tbl = s.first_table()
    with pytest.raises(ValueError, match="non-iceberg"):
        tbl.iceberg_ddl(database="adp_vehicle_knowledge_base", location="s3://x/")


def test_iceberg_ddl_requires_trailing_slash_in_location():
    s = sl.load_schema("charging_sessions", kind="product")
    tbl = s.first_table()
    with pytest.raises(ValueError, match="must end with '/'"):
        tbl.iceberg_ddl(database="adp_charging_sessions", location="s3://x")


# --- pyarrow + pandas dtype maps ---------------------------------------------


def test_pandas_dtype_map_covers_all_columns():
    s = sl.load_schema("charging_sessions", kind="product")
    tbl = s.first_table()
    dtypes = tbl.pandas_dtype_map()
    assert set(dtypes.keys()) == {c.name for c in tbl.columns}
    # session_date should be object (date32 round-trip via pyarrow).
    assert dtypes["session_date"] == "object"
    # start_time should be UTC timestamp microseconds.
    assert dtypes["start_time"] == "datetime64[us, UTC]"


def test_pyarrow_schema_code_is_executable():
    s = sl.load_schema("charging_sessions", kind="product")
    tbl = s.first_table()
    code = tbl.pyarrow_schema_code()
    # Just verify the snippet declares the expected fields; we do not
    # exec() at this stage because pyarrow is not installed in test_skeleton phase.
    assert "import pyarrow as pa" in code
    assert "pa.field('session_id', pa.string()" in code
    assert "pa.timestamp('us', tz='UTC')" in code
    assert "pa.decimal128(10, 4)" in code  # cost_usd


# --- Identifier patterns from data-contracts.md -----------------------------


def test_vin_pattern_is_iso3779():
    s = sl.load_schema("vins", kind="dimension")
    vin_col = s.first_table().column_by_name("vin")
    assert vin_col is not None
    assert vin_col.pattern == "^[A-HJ-NPR-Z0-9]{17}$"


def test_customer_id_pattern_is_documented_format():
    s = sl.load_schema("customers", kind="dimension")
    col = s.first_table().column_by_name("customer_id")
    assert col is not None
    assert col.pattern == "^CUST-[0-9A-F]{8}$"
    # Verify the pattern matches a representative ID and rejects malformed ones.
    pat = re.compile(col.pattern)
    assert pat.match("CUST-3F2504E0")
    assert not pat.match("CUST-INVALID")


def test_station_id_pattern_supports_all_networks():
    s = sl.load_schema("charging_stations", kind="dimension")
    col = s.first_table().column_by_name("station_id")
    assert col is not None
    pat = re.compile(col.pattern)
    for network in ("TS", "EA", "EVGO", "CP", "HOME", "DEST"):
        assert pat.match(f"STN-{network}-00012345"), f"Network {network} should match"


# --- Type allowlist ---------------------------------------------------------


def test_no_schema_uses_disallowed_types(all_product_schemas, all_dimension_schemas):
    all_schemas = {**all_product_schemas, **all_dimension_schemas}
    for name, s in all_schemas.items():
        for tbl in s.tables:
            for c in tbl.columns:
                assert c.type in sl.ALLOWED_COLUMN_TYPES, (
                    f"{name}.{tbl.name}.{c.name} uses disallowed type {c.type!r}"
                )


# --- Lake Formation tag generation ------------------------------------------


def test_lake_formation_tags_pii_columns():
    s = sl.load_schema("customer_360", kind="product")
    tbl = s.first_table()
    tags = tbl.lake_formation_column_tags()
    pii_count = sum(1 for t in tags for tt in t["tags"] if "PII" in tt["tag_values"])
    # customer_360 is a PII-bearing product; it must have multiple PII columns.
    assert pii_count >= 5


# --- Validation error paths --------------------------------------------------


def test_invalid_type_raises(tmp_path: Path):
    bad = tmp_path / "schema.yaml"
    bad.write_text(
        "name: bad_product\n"
        "kind: product\n"
        "domain: automotive\n"
        "display_name: 'Bad Product'\n"
        "tables:\n"
        "  - name: bad\n"
        "    storage_format: iceberg\n"
        "    columns:\n"
        "      - {name: x, type: struct}\n"
    )
    with pytest.raises(sl.SchemaValidationError, match="type must be one of"):
        sl.load_schema_from_path(bad)


def test_invalid_fk_target_raises(tmp_path: Path):
    bad = tmp_path / "schema.yaml"
    bad.write_text(
        "name: bad_product\n"
        "kind: product\n"
        "domain: automotive\n"
        "display_name: 'Bad Product'\n"
        "tables:\n"
        "  - name: bad\n"
        "    storage_format: iceberg\n"
        "    columns:\n"
        "      - {name: x, type: string}\n"
        "    foreign_keys:\n"
        "      - {column: x, references_table: nonexistent, references_column: y}\n"
    )
    with pytest.raises(sl.SchemaValidationError, match="references_table"):
        sl.load_schema_from_path(bad)
