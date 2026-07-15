"""Optional CMS→ADP ingest runtime helpers.

This package contains the *runtime* code paths that pair with the
``platform-foundation/stacks/optional/cms_ingest_stack.py`` CDK stack:

* :mod:`enable_streams` — pre-deploy operator helper that asserts (or
  enables) DynamoDB Streams on the CMS source table.
* :mod:`firehose_schema` — Glue table column declarations consumed by
  the Firehose ``DataFormatConversionConfiguration`` so JSON DDB
  records land on S3 as parquet that downstream Athena/Spark can read
  without a schema crawl.
* :mod:`glue_merge_job` — PySpark Glue 4.0 job that runs every 15
  minutes, MERGEs the staged parquet into the per-table Iceberg
  replica under the ``adp_{stage}_cms_ingest`` Glue database, then
  archives the consumed staged files.

The stack stays the source of truth for *what infrastructure exists*;
this package owns *how the ingestion actually executes*.

See :doc:`docs/cms-ingest-optional-module.md` for the operator-facing
runbook.
"""
