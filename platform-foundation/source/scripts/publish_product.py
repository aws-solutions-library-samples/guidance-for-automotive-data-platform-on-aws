#!/usr/bin/env python3
"""publish_product.py — Automate steps 2 and 3 of the ADP product publish flow.

Publishing a pandas data product to the lake has historically required three
manual steps, of which only the first was automated:

  Step 1 (automated)  make seed-<product>       writes curated/<product>/ locally
  Step 2 (was manual) aws s3 sync               uploads local → lake bucket
  Step 3 (was manual) Athena CREATE TABLE DDL   registers the Glue catalog table

This script covers steps 2 and 3.  The DDL column list is derived from the
product's schema.yaml via the schema_loader, so the registered table shape
cannot drift from the declared contract.

NOTE on storage format (2026-08-04, Fix Group 3a):
  schema.yaml files declare ``storage_format: iceberg``, but the pipeline
  produces plain Hive-style parquet (no Iceberg metadata tree).  Every
  deployed table is EXTERNAL_TABLE with MapredParquetInputFormat and a null
  ``table_type`` parameter — confirmed against live staging infrastructure.
  This script therefore emits Hive-style DDL (``CREATE EXTERNAL TABLE IF NOT
  EXISTS … STORED AS PARQUET``) rather than Iceberg DDL, matching what Athena
  can actually read.  The schema.yaml declaration is intentionally left as
  ``iceberg`` — it is a real intent gap affecting every product, tracked as
  follow-on item 9 in spec § "Follow-ons to file".  See decisions.md for
  full rationale.

Provenance enforcement (spec 2026-08-31-adp-curated-vintage-provenance § D3):
  Each table in schema.yaml carries a ``provenance`` field that governs
  publisher behaviour:

  | provenance          | on-disk state   | behaviour                               |
  |---------------------|-----------------|----------------------------------------|
  | single-vintage      | 1 partition     | additive sync (default)                 |
  | single-vintage      | >1 partition    | refuse; opt-in via --allow-purge        |
  | cumulative-snapshot | any             | additive sync + multi-vintage summary   |
  | managed             | any             | skip; ingestion is Bedrock-owned        |

  The ONLY code path that passes the delete flag to aws s3 sync is
  _purge_sync() — invoked exclusively for single-vintage + >1 partition
  when --allow-purge is supplied. All other sync paths are additive.

Safety design (per ~/.kiro/steering/non-interactive.md and production-safety):
  - STAGE is required; the script exits non-zero if it is missing.
  - Dry-run is the default; pass --apply to execute.
  - The S3 sync is additive by default.
  - prod requires an additional --allow-prod flag in addition to --apply.
  - --allow-purge requires --apply at the CLI level.
  - For prod with --allow-purge: also requires --allow-prod (three-gate posture).
  - The account ID is resolved at runtime via AWS STS, never hardcoded.

Usage:
  # Dry-run (default) — prints what it would do, does nothing:
  python3 publish_product.py --product tire_health --stage staging

  # Apply:
  python3 publish_product.py --product tire_health --stage staging --apply

  # Apply to prod (double gate):
  python3 publish_product.py --product tire_health --stage prod --apply --allow-prod

  # Purge single-vintage residue (three-gate posture at CLI):
  python3 publish_product.py --product service_records --stage staging --apply --allow-purge

Invoked via Makefile:
  make publish-product PRODUCT=tire_health STAGE=staging
  make publish-product PRODUCT=tire_health STAGE=staging APPLY=1
  make publish-product-with-purge PRODUCT=service_records STAGE=staging APPLY=1 ALLOW_PURGE=1
"""

from __future__ import annotations

import argparse
import dataclasses
import json as _json
import subprocess
import sys
import textwrap
from pathlib import Path


# ---------------------------------------------------------------------------
# Locate project root and set up import path for schema_loader
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve()
# source/scripts/publish_product.py -> platform-foundation/
_PF_ROOT = _HERE.parents[2]
_SOURCE_LIB = _PF_ROOT / "source" / "lib"

if str(_SOURCE_LIB) not in sys.path:
    sys.path.insert(0, str(_SOURCE_LIB))

import schema_loader as sl  # noqa: E402 (after sys.path fixup)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REGION = "us-east-1"

# Athena workgroup is stage-derived, NOT a constant.
#
# It was previously hardcoded to "cvx-staging-analytics" and used for every
# --stage, including prod — so prod catalog mutations executed through a
# staging, cross-project workgroup, sending query-result location, workgroup
# enforcement settings and cost attribution to the wrong stage. Found
# 2026-08-31 after 7 prod tables had already been registered that way; see
# issues/2026-08-31-adp-publish-product-cross-stage-workgroup/.
#
# Every other identifier in this module is already stage-derived
# (_lake_bucket_name, _glue_database_name, _s3_prefix). The workgroup was the
# single place the stage boundary leaked, which is exactly why it survived
# review. Keep it a function so it cannot drift back into a constant.
_ATHENA_WORKGROUP_TEMPLATE = "cvx-{stage}-analytics"

# Map schema_loader ADP column types to Hive/SerDe column types.
# Athena's Hive DDL uses a smaller type set than Iceberg.
_HIVE_TYPE: dict[str, str] = {
    "string": "string",
    "int": "int",
    "bigint": "bigint",
    "double": "double",
    # decimal is parameterized — handled inline below
    "decimal": "decimal",
    "boolean": "boolean",
    "timestamp": "timestamp",
    "date": "date",
    "array<string>": "array<string>",
    "array<int>": "array<int>",
}


# ---------------------------------------------------------------------------
# Hive DDL generation
# ---------------------------------------------------------------------------


def _hive_column_fragment(col: sl.Column) -> str:
    """Return a single ``  `name` type`` line for a Hive CREATE TABLE column list."""
    if col.type == "decimal":
        assert col.decimal_precision is not None
        assert col.decimal_scale is not None
        hive_type = f"decimal({col.decimal_precision},{col.decimal_scale})"
    else:
        hive_type = _HIVE_TYPE[col.type]
    return f"  `{col.name}` {hive_type}"


def _hive_parquet_ddl(
    table: sl.Table,
    *,
    database: str,
    location: str,
) -> str:
    """Generate a Hive-style CREATE EXTERNAL TABLE DDL for plain-parquet data.

    Emits ``EXTERNAL TABLE IF NOT EXISTS`` with ``STORED AS PARQUET``,
    matching the deployed table shape (MapredParquetInputFormat /
    ParquetHiveSerDe, table_type=null).

    Partition columns are taken from ``table.partition_keys`` only.
    The ``bucket()`` transform from ``table.bucketing`` is intentionally
    dropped — bucket transforms are an Iceberg concept with no Hive
    equivalent and would cause a DDL parse error.

    Column list is derived from schema.yaml via schema_loader, so the
    registered shape cannot drift from the declared contract.
    """
    if not location.endswith("/"):
        raise ValueError(f"location must end with '/', got: {location}")

    partition_key_set = set(table.partition_keys)

    # Non-partition columns appear in the main column list.
    # Partition columns appear only in PARTITIONED BY — listing them in
    # both places is a Hive DDL error.
    data_cols = [c for c in table.columns if c.name not in partition_key_set]
    part_cols = [c for c in table.columns if c.name in partition_key_set]

    data_col_lines = ",\n".join(_hive_column_fragment(c) for c in data_cols)

    lines: list[str] = [
        f"CREATE EXTERNAL TABLE IF NOT EXISTS `{database}`.`{table.name}` (",
        data_col_lines,
        ")",
    ]

    if part_cols:
        part_col_lines = ",\n".join(_hive_column_fragment(c) for c in part_cols)
        lines.append(f"PARTITIONED BY (")
        lines.append(part_col_lines)
        lines.append(")")

    lines.append("STORED AS PARQUET")
    lines.append(f"LOCATION '{location}';")

    return "\n".join(lines)


def _msck_repair_statement(database: str, table_name: str) -> str:
    """Return the MSCK REPAIR TABLE statement that discovers Hive partitions.

    Without this, a freshly-created Hive-partitioned table returns zero rows
    even when the S3 data is present.  The statement scans the LOCATION prefix
    and registers each ``<partition_key>=<value>/`` sub-prefix as a partition.
    """
    return f"MSCK REPAIR TABLE `{database}`.`{table_name}`;"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_account_id() -> str:
    """Resolve the caller's AWS account ID via STS at runtime.

    Never hardcoded — this file is on the public-mirror path.
    """
    result = subprocess.run(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text",
         "--region", _REGION],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _lake_bucket_name(stage: str, account_id: str) -> str:
    """Derive the lake bucket name from stage + account.

    Pattern matches foundation_stack.py:
      adp-{stage}-foundation-lake-{account}-{region}
    """
    return f"adp-{stage}-foundation-lake-{account_id}-{_REGION}"


def _s3_prefix(bucket: str, product: str, table: str) -> str:
    """S3 location prefix for a product table, with trailing slash.

    This is the RAW layer: plain Hive-partitioned parquet, governed by
    ``_purge_sync`` and the vintage-provenance manifest. Unchanged by the
    Iceberg conversion.
    """
    return f"s3://{bucket}/curated/{product}/{table}/"


# Iceberg conversion (spec 2026-09-19-adp-curated-products-vin-scope-pruning).
#
# The derived Iceberg layer lives under a SEPARATE prefix root from the raw
# layer. This is required, not stylistic: the raw parquet sits *at* the raw
# table's LOCATION, so an Iceberg table adopting the consumer-facing identifier
# cannot also adopt that prefix without the two layers overwriting each other.
#
# Consequence worth stating explicitly, because it is a data-loss trap: Athena
# treats Iceberg tables as MANAGED, so DROP TABLE on one deletes its data
# (unlike a Hive EXTERNAL table, where the S3 data survives). The idempotent
# refresh below relies on that, and it is safe ONLY because the derived layer is
# reconstructible from the untouched raw layer. Never point the refresh at the
# raw table.
_ICEBERG_PREFIX_ROOT = "iceberg"
_RAW_TABLE_SUFFIX = "_raw"

# Products this spec migrates to Iceberg. Deliberately an explicit allowlist
# rather than a predicate derived from schema.yaml.
#
# Gating on `bucketing` alone is tempting and wrong: FOUR products declare it
# (charging_sessions, tire_health, vehicle_telemetry_aggregated,
# customer_interactions), so a bucketing-derived gate converts three products
# this spec does not cover — one of which, tire_health, is among the
# currently prod-blocked set. Gating on `storage_format: iceberg` is worse still:
# all ten products declare it.
#
# The issue names three products and the conversion covers exactly those three.
# The follow-on that migrates the rest extends this set; until then, scope is
# legible in one place and a reviewer can check it against the spec by reading
# three lines.
_ICEBERG_MIGRATED_PRODUCTS = frozenset(
    {
        "service_records",
        "charging_sessions",
        "energy_usage",
    }
)


def _iceberg_s3_prefix(bucket: str, product: str, table: str) -> str:
    """S3 location prefix for the DERIVED Iceberg layer, with trailing slash.

    Deliberately a different prefix root from ``_s3_prefix`` — see the module
    comment above.
    """
    return f"s3://{bucket}/{_ICEBERG_PREFIX_ROOT}/{product}/{table}/"


def _raw_table_name(table_name: str) -> str:
    """Glue table name for the raw Hive layer backing an Iceberg conversion."""
    return f"{table_name}{_RAW_TABLE_SUFFIX}"


def _is_iceberg_conversion_target(table: sl.Table, *, product: str) -> bool:
    """True when this table should be published as Iceberg rather than Hive.

    Requires all three of:
      - the product is in ``_ICEBERG_MIGRATED_PRODUCTS`` (this spec's scope),
      - ``storage_format: iceberg``,
      - a non-empty ``bucketing`` declaration — the thing that makes an Iceberg
        partition spec differ from the Hive one, and therefore the thing worth
        converting for.

    All three are checked rather than just the allowlist, so that adding a
    product to the allowlist before it declares bucketing is a no-op rather than
    a table published with an identity-only partition spec.
    """
    return (
        product in _ICEBERG_MIGRATED_PRODUCTS
        and table.storage_format == "iceberg"
        and bool(table.bucketing)
    )


def _raw_hive_table(table: sl.Table) -> sl.Table:
    """Return a copy of ``table`` renamed to its raw-layer name.

    ``Table`` is a frozen dataclass, so this is a copy rather than a mutation —
    the caller's table object keeps the consumer-facing name for the Iceberg DDL.
    """
    return dataclasses.replace(table, name=_raw_table_name(table.name))


def _iceberg_drop_statement(database: str, table_name: str) -> str:
    """DROP the derived Iceberg table so the next CREATE+INSERT is a full refresh.

    ``IF EXISTS`` makes first-run and re-run identical. On the FIRST run the
    named table is still the old Hive EXTERNAL table, so this drops metadata only
    and the raw parquet survives. On every later run it is an Iceberg managed
    table, so this also deletes the derived data — which is the point: it is what
    makes re-publish idempotent instead of additive.
    """
    return f"DROP TABLE IF EXISTS `{database}`.`{table_name}`;"


_ICEBERG_OPEN_WRITER_LIMIT = 100
_ICEBERG_CELL_BUDGET = 96


def _bucket_cell_multiplier(table: sl.Table) -> int:
    """Partition cells created per distinct partition-key value.

    A table partitioned by ``(usage_date, bucket(16, vin))`` opens 16 writers
    for every distinct ``usage_date`` present in the batch, so the multiplier is
    the product of the bucket counts.
    """
    n = 1
    for count in (table.bucketing or {}).values():
        n *= int(count)
    return n


def _partition_batch_size(table: sl.Table) -> int:
    """How many distinct partition-key values one INSERT may safely cover.

    Athena caps concurrent open partition writers at
    ``_ICEBERG_OPEN_WRITER_LIMIT`` (100) and fails the whole statement with
    ``ICEBERG_TOO_MANY_OPEN_PARTITIONS`` when a single ``INSERT`` exceeds it.
    ``_ICEBERG_CELL_BUDGET`` (96) leaves a margin below the hard limit.

    At 16 buckets this yields 6 dates per INSERT, which was verified against
    real Athena: 6 dates x 16 buckets = 96 cells SUCCEEDED, while the
    unbatched 31 x 16 = 496 failed.

    Fails closed on multiple partition keys. The arithmetic below is only valid
    for ONE key: with two keys, filtering N values of key A still admits every
    distinct value of key B, so real open writers are N x |B| x buckets while
    this returns a size premised on N x buckets — safe-looking and wrong.

    The check lives HERE rather than in ``_iceberg_insert_batches`` because both
    the batching path and the dry-run summary call this function, and the
    dry-run previously printed the arity-1 arithmetic ("96 open writers per
    statement, cap 100") for a 2-key table while only the apply path raised.
    Review Cycle 7 demonstrated that by execution: guard fired False on the
    print, True on apply. One chokepoint, both callers.
    """
    if len(table.partition_keys) > 1:
        raise NotImplementedError(
            f"{table.name}: batching supports exactly one partition key, got "
            f"{list(table.partition_keys)}. Batching on the first key alone "
            f"would not bound open writers: real cells are "
            f"N x |{table.partition_keys[1]}| x buckets, not N x buckets. "
            f"Extend the cell arithmetic to the full key cross-product before "
            f"removing this guard."
        )
    return max(1, _ICEBERG_CELL_BUDGET // _bucket_cell_multiplier(table))


def _partition_literal(value: str, col_type: str) -> str:
    """Render a partition value as a TYPED SQL literal.

    Typed literals are load-bearing for cost, not cosmetic. A predicate like
    ``CAST("session_date" AS VARCHAR) IN ('2026-01-01', ...)`` would read
    correctly and silently defeat partition pruning, turning every batch into a
    full scan of the raw table — 183 full scans for ``charging_sessions``
    instead of one table's worth spread across 183 batches.
    """
    t = (col_type or "").strip().lower()
    if t == "date":
        return f"DATE '{value}'"
    if t.startswith("timestamp"):
        return f"TIMESTAMP '{value}'"
    if t in ("int", "integer", "bigint", "smallint", "tinyint",
             "double", "float", "real") or t.startswith("decimal"):
        return value
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _iceberg_insert_statement(
    table: sl.Table,
    *,
    database: str,
    raw_table_name: str,
    where: str | None = None,
    source_database: str | None = None,
) -> str:
    """INSERT the raw layer into the derived Iceberg table.

    Columns are enumerated explicitly from schema.yaml rather than using
    ``SELECT *``. The two column sets are currently identical, so a star-select
    would work today — but it would silently mis-map the moment either side's
    column order or membership changed, and Iceberg hidden partitioning makes
    exactly that kind of change plausible later.

    ``where`` restricts the statement to a subset of partition values. It is
    how the caller stays under Athena's 100-open-writer cap; see
    ``_partition_batch_size``.

    ``source_database`` qualifies the SELECT side when the raw layer lives in a
    different database from the target — as it does for the D19 arm-3 control
    table, which writes into ``adp_{stage}_verification`` while reading raw from
    ``adp_{stage}_charging_sessions``. Defaults to ``database``, so every
    same-database caller is unaffected.

    Pass the bare table name in ``raw_table_name``. Pre-qualifying it instead
    produces a THREE-part identifier, because this template already supplies a
    database — Trino then reads ``a.b.c`` as catalog.schema.table and fails with
    ``CATALOG_NOT_FOUND``. Review Cycle 9 caught exactly that by submitting the
    rendered SQL to a live workgroup.

    Identifiers are quoted with DOUBLE QUOTES, not backticks, and that is
    load-bearing rather than stylistic. Athena parses DDL
    (``CREATE EXTERNAL TABLE``, ``MSCK REPAIR``, and even Iceberg
    ``CREATE TABLE``) with a Hive-compatible parser that accepts backticks, but
    routes DML through Trino, which rejects them outright:

        InvalidRequestException: backquoted identifiers are not supported;
        use double quotes to quote identifiers

    So the same backtick style that is correct three statements earlier fails
    here. Found by executing against real Athena in Group 4 — every unit test
    for this path stubs the Athena client, and a stub cannot fail the way a
    service fails. See issues/2026-09-20-group4-three-stacked-blockers/
    and ``test_insert_uses_double_quotes_never_backticks``.
    """
    col_names = [c.name for c in table.columns]
    col_list = ',\n  '.join(f'"{c}"' for c in col_names)
    where_clause = f"\nWHERE {where}" if where else ""
    src_db = source_database or database
    return (
        f'INSERT INTO "{database}"."{table.name}" (\n'
        f"  {col_list}\n"
        f")\n"
        f"SELECT\n"
        f"  {col_list}\n"
        f'FROM "{src_db}"."{raw_table_name}"{where_clause};'
    )


def _iceberg_insert_batches(
    table: sl.Table,
    *,
    database: str,
    raw_table_name: str,
    partition_values: list[str],
    source_database: str | None = None,
) -> list[str]:
    """Split the load into INSERTs that each stay under the writer cap.

    Returns one unfiltered statement when the table declares no bucketing and
    no partition keys — otherwise one statement per batch of at most
    ``_partition_batch_size(table)`` distinct partition values.
    """
    if not table.partition_keys or not partition_values:
        return [
            _iceberg_insert_statement(
                table, database=database, raw_table_name=raw_table_name,
                source_database=source_database,
            )
        ]

    # Fail closed on multiple partition keys rather than silently under-batching.
    # _partition_batch_size counts cells as (values x bucket multiplier), which is
    # only correct when batching on ONE key: with two keys, filtering N values of
    # key A still admits every distinct value of key B, so the real open-writer
    # count is N x |B| x buckets and can breach the cap while the arithmetic here
    # says it is safe. Every ADP schema is arity 1 today (verified), so this is
    # latent — but D18 states the batching guarantee in the general form, and a
    # second key added later must not quietly invalidate it.
    if len(table.partition_keys) > 1:
        raise NotImplementedError(
            f"{table.name}: batching supports exactly one partition key, got "
            f"{table.partition_keys}. Batching on the first key alone would not "
            f"bound open writers (see _partition_batch_size). Extend the cell "
            f"arithmetic to the full key cross-product before removing this guard."
        )

    key = table.partition_keys[0]
    col_type = next(
        (c.type for c in table.columns if c.name == key), "varchar"
    )
    size = _partition_batch_size(table)

    statements = []
    for i in range(0, len(partition_values), size):
        chunk = partition_values[i : i + size]
        literals = ", ".join(_partition_literal(v, col_type) for v in chunk)
        statements.append(
            _iceberg_insert_statement(
                table,
                database=database,
                raw_table_name=raw_table_name,
                where=f'"{key}" IN ({literals})',
                source_database=source_database,
            )
        )
    return statements




def _glue_database_name(stage: str, product: str) -> str:
    """Glue database name: adp_{stage}_{product}."""
    return f"adp_{stage}_{product}"


def _local_product_dir(product: str) -> Path:
    """Absolute path to the local curated/<product>/ directory."""
    return _PF_ROOT / "curated" / product


def _load_table_provenance(product: str, table_name: str) -> str:
    """Load the provenance value for a specific table from its schema.yaml.

    Returns one of: 'single-vintage', 'cumulative-snapshot', 'managed'.
    Raises SchemaValidationError (via schema_loader) if the value is absent
    or invalid.

    This is the single call site that reads provenance — it is the function
    that tests monkeypatch via patch.object(pp, '_load_table_provenance', ...).
    """
    schema = sl.load_schema(product, kind="product")
    for table in schema.tables:
        if table.name == table_name:
            return table.provenance  # type: ignore[attr-defined]
    raise ValueError(
        f"Table '{table_name}' not found in schema for product '{product}'"
    )


def _count_on_disk_partitions(table_dir: Path) -> list[str]:
    """Return the list of partition subdirectory names under table_dir.

    A partition subdir is any direct child directory (e.g. snapshot_date=2026-08-30).
    Plain files and hidden directories are excluded.
    """
    if not table_dir.exists():
        return []
    return [
        d.name for d in sorted(table_dir.iterdir())
        if d.is_dir() and not d.name.startswith(".")
    ]


# Sync excludes applied to every aws s3 sync invocation.
# manifest.json and .vintage-meta.json sidecars must not ship to the Glue
# LOCATION (spec § D4 + security-review Cycle 2 Suggestion 3).
# aws s3 sync does NOT skip dotfiles by default, so the sidecar exclude is
# required explicitly.
_SYNC_EXCLUDES = [
    "--exclude", "manifest.json",
    "--exclude", "*/manifest.json",
    "--exclude", "*/.vintage-meta.json",
]


def _build_s3_sync_cmd(
    local_path: str, s3_uri: str, *, dry_run: bool
) -> list[str]:
    """Build an additive aws s3 sync command with manifest + sidecar excludes.

    Additive only — does not pass the purge flag.
    Includes _SYNC_EXCLUDES so manifest.json and .vintage-meta.json sidecars
    are never shipped to the Glue LOCATION.

    See T3.4: manifest + sidecar sync exclude (spec § D4).
    """
    cmd = ["aws", "s3", "sync", local_path, s3_uri, "--region", _REGION]
    cmd.extend(_SYNC_EXCLUDES)
    if dry_run:
        cmd.append("--dryrun")
    return cmd


def _purge_sync(local_path: str, s3_uri: str, *, dry_run: bool) -> list[str]:
    """Build an aws s3 sync command with the purge flag for single-vintage cleanup.

    # The only place --delete is passed. See spec 2026-08-31-adp-curated-vintage-provenance § D3.

    This helper is the exclusive call site for the object-deletion flag.
    It is only invoked when provenance == 'single-vintage' AND >1 partition
    exists on disk AND --allow-purge was explicitly supplied by the operator.

    Includes _SYNC_EXCLUDES so manifest.json and sidecars are never shipped.
    """
    cmd = ["aws", "s3", "sync", local_path, s3_uri, "--region", _REGION]
    cmd.extend(_SYNC_EXCLUDES)
    cmd.append("--delete")
    if dry_run:
        cmd.append("--dryrun")
    return cmd


def _build_hive_ddl(
    product: str, stage: str, bucket: str
) -> tuple[str, str, str]:
    """Generate Hive-parquet CREATE TABLE DDL and MSCK REPAIR for a product.

    Returns (create_ddl, msck_ddl, database_name).

    Derived from schema.yaml via schema_loader — the column list is never
    hand-written here.  ``storage_format`` from schema.yaml is intentionally
    ignored *by this helper*: it emits the Hive shape unconditionally, because
    the raw layer is Hive parquet for every product including the Iceberg ones.

    Note this is NOT the whole publish story any more. Tables that additionally
    declare ``bucketing`` are published as Iceberg by ``_register_iceberg_table``,
    which calls this helper for the raw ``<table>_raw`` layer and then builds a
    derived Iceberg table on top. See
    spec 2026-09-19-adp-curated-products-vin-scope-pruning.
    """
    schema = sl.load_schema(product, kind="product")
    database = _glue_database_name(stage, product)
    create_parts: list[str] = []
    msck_parts: list[str] = []

    for table in schema.tables:
        if table.storage_format == "documents":
            # vehicle_knowledge_base text artifacts — no Athena table
            continue
        location = _s3_prefix(bucket, product, table.name)
        create_parts.append(_hive_parquet_ddl(table, database=database, location=location))
        if table.partition_keys:
            msck_parts.append(_msck_repair_statement(database, table.name))

    create_ddl = "\n\n".join(create_parts)
    msck_ddl = "\n".join(msck_parts)
    return create_ddl, msck_ddl, database


def _register_iceberg_table(
    table: sl.Table,
    *,
    product: str,
    database: str,
    bucket: str,
    workgroup: str,
    apply: bool,
) -> None:
    """Convert one table's raw Hive layer into a derived Iceberg table.

    Five statements, in this order:

      1. ``CREATE EXTERNAL TABLE {table}_raw``  — the raw layer, read side of the
         conversion, at the UNCHANGED ``_s3_prefix`` location.
      2. ``MSCK REPAIR TABLE {table}_raw``      — discover the raw Hive partitions.
      3. ``DROP TABLE IF EXISTS {table}``       — idempotent refresh (see
         ``_iceberg_drop_statement`` for why this is safe).
      4. ``CREATE TABLE {table}`` (Iceberg)     — at the separate Iceberg prefix,
         emitted by schema_loader's existing ``Table.iceberg_ddl()``.
      5. ``INSERT INTO {table} SELECT … FROM {table}_raw``

    No ``MSCK REPAIR`` is issued for the Iceberg table — Iceberg tracks its own
    state through its metadata files, and the statement is not valid against one.

    The raw layer's S3 sync (Step 2), ``_purge_sync``, the provenance branching
    and the three-flag prod guard are all untouched by this path: it only adds
    catalog objects and a derived copy.
    """
    raw_table = _raw_hive_table(table)
    raw_location = _s3_prefix(bucket, product, table.name)
    iceberg_location = _iceberg_s3_prefix(bucket, product, table.name)

    raw_ddl = _hive_parquet_ddl(raw_table, database=database, location=raw_location)
    drop_ddl = _iceberg_drop_statement(database, table.name)
    iceberg_ddl = table.iceberg_ddl(database=database, location=iceberg_location)
    insert_ddl = _iceberg_insert_statement(
        table, database=database, raw_table_name=raw_table.name
    )

    print(f"  -- ICEBERG CONVERSION for {database}.{table.name} --")
    print(f"  --   raw layer     : {raw_location}")
    print(f"  --   iceberg layer : {iceberg_location}")
    print(f"  --   partition spec: {table.partition_keys} + bucketing {table.bucketing}")
    print()
    print(f"  -- [1/5] raw Hive layer {database}.{raw_table.name} --")
    print(textwrap.indent(raw_ddl, "  "))
    print()

    msck = None
    if raw_table.partition_keys:
        msck = _msck_repair_statement(database, raw_table.name)
        print(f"  -- [2/5] partition discovery for the RAW table only --")
        print(f"  -- (never for the Iceberg table: it tracks its own state) --")
        print(textwrap.indent(msck, "  "))
        print()

    print(f"  -- [3/5] drop derived table for idempotent refresh --")
    print(f"  -- (first run: drops the old Hive EXTERNAL table, raw data survives.")
    print(f"  --  later runs: drops the Iceberg MANAGED table and its derived data,")
    print(f"  --  which is what stops INSERT INTO doubling rows on re-publish) --")
    print(textwrap.indent(drop_ddl, "  "))
    print()
    print(f"  -- [4/5] derived Iceberg table {database}.{table.name} --")
    print(textwrap.indent(iceberg_ddl, "  "))
    print()
    print(f"  -- [5/5] load raw -> iceberg (explicit column list, never SELECT *) --")
    if table.partition_keys:
        _bsize = _partition_batch_size(table)
        _mult = _bucket_cell_multiplier(table)
        print(f"  -- BATCHED: {_bsize} partition value(s) per INSERT, {_mult} cells each")
        print(f"  --   = {_bsize * _mult} open writers per statement (cap {_ICEBERG_OPEN_WRITER_LIMIT},")
        print(f"  --   budget {_ICEBERG_CELL_BUDGET}). One INSERT per batch, each carrying")
        print(f"  --   WHERE \"{table.partition_keys[0]}\" IN (<= {_bsize} typed literals).")
        print(f"  --   The batch COUNT is discovered at --apply time from the raw")
        print(f"  --   layer, which does not exist yet on a first run, so it cannot")
        print(f"  --   be shown here. Shape of one batch:")
        _sample = _iceberg_insert_statement(
            table,
            database=database,
            raw_table_name=raw_table.name,
            where=f'"{table.partition_keys[0]}" IN (<batch of {_bsize} values>)',
        )
        print(textwrap.indent(_sample, "  "))
        print()
        print(f"  -- NOTE: the unfiltered single-statement form is NOT what runs.")
        print(f"  --   It fails with ICEBERG_TOO_MANY_OPEN_PARTITIONS for every")
        print(f"  --   product in this spec (see D18). Only batches are executed.")
    else:
        print(textwrap.indent(insert_ddl, "  "))
    print()

    if not apply:
        return

    print(f"  Executing raw-layer CREATE TABLE in Athena ...")
    _run_athena_query(raw_ddl, database, workgroup)
    print(f"  OK — {database}.{raw_table.name} registered.")

    if msck is not None:
        print(f"  Executing MSCK REPAIR TABLE on the raw layer ...")
        _run_athena_query(msck, database, workgroup)
        print(f"  OK — partitions registered for {database}.{raw_table.name}.")

    print(f"  Executing DROP of the derived table (idempotent refresh) ...")
    _run_athena_query(drop_ddl, database, workgroup)
    print(f"  OK — {database}.{table.name} dropped if present.")

    print(f"  Executing Iceberg CREATE TABLE in Athena ...")
    _run_athena_query(iceberg_ddl, database, workgroup)
    print(f"  OK — {database}.{table.name} registered as ICEBERG.")

    # Partition discovery has to happen AFTER the raw layer exists and its
    # partitions are registered, which is why it is not hoisted above.
    partition_values: list[str] = []
    if table.partition_keys:
        key = table.partition_keys[0]
        print(f"  Discovering distinct {key} values on the raw layer ...")
        partition_values = _discover_partition_values(
            database, raw_table.name, key, workgroup
        )
        print(f"  OK — {len(partition_values)} distinct {key} value(s).")

    batches = _iceberg_insert_batches(
        table,
        database=database,
        raw_table_name=raw_table.name,
        partition_values=partition_values,
    )
    cells = _bucket_cell_multiplier(table) * _partition_batch_size(table)
    print(
        f"  Executing INSERT INTO ... SELECT (raw -> iceberg) in "
        f"{len(batches)} batch(es), <= {cells} open writers each ..."
    )
    for i, stmt in enumerate(batches, start=1):
        # A longer ceiling than the DDL default: a batch moves real rows, and a
        # 120s cap would abort mid-load on the larger products.
        _run_athena_query(stmt, database, workgroup, max_polls=450)
        print(f"    [{i}/{len(batches)}] OK")
    print(f"  OK — {database}.{table.name} loaded from {raw_table.name}.")

    # Post-load reconciliation. A DROP followed by N INSERTs has no transaction
    # around it: if a batch fails, or if discovery returned a short list, the
    # consumer-facing table is left SHORT and fully queryable — answering with
    # plausible low numbers instead of failing. That is worse than an outage,
    # because nothing surfaces it. Assert the derived row count equals the raw
    # row count before declaring the conversion done.
    print(f"  Reconciling row counts (derived vs raw) ...")
    derived = _run_athena_query_rows(
        f'SELECT CAST(count(*) AS VARCHAR) FROM "{database}"."{table.name}"',
        database, workgroup, max_polls=450,
    )
    raw_rows = _run_athena_query_rows(
        f'SELECT CAST(count(*) AS VARCHAR) FROM "{database}"."{raw_table.name}"',
        database, workgroup, max_polls=450,
    )
    d_n = int(derived[0]) if derived else -1
    r_n = int(raw_rows[0]) if raw_rows else -1
    if d_n != r_n or d_n < 0:
        raise RuntimeError(
            f"ROW COUNT MISMATCH after loading {database}.{table.name}: "
            f"derived={d_n:,} raw={r_n:,} (delta {d_n - r_n:+,}) across "
            f"{len(batches)} batch(es). The consumer-facing table is short or "
            f"over-loaded and must not be left in this state — re-run the "
            f"conversion, which is idempotent (the DROP prevents doubling)."
        )
    print(f"  OK — reconciled: {d_n:,} rows in both layers.")


def _athena_workgroup(stage: str) -> str:
    """Athena workgroup for a stage.

    Mirrors the stage threading of _glue_database_name / _lake_bucket_name so
    that a prod publish can never execute DDL through a staging workgroup.
    """
    return _ATHENA_WORKGROUP_TEMPLATE.format(stage=stage)


def _run_athena_query_rows(
    sql: str, database: str, workgroup: str, *, max_polls: int = 60
) -> list[str]:
    """Execute a SELECT and return the first column of every data row.

    Mirrors ``_run_athena_query``'s execution and polling, but reads results
    back. Used only for partition discovery, which needs the actual distinct
    values in order to build correctly-typed batch predicates.
    """
    import time

    result = subprocess.run(
        [
            "aws", "athena", "start-query-execution",
            "--query-string", sql,
            "--query-execution-context", _json.dumps({"Database": database}),
            "--work-group", workgroup,
            "--region", _REGION,
            "--output", "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    exec_id = _json.loads(result.stdout)["QueryExecutionId"]

    for _ in range(max_polls):
        time.sleep(2)
        status_result = subprocess.run(
            [
                "aws", "athena", "get-query-execution",
                "--query-execution-id", exec_id,
                "--region", _REGION,
                "--output", "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        status_data = _json.loads(status_result.stdout)
        state = status_data["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status_data["QueryExecution"]["Status"].get(
                "StateChangeReason", "no reason given"
            )
            raise RuntimeError(
                f"Athena query {exec_id} {state}: {reason}\n\nSQL was:\n{sql}"
            )
    else:
        raise TimeoutError(
            f"Athena query {exec_id} did not complete within {max_polls * 2}s"
        )

    values: list[str] = []
    next_token = None
    first_page = True
    while True:
        cmd = [
            "aws", "athena", "get-query-results",
            "--query-execution-id", exec_id,
            "--region", _REGION,
            "--output", "json",
        ]
        if next_token:
            cmd += ["--next-token", next_token]
        page = _json.loads(
            subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        )
        rows = page["ResultSet"]["Rows"]
        if first_page and rows:
            # Athena returns the column header as row 0 of the FIRST page only.
            # Keyed off an explicit flag rather than `not values`: a first page
            # that contributes zero values (all-NULL, or a header-only page)
            # would leave `values` empty and strip a real data row off page 2.
            rows = rows[1:]
        first_page = False
        for row in rows:
            data = row.get("Data", [])
            if data and "VarCharValue" in data[0]:
                values.append(data[0]["VarCharValue"])
        next_token = page.get("NextToken")
        if not next_token:
            break
    return values


def _discover_partition_values(
    database: str, raw_table_name: str, partition_key: str, workgroup: str
) -> list[str]:
    """Distinct values of the partition key, ordered, read from the raw layer.

    Read from the RAW table rather than the local curated/ tree on purpose: the
    local tree is a stale partial subset for at least one product, and a
    partition count is a property of what Athena queries. Reading it locally is
    the error D12 recorded.

    Pagination is followed to completion. A truncated first page would silently
    drop partition values, and every dropped value is rows that never reach the
    derived table — a silent under-load that row-count verification would catch
    only if someone compared the numbers.
    """
    sql = (
        f'SELECT DISTINCT "{partition_key}" AS v '
        f'FROM "{database}"."{raw_table_name}" ORDER BY 1'
    )
    return _run_athena_query_rows(sql, database, workgroup)


def _run_athena_query(ddl: str, database: str, workgroup: str, *, max_polls: int = 60) -> None:
    """Execute a DDL statement in Athena and wait for completion."""
    import time

    result = subprocess.run(
        [
            "aws", "athena", "start-query-execution",
            "--query-string", ddl,
            "--query-execution-context", _json.dumps({"Database": database}),
            "--work-group", workgroup,
            "--region", _REGION,
            "--output", "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    exec_id = _json.loads(result.stdout)["QueryExecutionId"]

    # Poll until terminal state
    for _ in range(max_polls):
        time.sleep(2)
        status_result = subprocess.run(
            [
                "aws", "athena", "get-query-execution",
                "--query-execution-id", exec_id,
                "--region", _REGION,
                "--output", "json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        status_data = _json.loads(status_result.stdout)
        state = status_data["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            reason = status_data["QueryExecution"]["Status"].get(
                "StateChangeReason", "no reason given"
            )
            raise RuntimeError(
                f"Athena query {exec_id} {state}: {reason}\n\nDDL was:\n{ddl}"
            )
    raise TimeoutError(
        f"Athena query {exec_id} did not complete within {max_polls * 2}s"
    )


# ---------------------------------------------------------------------------
# Provenance-aware sync for a single table (T3.1–T3.4)
# ---------------------------------------------------------------------------


def _sync_table(
    table: sl.Table,
    *,
    product: str,
    stage: str,
    local_product_dir: Path,
    bucket: str,
    apply: bool,
    allow_purge: bool,
) -> None:
    """Execute the D3 enforcement matrix for a single table.

    Called from publish_product() once per publishable table.  Handles all
    four provenance branches:

      managed             → skip immediately (printed + return)
      single-vintage / 1  → additive sync
      single-vintage / >1 → refuse or purge-sync per allow_purge
      cumulative-snapshot → additive sync with multi-vintage summary
    """
    table_dir = local_product_dir / table.name
    s3_uri = _s3_prefix(bucket, product, table.name)
    local_path = str(table_dir)

    # ----- (1) Load provenance -----
    provenance = _load_table_provenance(product, table.name)

    # ----- (2) managed: skip; ingestion is Bedrock-owned -----
    if provenance == "managed":
        print(
            f"[SKIP] {table.name}: provenance=managed — "
            f"publisher skips; ingestion is Bedrock-owned."
        )
        return

    # ----- (3) Count on-disk partitions -----
    partitions = _count_on_disk_partitions(table_dir)
    n_partitions = len(partitions)

    # ----- (4) cumulative-snapshot: additive sync with summary -----
    if provenance == "cumulative-snapshot":
        # Determine how many are "new" vs pre-existing using the manifest.
        # "new" means the vintage's generated_at_utc matches last_run.generated_at_utc.
        manifest_path = local_product_dir / table.name / "manifest.json"
        n_new = 0
        if manifest_path.exists():
            try:
                manifest = _json.loads(manifest_path.read_text())
                last_run_ts = manifest.get("last_run", {}).get("generated_at_utc", "")
                if last_run_ts:
                    for vintage in manifest.get("vintages", []):
                        if vintage.get("generated_at_utc", "") == last_run_ts:
                            n_new += 1
            except Exception:
                # Manifest read errors are non-fatal; fall back to 0 new
                n_new = 0

        if manifest_path.exists():
            n_pre = n_partitions - n_new
            print(
                f"[INFO] {table.name}: publishing {n_partitions} vintages: "
                f"{n_pre} pre-existing on disk, {n_new} new"
            )
        else:
            # No manifest yet — report all as pre-existing and suggest backfill
            print(
                f"[INFO] {table.name}: publishing {n_partitions} vintages: "
                f"{n_partitions} pre-existing, 0 new; "
                f"consider running backfill"
            )

        sync_cmd = _build_s3_sync_cmd(local_path, s3_uri, dry_run=not apply)
        print(f"[STEP 2] S3 sync (additive): {table.name}")
        print(f"  local : {local_path}")
        print(f"  s3    : {s3_uri}")
        print(f"  cmd   : {' '.join(sync_cmd)}")
        print()
        subprocess.run(sync_cmd, check=True)
        return

    # ----- (5) single-vintage: enforce 1-partition invariant -----
    assert provenance == "single-vintage", f"Unexpected provenance: {provenance!r}"

    if n_partitions <= 1:
        # Exactly 0 or 1 partition on disk — additive sync
        sync_cmd = _build_s3_sync_cmd(local_path, s3_uri, dry_run=not apply)
        print(f"[STEP 2] S3 sync: {table.name}")
        print(f"  local : {local_path}")
        print(f"  s3    : {s3_uri}")
        print(f"  cmd   : {' '.join(sync_cmd)}")
        print()
        subprocess.run(sync_cmd, check=True)
        return

    # >1 partition: refuse or purge
    if not allow_purge:
        print(
            f"ERROR: '{table.name}' is provenance=single-vintage but has "
            f"{n_partitions} partitions on disk. "
            f"Only 1 partition is expected. Offending vintages:",
            file=sys.stderr,
        )
        for p in partitions:
            print(f"  {p}", file=sys.stderr)
        print(
            f"\nTo remove the extra vintages from S3 (irreversible), re-run with "
            f"--allow-purge (also requires --apply; prod also requires --allow-prod).",
            file=sys.stderr,
        )
        sys.exit(1)

    # allow_purge=True: three-gate enforcement at CLI level (main())
    purge_cmd = _purge_sync(local_path, s3_uri, dry_run=not apply)
    print(f"[STEP 2] S3 sync (purge): {table.name}")
    print(f"  local : {local_path}")
    print(f"  s3    : {s3_uri}")
    print(f"  cmd   : {' '.join(purge_cmd)}")
    print(f"  WARNING: --allow-purge is set; S3 objects not present locally will be removed.")
    print()
    subprocess.run(purge_cmd, check=True)


# ---------------------------------------------------------------------------
# Main publish logic
# ---------------------------------------------------------------------------


def publish_product(
    product: str,
    stage: str,
    *,
    apply: bool,
    allow_prod: bool,
    allow_purge: bool = False,
    register_only: bool = False,
) -> None:
    """Run the publish workflow for a single product.

    In dry-run mode (apply=False): prints all actions, executes nothing.
    In apply mode: runs aws s3 sync then registers the Glue table via Athena DDL.

    allow_purge: when True, enables purge-sync for single-vintage tables
      with >1 partition on disk. At the CLI, this requires apply=True.
      For prod at the CLI, this also requires allow_prod=True (three-gate
      posture per spec 2026-08-31-adp-curated-vintage-provenance § D3).
      The Python function itself does not enforce apply=True so that tests
      can verify the sync command that would be issued without executing it.

    register_only: skip Step 2 (S3 sync) and run only Step 3 (catalog
      registration). Mutates no S3 object.

    .. warning::

       **The local ``curated/`` tree is not guaranteed to mirror S3, and
       ``--allow-purge`` deletes S3 objects absent locally.**

       Measured 2026-09-19 on staging: ``charging_sessions`` has 569 partition
       directories locally and **1,093** on S3. Running this with
       ``--apply --allow-purge`` for that product would delete ~524 partitions of
       real data — over half the table — because purge-sync treats local as the
       source of truth.

       That interacts badly with the Iceberg conversion, which by design derives
       from data already on S3 and needs no sync at all. Use ``--register-only``
       for conversions. Reconcile the local tree before ever purging.
       See spec 2026-09-19-adp-curated-products-vin-scope-pruning D12.
    """
    # ----- safety gates -----
    if stage == "prod" and not allow_prod:
        print(
            "ERROR: --stage prod requires --allow-prod flag. "
            "Prod changes are an explicit operator decision (spec § D5).",
            file=sys.stderr,
        )
        sys.exit(1)

    # ----- resolve account id at runtime -----
    print(f"Resolving AWS account ID ...")
    account_id = _resolve_account_id()
    print(f"  account_id = {account_id}")

    bucket = _lake_bucket_name(stage, account_id)
    local_product_dir = _local_product_dir(product)

    if not local_product_dir.exists():
        print(
            f"ERROR: local product directory not found: {local_product_dir}\n"
            f"Run 'make seed-{product.replace('_', '-')} STAGE={stage}' first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load schema to enumerate tables.
    # NOTE: we do NOT filter on storage_format == 'documents' here for the
    # publishable_tables list — that filter lives in _build_hive_ddl() for DDL
    # generation only. The provenance path in _sync_table() handles 'managed'
    # tables explicitly (they are not 'documents'-skipped before provenance
    # branching, which was the root cause of test_managed_skipped failing for
    # the wrong reason: the 'documents' filter in the original code preempted
    # the managed provenance path entirely).
    schema = sl.load_schema(product, kind="product")
    all_tables = schema.tables

    database = _glue_database_name(stage, product)
    mode_label = "DRY-RUN" if not apply else "APPLY"
    purge_label = " +ALLOW-PURGE" if allow_purge else ""
    print(f"\n{'='*60}")
    print(f"publish-product  product={product}  stage={stage}  mode={mode_label}{purge_label}")
    print(f"{'='*60}")
    print(f"  lake bucket : {bucket}")
    print(f"  glue db     : {database}")

    # The DDL style is now per-table, not a property of the whole run, so this
    # banner has to be derived rather than asserted. It previously stated
    # unconditionally that "the pipeline produces plain parquet", which became
    # false for the bucketing-declared products once the Iceberg conversion
    # landed — a stale banner naming the wrong storage format is how the next
    # reader gets misled about what they just deployed.
    iceberg_targets = [
        t.name for t in all_tables if _is_iceberg_conversion_target(t, product=product)
    ]
    hive_targets = [
        t.name
        for t in all_tables
        if t.storage_format != "documents"
        and not _is_iceberg_conversion_target(t, product=product)
    ]
    if iceberg_targets:
        print(f"  DDL style   : per-table")
        print(f"    ICEBERG   : {', '.join(iceberg_targets)}")
        print(f"                (raw Hive layer retained as <table>{_RAW_TABLE_SUFFIX}"
              f" at curated/; derived Iceberg at {_ICEBERG_PREFIX_ROOT}/)")
        if hive_targets:
            print(f"    Hive      : {', '.join(hive_targets)}")
    else:
        print(f"  DDL style   : Hive EXTERNAL TABLE / STORED AS PARQUET")
        # Explain the correct reason: products not on the allowlist are excluded
        # by the allowlist, not by absent bucketing. tire_health,
        # vehicle_telemetry_aggregated, and customer_interactions all declare
        # bucketing and would have been incorrectly described as "none declares
        # bucketing" by the previous banner.
        if product in _ICEBERG_MIGRATED_PRODUCTS:
            print(f"  NOTE: this product is on the conversion allowlist but its table")
            print(f"        declares no bucketing yet (Group 3 adds it). The pipeline")
            print(f"        produces plain parquet until bucketing is declared.")
        else:
            print(f"  NOTE: this product is not on the conversion allowlist")
            print(f"        (allowlist: {sorted(_ICEBERG_MIGRATED_PRODUCTS)});")
            print(f"        the pipeline produces plain parquet and the DDL matches")
            print(f"        deployed reality. The three scoped products opt in via that")
            print(f"        allowlist (spec 2026-09-19-adp-curated-products-vin-scope-pruning).")
    print()

    # Track whether any non-managed table was processed (for the 'nothing to sync' guard)
    any_published = False

    # ----- Step 2: S3 sync (provenance-aware) -----
    if register_only:
        print("[STEP 2] SKIPPED — --register-only: no S3 object is read or written.")
        print("  The Iceberg conversion derives from data already on S3, so the raw")
        print("  layer needs no sync. This also avoids purge-sync, which treats the")
        print("  local tree as source of truth and would delete S3 partitions absent")
        print("  locally (see publish_product() docstring warning).")
        print()
        any_published = any(
            _load_table_provenance(product, t.name) != "managed" for t in all_tables
        )
    else:
        for table in all_tables:
            provenance = _load_table_provenance(product, table.name)
            if provenance == "managed":
                # _sync_table will print the skip message; still call it
                _sync_table(
                    table,
                    product=product,
                    stage=stage,
                    local_product_dir=local_product_dir,
                    bucket=bucket,
                    apply=apply,
                    allow_purge=allow_purge,
                )
                continue

            any_published = True
            _sync_table(
                table,
                product=product,
                stage=stage,
                local_product_dir=local_product_dir,
                bucket=bucket,
                apply=apply,
                allow_purge=allow_purge,
            )

    if not any_published:
        # All tables are managed — nothing to sync or register
        print(
            f"[INFO] All tables in '{product}' are managed (Bedrock-owned ingestion). "
            f"Nothing to sync or register via this publisher."
        )
        return

    # ----- Step 3: Athena DDL registration -----
    workgroup = _athena_workgroup(stage)

    # DDL only for parquet tables (not documents / managed)
    ddl_tables = [t for t in all_tables if t.storage_format != "documents"]
    # The header below derives its Iceberg list from _is_iceberg_conversion_target,
    # which requires a bucketing declaration. So mid-rollout — after Group 2 shipped
    # this path but before Group 3 adds bucketing to service_records and
    # energy_usage — those two correctly print the Hive branch while
    # charging_sessions prints Iceberg. That is the gate reporting the truth, not
    # the banner lying again (the false-banner defect this replaced is Cycle 3 W5).
    _iceberg_names = [
        t.name for t in ddl_tables if _is_iceberg_conversion_target(t, product=product)
    ]
    if _iceberg_names:
        _hive_suffix = (
            f"; Hive / STORED AS PARQUET for the rest"
            if len(_iceberg_names) < len(ddl_tables) else ""
        )
        print(
            f"[STEP 3] Glue table registration via Athena DDL"
            f" (Iceberg: {', '.join(_iceberg_names)}{_hive_suffix})"
        )
    else:
        print(f"[STEP 3] Glue table registration via Athena DDL (Hive / STORED AS PARQUET)")
    print(f"  workgroup : {workgroup}")
    print(f"  database  : {database}")
    print()

    for table in ddl_tables:
        if _is_iceberg_conversion_target(table, product=product):
            _register_iceberg_table(
                table,
                product=product,
                database=database,
                bucket=bucket,
                workgroup=workgroup,
                apply=apply,
            )
            continue

        location = _s3_prefix(bucket, product, table.name)
        create_ddl = _hive_parquet_ddl(table, database=database, location=location)

        print(f"  -- CREATE TABLE DDL for {database}.{table.name} --")
        print(textwrap.indent(create_ddl, "  "))
        print()

        if table.partition_keys:
            msck = _msck_repair_statement(database, table.name)
            print(f"  -- Partition registration for {database}.{table.name} --")
            print(f"  -- (MSCK REPAIR scans the S3 LOCATION and registers each")
            print(f"  --  <partition_key>=<value>/ sub-prefix as a partition;")
            print(f"  --  without this step the table exists but returns zero rows) --")
            print(textwrap.indent(msck, "  "))
            print()

        if apply:
            print(f"  Executing CREATE TABLE in Athena ...")
            _run_athena_query(create_ddl, database, workgroup)
            print(f"  OK — {database}.{table.name} registered.")

            if table.partition_keys:
                msck = _msck_repair_statement(database, table.name)
                print(f"  Executing MSCK REPAIR TABLE in Athena ...")
                _run_athena_query(msck, database, workgroup)
                print(f"  OK — partitions registered for {database}.{table.name}.")

    if not apply:
        print()
        print(
            "DRY-RUN complete — nothing was modified.\n"
            "Re-run with --apply (and --allow-prod for prod) to execute."
        )
    else:
        print()
        print(f"Publish complete: {product} @ {stage}")
        print(f"  Glue table(s) registered under: {database}")
        print(f"  Raw S3 location(s) under: s3://{bucket}/curated/{product}/")
        if any(_is_iceberg_conversion_target(t, product=product) for t in all_tables):
            print(
                f"  Derived Iceberg location(s) under: "
                f"s3://{bucket}/{_ICEBERG_PREFIX_ROOT}/{product}/"
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Publish an ADP data product: sync local curated/ to S3 "
            "and register the Glue table via Athena DDL.\n\n"
            "Dry-run by default. Pass --apply to execute.\n"
            "prod requires --apply AND --allow-prod.\n"
            "--allow-purge enables purge-sync for single-vintage tables\n"
            "with >1 partition on disk (requires --apply; prod also requires --allow-prod)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--product",
        required=True,
        help="Product technical name (matches curated/<product>/ directory and schema.yaml)",
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=["staging", "prod"],
        help="Deployment stage. Required.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help=(
            "Execute the sync and DDL registration. "
            "Without this flag the script is a dry-run."
        ),
    )
    parser.add_argument(
        "--allow-prod",
        action="store_true",
        default=False,
        dest="allow_prod",
        help=(
            "Required when --stage prod. Explicit operator acknowledgement "
            "that prod changes are intentional (spec § D5)."
        ),
    )
    parser.add_argument(
        "--allow-purge",
        action="store_true",
        default=False,
        dest="allow_purge",
        help=(
            "Enable purge-sync (S3 object removal) for single-vintage tables with >1 "
            "partition on disk. Requires --apply. For prod, also requires --allow-prod. "
            "Only applies to single-vintage tables — cumulative-snapshot tables "
            "are always synced additively regardless of this flag."
        ),
    )
    parser.add_argument(
        "--register-only",
        action="store_true",
        default=False,
        dest="register_only",
        help=(
            "Skip the S3 sync (Step 2) and run only catalog registration (Step 3). "
            "Use this for the Iceberg conversion, which derives its table from data "
            "ALREADY on S3 and must not touch the raw layer. Mutates no S3 object. "
            "Required for products whose local curated/ tree is not a faithful "
            "mirror of S3 -- see the warning in publish_product()'s docstring."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    # Three-gate posture (CLI-level enforcement per spec § D3):
    #   --allow-purge requires --apply (never dry-run-purges at CLI level)
    #   --allow-purge on prod also requires --allow-prod
    # These guards live in main() (CLI) rather than publish_product() so that
    # the Python API can be called with apply=False + allow_purge=True in tests
    # to verify the sync command that would be issued without executing it.
    if args.allow_purge and not args.apply:
        print(
            "ERROR: --allow-purge requires --apply. "
            "Pass both --apply and --allow-purge to execute a purge.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.allow_purge and args.stage == "prod" and not args.allow_prod:
        print(
            "ERROR: --allow-purge on prod requires --apply + --allow-prod + --allow-purge. "
            "Three-gate posture per spec 2026-08-31-adp-curated-vintage-provenance § D3.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.register_only and args.allow_purge:
        print(
            "ERROR: --register-only and --allow-purge are mutually exclusive. "
            "--register-only skips the sync entirely; --allow-purge is a sync flag. "
            "Passing both is a contradiction and most likely means the caller wants "
            "--register-only alone.",
            file=sys.stderr,
        )
        sys.exit(1)

    publish_product(
        args.product,
        args.stage,
        apply=args.apply,
        allow_prod=args.allow_prod,
        allow_purge=args.allow_purge,
        register_only=args.register_only,
    )


if __name__ == "__main__":
    main()
