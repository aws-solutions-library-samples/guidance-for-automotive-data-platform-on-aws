"""Schema loader for ADP foundation data products and dimensions.

Pure-Python module — no AWS calls. Loads schema YAML files for the
nine data products and seven dimensions, validates them, and
generates downstream artifacts:

- pandas dtype map (for DataFrame construction)
- pyarrow schema (for parquet write with correct types)
- Iceberg ``CREATE TABLE`` DDL (for Athena Engine V3)
- DataZone catalog asset metadata (for ``create_data_source``)
- Lake Formation column-tag metadata (for tag-based access control)

Multi-table products (``ota_campaigns``, which materializes as both
``ota_campaigns`` and ``ota_campaign_events``) are supported via the
``tables:`` list at the YAML top level.

Reference: :file:`docs/data-contracts.md` is the contract this loader
enforces. :file:`docs/tech.md` documents the API surfaces this loader
generates against.

Usage::

    from platform_foundation.source.lib.schema_loader import load_schema

    schema = load_schema('charging_sessions')
    print(schema.iceberg_ddl(table='charging_sessions',
                             location='s3://adp-foundation-lake-.../curated/charging_sessions/'))

CLI::

    python3 -m platform_foundation.source.lib.schema_loader --validate-all
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Allowed types (per spec.md "data product schemas" Constraint).
# Restricted set — no struct or other nested types in v1.
# ---------------------------------------------------------------------------

ALLOWED_COLUMN_TYPES: set[str] = {
    "string",
    "int",
    "bigint",
    "double",
    "decimal",
    "boolean",
    "timestamp",
    "date",
    "array<string>",
    "array<int>",
}

# Map ADP types -> pandas dtypes. Decimal is stored as object (Decimal).
_PANDAS_DTYPE: dict[str, str] = {
    "string": "string",
    "int": "Int32",
    "bigint": "Int64",
    "double": "Float64",
    "decimal": "object",
    "boolean": "boolean",
    "timestamp": "datetime64[us, UTC]",
    "date": "object",  # pandas date32 round-trip via pyarrow only
    "array<string>": "object",
    "array<int>": "object",
}

# Map ADP types -> pyarrow type expressions (string form, eval'd downstream).
_PYARROW_TYPE: dict[str, str] = {
    "string": "string()",
    "int": "int32()",
    "bigint": "int64()",
    "double": "float64()",
    # decimal is parameterized; handled in field generation below
    "decimal": "decimal128",
    "boolean": "bool_()",
    "timestamp": "timestamp('us', tz='UTC')",
    "date": "date32()",
    "array<string>": "list_(string())",
    "array<int>": "list_(int32())",
}

# Map ADP types -> Iceberg/Athena DDL types.
_ICEBERG_TYPE: dict[str, str] = {
    "string": "string",
    "int": "int",
    "bigint": "bigint",
    "double": "double",
    # decimal parameterized; handled in DDL generation
    "decimal": "decimal",
    "boolean": "boolean",
    "timestamp": "timestamp",
    "date": "date",
    "array<string>": "array<string>",
    "array<int>": "array<int>",
}

# Allowed values for storage_format — one ``iceberg`` is the v1 default.
# ``documents`` is the special-case for vehicle_knowledge_base (text/PDF, no Iceberg).
ALLOWED_STORAGE_FORMATS: set[str] = {"iceberg", "documents", "parquet"}

# Allowed values for provenance — declared per table in schema.yaml for ``kind == 'product'``.
# Dimensions are excluded from this requirement (follow-on per spec § "Items I could not
# turn into a fully-verifiable task" item 1).
#   single-vintage      — table produces exactly one output partition per run
#   cumulative-snapshot — table accumulates partitions as a time-series (e.g. daily snapshots)
#   managed             — contents governed by an external system (e.g. Bedrock ingestion)
ALLOWED_PROVENANCE: set[str] = {"single-vintage", "cumulative-snapshot", "managed"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    """A single column in a product or dimension schema."""

    name: str
    type: str
    nullable: bool = True
    pii: bool = False
    edge_case_eligible: bool = False
    # ``pii_drift_target: True`` nominates this column as the per-table
    # destination for the ``bad_pii`` edge-case injection — see
    # ``EdgeCaseInjector.bad_pii`` in ``product_generator.py``. Tag only
    # NON-FK PII columns; FK columns must NEVER carry this flag because
    # corrupting them folds ``bad_pii`` into ``orphan_fk`` and breaks
    # spec Constraint #5 / #6 (review.md cycle 3).
    pii_drift_target: bool = False
    description: str = ""
    range: tuple[float, float] | None = None
    enum_values: tuple[str, ...] | None = None
    decimal_precision: int | None = None
    decimal_scale: int | None = None
    pattern: str | None = None  # regex for string columns (VSS v6.0 keyword)

    def pandas_dtype(self) -> str:
        return _PANDAS_DTYPE[self.type]

    def pyarrow_field_expr(self) -> str:
        """Return a string that evaluates to a pyarrow field at runtime."""
        if self.type == "decimal":
            assert self.decimal_precision is not None
            assert self.decimal_scale is not None
            ty = f"pa.decimal128({self.decimal_precision}, {self.decimal_scale})"
        else:
            ty = f"pa.{_PYARROW_TYPE[self.type]}"
        return f"pa.field('{self.name}', {ty}, nullable={self.nullable})"

    def iceberg_ddl_fragment(self) -> str:
        if self.type == "decimal":
            assert self.decimal_precision is not None
            assert self.decimal_scale is not None
            ty = f"decimal({self.decimal_precision},{self.decimal_scale})"
        else:
            ty = _ICEBERG_TYPE[self.type]
        # 2026-06-02 fix (within-quota-seed spec, decisions.md "STOP at
        # Group 2"): two changes from the closed-spec version:
        #   1. Quote column names with BACKTICKS (Hive identifier quoting).
        #      Athena Iceberg DDL uses Hive parser, NOT Trino — double
        #      quotes fail with "no viable alternative at input". Backticks
        #      protect against reserved words like `trim` (vehicle_identity).
        #   2. Drop `NOT NULL` constraint emission — Athena Iceberg DDL
        #      does not support inline column constraints. The schema
        #      YAML's `nullable: false` remains an assertion at the YAML/
        #      pyarrow-write layer (parquet schema enforces it); the Glue-
        #      catalog Iceberg table treats every column as nullable.
        return f"  `{self.name}` {ty}"


@dataclass(frozen=True)
class ForeignKey:
    """A foreign-key reference from this table to a dimension or other product table."""

    column: str
    references_table: str  # one of: vins, customers, dealers, suppliers, parts, charging_stations, ota_campaigns
    references_column: str

    # Foreign keys are validated in `_validate` against the allowed set.


@dataclass(frozen=True)
class Table:
    """A single Iceberg table within a product. Most products have one; ``ota_campaigns`` has two."""

    name: str
    storage_format: str  # iceberg | documents | parquet
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...] = ()
    partition_keys: tuple[str, ...] = ()
    bucketing: dict[str, int] = field(default_factory=dict)  # {column: bucket_count}
    foreign_keys: tuple[ForeignKey, ...] = ()
    # Required for ``kind == 'product'`` tables; validated in _validate_table().
    # Allowed values: single-vintage | cumulative-snapshot | managed
    provenance: str = ""

    def column_by_name(self, name: str) -> Column | None:
        for c in self.columns:
            if c.name == name:
                return c
        return None

    def pandas_dtype_map(self) -> dict[str, str]:
        return {c.name: c.pandas_dtype() for c in self.columns}

    def pyarrow_schema_code(self) -> str:
        """Return runnable Python source that constructs a pyarrow.Schema."""
        lines = ["import pyarrow as pa", "", "schema = pa.schema(["]
        for c in self.columns:
            lines.append(f"    {c.pyarrow_field_expr()},")
        lines.append("])")
        return "\n".join(lines)

    def iceberg_ddl(self, *, database: str, location: str) -> str:
        """Generate Athena Engine V3 ``CREATE TABLE`` DDL for this Iceberg table.

        ``database`` is the Glue database name (e.g., ``adp_charging_sessions``).
        ``location`` is the S3 prefix; must end with ``/``.
        """
        if self.storage_format != "iceberg":
            raise ValueError(
                f"iceberg_ddl() called on non-iceberg table '{self.name}' "
                f"(storage_format={self.storage_format})"
            )
        if not location.endswith("/"):
            raise ValueError(f"location must end with '/', got: {location}")

        cols = ",\n".join(c.iceberg_ddl_fragment() for c in self.columns)
        partition_clause = self._partition_clause()
        return (
            f"CREATE TABLE {database}.{self.name} (\n"
            f"{cols}\n"
            f")\n"
            f"{partition_clause}"
            f"LOCATION '{location}'\n"
            f"TBLPROPERTIES (\n"
            f"  'table_type' = 'ICEBERG',\n"
            f"  'format' = 'parquet',\n"
            f"  'write_compression' = 'zstd',\n"
            f"  'optimize_rewrite_data_file_threshold' = '5',\n"
            f"  'vacuum_min_snapshots_to_keep' = '10',\n"
            f"  'vacuum_max_snapshot_age_seconds' = '604800'\n"
            f");\n"
        )

    def _partition_clause(self) -> str:
        if not self.partition_keys:
            return ""
        parts: list[str] = list(self.partition_keys)
        for col, count in self.bucketing.items():
            parts.append(f"bucket({count}, {col})")
        return f"PARTITIONED BY ({', '.join(parts)})\n"

    def datazone_asset_metadata(self) -> dict[str, Any]:
        """Return the DataZone ``create_data_source`` asset description."""
        return {
            "name": self.name,
            "type": "GLUE",
            "columns": [
                {
                    "name": c.name,
                    "type": c.type,
                    "description": c.description,
                    "pii": c.pii,
                }
                for c in self.columns
            ],
        }

    def lake_formation_column_tags(self) -> list[dict[str, Any]]:
        """Return per-column tag metadata for Lake Formation."""
        out: list[dict[str, Any]] = []
        for c in self.columns:
            out.append(
                {
                    "column_name": c.name,
                    "tags": [
                        {
                            "tag_key": "adp-classification",
                            "tag_values": ["PII"] if c.pii else ["non-PII"],
                        }
                    ],
                }
            )
        return out


@dataclass(frozen=True)
class Schema:
    """Top-level schema for a product or dimension. May contain >1 table."""

    name: str  # product or dimension technical name (snake_case)
    kind: str  # "product" | "dimension"
    domain: str  # "automotive" | "ev_operations" | "customer" | "service" | "knowledge" | "dimension"
    display_name: str
    tables: tuple[Table, ...]
    deterministic_seed: int = 42  # dimensions only; products inherit from dimensions
    version: str = "1.0.0"

    def first_table(self) -> Table:
        return self.tables[0]

    def is_multi_table(self) -> bool:
        return len(self.tables) > 1

    def iceberg_database(self) -> str:
        """Glue database name convention: ``adp_<technical_name>``."""
        return f"adp_{self.name}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


_VALID_DIMENSION_REFS: set[str] = {
    "vins",
    "customers",
    "dealers",
    "suppliers",
    "parts",
    "charging_stations",
    "ota_campaigns",  # cross-table FK from ota_campaign_events to ota_campaigns
}


_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class SchemaValidationError(Exception):
    """Raised when a schema YAML fails validation."""


def _validate_column(c: dict[str, Any], *, table_name: str) -> Column:
    name = c.get("name")
    type_ = c.get("type")
    if not isinstance(name, str) or not _SNAKE_CASE_RE.match(name):
        raise SchemaValidationError(
            f"[{table_name}] column name must be snake_case string, got: {name!r}"
        )
    if type_ not in ALLOWED_COLUMN_TYPES:
        raise SchemaValidationError(
            f"[{table_name}.{name}] type must be one of {sorted(ALLOWED_COLUMN_TYPES)}, "
            f"got: {type_!r}"
        )

    decimal_precision = None
    decimal_scale = None
    if type_ == "decimal":
        decimal_precision = c.get("precision")
        decimal_scale = c.get("scale")
        if not (isinstance(decimal_precision, int) and isinstance(decimal_scale, int)):
            raise SchemaValidationError(
                f"[{table_name}.{name}] decimal columns require precision and scale (int)"
            )
        if not (1 <= decimal_precision <= 38) or not (0 <= decimal_scale <= decimal_precision):
            raise SchemaValidationError(
                f"[{table_name}.{name}] invalid decimal precision/scale "
                f"({decimal_precision}, {decimal_scale})"
            )

    range_ = c.get("range")
    if range_ is not None:
        if not (isinstance(range_, list) and len(range_) == 2):
            raise SchemaValidationError(
                f"[{table_name}.{name}] range must be a 2-element list [min, max]"
            )
        range_ = (float(range_[0]), float(range_[1]))

    enum_values = c.get("enum_values")
    if enum_values is not None:
        if not (isinstance(enum_values, list) and all(isinstance(v, str) for v in enum_values)):
            raise SchemaValidationError(
                f"[{table_name}.{name}] enum_values must be a list of strings"
            )
        enum_values = tuple(enum_values)

    pattern = c.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            raise SchemaValidationError(
                f"[{table_name}.{name}] pattern must be a string regex"
            )
        try:
            re.compile(pattern)
        except re.error as e:
            raise SchemaValidationError(
                f"[{table_name}.{name}] pattern is not a valid Python regex: {e}"
            )

    return Column(
        name=name,
        type=type_,
        nullable=bool(c.get("nullable", True)),
        pii=bool(c.get("pii", False)),
        edge_case_eligible=bool(c.get("edge_case_eligible", False)),
        pii_drift_target=bool(c.get("pii_drift_target", False)),
        description=str(c.get("description", "")),
        range=range_,
        enum_values=enum_values,
        decimal_precision=decimal_precision,
        decimal_scale=decimal_scale,
        pattern=pattern,
    )


def _validate_foreign_keys(
    fks_raw: list[dict[str, Any]] | None, *, table_name: str, columns: tuple[Column, ...]
) -> tuple[ForeignKey, ...]:
    if not fks_raw:
        return ()
    column_names = {c.name for c in columns}
    out: list[ForeignKey] = []
    for fk in fks_raw:
        col = fk.get("column")
        ref_table = fk.get("references_table")
        ref_column = fk.get("references_column")
        if col not in column_names:
            raise SchemaValidationError(
                f"[{table_name}] foreign_key.column '{col}' not in this table's columns"
            )
        if ref_table not in _VALID_DIMENSION_REFS:
            raise SchemaValidationError(
                f"[{table_name}] foreign_key.references_table '{ref_table}' not in "
                f"allowed set {sorted(_VALID_DIMENSION_REFS)}"
            )
        if not isinstance(ref_column, str) or not _SNAKE_CASE_RE.match(ref_column):
            raise SchemaValidationError(
                f"[{table_name}] foreign_key.references_column must be snake_case, "
                f"got: {ref_column!r}"
            )
        out.append(ForeignKey(column=col, references_table=ref_table, references_column=ref_column))
    return tuple(out)


def _validate_table(t_raw: dict[str, Any], *, schema_name: str, schema_kind: str = "product") -> Table:
    name = t_raw.get("name")
    if not isinstance(name, str) or not _SNAKE_CASE_RE.match(name):
        raise SchemaValidationError(
            f"[{schema_name}] table name must be snake_case string, got: {name!r}"
        )

    storage_format = t_raw.get("storage_format", "iceberg")
    if storage_format not in ALLOWED_STORAGE_FORMATS:
        raise SchemaValidationError(
            f"[{schema_name}.{name}] storage_format must be one of "
            f"{sorted(ALLOWED_STORAGE_FORMATS)}, got: {storage_format!r}"
        )

    # Validate provenance — required for product schemas; dimensions are out of scope v1.
    # See spec 2026-08-31-adp-curated-vintage-provenance § D1 and tasks.md item 1.
    provenance: str = ""
    if schema_kind == "product":
        provenance = t_raw.get("provenance") or ""
        if not provenance:
            raise SchemaValidationError(
                f"[{schema_name}.{name}] table is missing required 'provenance' field"
            )
        if provenance not in ALLOWED_PROVENANCE:
            raise SchemaValidationError(
                f"[{schema_name}.{name}] provenance '{provenance}' is not in the allowed set "
                f"{sorted(ALLOWED_PROVENANCE)}"
            )

    columns_raw = t_raw.get("columns", [])
    if not isinstance(columns_raw, list) or not columns_raw:
        raise SchemaValidationError(
            f"[{schema_name}.{name}] table must declare a non-empty 'columns' list"
        )
    columns = tuple(_validate_column(c, table_name=name) for c in columns_raw)

    column_names = {c.name for c in columns}
    primary_key = tuple(t_raw.get("primary_key", []) or ())
    for pk in primary_key:
        if pk not in column_names:
            raise SchemaValidationError(
                f"[{schema_name}.{name}] primary_key column '{pk}' not in columns list"
            )

    partition_keys = tuple(t_raw.get("partition_keys", []) or ())
    for pkey in partition_keys:
        if pkey not in column_names:
            raise SchemaValidationError(
                f"[{schema_name}.{name}] partition_key '{pkey}' not in columns list"
            )

    bucketing_raw = t_raw.get("bucketing", {}) or {}
    if not isinstance(bucketing_raw, dict):
        raise SchemaValidationError(
            f"[{schema_name}.{name}] bucketing must be a mapping {{column: count}}"
        )
    for col, count in bucketing_raw.items():
        if col not in column_names:
            raise SchemaValidationError(
                f"[{schema_name}.{name}] bucketing column '{col}' not in columns list"
            )
        if not isinstance(count, int) or count <= 0:
            raise SchemaValidationError(
                f"[{schema_name}.{name}] bucketing[{col}] must be a positive int"
            )

    foreign_keys = _validate_foreign_keys(
        t_raw.get("foreign_keys"), table_name=name, columns=columns
    )

    return Table(
        name=name,
        storage_format=storage_format,
        columns=columns,
        primary_key=primary_key,
        partition_keys=partition_keys,
        bucketing=bucketing_raw,
        foreign_keys=foreign_keys,
        provenance=provenance,
    )


_ALLOWED_DOMAINS = {
    "automotive",
    "ev_operations",
    "customer",
    "service",
    "knowledge",
    "dimension",
}


def _validate(raw: dict[str, Any], *, source_path: Path) -> Schema:
    name = raw.get("name")
    if not isinstance(name, str) or not _SNAKE_CASE_RE.match(name):
        raise SchemaValidationError(
            f"[{source_path}] schema name must be snake_case string, got: {name!r}"
        )

    kind = raw.get("kind")
    if kind not in ("product", "dimension"):
        raise SchemaValidationError(
            f"[{source_path}] kind must be 'product' or 'dimension', got: {kind!r}"
        )

    domain = raw.get("domain")
    if domain not in _ALLOWED_DOMAINS:
        raise SchemaValidationError(
            f"[{source_path}] domain must be one of {sorted(_ALLOWED_DOMAINS)}, got: {domain!r}"
        )

    display_name = raw.get("display_name")
    if not isinstance(display_name, str) or not display_name:
        raise SchemaValidationError(
            f"[{source_path}] display_name must be a non-empty string"
        )

    version = raw.get("version", "1.0.0")
    if not (isinstance(version, str) and _VERSION_RE.match(version)):
        raise SchemaValidationError(
            f"[{source_path}] version must be semver (e.g., '1.0.0'), got: {version!r}"
        )

    seed = raw.get("deterministic_seed", 42)
    if not isinstance(seed, int):
        raise SchemaValidationError(
            f"[{source_path}] deterministic_seed must be an int, got: {seed!r}"
        )

    tables_raw = raw.get("tables", [])
    if not isinstance(tables_raw, list) or not tables_raw:
        raise SchemaValidationError(
            f"[{source_path}] schema must declare a non-empty 'tables' list"
        )
    tables = tuple(_validate_table(t, schema_name=name, schema_kind=kind) for t in tables_raw)

    return Schema(
        name=name,
        kind=kind,
        domain=domain,
        display_name=display_name,
        tables=tables,
        deterministic_seed=seed,
        version=version,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _project_root() -> Path:
    """Return platform-foundation/ root regardless of where the loader is imported from."""
    here = Path(__file__).resolve()
    # platform-foundation/source/lib/schema_loader.py -> platform-foundation/
    return here.parents[2]


def schema_yaml_path(name: str, *, kind: str | None = None) -> Path:
    """Return the on-disk YAML path for a product or dimension schema."""
    root = _project_root()
    candidates: list[Path] = []
    if kind in (None, "product"):
        candidates.append(root / "source" / "data-products" / name / "schema.yaml")
    if kind in (None, "dimension"):
        candidates.append(root / "source" / "dimensions" / name / "schema.yaml")
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"No schema.yaml found for '{name}' (searched: {[str(c) for c in candidates]})"
    )


def load_schema(name: str, *, kind: str | None = None) -> Schema:
    """Load a product or dimension schema by technical name.

    Parameters
    ----------
    name
        Technical name in snake_case (e.g., ``charging_sessions``,
        ``vins``).
    kind
        ``"product"``, ``"dimension"``, or ``None`` (search both).

    Returns
    -------
    Schema
        Parsed and validated schema.
    """
    path = schema_yaml_path(name, kind=kind)
    return load_schema_from_path(path)


def load_schema_from_path(path: Path) -> Schema:
    with path.open("r") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise SchemaValidationError(f"[{path}] top-level YAML must be a mapping")
    return _validate(raw, source_path=path)


def discover_schemas(*, kind: str | None = None) -> list[Path]:
    """Find all schema.yaml files under platform-foundation/source/."""
    root = _project_root()
    paths: list[Path] = []
    if kind in (None, "product"):
        paths.extend(sorted((root / "source" / "data-products").glob("*/schema.yaml")))
    if kind in (None, "dimension"):
        paths.extend(sorted((root / "source" / "dimensions").glob("*/schema.yaml")))
    return paths


def validate_all() -> tuple[int, list[tuple[Path, str]]]:
    """Validate every schema YAML in the project.

    Returns ``(count_ok, errors)`` where ``errors`` is a list of
    ``(path, error_message)`` tuples.
    """
    paths = discover_schemas()
    errors: list[tuple[Path, str]] = []
    ok = 0
    for path in paths:
        try:
            load_schema_from_path(path)
            ok += 1
        except (SchemaValidationError, yaml.YAMLError, OSError) as e:
            errors.append((path, str(e)))
    return ok, errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="schema_loader",
        description="ADP foundation schema loader and validator.",
    )
    parser.add_argument(
        "--validate-all",
        action="store_true",
        help="Validate every schema.yaml under platform-foundation/source/",
    )
    parser.add_argument(
        "--ddl",
        metavar="PRODUCT",
        help="Print Iceberg DDL for the named product (use with --account/--region).",
    )
    parser.add_argument("--account", default="000000000000", help="AWS account ID for DDL gen.")
    parser.add_argument("--region", default="us-east-1", help="AWS region for DDL gen.")
    args = parser.parse_args(argv)

    if args.validate_all:
        ok, errors = validate_all()
        if errors:
            for path, err in errors:
                print(f"FAIL {path}: {err}", file=sys.stderr)
            print(f"{ok} schemas OK, {len(errors)} schemas FAILED", file=sys.stderr)
            return 1
        if ok == 0:
            print("No schemas discovered. Have you created the YAML files yet?", file=sys.stderr)
            # Returning 0 here is intentional during the test-skeleton phase: the loader
            # must run cleanly even before Group 1 task 4/5 schemas land.
        else:
            print(f"All {ok} schemas validated.")
        return 0

    if args.ddl:
        s = load_schema(args.ddl)
        for table in s.tables:
            if table.storage_format != "iceberg":
                continue
            location = (
                f"s3://adp-foundation-lake-{args.account}-{args.region}/"
                f"curated/{s.name}/{table.name}/"
            )
            print(table.iceberg_ddl(database=s.iceberg_database(), location=location))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
