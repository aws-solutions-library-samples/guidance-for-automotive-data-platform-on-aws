"""Unit tests for source/scripts/publish_product.py.

Covers:
  - DDL generation from schema.yaml (columns derived, not hand-written)
  - DDL shape: EXTERNAL TABLE + STORED AS PARQUET (not ICEBERG TBLPROPERTIES)
  - Partition registration: MSCK REPAIR TABLE present in dry-run output
  - prod guard: refusing prod without --allow-prod
  - prod guard: refusing prod without --apply
  - missing STAGE exits non-zero via argparse
  - S3 sync command construction (no --delete, correct URI pattern)
  - account ID is never hardcoded in generated artefacts

Per spec § D4 task T3.1 + Fix Group 3a task T3.2.

NOTE on storage format (T3.2):
  schema.yaml declares ``storage_format: iceberg`` but the pipeline and all
  deployed tables are plain Hive-parquet (EXTERNAL_TABLE / MapredParquetInputFormat /
  ParquetHiveSerDe, table_type=null).  The DDL emitted by publish_product.py
  matches the *deployed* reality, not the schema declaration.  Tests that
  previously asserted Iceberg TBLPROPERTIES have been updated accordingly, with
  a comment explaining the intent gap.  The schema.yaml declaration is
  intentionally left unchanged (see spec § "Follow-ons to file" #9).

These tests run without any AWS calls (all AWS-bound paths are mocked or
tested via argument parsing alone).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the module under test and schema_loader are importable
# ---------------------------------------------------------------------------

_PF_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_LIB = _PF_ROOT / "source" / "lib"
_SOURCE_SCRIPTS = _PF_ROOT / "source" / "scripts"

for _p in (_SOURCE_LIB, _SOURCE_SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import publish_product as pp  # noqa: E402
import schema_loader as sl  # noqa: E402


# ---------------------------------------------------------------------------
# DDL generation — derived from schema.yaml, Hive/parquet shape
# ---------------------------------------------------------------------------


class TestDDLGeneration:
    """DDL column list must be derived from schema.yaml and match the deployed
    Hive/parquet table shape (EXTERNAL TABLE, STORED AS PARQUET).

    schema.yaml declares storage_format=iceberg, but every deployed table is
    MapredParquetInputFormat / ParquetHiveSerDe with a null table_type.
    Registering an Iceberg table over plain-parquet files would produce a table
    that returns zero rows.  publish_product.py therefore emits Hive-style DDL
    regardless of schema.yaml's storage_format declaration.
    """

    def test_tire_health_ddl_contains_all_schema_columns(self):
        """Every column declared in tire_health/schema.yaml must appear in the DDL."""
        schema = sl.load_schema("tire_health", kind="product")
        table = schema.first_table()

        database = "adp_staging_tire_health"
        location = "s3://adp-staging-foundation-lake-123456789012-us-east-1/curated/tire_health/tire_health/"
        ddl = pp._hive_parquet_ddl(table, database=database, location=location)

        # All columns must appear in the DDL (data cols in body, partition cols in
        # PARTITIONED BY).  Both sections use backtick-quoted names.
        for col in table.columns:
            assert f"`{col.name}`" in ddl, (
                f"Column '{col.name}' from schema.yaml is missing from the generated DDL.\n"
                f"DDL:\n{ddl}"
            )

    def test_tire_health_ddl_has_15_columns(self):
        """tire_health schema.yaml declares 15 columns — all must be represented."""
        schema = sl.load_schema("tire_health", kind="product")
        table = schema.first_table()
        assert len(table.columns) == 15, (
            f"Expected 15 columns in tire_health schema, found {len(table.columns)}: "
            f"{[c.name for c in table.columns]}"
        )

    def test_tire_health_ddl_has_partition_key_event_date(self):
        """tire_health is partitioned by event_date — DDL must include PARTITIONED BY."""
        schema = sl.load_schema("tire_health", kind="product")
        table = schema.first_table()
        assert "event_date" in table.partition_keys

        database = "adp_staging_tire_health"
        location = "s3://adp-staging-foundation-lake-123456789012-us-east-1/curated/tire_health/tire_health/"
        ddl = pp._hive_parquet_ddl(table, database=database, location=location)

        assert "PARTITIONED BY" in ddl
        assert "event_date" in ddl

    def test_service_records_ddl_contains_all_schema_columns(self):
        """Every column in service_records/schema.yaml must appear in the DDL."""
        schema = sl.load_schema("service_records", kind="product")
        table = schema.first_table()

        database = "adp_staging_service_records"
        location = "s3://adp-staging-foundation-lake-123456789012-us-east-1/curated/service_records/service_records/"
        ddl = pp._hive_parquet_ddl(table, database=database, location=location)

        for col in table.columns:
            assert f"`{col.name}`" in ddl, (
                f"Column '{col.name}' from schema.yaml is missing from service_records DDL.\n"
                f"DDL:\n{ddl}"
            )

    def test_service_records_ddl_has_partition_key_service_month(self):
        """service_records is partitioned by service_month."""
        schema = sl.load_schema("service_records", kind="product")
        table = schema.first_table()
        assert "service_month" in table.partition_keys

        database = "adp_staging_service_records"
        location = "s3://adp-staging-foundation-lake-123456789012-us-east-1/curated/service_records/service_records/"
        ddl = pp._hive_parquet_ddl(table, database=database, location=location)

        assert "PARTITIONED BY" in ddl
        assert "service_month" in ddl

    def test_ddl_is_external_table_stored_as_parquet(self):
        """Generated DDL must use EXTERNAL TABLE syntax with STORED AS PARQUET.

        This matches the deployed table shape (MapredParquetInputFormat /
        ParquetHiveSerDe, table_type=null).  Previously this test asserted
        ``'table_type' = 'ICEBERG'`` but that shape would create a table over
        plain-parquet files that Athena cannot read via the Iceberg catalog
        (no manifest metadata tree exists).
        """
        schema = sl.load_schema("tire_health", kind="product")
        table = schema.first_table()

        database = "adp_staging_tire_health"
        location = "s3://adp-staging-foundation-lake-123456789012-us-east-1/curated/tire_health/tire_health/"
        ddl = pp._hive_parquet_ddl(table, database=database, location=location)

        assert "EXTERNAL TABLE" in ddl, (
            "Generated DDL must declare EXTERNAL TABLE to match deployed shape"
        )
        assert "STORED AS PARQUET" in ddl, (
            "Generated DDL must declare STORED AS PARQUET to match deployed SerDe"
        )
        # No Iceberg-specific syntax should be present
        assert "ICEBERG" not in ddl, (
            "Generated DDL must not contain ICEBERG — plain-parquet files have no "
            "Iceberg manifest and the table would return zero rows"
        )
        assert "bucket(" not in ddl, (
            "Generated DDL must not contain bucket() — that is Iceberg hidden "
            "partitioning with no Hive equivalent and would cause a parse error"
        )

    def test_ddl_uses_if_not_exists(self):
        """DDL must use IF NOT EXISTS so re-runs are idempotent."""
        schema = sl.load_schema("tire_health", kind="product")
        table = schema.first_table()

        database = "adp_staging_tire_health"
        location = "s3://adp-staging-foundation-lake-123456789012-us-east-1/curated/tire_health/tire_health/"
        ddl = pp._hive_parquet_ddl(table, database=database, location=location)

        assert "IF NOT EXISTS" in ddl, (
            "Generated DDL must use CREATE EXTERNAL TABLE IF NOT EXISTS for idempotency"
        )

    def test_ddl_partition_columns_not_duplicated_in_body(self):
        """Partition columns must appear ONLY in PARTITIONED BY, not in the column body.

        Listing a partition column in both places is a Hive DDL error.
        """
        schema = sl.load_schema("tire_health", kind="product")
        table = schema.first_table()
        assert "event_date" in table.partition_keys

        database = "adp_staging_tire_health"
        location = "s3://adp-staging-foundation-lake-123456789012-us-east-1/curated/tire_health/tire_health/"
        ddl = pp._hive_parquet_ddl(table, database=database, location=location)

        # The column body is between the opening '(' and 'PARTITIONED BY'.
        # Split on PARTITIONED BY and check the first part.
        if "PARTITIONED BY" in ddl:
            body, partitioned_by_section = ddl.split("PARTITIONED BY", 1)
            assert "`event_date`" not in body, (
                "Partition column 'event_date' must not appear in the main column body"
            )

    def test_ddl_no_bucket_transform(self):
        """bucket() transform must not appear in any DDL — it is Iceberg-only."""
        for product in ("tire_health", "service_records"):
            schema = sl.load_schema(product, kind="product")
            table = schema.first_table()
            database = f"adp_staging_{product}"
            location = (
                f"s3://adp-staging-foundation-lake-123456789012-us-east-1"
                f"/curated/{product}/{table.name}/"
            )
            ddl = pp._hive_parquet_ddl(table, database=database, location=location)
            assert "bucket(" not in ddl, (
                f"[{product}] DDL must not contain bucket() — Iceberg-only transform"
            )

    def test_ddl_location_contains_account_id_placeholder_not_literal(self):
        """The DDL location uses the provided argument — no account ID is hardcoded
        inside publish_product.py or schema_loader.py.
        """
        schema = sl.load_schema("tire_health", kind="product")
        table = schema.first_table()

        fake_account = "111122223333"
        database = "adp_staging_tire_health"
        location = (
            f"s3://adp-staging-foundation-lake-{fake_account}-us-east-1"
            f"/curated/tire_health/tire_health/"
        )
        ddl = pp._hive_parquet_ddl(table, database=database, location=location)

        assert fake_account in ddl, (
            "Account ID passed as argument must appear in the LOCATION clause of DDL"
        )

    def test_build_hive_ddl_helper(self):
        """_build_hive_ddl returns CREATE DDL, MSCK DDL, and the correct database name."""
        fake_account = "999988887777"
        bucket = f"adp-staging-foundation-lake-{fake_account}-us-east-1"
        create_ddl, msck_ddl, database = pp._build_hive_ddl("tire_health", "staging", bucket)

        assert database == "adp_staging_tire_health"
        assert "CREATE EXTERNAL TABLE" in create_ddl
        assert "adp_staging_tire_health" in create_ddl
        assert "`tire_health`" in create_ddl
        assert "STORED AS PARQUET" in create_ddl
        assert fake_account in create_ddl  # account id in LOCATION, never hardcoded
        assert "ICEBERG" not in create_ddl
        # tire_health has partitions, so MSCK must be present
        assert "MSCK REPAIR TABLE" in msck_ddl

    def test_build_hive_ddl_service_records(self):
        """_build_hive_ddl works for service_records."""
        fake_account = "123456789012"
        bucket = f"adp-staging-foundation-lake-{fake_account}-us-east-1"
        create_ddl, msck_ddl, database = pp._build_hive_ddl("service_records", "staging", bucket)

        assert database == "adp_staging_service_records"
        assert "EXTERNAL TABLE" in create_ddl
        assert "STORED AS PARQUET" in create_ddl
        assert "service_month" in create_ddl  # partition key
        assert "ICEBERG" not in create_ddl
        assert "MSCK REPAIR TABLE" in msck_ddl


# ---------------------------------------------------------------------------
# Partition registration — MSCK REPAIR TABLE
# ---------------------------------------------------------------------------


class TestPartitionRegistration:
    """Creating a Hive-partitioned table does not discover partitions.
    Without MSCK REPAIR TABLE the table exists but returns zero rows.
    The DDL output and dry-run must include the MSCK statement.
    """

    def test_msck_repair_statement_format(self):
        """MSCK REPAIR TABLE must reference the correct database and table."""
        stmt = pp._msck_repair_statement("adp_staging_tire_health", "tire_health")
        assert "MSCK REPAIR TABLE" in stmt
        assert "`adp_staging_tire_health`" in stmt
        assert "`tire_health`" in stmt

    def test_msck_repair_statement_format_service_records(self):
        stmt = pp._msck_repair_statement("adp_staging_service_records", "service_records")
        assert "MSCK REPAIR TABLE" in stmt
        assert "`adp_staging_service_records`" in stmt
        assert "`service_records`" in stmt

    def test_build_hive_ddl_includes_msck_for_partitioned_table(self):
        """Products with partition_keys must produce a non-empty msck_ddl."""
        bucket = "adp-staging-foundation-lake-123456789012-us-east-1"
        _, msck_ddl, _ = pp._build_hive_ddl("tire_health", "staging", bucket)
        assert msck_ddl, (
            "tire_health has partition_keys — msck_ddl must be non-empty"
        )
        assert "MSCK REPAIR TABLE" in msck_ddl

    def test_dry_run_output_contains_msck(self, capsys, tmp_path):
        """In dry-run mode the printed output must include MSCK REPAIR TABLE
        so an operator can see both steps before applying.
        """
        product_dir = tmp_path / "tire_health" / "tire_health"
        product_dir.mkdir(parents=True)
        (product_dir / "dummy.parquet").write_bytes(b"")

        with patch.object(pp, "_local_product_dir", return_value=tmp_path / "tire_health"):
            with patch.object(pp, "_resolve_account_id", return_value="123456789012"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                    pp.publish_product(
                        "tire_health",
                        "staging",
                        apply=False,
                        allow_prod=False,
                    )

        captured = capsys.readouterr()
        assert "MSCK REPAIR TABLE" in captured.out, (
            "Dry-run output must include MSCK REPAIR TABLE so an operator "
            "can review partition registration before applying"
        )

    def test_dry_run_output_contains_external_table(self, capsys, tmp_path):
        """A NON-migrated product still emits a plain Hive external table.

        This is the original form of this test, re-pointed from
        ``service_records`` to ``tire_health`` by Group 3. The invariant it
        guards is unchanged and still load-bearing for the 7 products this
        spec does not migrate: registering an Iceberg table directly over
        plain-parquet files yields a table that returns zero rows, so
        ``ICEBERG`` must not appear anywhere in their DDL.

        ``tire_health`` is the right control: it is partitioned
        (``event_date``), it *declares* ``bucketing: {vin: 16}``, and it is
        excluded from ``_ICEBERG_MIGRATED_PRODUCTS`` — so it also proves the
        allowlist, not the bucketing declaration, is what gates conversion.
        """
        product_dir = tmp_path / "tire_health" / "tire_health"
        product_dir.mkdir(parents=True)
        (product_dir / "dummy.parquet").write_bytes(b"")

        with patch.object(pp, "_local_product_dir", return_value=tmp_path / "tire_health"):
            with patch.object(pp, "_resolve_account_id", return_value="123456789012"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                    pp.publish_product(
                        "tire_health",
                        "staging",
                        apply=False,
                        allow_prod=False,
                    )

        captured = capsys.readouterr()
        assert "EXTERNAL TABLE" in captured.out
        assert "STORED AS PARQUET" in captured.out
        assert "ICEBERG" not in captured.out, (
            "Dry-run output must not reference ICEBERG for a non-migrated "
            "product — that would register a table over plain-parquet files "
            "that returns zero rows"
        )

    def test_dry_run_output_for_migrated_product_shows_both_layers(
        self, capsys, tmp_path
    ):
        """A migrated product emits BOTH layers, at DIFFERENT prefixes.

        Group 3 gave ``service_records`` a ``bucketing`` declaration, making it
        an Iceberg conversion target. Its dry-run output therefore now contains
        ``ICEBERG``, which the sibling test above forbids for non-migrated
        products.

        That is not the old zero-rows defect resurfacing, and this test exists
        to pin the reason it is not: under D4 the Iceberg table is NOT
        registered over the raw parquet. The raw layer stays a Hive external
        table at ``curated/`` (registered as ``<table>_raw``) and the derived
        Iceberg table lives at a separate ``iceberg/`` prefix, populated by an
        explicit ``INSERT INTO … SELECT``. The two-layer split IS the
        protection the old assertion was reaching for, so it is asserted here
        directly rather than inferred from the absence of a word.
        """
        product_dir = tmp_path / "service_records" / "service_records"
        product_dir.mkdir(parents=True)
        (product_dir / "dummy.parquet").write_bytes(b"")

        with patch.object(pp, "_local_product_dir", return_value=tmp_path / "service_records"):
            with patch.object(pp, "_resolve_account_id", return_value="123456789012"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                    pp.publish_product(
                        "service_records",
                        "staging",
                        apply=False,
                        allow_prod=False,
                    )

        out = capsys.readouterr().out

        # The raw Hive layer survives, under the _raw name.
        assert "EXTERNAL TABLE" in out
        assert "STORED AS PARQUET" in out
        assert "service_records_raw" in out

        # The derived Iceberg layer is present and carries the bucket transform.
        assert "ICEBERG" in out
        assert "bucket(16, vin)" in out

        # The load-bearing property: the two layers are at DIFFERENT prefixes.
        # An Iceberg table rooted at the vintage-governed curated/ prefix is a
        # data-loss bug, because Athena treats Iceberg tables as MANAGED.
        assert "/iceberg/" in out, "derived Iceberg layer must live under iceberg/"
        assert "/curated/" in out, "raw layer must remain under curated/"
        iceberg_locs = [
            ln for ln in out.splitlines()
            if "LOCATION" in ln and "/iceberg/" in ln
        ]
        assert iceberg_locs, "expected an Iceberg LOCATION line"
        for ln in iceberg_locs:
            assert "/curated/" not in ln, (
                f"Iceberg LOCATION must not sit under curated/: {ln!r}"
            )

    def test_dry_run_output_contains_no_bucket_transform(self, capsys, tmp_path):
        """Dry-run output must not contain bucket() (Iceberg hidden partitioning)."""
        product_dir = tmp_path / "tire_health" / "tire_health"
        product_dir.mkdir(parents=True)
        (product_dir / "dummy.parquet").write_bytes(b"")

        with patch.object(pp, "_local_product_dir", return_value=tmp_path / "tire_health"):
            with patch.object(pp, "_resolve_account_id", return_value="123456789012"):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                    pp.publish_product(
                        "tire_health",
                        "staging",
                        apply=False,
                        allow_prod=False,
                    )

        captured = capsys.readouterr()
        assert "bucket(" not in captured.out, (
            "Dry-run output must not contain bucket() — Iceberg hidden partitioning "
            "has no Hive equivalent"
        )


# ---------------------------------------------------------------------------
# S3 sync command construction
# ---------------------------------------------------------------------------


class TestS3SyncCommand:
    """aws s3 sync must never include --delete."""

    def test_sync_command_has_no_delete_flag(self):
        cmd = pp._build_s3_sync_cmd(
            "/local/path", "s3://bucket/prefix/", dry_run=False
        )
        assert "--delete" not in cmd, (
            "S3 sync command must never include --delete (spec § D4)"
        )

    def test_sync_command_dry_run_includes_dryrun_flag(self):
        cmd = pp._build_s3_sync_cmd(
            "/local/path", "s3://bucket/prefix/", dry_run=True
        )
        assert "--dryrun" in cmd, (
            "Dry-run S3 sync must include --dryrun flag"
        )

    def test_sync_command_apply_excludes_dryrun_flag(self):
        cmd = pp._build_s3_sync_cmd(
            "/local/path", "s3://bucket/prefix/", dry_run=False
        )
        assert "--dryrun" not in cmd

    def test_sync_command_structure(self):
        cmd = pp._build_s3_sync_cmd(
            "/curated/tire_health/tire_health",
            "s3://adp-staging-foundation-lake-123456789012-us-east-1/curated/tire_health/tire_health/",
            dry_run=True,
        )
        assert cmd[0] == "aws"
        assert "s3" in cmd
        assert "sync" in cmd
        assert "--region" in cmd
        assert "us-east-1" in cmd


# ---------------------------------------------------------------------------
# Prod guard
# ---------------------------------------------------------------------------


class TestProdGuard:
    """prod stage must be refused unless both --apply and --allow-prod are passed."""

    def test_prod_without_allow_prod_exits_nonzero(self, capsys):
        """Calling publish_product with stage=prod but allow_prod=False must sys.exit(1)."""
        with patch.object(pp, "_resolve_account_id", return_value="123456789012"):
            with pytest.raises(SystemExit) as exc_info:
                pp.publish_product(
                    "tire_health",
                    "prod",
                    apply=True,
                    allow_prod=False,
                )
        assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "allow-prod" in captured.err.lower() or "allow_prod" in captured.err.lower(), (
            "Error message should mention the --allow-prod flag"
        )

    def test_prod_with_allow_prod_false_error_message_mentions_prod(self, capsys):
        """Error message must explain the prod gate clearly."""
        with patch.object(pp, "_resolve_account_id", return_value="123456789012"):
            with pytest.raises(SystemExit):
                pp.publish_product(
                    "tire_health",
                    "prod",
                    apply=False,
                    allow_prod=False,
                )
        captured = capsys.readouterr()
        assert "prod" in captured.err.lower()

    def test_staging_does_not_require_allow_prod(self, capsys, tmp_path):
        """staging must not require --allow-prod — it would block the normal workflow."""
        product_dir = tmp_path / "tire_health" / "tire_health"
        product_dir.mkdir(parents=True)
        (product_dir / "dummy.parquet").write_bytes(b"")

        with patch.object(pp, "_local_product_dir", return_value=tmp_path / "tire_health"):
            with patch.object(pp, "_resolve_account_id", return_value="123456789012"):
                with patch.object(pp, "_build_s3_sync_cmd") as mock_sync_cmd:
                    mock_sync_cmd.return_value = ["echo", "dry-run-ok"]
                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                        try:
                            pp.publish_product(
                                "tire_health",
                                "staging",
                                apply=False,
                                allow_prod=False,
                            )
                        except SystemExit as e:
                            pytest.fail(
                                f"staging publish_product unexpectedly called sys.exit({e.code})"
                            )


# ---------------------------------------------------------------------------
# Missing STAGE guard (via CLI arg parsing)
# ---------------------------------------------------------------------------


class TestArgParsing:
    """The CLI must reject calls that are missing required arguments."""

    def test_missing_stage_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc_info:
            pp._parse_args(["--product", "tire_health"])
        assert exc_info.value.code != 0

    def test_missing_product_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc_info:
            pp._parse_args(["--stage", "staging"])
        assert exc_info.value.code != 0

    def test_invalid_stage_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc_info:
            pp._parse_args(["--product", "tire_health", "--stage", "dev"])
        assert exc_info.value.code != 0

    def test_valid_staging_args_parse(self):
        args = pp._parse_args(["--product", "tire_health", "--stage", "staging"])
        assert args.product == "tire_health"
        assert args.stage == "staging"
        assert args.apply is False
        assert args.allow_prod is False

    def test_apply_flag_sets_apply_true(self):
        args = pp._parse_args(["--product", "service_records", "--stage", "staging", "--apply"])
        assert args.apply is True

    def test_allow_prod_flag_sets_allow_prod_true(self):
        args = pp._parse_args(
            ["--product", "tire_health", "--stage", "prod", "--apply", "--allow-prod"]
        )
        assert args.allow_prod is True


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    """Test pure helper functions that don't require AWS calls."""

    def test_lake_bucket_name(self):
        name = pp._lake_bucket_name("staging", "123456789012")
        assert name == "adp-staging-foundation-lake-123456789012-us-east-1"
        assert "123456789012" in name

    def test_lake_bucket_name_prod(self):
        name = pp._lake_bucket_name("prod", "123456789012")
        assert name == "adp-prod-foundation-lake-123456789012-us-east-1"

    def test_lake_bucket_name_no_hardcoded_account(self):
        name_a = pp._lake_bucket_name("staging", "111111111111")
        name_b = pp._lake_bucket_name("staging", "222222222222")
        assert "111111111111" in name_a
        assert "222222222222" in name_b
        assert "111111111111" not in name_b
        assert "222222222222" not in name_a

    def test_s3_prefix_trailing_slash(self):
        prefix = pp._s3_prefix("my-bucket", "tire_health", "tire_health")
        assert prefix.endswith("/"), "S3 prefix must end with /"

    def test_s3_prefix_structure(self):
        prefix = pp._s3_prefix(
            "adp-staging-foundation-lake-123456789012-us-east-1",
            "tire_health", "tire_health"
        )
        assert prefix == (
            "s3://adp-staging-foundation-lake-123456789012-us-east-1"
            "/curated/tire_health/tire_health/"
        )

    def test_glue_database_name_staging(self):
        db = pp._glue_database_name("staging", "tire_health")
        assert db == "adp_staging_tire_health"

    def test_glue_database_name_prod(self):
        db = pp._glue_database_name("prod", "service_records")
        assert db == "adp_prod_service_records"

    def test_hive_column_fragment_string(self):
        col = sl.Column(name="vin", type="string")
        frag = pp._hive_column_fragment(col)
        assert frag == "  `vin` string"

    def test_hive_column_fragment_decimal(self):
        col = sl.Column(
            name="total_cost_usd", type="decimal",
            decimal_precision=12, decimal_scale=2
        )
        frag = pp._hive_column_fragment(col)
        assert frag == "  `total_cost_usd` decimal(12,2)"

    def test_hive_column_fragment_array(self):
        col = sl.Column(name="dtc_codes", type="array<string>")
        frag = pp._hive_column_fragment(col)
        assert frag == "  `dtc_codes` array<string>"

    def test_hive_parquet_ddl_location_requires_trailing_slash(self):
        """_hive_parquet_ddl must raise ValueError if location lacks trailing /."""
        schema = sl.load_schema("tire_health", kind="product")
        table = schema.first_table()
        with pytest.raises(ValueError, match="trailing"):
            pp._hive_parquet_ddl(
                table,
                database="adp_staging_tire_health",
                location="s3://bucket/no-trailing-slash",
            )


class TestAthenaWorkgroupStageBoundary:
    """The Athena workgroup must be stage-derived, never a fixed constant.

    Regression guard for issues/2026-08-31-adp-publish-product-cross-stage-workgroup:
    `_ATHENA_WORKGROUP` was hardcoded to "cvx-staging-analytics" and used for
    every --stage, so prod catalog mutations executed through a staging,
    cross-project workgroup. Seven prod tables were registered that way before
    it was caught.

    The boundary is asserted behaviourally (what the publish path actually
    passes to Athena), not just on the helper — a helper can be correct while
    a call site still references a stale constant, which is precisely the shape
    of the original defect.
    """

    def test_workgroup_is_stage_derived(self):
        assert pp._athena_workgroup("staging") == "cvx-staging-analytics"
        assert pp._athena_workgroup("prod") == "cvx-prod-analytics"

    def test_prod_workgroup_never_contains_staging(self):
        """The core invariant. A prod publish must not touch a staging workgroup."""
        assert "staging" not in pp._athena_workgroup("prod")

    def test_workgroups_differ_by_stage(self):
        """Positive control: the two stages must not collapse to one value."""
        assert pp._athena_workgroup("prod") != pp._athena_workgroup("staging")

    def test_module_exposes_no_fixed_workgroup_constant(self):
        """Guard against the fix being reverted to a constant.

        A bare `_ATHENA_WORKGROUP` string attribute is how the defect looked;
        if one reappears, fail loudly rather than let call sites drift back.
        """
        assert not hasattr(pp, "_ATHENA_WORKGROUP"), (
            "publish_product must not expose a fixed _ATHENA_WORKGROUP constant; "
            "the workgroup is stage-derived via _athena_workgroup(stage)."
        )

    @pytest.mark.parametrize("stage", ["staging", "prod"])
    def test_publish_passes_stage_correct_workgroup_to_athena(self, stage, tmp_path):
        """End-to-end: whatever `publish_product` hands Athena must match the stage.

        Exercises the real publish path with AWS calls mocked, so a call site
        still holding a stale constant would fail here even if the helper is
        correct — which is the shape the original defect had.
        """
        product_dir = tmp_path / "tire_health" / "tire_health"
        product_dir.mkdir(parents=True)
        (product_dir / "dummy.parquet").write_bytes(b"")

        seen: list[str] = []

        def _capture(ddl, database, workgroup):
            seen.append(workgroup)

        with patch.object(pp, "_local_product_dir", return_value=tmp_path / "tire_health"), \
             patch.object(pp, "_resolve_account_id", return_value="123456789012"), \
             patch.object(pp, "_run_athena_query", side_effect=_capture), \
             patch.object(pp, "_build_s3_sync_cmd", return_value=["echo", "sync-ok"]), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            pp.publish_product(
                "tire_health",
                stage,
                apply=True,
                allow_prod=True,
            )

        assert seen, "publish_product() did not reach the Athena DDL step"
        expected = f"cvx-{stage}-analytics"
        assert set(seen) == {expected}, (
            f"stage={stage} must use {expected}, got {sorted(set(seen))}"
        )
        if stage == "prod":
            assert all("staging" not in wg for wg in seen), (
                "a prod publish must never execute DDL through a staging workgroup"
            )
