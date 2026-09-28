"""Glue / Firehose schema declarations for the CMS→ADP ingest module.

The Firehose ``DataFormatConversionConfiguration`` reads a Glue table
to drive the JSON-to-parquet conversion. That Glue table needs to be
declared in CDK *and* match the actual DDB-Stream payload shape we
expect Firehose to receive.

This module is the single source of truth for that schema. It is
consumed by:

* ``platform-foundation/stacks/optional/cms_ingest_stack.py`` — at CDK
  synth time, to build the ``glue.CfnTable`` used as the Firehose
  schema target.
* :mod:`glue_merge_job` — at runtime, to validate the staged parquet
  before MERGEing into the Iceberg replica.

Per spec Constraint #14 (single account v1) the schema is declared
once per source table; cross-account future work is documented but
deferred.

The schema deliberately mirrors the DDB-Stream record envelope, NOT
the CMS application-level row shape:

* Top level columns are the stream-record fields
  (``eventID``, ``eventName``, ``eventVersion``, ``eventSource``,
  ``awsRegion``, ``approximate_creation_datetime``,
  ``sequence_number``, ``size_bytes``).
* The DDB image payload lives in ``new_image`` / ``old_image`` as JSON
  strings (raw DynamoDB AttributeValue maps, e.g.
  ``{"vin": {"S": "MRD..."}, "battery_pct": {"N": "82"}}``). Storing
  them as ``string`` keeps the Firehose schema small and stable
  across CMS schema evolution; the MERGE job parses these into
  per-table strongly-typed Iceberg columns.

Storing the DDB image as opaque JSON, rather than declaring every
attribute as a top-level Glue column, is intentional. It means:

* Firehose does NOT need a schema migration when CMS adds a new
  attribute to its DDB table.
* The MERGE job (which IS aware of the per-table Iceberg shape) is
  the single place where the JSON→typed projection lives — easy to
  test, easy to evolve.

Pitfalls
--------
* ``Compression: ZSTD`` on parquet output requires the Firehose role
  to have ``glue:GetTable`` and ``glue:GetTableVersion``. The CDK
  stack already grants both.
* Glue table column types here MUST be the Hive types Firehose
  understands (``string``, ``bigint``, ``timestamp``), NOT the
  Iceberg types used in ``schema_loader.py``. The MERGE job converts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlueColumn:
    """A single column in the Firehose schema-target Glue table."""

    name: str
    type_: str  # Hive type string consumed by Glue / Firehose
    comment: str

    def to_cfn(self) -> dict:
        """Return the dict shape ``glue.CfnTable`` expects for a column."""
        return {"name": self.name, "type": self.type_, "comment": self.comment}


#: Stage-prefixed parquet location relative to the foundation lake bucket.
#:
#: The ``{stage}`` placeholder is filled by
#: :func:`firehose_s3_prefix_template` so staging and prod can route
#: into separate S3 trees on the same lake bucket.
STAGED_PREFIX_TEMPLATE = "cms-ingest/{table}/dt=!{{timestamp:yyyy-MM-dd}}/"
ERROR_PREFIX_TEMPLATE = (
    "cms-ingest/_errors/{table}/!{{firehose:error-output-type}}/"
    "dt=!{{timestamp:yyyy-MM-dd}}/"
)

#: Firehose buffering: 60 s OR 64 MiB whichever fires first. Per
#: ``docs/tech.md`` "Kinesis Firehose — dynamic partitioning to S3
#: parquet": 60 s = micro-batch, NOT streaming, so we stay inside spec
#: Constraint #9 ("no streaming integration in v1").
BUFFERING_INTERVAL_SECONDS = 60
BUFFERING_SIZE_MB = 64


def firehose_s3_prefix(table_logical_name: str) -> str:
    """Return the parquet prefix template for a CMS source table.

    Example
    -------
    >>> firehose_s3_prefix("vehicle_state")
    'cms-ingest/vehicle_state/dt=!{timestamp:yyyy-MM-dd}/'

    The ``!{timestamp:yyyy-MM-dd}`` placeholder is resolved by
    Firehose at delivery time (NOT by Python str.format).
    """
    return STAGED_PREFIX_TEMPLATE.format(table=table_logical_name)


def firehose_error_prefix(table_logical_name: str) -> str:
    """Return the error-output prefix template for a CMS source table."""
    return ERROR_PREFIX_TEMPLATE.format(table=table_logical_name)


#: Glue columns Firehose will write as parquet for every CMS source
#: table. The schema is intentionally generic (DDB-Stream record shape)
#: so a single Firehose schema-target works across all CMS source
#: tables. Per-table typed projections happen in the MERGE job.
STREAM_RECORD_COLUMNS: tuple[GlueColumn, ...] = (
    GlueColumn(
        "event_id",
        "string",
        "DynamoDB Stream event ID (idempotency key for the MERGE job).",
    ),
    GlueColumn(
        "event_name",
        "string",
        "INSERT | MODIFY | REMOVE — drives the MERGE branch.",
    ),
    GlueColumn(
        "event_version",
        "string",
        "DDB Stream record version (currently '1.1').",
    ),
    GlueColumn(
        "event_source",
        "string",
        "Always 'aws:dynamodb' for DDB Streams; here for sanity checks.",
    ),
    GlueColumn(
        "aws_region",
        "string",
        "Source DDB table region (must equal the foundation region).",
    ),
    GlueColumn(
        "approximate_creation_datetime",
        "timestamp",
        "DDB-side write timestamp (microsecond precision).",
    ),
    GlueColumn(
        "ingest_time",
        "timestamp",
        "ADP-side ingestion timestamp (set by the Lambda transformer).",
    ),
    GlueColumn(
        "sequence_number",
        "string",
        "DDB Stream sequence number (lexicographically orderable).",
    ),
    GlueColumn(
        "size_bytes",
        "bigint",
        "Size of the JSON-encoded record on the wire.",
    ),
    GlueColumn(
        "table_name",
        "string",
        (
            "Logical CMS source table name (e.g. 'vehicle_state'). "
            "Used by Firehose dynamic partitioning to route records "
            "into the right per-table S3 prefix."
        ),
    ),
    GlueColumn(
        "keys",
        "string",
        (
            "DDB primary-key attributes for the row, JSON-encoded "
            "AttributeValue map. Stable across every event_name."
        ),
    ),
    GlueColumn(
        "new_image",
        "string",
        (
            "Post-write DDB image, JSON-encoded AttributeValue map. "
            "NULL on REMOVE events. Parsed by the MERGE job."
        ),
    ),
    GlueColumn(
        "old_image",
        "string",
        (
            "Pre-write DDB image, JSON-encoded AttributeValue map. "
            "NULL on INSERT events. Parsed by the MERGE job to drive "
            "Iceberg deletes."
        ),
    ),
)


def stream_record_columns_cfn() -> list[dict]:
    """Return :data:`STREAM_RECORD_COLUMNS` in the dict shape ``glue.CfnTable`` expects."""
    return [col.to_cfn() for col in STREAM_RECORD_COLUMNS]


#: Glue ``StorageDescriptor`` used by Firehose's parquet conversion.
#:
#: ``ParquetSerDe`` + ``ParquetInputFormat`` + ``ParquetOutputFormat``
#: is the canonical triple for a parquet-backed Glue table. The
#: ``compression=zstd`` SerDe parameter must be set so that the
#: parquet writer Firehose embeds emits ZSTD-compressed page data
#: (matching the lake's general compression default).
PARQUET_INPUT_FORMAT = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
PARQUET_OUTPUT_FORMAT = (
    "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
)
PARQUET_SERDE = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"


def storage_descriptor_cfn(s3_location: str) -> dict:
    """Return a ``StorageDescriptor`` dict suitable for ``glue.CfnTable``.

    Parameters
    ----------
    s3_location:
        Fully-qualified ``s3://bucket/prefix/`` path that the Firehose
        stream writes parquet into. Per the prefix template above this
        is the *table-level* prefix without the ``dt=`` partition
        segment — Firehose appends the partition at write time.
    """
    return {
        "columns": stream_record_columns_cfn(),
        "location": s3_location,
        "input_format": PARQUET_INPUT_FORMAT,
        "output_format": PARQUET_OUTPUT_FORMAT,
        "serde_info": {
            "serialization_library": PARQUET_SERDE,
            "parameters": {
                "serialization.format": "1",
                "compression": "zstd",
            },
        },
        "stored_as_sub_directories": True,
        "compressed": True,
        "parameters": {
            "classification": "parquet",
            "compressionType": "zstd",
            "typeOfData": "file",
        },
    }


def partition_keys_cfn() -> list[dict]:
    """Hive-style partition columns Firehose materializes via dynamic partitioning.

    The single ``dt`` partition matches the prefix template
    (``cms-ingest/<table>/dt=YYYY-MM-DD/``). The MERGE job uses ``dt``
    to scope its source-window read so it never re-MERGEs already-
    consumed data.
    """
    return [
        {
            "name": "dt",
            "type": "date",
            "comment": "Hive-style date partition driven by Firehose dynamic partitioning.",
        }
    ]
