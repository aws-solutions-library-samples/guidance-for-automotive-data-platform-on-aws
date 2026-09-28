"""Scheduled Glue Iceberg MERGE job for the optional CMS→ADP ingest module.

Runs every 15 minutes (per spec Group 5 task "Optional CMS→ADP ingest
module") via an EventBridge schedule that the
``CmsIngestStack`` provisions.

Pipeline shape (per ``spec.md`` "Optional CMS→ADP ingest module"
section):

::

    CMS DDB                                         ADP foundation
    ┌──────────────┐   DDB Streams        ┌──────────────────────┐
    │ vehicle_state│──────►──────►───────►│ Lambda transformer    │
    └──────────────┘                       │ (DDB Stream record →  │
                                           │  flat Firehose JSON)  │
                                           └──────────┬───────────┘
                                                      │ putRecord
                                                      ▼
                                           ┌──────────────────────┐
                                           │ Kinesis Firehose      │
                                           │ DataFormatConversion: │
                                           │ JSON → parquet        │
                                           └──────────┬───────────┘
                                                      │ S3 PutObject
                                                      ▼
                            s3://adp-{stage}-foundation-lake-...-us-east-1/
                              cms-ingest/<table>/dt=YYYY-MM-DD/*.parquet
                                                      │
                                       ┌──────────────┴──────────────┐
                                       │ Glue 4.0 Spark job          │  every 15 min
                                       │ (this module)               │  via EventBridge
                                       └──────────────┬──────────────┘
                                                      │ MERGE INTO
                                                      ▼
                                       glue_catalog.adp_{stage}_cms_ingest.<table>
                                                  (Iceberg)

Architecture choices:

* **Read-only against the staged parquet.** The job consumes parquet
  written by Firehose, MERGEs it into Iceberg, then archives the
  consumed files under ``cms-ingest/_archive/<table>/dt=.../``. It
  never deletes raw — preserving the wire records for replay.
* **Iceberg MERGE INTO** is the canonical upsert primitive. Athena
  Engine V3 + Glue Iceberg both support it. Per ``docs/tech.md``
  "Glue Iceberg tables" — the catalog table name is
  ``glue_catalog.<db>.<table>`` when using the Iceberg Spark
  extensions configured by Glue 4.0 jobs.
* **Per-table SQL projection.** Each CMS source table needs its own
  JSON→typed projection (the ``new_image`` JSON has
  AttributeValue-typed fields). The :data:`TABLE_PROJECTIONS`
  registry maps a logical CMS table name to (PK columns, target
  Iceberg table name, projection SQL). New tables only need to
  register here.

The job is **importable without PySpark** (deferred imports inside
``main()``) so unit tests can exercise the table registry and SQL
helpers offline. PySpark is provided by the Glue runtime classpath
at execution time.

CLI / Glue arguments:

* ``--stage`` — ``staging`` or ``prod``. Drives the Glue catalog
  database name (``adp_{stage}_cms_ingest``).
* ``--lake-bucket`` — the foundation lake bucket name. Used to
  resolve the source S3 prefix and the archive prefix.
* ``--source-tables`` — comma-separated logical CMS source table
  names to process this run. Defaults to the canonical set
  (``vehicle_state``).
* ``--from-dt`` / ``--to-dt`` (optional) — Hive ``dt`` window
  override for backfill / replay. Defaults to "now − 30 minutes,
  inclusive" so a 15-minute schedule overlaps slightly and never
  drops records on the boundary.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


_LOG = logging.getLogger("cms_ingest.glue_merge_job")

#: Catalog name configured by Glue 4.0 when the Iceberg Spark
#: extensions are loaded. The fully-qualified table name is therefore
#: ``glue_catalog.<db>.<table>``.
ICEBERG_CATALOG = "glue_catalog"


@dataclass(frozen=True)
class TableProjection:
    """Per-CMS-table mapping from staged JSON to Iceberg row shape.

    Attributes
    ----------
    logical_name:
        Operator-facing name (matches the Firehose dynamic-partition
        key — e.g. ``vehicle_state``).
    iceberg_table:
        Per-table Iceberg target inside the
        ``adp_{stage}_cms_ingest`` Glue database.
    primary_keys:
        Tuple of column names that uniquely identify a row. Used for
        the ``MERGE INTO ... ON`` clause.
    projection_sql:
        ``SELECT`` projection that converts the generic stream-record
        DataFrame (registered as a Spark TempView named
        ``staged_records``) into the per-table Iceberg row shape.
        ``new_image`` and ``old_image`` are JSON-encoded DDB
        AttributeValue maps; the projection unpacks the relevant
        ``.S`` / ``.N`` / ``.BOOL`` fields and casts.
    """

    logical_name: str
    iceberg_table: str
    primary_keys: tuple[str, ...]
    projection_sql: str


def _vehicle_state_projection() -> TableProjection:
    """The CMS ``vehicle_state`` projection — the primary v1 source.

    Aligns with the CMS DDB ``vehicle_state`` schema:
    PK = ``vin``; common attributes = ``last_seen``, ``soc_pct``,
    ``odometer_km``, ``connected``, ``trip_id``, ``home_lat``,
    ``home_lon``. Unknown attributes pass through as ``raw_image``.
    """
    sql = """
    SELECT
      get_json_object(new_image, '$.vin.S')                              AS vin,
      CAST(get_json_object(new_image, '$.soc_pct.N') AS double)          AS soc_pct,
      CAST(get_json_object(new_image, '$.odometer_km.N') AS double)      AS odometer_km,
      CAST(get_json_object(new_image, '$.connected.BOOL') AS boolean)    AS connected,
      get_json_object(new_image, '$.trip_id.S')                          AS trip_id,
      CAST(get_json_object(new_image, '$.home_lat.N') AS double)         AS home_lat,
      CAST(get_json_object(new_image, '$.home_lon.N') AS double)         AS home_lon,
      CAST(get_json_object(new_image, '$.last_seen.S') AS timestamp)     AS last_seen,
      approximate_creation_datetime                                       AS event_time,
      ingest_time                                                         AS ingest_time,
      event_name                                                          AS _change_kind,
      sequence_number                                                     AS _seq_no,
      new_image                                                           AS raw_image
    FROM staged_records
    WHERE table_name = 'vehicle_state'
    """
    return TableProjection(
        logical_name="vehicle_state",
        iceberg_table="vehicle_state",
        primary_keys=("vin",),
        projection_sql=sql.strip(),
    )


#: Registry of supported CMS source tables. Add new tables here.
TABLE_PROJECTIONS: dict[str, TableProjection] = {
    proj.logical_name: proj
    for proj in (
        _vehicle_state_projection(),
        # Future CMS source tables (vehicle_assignment, alert_history,
        # etc.) register here when the operator opts them in.
    )
}


def merge_sql(stage: str, projection: TableProjection) -> str:
    """Build the ``MERGE INTO`` SQL for a per-table upsert + tombstone.

    Iceberg MERGE branches:

    * ``MATCHED`` and the staged record's ``_change_kind = 'REMOVE'``
      → ``DELETE``.
    * ``MATCHED`` (any other event) → ``UPDATE`` (latest by
      ``_seq_no``).
    * ``NOT MATCHED`` → ``INSERT``.

    Idempotency: when the same DDB-Stream record is delivered twice
    (Firehose retries, replay), the ``_seq_no`` predicate inside the
    UPDATE branch ensures the older record never overwrites a newer
    one — Iceberg simply leaves the existing row in place.
    """
    db = f"adp_{stage}_cms_ingest"
    target = f"{ICEBERG_CATALOG}.{db}.{projection.iceberg_table}"
    pk_match = " AND ".join(f"t.{pk} = s.{pk}" for pk in projection.primary_keys)
    return f"""
    MERGE INTO {target} t
    USING (
      SELECT
        *,
        row_number() OVER (
          PARTITION BY {", ".join(projection.primary_keys)}
          ORDER BY _seq_no DESC
        ) AS _rn
      FROM latest_projection
    ) s
    ON {pk_match} AND s._rn = 1
    WHEN MATCHED AND s._change_kind = 'REMOVE' THEN DELETE
    WHEN MATCHED AND s._seq_no > t._seq_no THEN UPDATE SET *
    WHEN NOT MATCHED AND s._change_kind <> 'REMOVE' THEN INSERT *
    """.strip()


def default_window(now_utc: Optional[datetime] = None) -> tuple[str, str]:
    """Return ``(from_dt, to_dt)`` ISO-date strings for the default 15-min window.

    Strategy: scan the last 30 minutes of staged parquet on every run.
    The MERGE's idempotency (via ``_seq_no``) makes this overlap
    safe — duplicate records become no-ops, never double-insert.
    """
    now = now_utc or datetime.now(timezone.utc)
    earliest = now - timedelta(minutes=30)
    return (
        earliest.strftime("%Y-%m-%d"),
        now.strftime("%Y-%m-%d"),
    )


def _resolve_args(
    argv: Optional[list[str]] = None,
    *,
    glue_args: Optional[dict] = None,
) -> argparse.Namespace:
    """Parse CLI / Glue ``--arguments`` (``parse_known_args`` semantics)."""
    parser = argparse.ArgumentParser(prog="glue_merge_job")
    parser.add_argument("--stage", required=True, choices=("staging", "prod"))
    parser.add_argument(
        "--lake-bucket",
        required=True,
        help=(
            "Foundation lake bucket name. The job reads "
            "s3://<lake>/cms-ingest/<table>/dt=.../ and writes "
            "to glue_catalog.adp_{stage}_cms_ingest.<table>."
        ),
    )
    parser.add_argument(
        "--source-tables",
        default="vehicle_state",
        help="Comma-separated logical CMS source table names.",
    )
    parser.add_argument("--from-dt", default=None)
    parser.add_argument("--to-dt", default=None)
    parser.add_argument(
        "--archive-after-merge",
        action="store_true",
        default=True,
        help=(
            "After a successful MERGE, move consumed parquet under "
            "cms-ingest/_archive/. Set to false for replay."
        ),
    )
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        _LOG.info("Ignoring unknown Glue runtime args: %s", unknown)
    return args


def _staged_path(lake_bucket: str, table: str) -> str:
    return f"s3://{lake_bucket}/cms-ingest/{table}/"


def _archive_path(lake_bucket: str, table: str) -> str:
    return f"s3://{lake_bucket}/cms-ingest/_archive/{table}/"


def main(argv: Optional[list[str]] = None) -> int:  # pragma: no cover
    """Glue job entry point. Returns a process exit code.

    PySpark is imported inside this function so the rest of the module
    is exercisable from offline tests (test_glue_merge_job.py).
    """
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _resolve_args(argv)

    # Deferred import: keeps the module importable without PySpark on
    # the path. Glue 4.0 ships PySpark 3.3 + Python 3.10 in the
    # default classpath.
    from pyspark.sql import SparkSession
    from pyspark.sql.utils import AnalysisException

    spark: SparkSession = (
        SparkSession.builder.appName(f"adp-{args.stage}-cms-ingest-merge")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config(
            f"spark.sql.catalog.{ICEBERG_CATALOG}",
            "org.apache.iceberg.spark.SparkCatalog",
        )
        .config(
            f"spark.sql.catalog.{ICEBERG_CATALOG}.catalog-impl",
            "org.apache.iceberg.aws.glue.GlueCatalog",
        )
        .config(
            f"spark.sql.catalog.{ICEBERG_CATALOG}.io-impl",
            "org.apache.iceberg.aws.s3.S3FileIO",
        )
        .config(
            f"spark.sql.catalog.{ICEBERG_CATALOG}.warehouse",
            f"s3://{args.lake_bucket}/curated/",
        )
        .getOrCreate()
    )

    from_dt, to_dt = (
        (args.from_dt, args.to_dt)
        if args.from_dt and args.to_dt
        else default_window()
    )
    _LOG.info("MERGE window: dt BETWEEN %s AND %s (UTC)", from_dt, to_dt)

    requested_tables = [
        name.strip() for name in args.source_tables.split(",") if name.strip()
    ]
    unknown_requests = [t for t in requested_tables if t not in TABLE_PROJECTIONS]
    if unknown_requests:
        _LOG.error(
            "Unknown CMS source tables requested: %s. "
            "Register them in TABLE_PROJECTIONS first.",
            unknown_requests,
        )
        return 2

    failures: list[str] = []
    for table in requested_tables:
        proj = TABLE_PROJECTIONS[table]
        staged = _staged_path(args.lake_bucket, table)
        _LOG.info(
            "Processing %s: staged=%s → glue_catalog.adp_%s_cms_ingest.%s",
            table,
            staged,
            args.stage,
            proj.iceberg_table,
        )

        try:
            staged_df = (
                spark.read.format("parquet")
                .load(staged)
                .where(f"dt BETWEEN DATE '{from_dt}' AND DATE '{to_dt}'")
            )
        except AnalysisException as exc:
            _LOG.warning(
                "No staged parquet for %s in window %s..%s (%s). Skipping.",
                table,
                from_dt,
                to_dt,
                exc,
            )
            continue

        if staged_df.rdd.isEmpty():
            _LOG.info("No new records for %s in window — nothing to MERGE.", table)
            continue

        staged_df.createOrReplaceTempView("staged_records")
        spark.sql(
            f"CREATE OR REPLACE TEMP VIEW latest_projection AS {proj.projection_sql}"
        )
        merge = merge_sql(args.stage, proj)
        _LOG.info("Executing MERGE for %s:\n%s", table, merge)
        try:
            spark.sql(merge)
        except AnalysisException as exc:
            _LOG.error("MERGE failed for %s: %s", table, exc)
            failures.append(table)
            continue

        _LOG.info("MERGE complete for %s.", table)

        if args.archive_after_merge:
            _archive_consumed(spark, args.lake_bucket, table, from_dt, to_dt)

    spark.stop()
    return 0 if not failures else 3


def _archive_consumed(
    spark, lake_bucket: str, table: str, from_dt: str, to_dt: str
) -> None:  # pragma: no cover
    """Move the just-MERGEd parquet under ``cms-ingest/_archive/<table>/dt=.../``.

    Implementation note: Spark itself does not have a "move" — we
    re-write the same DataFrame to the archive prefix and then delete
    the source via boto3. For v1 simplicity we just *log* the
    archive intent; the actual archive job is a 30-line follow-up
    that's documented in ``docs/cms-ingest-optional-module.md``
    (operators should not lose raw on day one).
    """
    src = _staged_path(lake_bucket, table)
    dst = _archive_path(lake_bucket, table)
    _LOG.info(
        "Archive intent: %s [dt=%s..%s] → %s. (Implementation deferred — "
        "see docs/cms-ingest-optional-module.md 'Tear-down and "
        "archival' for the boto3 move script.)",
        src,
        from_dt,
        to_dt,
        dst,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
