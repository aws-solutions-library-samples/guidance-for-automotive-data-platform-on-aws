"""Tests for the Iceberg conversion path in publish_product.py.

Spec: .kiro/specs/2026-09-19-adp-curated-products-vin-scope-pruning/
      (Group 2 — Athena conversion path + idempotency)

Covers the four properties the spec calls load-bearing:

  1. Opt-in is gated on **all three** of: membership in
     ``_ICEBERG_MIGRATED_PRODUCTS``, ``storage_format == "iceberg"``, and a
     non-empty ``bucketing`` declaration. Neither of the latter two is
     sufficient alone: every ADP product declares ``storage_format: iceberg``,
     so that field by itself would sweep all ten into the conversion — and
     ``bucketing`` is declared by four products (``charging_sessions`` plus the
     out-of-scope ``tire_health``, ``vehicle_telemetry_aggregated`` and
     ``customer_interactions``), so gating on it silently converted three
     products this spec does not cover. The explicit allowlist is what bounds
     scope; see ``test_bucketing_alone_does_not_opt_an_out_of_scope_product_in``.
  2. The raw and derived LOCATIONs differ. They share a prefix only if someone
     breaks it, and if they did the two layers would overwrite each other.
  3. MSCK REPAIR targets the RAW table and never the Iceberg table.
  4. Re-publish is idempotent: a DROP precedes the CREATE+INSERT, so a second
     run cannot double rows.

Each of those has a matching mutation recorded in the spec's decisions.md — the
tests are written to fail when the property is broken, not merely to observe that
a statement was emitted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PF_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PF_ROOT / "source" / "scripts"))
sys.path.insert(0, str(_PF_ROOT / "source" / "lib"))

import publish_product as pp  # noqa: E402
import schema_loader as sl  # noqa: E402

BUCKET = "adp-staging-foundation-lake-000000000000-us-east-1"
DB = "adp_staging_charging_sessions"


def _table(name: str) -> sl.Table:
    """Load a real product table from schema.yaml — not a hand-built fixture.

    Using the real schema means these tests break if a schema edit silently
    removes the bucketing declaration the conversion depends on, which a
    synthetic fixture would hide.
    """
    return sl.load_schema(name, kind="product").tables[0]


# ---------------------------------------------------------------------------
# 1. Opt-in gating
# ---------------------------------------------------------------------------


def test_bucketing_declaration_is_what_opts_a_table_in():
    """charging_sessions declares bucketing today, so it converts."""
    tbl = _table("charging_sessions")
    assert tbl.storage_format == "iceberg"
    assert tbl.bucketing.get("vin") == 16
    assert pp._is_iceberg_conversion_target(tbl, product="charging_sessions") is True


def test_storage_format_alone_does_not_opt_a_table_in():
    """A table declaring iceberg but NO bucketing stays on the Hive path.

    This is the gate that keeps the other seven products out of the conversion.
    If it regressed, publishing any ADP product would start converting it.
    """
    tbl = _table("customer_360")
    assert tbl.storage_format == "iceberg", "precondition: all ADP products declare iceberg"
    assert not tbl.bucketing, "precondition: customer_360 declares no bucketing"
    assert pp._is_iceberg_conversion_target(tbl, product="customer_360") is False


@pytest.mark.parametrize(
    "product", ["tire_health", "vehicle_telemetry_aggregated", "customer_interactions"]
)
def test_bucketing_alone_does_not_opt_an_out_of_scope_product_in(product):
    """Regression guard for a defect this spec introduced and an existing test caught.

    FOUR products declare `bucketing`, not one: charging_sessions (in scope) plus
    these three (out of scope). The first implementation gated purely on
    `storage_format == iceberg and bucketing`, which silently converted all four —
    including tire_health, which is among the prod-blocked products. Caught by
    test_publish_product.py::test_dry_run_output_contains_no_bucket_transform,
    which publishes tire_health and asserts no bucket transform reaches the
    output.

    Scope is now an explicit allowlist. This test fails if someone re-derives the
    gate from schema fields alone.
    """
    tbl = _table(product)
    assert tbl.bucketing, f"precondition: {product} declares bucketing"
    assert tbl.storage_format == "iceberg", f"precondition: {product} declares iceberg"
    assert pp._is_iceberg_conversion_target(tbl, product=product) is False


def test_allowlist_contains_exactly_the_three_products_the_spec_scopes():
    assert pp._ICEBERG_MIGRATED_PRODUCTS == frozenset(
        {"service_records", "charging_sessions", "energy_usage"}
    )


def test_allowlist_membership_alone_is_not_sufficient():
    """An allowlisted product with no bucketing must still not convert.

    Otherwise adding a product to the allowlist before Group 3 declares its
    bucketing would publish it with an identity-only partition spec — an Iceberg
    table with none of the pruning benefit, which is worse than leaving it Hive
    because it looks migrated.
    """
    tbl = _table("customer_360")
    assert pp._is_iceberg_conversion_target(tbl, product="service_records") is False, (
        "a table without bucketing must not convert even under an allowlisted product name"
    )


def test_documents_tables_are_never_conversion_targets():
    tbl = _table("vehicle_knowledge_base")
    assert pp._is_iceberg_conversion_target(tbl, product="vehicle_knowledge_base") is False


@pytest.mark.parametrize(
    "product",
    ["tire_health", "vehicle_telemetry_aggregated", "customer_interactions"],
)
def test_else_branch_banner_does_not_claim_absent_bucketing_for_products_that_declare_it(
    product, monkeypatch, capsys, tmp_path
):
    """W5: the else-branch banner must not say 'none declares bucketing' for products
    that do declare it but are excluded by the allowlist.

    ``tire_health``, ``vehicle_telemetry_aggregated``, and
    ``customer_interactions`` all carry a ``bucketing`` declaration in schema.yaml
    and are excluded by ``_ICEBERG_MIGRATED_PRODUCTS``.  Before this fix the
    banner printed "none declares bucketing, so the pipeline produces plain parquet
    and the DDL matches deployed reality. Products opt in to Iceberg by declaring
    bucketing" — a false statement visible to every operator who publishes these
    products.
    """
    monkeypatch.setattr(pp, "_run_athena_query", lambda ddl, db, wg: None)
    monkeypatch.setattr(pp, "_local_product_dir", lambda p: tmp_path / p)
    monkeypatch.setattr(pp, "_resolve_account_id", lambda: "123456789012")
    # Prevent Step 2 S3 sync from reaching AWS — the test only needs to verify
    # the Step 1 DDL-style banner, which is printed before Step 2 runs.
    monkeypatch.setattr(pp, "_sync_table", lambda *a, **kw: None)
    # Create the minimal directory structure the publisher expects.
    (tmp_path / product / product).mkdir(parents=True)

    pp.publish_product(product, "staging", apply=False, allow_prod=False)

    out = capsys.readouterr().out
    assert "none declares bucketing" not in out, (
        f"Banner falsely claims no bucketing for {product}, which declares it: {out!r}"
    )
    assert "Products opt in to Iceberg by declaring bucketing" not in out, (
        f"Banner falsely attributes exclusion to missing bucketing for {product}: {out!r}"
    )
    # The correct reason is the allowlist, so it must be named.
    assert "_ICEBERG_MIGRATED_PRODUCTS" in out or "allowlist" in out, (
        f"Banner for {product} must name the allowlist as the reason: {out!r}"
    )


def test_raw_and_iceberg_locations_differ():
    raw = pp._s3_prefix(BUCKET, "charging_sessions", "charging_sessions")
    ice = pp._iceberg_s3_prefix(BUCKET, "charging_sessions", "charging_sessions")
    assert raw != ice
    # Neither may be a prefix of the other: an Iceberg table writing under the
    # raw prefix would corrupt the vintage-governed layer, and the reverse would
    # put raw parquet inside Iceberg's metadata tree.
    assert not ice.startswith(raw), f"iceberg location nests under raw: {ice}"
    assert not raw.startswith(ice), f"raw location nests under iceberg: {raw}"
    assert "/curated/" in raw
    assert "/iceberg/" in ice


def test_both_locations_end_with_slash():
    """Both DDL emitters reject a location without a trailing slash."""
    for loc in (
        pp._s3_prefix(BUCKET, "charging_sessions", "charging_sessions"),
        pp._iceberg_s3_prefix(BUCKET, "charging_sessions", "charging_sessions"),
    ):
        assert loc.endswith("/")


# ---------------------------------------------------------------------------
# 3. Emitted DDL shape
# ---------------------------------------------------------------------------


def test_iceberg_ddl_carries_table_type_and_bucket_transform():
    tbl = _table("charging_sessions")
    ddl = tbl.iceberg_ddl(
        database=DB,
        location=pp._iceberg_s3_prefix(BUCKET, "charging_sessions", "charging_sessions"),
    )
    assert "'table_type' = 'ICEBERG'" in ddl
    # The exact partition spec, not merely "a PARTITIONED BY clause exists" —
    # the bucket transform is the whole point of the migration.
    assert "PARTITIONED BY (session_date, bucket(16, vin))" in ddl


@pytest.mark.parametrize(
    "product,expected",
    [
        ("charging_sessions", "PARTITIONED BY (session_date, bucket(16, vin))"),
        ("service_records", "PARTITIONED BY (service_month, bucket(16, vin))"),
        ("energy_usage", "PARTITIONED BY (usage_date, bucket(16, vin))"),
    ],
)
def test_partition_spec_per_migrated_product(product, expected):
    """All three products in scope render their expected partition spec.

    service_records and energy_usage only satisfy this once Group 3 adds their
    bucketing declaration; until then this documents the target.
    """
    tbl = _table(product)
    if not tbl.bucketing:
        pytest.skip(f"{product} has no bucketing declaration yet (Group 3 adds it)")
    ddl = tbl.iceberg_ddl(
        database=f"adp_staging_{product}",
        location=pp._iceberg_s3_prefix(BUCKET, product, product),
    )
    assert expected in ddl


def test_raw_table_is_named_with_suffix_and_hive_shaped():
    tbl = _table("charging_sessions")
    raw = pp._raw_hive_table(tbl)
    assert raw.name == "charging_sessions_raw"
    # The original is a frozen dataclass and must be unchanged — the Iceberg DDL
    # depends on it still carrying the consumer-facing name.
    assert tbl.name == "charging_sessions"

    ddl = pp._hive_parquet_ddl(
        raw,
        database=DB,
        location=pp._s3_prefix(BUCKET, "charging_sessions", "charging_sessions"),
    )
    assert "CREATE EXTERNAL TABLE IF NOT EXISTS `adp_staging_charging_sessions`.`charging_sessions_raw`" in ddl
    assert "STORED AS PARQUET" in ddl
    # Hive cannot express bucket transforms; _hive_parquet_ddl drops them.
    assert "bucket(" not in ddl
    assert "ICEBERG" not in ddl


def test_msck_repair_targets_the_raw_table_never_the_iceberg_table():
    """MSCK REPAIR against an Iceberg table is invalid; it must name only the raw one."""
    msck = pp._msck_repair_statement(DB, pp._raw_table_name("charging_sessions"))
    assert "charging_sessions_raw" in msck
    # The bare table name must not appear as the MSCK target. Checking the
    # backticked identifier rather than a substring, because "charging_sessions"
    # is necessarily a substring of "charging_sessions_raw".
    assert "`charging_sessions`" not in msck


# ---------------------------------------------------------------------------
# 4. Idempotency
# ---------------------------------------------------------------------------


def test_drop_statement_precedes_refresh_and_is_conditional():
    drop = pp._iceberg_drop_statement(DB, "charging_sessions")
    assert drop.startswith("DROP TABLE IF EXISTS")
    assert "`adp_staging_charging_sessions`.`charging_sessions`" in drop
    # Must NOT target the raw layer: that is a Hive EXTERNAL table whose data
    # would survive, but dropping it would still break the conversion's read side.
    assert "_raw" not in drop


def test_insert_enumerates_columns_and_never_uses_select_star():
    tbl = _table("charging_sessions")
    ins = pp._iceberg_insert_statement(
        tbl, database=DB, raw_table_name=pp._raw_table_name("charging_sessions")
    )
    assert "SELECT *" not in ins
    assert ins.startswith('INSERT INTO "adp_staging_charging_sessions"."charging_sessions"')
    assert 'FROM "adp_staging_charging_sessions"."charging_sessions_raw"' in ins
    # Every declared column appears, so a column added to schema.yaml without a
    # corresponding DDL change surfaces here rather than at load time.
    for col in tbl.columns:
        assert f'"{col.name}"' in ins
    # Column count is symmetric between the INSERT target list and the SELECT list.
    assert ins.count('"vin"') == 2


def test_insert_uses_double_quotes_never_backticks():
    """Athena DML rejects backquoted identifiers. DDL accepts them.

    Regression guard for the Group 4 live-conversion failure:

        InvalidRequestException: backquoted identifiers are not supported;
        use double quotes to quote identifiers

    Athena parses DDL with a Hive-compatible parser and DML through Trino, so
    the backtick style that is correct in statements [1/5], [2/5] and [4/5] is
    invalid in [5/5]. The original implementation used backticks throughout;
    statements 1-4 succeeded against real Athena and the INSERT failed, leaving
    the derived table created and EMPTY.

    Every test for this path stubs the Athena client, so none of them could
    have caught it — this one asserts the property the service enforces.
    See issues/2026-09-20-athena-iceberg-insert-backquoted-identifiers/.
    """
    for product in ("charging_sessions", "service_records", "energy_usage"):
        tbl = _table(product)
        ins = pp._iceberg_insert_statement(
            tbl, database=f"adp_staging_{product}",
            raw_table_name=pp._raw_table_name(product),
        )
        assert "`" not in ins, (
            f"{product}: INSERT carries a backtick, which Athena DML rejects "
            f"outright: {ins[:200]!r}"
        )
        # And the identifiers are actually quoted, not merely bare.
        assert f'"adp_staging_{product}"."{product}"' in ins
        assert '"vin"' in ins


def test_ddl_statements_keep_backticks():
    """The converse guard: DDL must NOT be migrated to double quotes.

    `test_insert_uses_double_quotes_never_backticks` above could tempt a future
    reader into a global backtick purge. That would break the three statements
    that currently work, because Athena's DDL parser is the Hive-compatible one.
    Pin both halves so the asymmetry is explicit rather than accidental.
    """
    tbl = _table("charging_sessions")
    raw = pp._raw_hive_table(tbl)
    raw_ddl = pp._hive_parquet_ddl(
        raw, database=DB, location="s3://b/curated/charging_sessions/charging_sessions/"
    )
    assert "`" in raw_ddl, "raw Hive DDL must keep backticks (Hive parser)"

    msck = pp._msck_repair_statement(DB, raw.name)
    assert "`" in msck, "MSCK REPAIR must keep backticks (Hive parser)"


def test_statement_order_is_raw_then_drop_then_create_then_insert(monkeypatch, capsys):
    """The ordering IS the idempotency property, so assert it explicitly.

    A bare additive INSERT (no preceding DROP) would double rows on re-publish
    while leaving the table queryable — a silent failure. This test fails if the
    DROP is removed or moved after the CREATE.

    Also asserts the LOCATION embedded in each emitted DDL at the call site
    (C4): the Iceberg CREATE TABLE must target the /iceberg/ prefix and not
    /curated/, and the raw CREATE EXTERNAL TABLE must target /curated/ and not
    /iceberg/. These assertions pin M3b — the call-site mutation
    ``iceberg_location``→``raw_location`` at publish_product.py:533 — which
    escapes every other test in the suite because they inspect the prefix helpers
    in isolation rather than what reaches the emitted DDL.

    If that mutation is applied, the Iceberg CREATE TABLE LOCATION will carry
    ``/curated/`` and this test will fail on ``assert '/iceberg/' in ice_location``.
    """
    executed: list[str] = []
    monkeypatch.setattr(
        pp,
        "_run_athena_query",
        lambda ddl, db, wg, **kw: executed.append(ddl),
    )
    # Partition discovery is a SELECT, so it goes through the results-returning
    # helper rather than _run_athena_query. 13 values at 6-per-batch is
    # deliberately not a multiple of the batch size, so an off-by-one in the
    # chunking (dropping or duplicating the short final batch) shows up.
    fake_dates = [f"2026-01-{d:02d}" for d in range(1, 14)]

    def fake_rows(sql, db, wg, **kw):
        # The post-load reconciliation (W4) also goes through this helper, so
        # distinguish the discovery SELECT from the two count(*) SELECTs and
        # return a matching pair so reconciliation passes.
        if "count(*)" in sql:
            return ["13"]
        return list(fake_dates)

    monkeypatch.setattr(pp, "_run_athena_query_rows", fake_rows)

    pp._register_iceberg_table(
        _table("charging_sessions"),
        product="charging_sessions",
        database=DB,
        bucket=BUCKET,
        workgroup="cvx-staging-analytics",
        apply=True,
    )

    kinds = []
    for stmt in executed:
        head = stmt.strip().split("\n")[0]
        if head.startswith("CREATE EXTERNAL TABLE"):
            kinds.append("raw")
        elif head.startswith("MSCK REPAIR"):
            kinds.append("msck")
        elif head.startswith("DROP TABLE"):
            kinds.append("drop")
        elif head.startswith("CREATE TABLE"):
            kinds.append("iceberg")
        elif head.startswith("INSERT INTO"):
            kinds.append("insert")
        else:
            kinds.append(f"UNKNOWN:{head[:40]}")

    assert kinds == [
        "raw", "msck", "drop", "iceberg", "insert", "insert", "insert"
    ], kinds
    # The refresh must precede the load, or INSERT INTO is additive.
    assert kinds.index("drop") < kinds.index("insert")
    assert kinds.index("drop") < kinds.index("iceberg")

    # --- Batching: 13 partition values at 16 buckets -> 6 per batch -> 3 INSERTs.
    inserts = [s for s, k in zip(executed, kinds) if k == "insert"]
    assert len(inserts) == 3, f"expected 3 batches for 13 values, got {len(inserts)}"
    # Every discovered value appears exactly once across the batches. This is the
    # property that matters: a dropped value is rows that silently never load.
    all_insert_sql = "\n".join(inserts)
    for d in fake_dates:
        assert all_insert_sql.count(f"DATE '{d}'") == 1, (
            f"partition value {d} appears {all_insert_sql.count(f'DATE {d!r}')} "
            f"times across batches; expected exactly 1"
        )
    # Typed DATE literals, not CAST-to-varchar — a CAST would defeat partition
    # pruning and turn each batch into a full scan of the raw table.
    assert "CAST(" not in all_insert_sql
    assert 'WHERE "session_date" IN (' in all_insert_sql

    # --- C4: assert the LOCATION in each emitted DDL, pinning the call site ---
    # Extract the LOCATION string from a DDL statement.
    def _location_of(stmt: str) -> str:
        for line in stmt.split("\n"):
            stripped = line.strip()
            if stripped.startswith("LOCATION"):
                return stripped
        return ""

    raw_stmt = executed[kinds.index("raw")]
    iceberg_stmt = executed[kinds.index("iceberg")]

    raw_location = _location_of(raw_stmt)
    ice_location = _location_of(iceberg_stmt)

    # The raw CREATE EXTERNAL TABLE must point at the /curated/ prefix.
    assert "/curated/" in raw_location, (
        f"raw CREATE EXTERNAL TABLE LOCATION does not contain /curated/: {raw_location!r}"
    )
    assert "/iceberg/" not in raw_location, (
        f"raw CREATE EXTERNAL TABLE LOCATION must not contain /iceberg/: {raw_location!r}"
    )

    # The Iceberg CREATE TABLE must point at the /iceberg/ prefix — never /curated/.
    # Applying the mutation ``iceberg_location``→``raw_location`` at the call site
    # (publish_product.py:533) causes this assertion to fail because the submitted DDL
    # carries the curated/ prefix while the dry-run banner still prints iceberg/.
    assert "/iceberg/" in ice_location, (
        f"Iceberg CREATE TABLE LOCATION does not contain /iceberg/: {ice_location!r}"
    )
    assert "/curated/" not in ice_location, (
        f"Iceberg CREATE TABLE LOCATION must not contain /curated/: {ice_location!r}"
    )


def test_dry_run_executes_nothing(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(pp, "_run_athena_query", lambda ddl, db, wg: calls.append(ddl))
    pp._register_iceberg_table(
        _table("charging_sessions"),
        product="charging_sessions",
        database=DB,
        bucket=BUCKET,
        workgroup="cvx-staging-analytics",
        apply=False,
    )
    assert calls == []


# ---------------------------------------------------------------------------
# 5. The raw layer / vintage contract is untouched
# ---------------------------------------------------------------------------


def test_conversion_path_issues_no_s3_delete():
    """_purge_sync governs the raw layer and this path must not invoke deletion.

    Raw-layer retention is a deliberately deferred decision; silently deleting a
    layer the vintage-provenance contract governs is the failure this guards.
    """
    raw_location = pp._s3_prefix(BUCKET, "charging_sessions", "charging_sessions")
    tbl = _table("charging_sessions")
    statements = [
        pp._hive_parquet_ddl(pp._raw_hive_table(tbl), database=DB, location=raw_location),
        pp._iceberg_drop_statement(DB, tbl.name),
        tbl.iceberg_ddl(
            database=DB,
            location=pp._iceberg_s3_prefix(BUCKET, "charging_sessions", "charging_sessions"),
        ),
        pp._iceberg_insert_statement(
            tbl, database=DB, raw_table_name=pp._raw_table_name(tbl.name)
        ),
    ]
    for stmt in statements:
        assert "--delete" not in stmt
        assert "DELETE FROM" not in stmt.upper()


def test_purge_sync_still_passes_delete_only_via_its_own_helper():
    """Unchanged-behaviour guard for the raw layer's deletion path."""
    cmd = pp._purge_sync("/local/path", "s3://b/k/", dry_run=True)
    assert "--delete" in cmd
    additive = pp._build_s3_sync_cmd("/local/path", "s3://b/k/", dry_run=True)
    assert "--delete" not in additive



# ---------------------------------------------------------------------------
# 6. --register-only: convert without touching the raw layer
# ---------------------------------------------------------------------------


def test_register_only_skips_the_sync_entirely(monkeypatch, capsys, tmp_path):
    """The conversion must be runnable without any S3 sync.

    Why this flag exists, measured rather than theorised: `charging_sessions` has
    569 partition directories locally and 1,093 on staging S3. The vintage guard
    refuses to publish a single-vintage table with >1 local partition unless
    `--allow-purge` is passed, and purge-sync is `aws s3 sync --delete` with local
    as source of truth — so converting that product through the normal path would
    delete ~524 partitions of real data, over half the table.

    The Iceberg conversion derives from data already on S3 and needs no sync at
    all, so the correct answer is to skip Step 2 rather than to force a purge.
    """
    product_dir = tmp_path / "charging_sessions" / "charging_sessions"
    product_dir.mkdir(parents=True)
    # Deliberately >1 partition: the state that makes the vintage guard refuse.
    for day in ("session_date=2025-03-01", "session_date=2025-03-02"):
        (product_dir / day).mkdir()

    sync_calls: list[list[str]] = []
    monkeypatch.setattr(
        pp, "_build_s3_sync_cmd", lambda *a, **k: sync_calls.append(["additive"]) or []
    )
    monkeypatch.setattr(
        pp, "_purge_sync", lambda *a, **k: sync_calls.append(["PURGE"]) or []
    )
    monkeypatch.setattr(pp, "_local_product_dir", lambda p: tmp_path / p)
    monkeypatch.setattr(pp, "_resolve_account_id", lambda: "123456789012")

    pp.publish_product(
        "charging_sessions",
        "staging",
        apply=False,
        allow_prod=False,
        register_only=True,
    )

    out = capsys.readouterr().out
    assert "[STEP 2] SKIPPED" in out
    assert sync_calls == [], f"register_only must issue no sync, got {sync_calls}"
    # And it must still reach Step 3 and emit the conversion.
    assert "ICEBERG CONVERSION" in out
    assert "PARTITIONED BY (session_date, bucket(16, vin))" in out


def test_register_only_still_reaches_step3_despite_the_vintage_guard(
    monkeypatch, capsys, tmp_path
):
    """Without --register-only this same state exits(1) at the vintage guard.

    This is the control for the test above: it pins that the >1-local-partition
    state really does block the normal path, so --register-only is load-bearing
    rather than a convenience.
    """
    product_dir = tmp_path / "charging_sessions" / "charging_sessions"
    product_dir.mkdir(parents=True)
    for day in ("session_date=2025-03-01", "session_date=2025-03-02"):
        (product_dir / day).mkdir()

    monkeypatch.setattr(pp, "_local_product_dir", lambda p: tmp_path / p)
    monkeypatch.setattr(pp, "_resolve_account_id", lambda: "123456789012")

    with pytest.raises(SystemExit) as exc:
        pp.publish_product(
            "charging_sessions", "staging", apply=False, allow_prod=False
        )
    assert exc.value.code == 1
    assert "ICEBERG CONVERSION" not in capsys.readouterr().out


def test_register_only_and_allow_purge_are_mutually_exclusive():
    """Passing both is contradictory and must fail closed rather than pick one."""
    with pytest.raises(SystemExit) as exc:
        pp.main(
            [
                "--product", "charging_sessions",
                "--stage", "staging",
                "--apply",
                "--register-only",
                "--allow-purge",
            ]
        )
    assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Batching against Athena's 100-open-partition-writer cap (Group 4 blocker 2)
# ---------------------------------------------------------------------------


def test_partition_batch_size_stays_under_the_open_writer_cap():
    """Batch size x bucket multiplier must never exceed the budget.

    Verified against real Athena: 6 dates x 16 buckets = 96 cells SUCCEEDED,
    while the unbatched 31 x 16 = 496 failed with
    ICEBERG_TOO_MANY_OPEN_PARTITIONS. This asserts the arithmetic that keeps
    every generated batch on the working side of that line.
    """
    for product in ("charging_sessions", "service_records", "energy_usage"):
        tbl = _table(product)
        mult = pp._bucket_cell_multiplier(tbl)
        size = pp._partition_batch_size(tbl)
        assert mult == 16, f"{product}: expected 16 buckets, got {mult}"
        assert size == 6, f"{product}: expected 6 values per batch, got {size}"
        assert size * mult <= pp._ICEBERG_CELL_BUDGET
        assert size * mult < pp._ICEBERG_OPEN_WRITER_LIMIT
        assert size >= 1


def test_batches_cover_every_partition_value_exactly_once():
    """No value dropped, none duplicated — at an exact and an inexact multiple.

    A dropped value is rows that silently never reach the derived table; a
    duplicated one is rows loaded twice. Both survive a row count only if
    nobody compares it to the source.
    """
    tbl = _table("charging_sessions")
    for n in (1, 5, 6, 7, 12, 13, 100):
        values = [f"2026-01-{i:02d}" for i in range(1, n + 1)]
        stmts = pp._iceberg_insert_batches(
            tbl, database=DB, raw_table_name="charging_sessions_raw",
            partition_values=values,
        )
        expected_batches = (n + 5) // 6
        assert len(stmts) == expected_batches, (n, len(stmts))
        joined = "\n".join(stmts)
        for v in values:
            assert joined.count(f"DATE '{v}'") == 1, (n, v)


def test_batch_predicates_use_typed_date_literals_not_casts():
    """A CAST in the predicate reads fine and defeats partition pruning.

    With CAST(col AS VARCHAR) each batch would scan the whole raw table —
    183 full scans for charging_sessions rather than one table's worth spread
    across 183 batches. The cost is invisible in the result.
    """
    tbl = _table("charging_sessions")
    stmts = pp._iceberg_insert_batches(
        tbl, database=DB, raw_table_name="charging_sessions_raw",
        partition_values=["2026-01-01", "2026-01-02"],
    )
    sql = stmts[0]
    assert "CAST(" not in sql
    assert "DATE '2026-01-01'" in sql
    assert 'WHERE "session_date" IN (' in sql
    # Still double-quoted, never backticked (blocker 1 must not regress).
    assert "`" not in sql


def test_unpartitioned_table_yields_one_unfiltered_insert():
    """No partition keys means no WHERE clause and exactly one statement."""
    tbl = _table("charging_sessions")
    stmts = pp._iceberg_insert_batches(
        tbl, database=DB, raw_table_name="charging_sessions_raw",
        partition_values=[],
    )
    assert len(stmts) == 1
    assert "WHERE" not in stmts[0]


def test_partition_literal_renders_by_type():
    assert pp._partition_literal("2026-01-01", "date") == "DATE '2026-01-01'"
    assert pp._partition_literal("7", "int") == "7"
    assert pp._partition_literal("abc", "string") == "'abc'"
    # Quote injection in a partition value cannot break out of the literal.
    assert pp._partition_literal("a'b", "string") == "'a''b'"


# ---------------------------------------------------------------------------
# Review Cycle 6 findings (W2-W5)
# ---------------------------------------------------------------------------


def test_multiple_partition_keys_fail_closed(monkeypatch):
    """W5: batching on the first of two keys does not bound open writers.

    Filtering N values of key A still admits every distinct value of key B, so
    real open writers are N x |B| x buckets while _partition_batch_size's
    arithmetic says N x buckets. Every ADP schema is arity 1 today, so this is
    latent -- but D18 states the guarantee generally, and a second key added
    later must not quietly invalidate it.
    """
    import dataclasses
    tbl = _table("charging_sessions")
    two_keys = dataclasses.replace(
        tbl, partition_keys=["session_date", "station_id"]
    )
    try:
        pp._iceberg_insert_batches(
            two_keys, database=DB, raw_table_name="charging_sessions_raw",
            partition_values=["2026-01-01", "2026-01-02"],
        )
    except NotImplementedError as exc:
        assert "one partition key" in str(exc)
        assert "station_id" in str(exc)
    else:
        raise AssertionError("expected NotImplementedError on a 2-key table")


def test_query_rows_strips_header_only_on_the_first_page(monkeypatch):
    """W3: the header strip must key off page position, not emptiness.

    A first page contributing zero values (all-NULL, or header-only) would leave
    `values` empty, and an emptiness-keyed strip would then eat a real data row
    off page 2. Simulated with a header-only first page.
    """
    pages = [
        {"ResultSet": {"Rows": [{"Data": [{"VarCharValue": "v"}]}]},
         "NextToken": "t1"},
        {"ResultSet": {"Rows": [
            {"Data": [{"VarCharValue": "2026-01-01"}]},
            {"Data": [{"VarCharValue": "2026-01-02"}]},
        ]}},
    ]
    calls = {"n": 0}

    class _R:
        def __init__(self, out): self.stdout = out

    def fake_run(cmd, **kw):
        import json as _j
        if "start-query-execution" in cmd:
            return _R(_j.dumps({"QueryExecutionId": "qid"}))
        if "get-query-execution" in cmd:
            return _R(_j.dumps(
                {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}))
        out = _R(_j.dumps(pages[calls["n"]]))
        calls["n"] += 1
        return out

    monkeypatch.setattr(pp.subprocess, "run", fake_run)
    monkeypatch.setattr(pp, "_REGION", "us-east-1")
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda *_: None)

    got = pp._run_athena_query_rows("SELECT 1", "db", "wg")
    # Page 1's single row is the header and is dropped; BOTH page-2 rows survive.
    assert got == ["2026-01-01", "2026-01-02"], got


def test_row_count_mismatch_after_load_raises(monkeypatch, capsys):
    """W4: DROP + N INSERTs has no transaction; a short load must not pass.

    A partial load leaves the consumer-facing table queryable and SHORT, which
    answers with plausible low numbers instead of failing -- worse than an
    outage, because nothing surfaces it.
    """
    monkeypatch.setattr(pp, "_run_athena_query", lambda *a, **k: None)
    monkeypatch.setattr(
        pp, "_run_athena_query_rows",
        lambda sql, db, wg, **kw: (
            ["7"] if "charging_sessions_raw" not in sql else ["9"]
        ),
    )
    try:
        pp._register_iceberg_table(
            _table("charging_sessions"), product="charging_sessions",
            database=DB, bucket=BUCKET, workgroup="wg", apply=True,
        )
    except RuntimeError as exc:
        assert "ROW COUNT MISMATCH" in str(exc)
        assert "derived=7" in str(exc) and "raw=9" in str(exc)
    else:
        raise AssertionError("expected RuntimeError on a short load")


def test_dry_run_does_not_print_the_unbatched_insert(capsys):
    """W2: the dry-run must not show a statement that provably fails.

    [5/5] previously printed the unfiltered single-statement form -- exactly
    what blocker 2 proved fails with ICEBERG_TOO_MANY_OPEN_PARTITIONS for every
    product in this spec -- while the apply path ran 183 batched statements.
    """
    pp._register_iceberg_table(
        _table("charging_sessions"), product="charging_sessions",
        database=DB, bucket=BUCKET, workgroup="wg", apply=False,
    )
    out = capsys.readouterr().out
    assert "BATCHED:" in out
    assert "WHERE" in out, "dry-run must show the filtered batch shape"
    assert "ICEBERG_TOO_MANY_OPEN_PARTITIONS" in out, (
        "dry-run must say why the unfiltered form is not what runs"
    )
    # The bare unfiltered INSERT (ending at FROM ...raw"; with no WHERE) must
    # not appear as the [5/5] statement.
    assert 'FROM "adp_staging_charging_sessions"."charging_sessions_raw";' not in out


def test_arm3_control_matches_arm2_columns_and_has_no_bucket_transform():
    """D19/D20 arm 3 must be arm 2 minus the bucketing, nothing else.

    Two properties, both load-bearing for the causal claim:

      1. IDENTICAL columns in identical order. If they diverge, arm3-vs-arm2 is
         not like-for-like and the ratio comparison means nothing. This is the
         defect that killed the hand-written .sql version of this control arm --
         15 invented columns against the schema's real 24.
      2. NO bucket transform. If arm 3 carried one it would not be a control at
         all, and the gate would compare a bucketed table against itself.

    Mirrors what arm3_nobucket_control.py derives, so a schema change to
    charging_sessions cannot silently desynchronise the control arm.
    """
    import dataclasses
    base = _table("charging_sessions")
    assert base.bucketing, "arm 2 must be bucketed or there is nothing to control"

    control = dataclasses.replace(
        base, name="charging_sessions_nobucket", bucketing={}
    )

    assert [c.name for c in control.columns] == [c.name for c in base.columns]
    assert [c.type for c in control.columns] == [c.type for c in base.columns]
    assert control.partition_keys == base.partition_keys
    assert not control.bucketing

    ddl = control.iceberg_ddl(
        database=DB, location="s3://b/iceberg-control/charging_sessions_nobucket/"
    )
    assert "bucket(" not in ddl, f"control arm must carry no bucket transform:\n{ddl}"
    assert "PARTITIONED BY (session_date)" in ddl
    # And it must not be pointed at either the raw or arm 2's prefix.
    assert "/iceberg-control/" in ddl
    assert "/curated/" not in ddl

    # Arm 2, for contrast, must still carry it -- otherwise this test would pass
    # against a broken Group 3.
    arm2_ddl = base.iceberg_ddl(database=DB, location="s3://b/iceberg/cs/")
    assert "bucket(16, vin)" in arm2_ddl


def test_dry_run_also_fails_closed_on_multiple_partition_keys(capsys):
    """Cycle 7: the arity guard must cover the DRY-RUN path, not only apply.

    W5's original guard sat in _iceberg_insert_batches, which the dry-run never
    calls. So a 2-key table printed the arity-1 arithmetic -- "96 open writers
    per statement (cap 100)" -- reassuring the operator, while only --apply
    raised. Cycle 7 demonstrated the split by execution. The guard now lives in
    _partition_batch_size, which both callers go through.
    """
    import dataclasses
    two_keys = dataclasses.replace(
        _table("charging_sessions"),
        partition_keys=["session_date", "station_id"],
    )
    try:
        pp._register_iceberg_table(
            two_keys, product="charging_sessions", database=DB,
            bucket=BUCKET, workgroup="wg", apply=False,
        )
    except NotImplementedError as exc:
        assert "station_id" in str(exc)
    else:
        out = capsys.readouterr().out
        raise AssertionError(
            f"dry-run printed a writer estimate for a 2-key table instead of "
            f"failing closed:\n{out[-400:]}"
        )


def test_arm3_control_script_is_importable_and_derives_from_schema():
    """Cycle 7: the arm-3 guard must exercise the SCRIPT, not a copy of it.

    test_arm3_control_matches_arm2_columns_and_has_no_bucket_transform
    re-derives the control table inline, so edits to arm3_nobucket_control.py
    are invisible to it and its columns-identical assertion is tautological
    under dataclasses.replace. This one imports the script and asserts against
    what the script itself builds.
    """
    import importlib.util
    from pathlib import Path

    here = Path(__file__).resolve()
    script = None
    for up in here.parents:
        cand = (up / ".kiro" / "specs"
                / "2026-09-19-adp-curated-products-vin-scope-pruning"
                / "arm3_nobucket_control.py")
        if cand.exists():
            script = cand
            break
    assert script is not None, "arm3_nobucket_control.py not found"

    spec = importlib.util.spec_from_file_location("arm3_ctl", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Declared invariants the script relies on.
    assert mod.PRODUCT == "charging_sessions"
    assert mod.CONTROL_TABLE == "charging_sessions_nobucket"
    assert mod.CONTROL_PREFIX == "iceberg-control"
    assert mod.WINDOW_START == "2025-09-19"

    # The script's OWN control-table construction, not a reimplementation.
    control = mod._control_table("123456789012")
    base = _table("charging_sessions")
    assert not control.bucketing, "script must strip bucketing"
    assert [c.name for c in control.columns] == [c.name for c in base.columns]
    assert control.name == "charging_sessions_nobucket"

    ddl = control.iceberg_ddl(
        database=DB, location="s3://b/iceberg-control/charging_sessions_nobucket/"
    )
    assert "bucket(" not in ddl
    assert "/curated/" not in ddl


def test_arm3_script_pins_prefix_window_and_batch_count():
    """Cycle 8: three arm-3 properties that mutated silently before.

    Cycle 7 named four arm-3 mutations; two still passed after Fix Group 6 --
    a location ignoring CONTROL_PREFIX, and a dropped window filter -- and the
    354-dates -> 4-batches pin it asked for was never added. All three here.
    """
    import importlib.util
    from pathlib import Path

    here = Path(__file__).resolve()
    script = next(
        (up / ".kiro" / "specs"
         / "2026-09-19-adp-curated-products-vin-scope-pruning"
         / "arm3_nobucket_control.py")
        for up in here.parents
        if (up / ".kiro" / "specs"
            / "2026-09-19-adp-curated-products-vin-scope-pruning"
            / "arm3_nobucket_control.py").exists()
    )
    spec = importlib.util.spec_from_file_location("arm3_ctl_pins", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 1. The control arm must NOT be built in a consumer-shared database (S4):
    #    governance grants those per-database with table_wildcard={}.
    assert mod.CONTROL_DATABASE_SUFFIX == "verification"
    for shared in ("charging_sessions", "service_records", "energy_usage"):
        assert mod.CONTROL_DATABASE_SUFFIX != shared

    # 2. The window filter must actually drop out-of-window values.
    vals = ["2025-09-17", "2025-09-18", mod.WINDOW_START, "2026-01-01"]
    got = mod._in_window(vals)
    assert got == [mod.WINDOW_START, "2026-01-01"], got
    assert "2025-09-17" not in got

    # 3. 354 in-window dates with no bucketing -> exactly 4 batches, and the
    #    location must carry CONTROL_PREFIX rather than any other prefix.
    control = mod._control_table("123456789012")
    assert pp._partition_batch_size(control) == 96, "no bucketing -> 96 per batch"
    values = [f"d{i:04d}" for i in range(354)]
    batches = pp._iceberg_insert_batches(
        control, database="adp_staging_verification",
        raw_table_name="adp_staging_charging_sessions\".\"charging_sessions_raw",
        partition_values=values,
    )
    assert len(batches) == 4, f"354 values at 96/batch -> 4 batches, got {len(batches)}"

    ddl = control.iceberg_ddl(
        database="adp_staging_verification",
        location=f"s3://b/{mod.CONTROL_PREFIX}/{mod.CONTROL_TABLE}/",
    )
    assert f"/{mod.CONTROL_PREFIX}/" in ddl
    assert "/curated/" not in ddl
    assert "/iceberg/" not in ddl.replace(f"/{mod.CONTROL_PREFIX}/", "")


def test_arm3_planner_pins_location_and_window_at_the_usage_site():
    """Cycle 9: the previous pins guarded the constants, not their use.

    `CONTROL_PREFIX`'s value and `_in_window`'s body were both asserted, while
    the call sites in `main()` were not -- so a mutation that ignored either
    still passed. `_plan()` returns both, putting them on one testable surface.
    """
    import importlib.util
    from pathlib import Path

    here = Path(__file__).resolve()
    script = next(
        (up / ".kiro" / "specs"
         / "2026-09-19-adp-curated-products-vin-scope-pruning"
         / "arm3_nobucket_control.py")
        for up in here.parents
        if (up / ".kiro" / "specs"
            / "2026-09-19-adp-curated-products-vin-scope-pruning"
            / "arm3_nobucket_control.py").exists()
    )
    spec = importlib.util.spec_from_file_location("arm3_plan", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Default is the FULL table: arm 2 holds all 20M rows, so a window-scoped
    # arm 3 makes the 2a ratio comparison not like-for-like. The first Group 5
    # measurement used window-scoping and that confound is recorded in
    # decisions.md § "Post-migration measurement" Finding 3.
    loc, full = mod._plan(
        ["2025-09-17", "2025-09-18", "2025-09-19", "2026-01-01"], bucket="B"
    )
    assert full == ["2025-09-17", "2025-09-18", "2025-09-19", "2026-01-01"], full

    # Window-scoping is still available, and must actually filter when asked.
    loc2, win = mod._plan(
        ["2025-09-17", "2025-09-18", "2025-09-19", "2026-01-01"],
        bucket="B", window_scoped=True,
    )
    assert win == ["2025-09-19", "2026-01-01"], win
    assert len(win) < 4, "the window filter was not applied at the usage site"
    assert loc2 == loc, "location must not depend on the load scope"

    # Location must carry CONTROL_PREFIX and neither of the other two prefixes.
    assert loc == f"s3://B/{mod.CONTROL_PREFIX}/{mod.CONTROL_TABLE}/", loc
    assert "/iceberg-control/" in loc
    assert "/curated/" not in loc


def test_arm3_shared_database_denylist_is_derived_not_hand_copied():
    """Security S6 / Cycle 9: the hand-copy was short 3 of 10 within a day.

    Derived from GovernanceStack's own *_SHARE_DATABASES attributes, so a
    database added to a share list cannot silently become a legal target for
    the control arm.
    """
    import importlib.util
    from pathlib import Path

    here = Path(__file__).resolve()
    script = next(
        (up / ".kiro" / "specs"
         / "2026-09-19-adp-curated-products-vin-scope-pruning"
         / "arm3_nobucket_control.py")
        for up in here.parents
        if (up / ".kiro" / "specs"
            / "2026-09-19-adp-curated-products-vin-scope-pruning"
            / "arm3_nobucket_control.py").exists()
    )
    spec = importlib.util.spec_from_file_location("arm3_shared", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    shared = mod._consumer_shared_databases()
    assert len(shared) >= 10, f"expected >=10 shared databases, derived {len(shared)}"
    # The three the hand-copied denylist was missing.
    for missed in ("dealer_domain", "parts_domain", "tire_health"):
        assert missed in shared, f"{missed} absent -- derivation is incomplete"
    # And the control arm's own database must not be among them.
    assert mod.CONTROL_DATABASE_SUFFIX not in shared


def test_insert_qualifies_the_source_database_without_a_third_part():
    """Cycle 9 Critical: pre-qualifying raw_table_name rendered catalog.schema.table.

    `_iceberg_insert_statement` already supplies a database, so passing
    'db"."table' produced
    FROM "verification"."charging_sessions"."charging_sessions_raw"
    which Trino reads as catalog.schema.table -- CATALOG_NOT_FOUND against the
    live workgroup. source_database is the correct seam.
    """
    tbl = _table("charging_sessions")
    sql = pp._iceberg_insert_statement(
        tbl, database="adp_staging_verification",
        raw_table_name="charging_sessions_raw",
        source_database="adp_staging_charging_sessions",
    )
    assert 'INSERT INTO "adp_staging_verification"."charging_sessions_nobucket"' not in sql
    assert 'FROM "adp_staging_charging_sessions"."charging_sessions_raw"' in sql
    # Exactly two dotted-quote joins: one in the INSERT target, one in the FROM.
    assert sql.count('"."') == 2, f"expected 2 two-part identifiers, got {sql.count(chr(34)+'.'+chr(34))}"
    # Same-database callers are unaffected when source_database is omitted.
    same = pp._iceberg_insert_statement(
        tbl, database=DB, raw_table_name="charging_sessions_raw"
    )
    assert f'FROM "{DB}"."charging_sessions_raw"' in same
    assert same.count('"."') == 2
