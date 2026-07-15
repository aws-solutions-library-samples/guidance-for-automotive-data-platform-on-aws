# Tech Research — ADP Foundation

This document is the authoritative API/SDK reference for the
`platform-foundation/` build. Every implementation task in
`tasks.md` Groups 2–6 references it — do not write code against
APIs that aren't documented here. When an API surface changes, this
doc is updated first; downstream code follows.

> **Placeholder notation in code and ARNs below**: any `<account>`
> token is a **user-substitution** — replace it with your 12-digit
> AWS account ID before running the snippet (e.g.
> `aws sts get-caller-identity --query Account --output text`).
> Region is pinned to `us-east-1` as a literal throughout
> (single-region by design — see
> [`docs/DEPLOYMENT.md` "Why single-region"](DEPLOYMENT.md#why-single-region));
> there is no `<region>` placeholder.

## Pinned versions

| Package | Version | Released | Source |
|---|---|---|---|
| `boto3` | 1.40.0 | 2025-07-21 (>7d) | https://pypi.org/project/boto3/1.40.0/ |
| `botocore` | 1.40.0 | 2025-07-21 (>7d) | https://pypi.org/project/botocore/1.40.0/ |
| `pyiceberg` | 0.7.1 | 2024-09-12 (>7d) | https://pypi.org/project/pyiceberg/0.7.1/ |
| `pyarrow` | 17.0.0 | 2024-07-16 (>7d) | https://pypi.org/project/pyarrow/17.0.0/ |
| `pandas` | 2.2.3 | 2024-09-20 (>7d) | https://pypi.org/project/pandas/2.2.3/ |
| `numpy` | 2.0.2 | 2024-08-26 (>7d) | https://pypi.org/project/numpy/2.0.2/ |
| `faker` | 30.3.0 | 2024-10-09 (>7d) | https://pypi.org/project/faker/30.3.0/ |
| `pyyaml` | 6.0.2 | 2024-08-06 (>7d) | https://pypi.org/project/PyYAML/6.0.2/ |
| `pytest` | 8.3.3 | 2024-09-09 (>7d) | https://pypi.org/project/pytest/8.3.3/ |
| `aws-cdk-lib` | 2.165.0 | 2024-10-30 (>7d) | https://pypi.org/project/aws-cdk-lib/2.165.0/ |
| `constructs` | 10.4.2 | 2024-09-13 (>7d) | https://pypi.org/project/constructs/10.4.2/ |
| `cdk-nag` | 2.34.0 | 2024-10-30 (>7d) | https://pypi.org/project/cdk-nag/2.34.0/ |
| **VSS catalog** | **v6.0** | **2026-01-16 (>7d)** | https://github.com/COVESA/vehicle_signal_specification/releases/tag/v6.0 |
| AWS Glue runtime | 4.0 (Spark 3.3, Python 3.10) | n/a | https://docs.aws.amazon.com/glue/latest/dg/release-notes.html |
| Athena engine | v3 | n/a | https://docs.aws.amazon.com/athena/latest/ug/engine-versions.html |

When a future session installs these packages, re-verify each release
date is still ≥7 days old at install time per
`~/.kiro/steering/dependency-versions.md`. Bump only if a security
advisory requires it.

Source: https://pypi.org/project/boto3/1.40.0/
Source: https://pypi.org/project/pyiceberg/0.7.1/
Source: https://pypi.org/project/pyarrow/17.0.0/
Source: https://pypi.org/project/pandas/2.2.3/
Source: https://pypi.org/project/aws-cdk-lib/2.165.0/

## Region & account assumptions

- Single AWS account, single region: `us-east-1`. Pinned per spec
  Constraint #3.
- No multi-region, no multi-account deployments in v1. The optional
  CMS→ADP ingest module (Should-Have, opt-in) assumes CMS and ADP in
  the same account; cross-account is documented but not implemented.
- DataZone V2 domain ID is captured at deploy time (not pre-pinned).
  Downstream tasks read it from CFN Outputs / SSM Parameter Store.

## API References

### AWS DataZone V2

API model: `bedrock-agent`-style POST endpoints; SDK class
`boto3.client('datazone')`. All operations require a
`domainIdentifier`.

Source: https://docs.aws.amazon.com/datazone/latest/APIReference/API_CreateDataSource.html
Source: https://docs.aws.amazon.com/datazone/latest/userguide/quickstart-apis.html
Source: https://docs.aws.amazon.com/datazone/latest/userguide/working-with-blueprints.html

#### `create_data_source`

```python
client = boto3.client('datazone', region_name='us-east-1')
response = client.create_data_source(
    domainIdentifier=domain_id,            # required (URI)
    name='vehicle_telemetry_aggregated',   # required, snake_case
    projectIdentifier=project_id,          # required, the owning DataZone project
    type='GLUE',                           # 'GLUE' or 'REDSHIFT'
    configuration={
        'glueRunConfiguration': {
            'relationalFilterConfigurations': [{
                'databaseName': 'adp_vehicle_telemetry_aggregated',
                'filterExpressions': [{
                    'expression': 'vehicle_telemetry_aggregated',
                    'type': 'INCLUDE',
                }],
            }],
        }
    },
    enableSetting='ENABLED',               # 'ENABLED' | 'DISABLED'
    publishOnImport=True,                  # auto-publish to catalog
    schedule={'schedule': 'cron(0 1 * * ? *)', 'timezone': 'UTC'},
    clientToken=str(uuid.uuid4()),         # idempotency
)
data_source_id = response['id']
```

**Pitfalls**:
- `name` must be unique within the project; use snake_case to match
  Glue database naming convention.
- `publishOnImport=True` auto-creates catalog assets but does NOT
  create subscription targets — those are separate API calls
  (`create_subscription_target`, `create_subscription_request`).
- `domainIdentifier` is the DataZone **domain** ID (not account ID).

#### Built-in blueprints

DataZone V2 ships three blueprints — Data Lake (Glue + Lake
Formation + Athena), Data Warehouse (Redshift), and SageMaker. ADP
v1 uses the Data Lake blueprint for all 9 product projects and the
Tooling blueprint for the domain itself.

| Blueprint | Use in ADP |
|---|---|
| `DefaultDataLake` | All 9 product projects |
| `DefaultTooling` | Domain-level shared services |
| `MLExperiments` (SageMaker) | Predictive-maintenance reference consumer |

Blueprint enablement happens once per account at domain creation
(via Quick Setup) or post-creation via console / CFN.

Source: https://docs.aws.amazon.com/datazone/latest/userguide/working-with-blueprints.html

### AWS Glue — Iceberg `create_table`

The Glue Catalog supports Iceberg tables via the
`OpenTableFormatInput` parameter on `create_table`. Tables created
this way are queryable from Athena Engine V3 and writable from Glue
4.0 Spark + EMR + Athena CTAS.

Source: https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-glue-table-opentableformatinput.html
Source: https://docs.aws.amazon.com/glue/latest/dg/aws-glue-api-catalog-tables.html

```python
client = boto3.client('glue', region_name='us-east-1')
client.create_table(
    DatabaseName='adp_charging_sessions',
    TableInput={
        'Name': 'charging_sessions',
        'TableType': 'EXTERNAL_TABLE',
        'Parameters': {
            'table_type': 'ICEBERG',
            'classification': 'parquet',
        },
        'StorageDescriptor': {
            'Columns': [
                {'Name': 'session_id', 'Type': 'string'},
                {'Name': 'vin', 'Type': 'string'},
                # ... etc
                {'Name': 'session_date', 'Type': 'date'},
            ],
            'Location': 's3://adp-foundation-lake-<account>-us-east-1/curated/charging_sessions/',
        },
        'PartitionKeys': [
            {'Name': 'session_date', 'Type': 'date'},
        ],
    },
    OpenTableFormatInput={
        'IcebergInput': {
            'MetadataOperation': 'CREATE',
            'Version': '2',  # Iceberg spec version 2
        }
    },
)
```

**Pitfalls**:
- `OpenTableFormatInput.IcebergInput.Version='2'` is required for
  Athena Engine V3 read+write compatibility. Version 1 is read-only
  in Athena.
- `TableType='EXTERNAL_TABLE'` is mandatory for Iceberg-on-Glue.
- Bucketing transforms (`bucket(16, vin)`) are NOT exposed through
  the Glue API — they must be set via Athena DDL `CREATE TABLE` or
  Spark DataFrame writer. See "Athena Engine V3 Iceberg DDL" below.
- For tables with bucketing requirements, prefer creating the table
  via Athena CTAS or Spark — then use Glue API only for catalog
  operations (alter, list, get).

### Athena Engine V3 — Iceberg DDL

Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/apache-iceberg-on-aws/getting-started.html
Source: https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg-creating-tables.html

#### Hidden-partitioned table (preferred)

```sql
CREATE TABLE adp_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated (
    vin             string,
    event_time      timestamp,
    speed_kmh       double,
    soc_pct         double,
    -- ... etc
    ingest_time     timestamp
)
PARTITIONED BY (day(event_time), bucket(16, vin))
LOCATION 's3://adp-foundation-lake-<account>-us-east-1/curated/vehicle_telemetry_aggregated/'
TBLPROPERTIES (
    'table_type'                    = 'ICEBERG',
    'format'                        = 'parquet',
    'write_compression'             = 'zstd',
    'optimize_rewrite_data_file_threshold' = '5',
    'vacuum_min_snapshots_to_keep'  = '10',
    'vacuum_max_snapshot_age_seconds' = '604800'
);
```

#### Bucketing on FK columns

Bucketing is a partition transform: `bucket(N, column)`. Use **16**
buckets for VIN-keyed fact tables >50M rows (per spec convention).

```sql
PARTITIONED BY (day(session_date), bucket(16, vin))
```

#### Available transforms (Athena V3)

| Transform | Use case |
|---|---|
| `year(ts)` / `month(ts)` / `day(ts)` / `hour(ts)` | Time-series partitioning |
| `bucket(N, col)` | High-cardinality FK distribution |
| `truncate(N, col)` | Long string keys (e.g., `truncate(8, customer_id)`) |
| `identity(col)` | Explicit partition column (legacy fall-back) |

**Pitfalls**:
- Hidden partitioning is supported in Athena Engine V3 only. Engine
  V2 cannot read tables created with `bucket()` or
  `day()` transforms — verify the Athena workgroup is V3.
- `MERGE INTO` is supported; useful for the optional CMS-ingest
  module that upserts CMS DDB rows into Iceberg.
- `OPTIMIZE` and `VACUUM` are essential for write-heavy tables; run
  weekly via scheduled query.

### PyIceberg vs Spark-on-Glue — choosing a writer

Source: https://py.iceberg.apache.org/api/
Source: https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-format-iceberg.html

| Criterion | PyIceberg 0.7.x (pandas) | Spark-on-Glue 4.0 |
|---|---|---|
| Max practical row count per write | ~10M (single Python process) | 100M+ (distributed) |
| File-size targeting (256 MB parquet) | Manual via `pyarrow` row-group sizing | Native via `spark.sql.files.maxPartitionBytes` |
| Bucketing transform | Not supported in 0.7 (planned 0.8+) | Supported via DataFrame `bucketBy` or DDL |
| Multi-table commit | No | No (single-table writes) |
| Cost | Low (single Lambda or EC2) | Glue DPU-hours |
| Cold start | None | ~60–90s job startup |

**Decision** (matches `tasks.md` Group 3 split):
- PySpark on Glue 4.0: `vehicle_telemetry_aggregated` (~100M),
  `customer_interactions` (50M), `energy_usage` (~450M).
- pandas + PyIceberg: `vehicle_identity` (5M), `customer_360` (5M
  snapshot/day, daily), `service_records` (10M),
  `charging_sessions` (20M), `ota_campaigns` (~30M events).
- The Group 1 spike (task 8, deferred to a session with AWS auth)
  validates Spark-side file-size targeting.

### pandas + pyarrow parquet schema declaration

Source: https://arrow.apache.org/docs/python/parquet.html
Source: https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_parquet.html

The schema_loader produces an `pyarrow.Schema` object that is passed
to `pq.ParquetWriter` to control row-group size, compression, and
nullability:

```python
import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd

schema = pa.schema([
    pa.field('vin',           pa.string(),    nullable=False),
    pa.field('customer_id',   pa.string(),    nullable=True),
    pa.field('session_date',  pa.date32(),    nullable=False),
    pa.field('start_time',    pa.timestamp('us', tz='UTC'),    nullable=False),
    pa.field('kwh_delivered', pa.float64(),   nullable=False),
    pa.field('cost_usd',      pa.decimal128(10, 4), nullable=True),
])

table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
pq.write_table(
    table,
    's3://adp-foundation-lake-.../curated/charging_sessions/dt=2025-09-01/00.parquet',
    row_group_size=200_000,
    compression='zstd',
    use_dictionary=True,
)
```

**Pitfalls**:
- `pa.timestamp('us', tz='UTC')` matches Iceberg's `timestamp` type.
  `pa.timestamp('ns')` does NOT round-trip cleanly to Iceberg.
- `pa.decimal128(precision, scale)` for currency. Don't use float64
  for `cost_usd` — currency arithmetic loses precision.
- Set `nullable=False` for required columns; pyarrow won't enforce
  it on read but it lets the schema_loader generate Iceberg DDL with
  `NOT NULL` correctly.
- Avoid `preserve_index=True` — it adds a `__index_level_0__`
  column to the parquet schema.

### Lake Formation — tag-based access control (LF-TBAC)

Source: https://docs.aws.amazon.com/lake-formation/latest/dg/tag-based-access-control.html

LF-TBAC grants permissions by matching key-value tags on Data
Catalog resources rather than by enumerating individual resource
ARNs. ADP uses two tag values: `PII` and `non-PII`.

```python
client = boto3.client('lakeformation', region_name='us-east-1')

# 1) Define the tag key (once per account)
client.create_lf_tag(
    TagKey='adp-classification',
    TagValues=['PII', 'non-PII'],
)

# 2) Tag a database
client.add_lf_tags_to_resource(
    Resource={'Database': {'Name': 'adp_customer_360'}},
    LFTags=[{'TagKey': 'adp-classification', 'TagValues': ['PII']}],
)

# 3) Grant by tag (not by resource ARN)
client.grant_permissions(
    Principal={'DataLakePrincipalIdentifier': 'arn:aws:iam::ACCT:role/adp-data-consumers'},
    Resource={
        'LFTagPolicy': {
            'ResourceType': 'DATABASE',
            'Expression': [{'TagKey': 'adp-classification', 'TagValues': ['non-PII']}],
        }
    },
    Permissions=['DESCRIBE', 'SELECT'],
)
```

**Pitfalls**:
- LF-TBAC is distinct from IAM tags. Don't confuse the two.
- The ADP IAM principal must already be a Lake Formation **Data
  Lake Administrator** before the principal can grant by tag.
- For the foundation, define the tag once at the account level, then
  apply it per-product database in the governance stack.
- Column-level tags (PII columns inside a table) are also supported
  via `add_lf_tags_to_resource` with `TableWithColumns`.

### Bedrock Knowledge Base — ingestion

Source: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_StartIngestionJob.html

```python
client = boto3.client('bedrock-agent', region_name='us-east-1')

# 1) Knowledge base + S3 data source created via CDK or
#    bedrock-agent.create_knowledge_base / create_data_source.
# 2) Trigger ingestion (HTTP 202 — async):
response = client.start_ingestion_job(
    knowledgeBaseId=kb_id,
    dataSourceId=ds_id,
    description='vehicle_knowledge_base v1 ingest',
    clientToken=str(uuid.uuid4()),
)
job_id = response['ingestionJob']['ingestionJobId']

# 3) Poll for completion:
while True:
    job = client.get_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
        ingestionJobId=job_id,
    )['ingestionJob']
    if job['status'] in ('COMPLETE', 'FAILED'):
        break
    time.sleep(30)
```

**Pitfalls**:
- `start_ingestion_job` is async — returns 202 immediately with a
  job ID. Always poll `get_ingestion_job` for completion.
- `clientToken` MUST be unique per re-ingest; otherwise the API
  returns the previous (cached) job.
- The KB's IAM role needs `s3:ListBucket` and `s3:GetObject` on
  the source prefix; otherwise the job fails silently with
  `"errors": [{"errorMessage": "AccessDenied"}]` in the job summary.

### Kinesis Firehose — dynamic partitioning to S3 parquet

Source: https://docs.aws.amazon.com/firehose/latest/dev/dynamic-partitioning-partitioning-keys.html
Source: https://docs.aws.amazon.com/firehose/latest/dev/record-format-conversion.html

Used by the optional CMS→ADP ingest module to land DDB-Stream
records as parquet under `s3://.../cms-ingest/<table>/dt=YYYY-MM-DD/`
keyed by event date, ready for an Iceberg MERGE job.

```yaml
# CDK / CloudFormation snippet (illustrative)
DeliveryStreamType: KinesisStreamAsSource
KinesisStreamSourceConfiguration:
  KinesisStreamARN: !GetAtt CMSDDBChangeStream.Arn
  RoleARN: !GetAtt FirehoseRole.Arn

ExtendedS3DestinationConfiguration:
  BucketARN: !Sub arn:aws:s3:::adp-foundation-lake-${AWS::AccountId}-us-east-1
  Prefix: 'cms-ingest/!{partitionKeyFromQuery:tablename}/dt=!{timestamp:yyyy-MM-dd}/'
  ErrorOutputPrefix: 'cms-ingest-errors/!{firehose:error-output-type}/'
  BufferingHints:
    SizeInMBs: 64
    IntervalInSeconds: 60          # 60s = micro-batch (NOT streaming, per spec Constraint #9)
  CompressionFormat: UNCOMPRESSED   # Required when DataFormatConversionConfiguration is used

  DynamicPartitioningConfiguration:
    Enabled: true
    RetryOptions:
      DurationInSeconds: 300

  ProcessingConfiguration:
    Enabled: true
    Processors:
      - Type: MetadataExtraction
        Parameters:
          - ParameterName: MetadataExtractionQuery
            ParameterValue: '{tablename: .tableName}'
          - ParameterName: JsonParsingEngine
            ParameterValue: JQ-1.6

  DataFormatConversionConfiguration:
    Enabled: true
    OutputFormatConfiguration:
      Serializer: { ParquetSerDe: { Compression: ZSTD } }
    InputFormatConfiguration:
      Deserializer: { OpenXJsonSerDe: {} }
    SchemaConfiguration:                  # Glue table = parquet schema source
      DatabaseName: adp_cms_ingest_staging
      TableName: !Ref CMSStreamStagingTable
      RoleARN: !GetAtt FirehoseRole.Arn
```

**Pitfalls**:
- `BufferingHints.IntervalInSeconds=60` keeps us inside the spec's
  "no streaming" constraint (micro-batch).
- Dynamic partitioning requires `Enabled: true` AND a
  `MetadataExtractionQuery` (JQ) OR a Lambda transformer. Neither
  alone is sufficient.
- `DataFormatConversionConfiguration` requires
  `CompressionFormat: UNCOMPRESSED` on the S3 destination — the
  parquet writer compresses internally.
- The Glue table referenced by `SchemaConfiguration` must exist
  before the Firehose stream is created. Order CDK constructs
  accordingly.
- Firehose can fan-out to >500 partitions; beyond that, you hit the
  per-stream active-partition limit and records buffer in error.

### DynamoDB Streams — cross-account configuration

Source: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/rbac-cross-account-access.html
Source: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/rbac-iam-actions.html

For the optional CMS→ADP ingest module:
- v1 assumes CMS and ADP in the **same** AWS account → no
  cross-account IAM needed; ADP simply consumes the DDB stream ARN.
- Cross-account is documented as a follow-up:
  - CMS-side: attach a DDB **resource-based policy** (RBP) to the
    table allowing ADP's role `dynamodb:DescribeStream`,
    `dynamodb:GetRecords`, `dynamodb:GetShardIterator`,
    `dynamodb:ListStreams`.
  - ADP-side: identity-based policy granting the same actions
    against the CMS stream ARN.
  - Both halves are required (RBP + identity policy).
- CloudTrail logs the cross-account read in both accounts.
- Note: **Stream RBPs and stream cross-account policies do not exist
  on the stream itself** — the policy lives on the parent table.
  All API calls to the stream resolve back to the table for auth.

**Pitfalls**:
- "Internal table configuration APIs" (e.g., `UpdateTimeToLive`,
  `DisableKinesisStreamingDestination`) do **not** support
  cross-account access. ADP must NEVER attempt to alter CMS table
  state — ingest is read-only on streams.
- Lambda's DDB-stream event source mapping accepts a stream ARN
  from another account; Firehose's Kinesis-stream-as-source does
  **not** accept cross-account Kinesis Streams natively. For
  cross-account, route DDB stream → Lambda (in CMS account) →
  cross-account Kinesis Data Streams (in ADP account) → Firehose.
  This is documented as v2 follow-up, not v1.

### VSS (Vehicle Signal Specification) — v6.0

Source: https://github.com/COVESA/vehicle_signal_specification/releases/tag/v6.0
Source: https://covesa.github.io/vehicle_signal_specification/catalog/

VSS v6.0 (released 2026-01-16) is the canonical signal vocabulary
ADP adopts. Key changes from v5.1:
- `Vehicle.OBD` branch removed (irrelevant to ADP — EV scope).
- `celsius` unit renamed to `Celsius` (we adopt the new spelling).
- New Vehicle Health Management signals (relevant to
  `service_records` narratives).
- Extended Range EV signal definitions (used in `vehicle_identity`).
- New `pattern` keyword on string types (used in VIN signal).

**Tooling**: `vss-tools` provides `vspec2csv`, `vspec2json`, etc.,
to expand the master catalog into ADP's column dtype map. ADP does
not vendor the vss-tools package — instead, the 40-signal subset is
hardcoded in `docs/data-contracts.md` and verified by tests against
the published `vss.json` from the v6.0 release artifact.

**Subset published by ADP**: see
`docs/data-contracts.md` "VSS vocabulary subset" section — 40 signals
covering battery, propulsion, charging, thermal, drive state.

**Unit conventions** (carry-overs from VSS catalog):
| Quantity | VSS unit | ADP storage |
|---|---|---|
| Speed | `km/h` | `double` km/h (do NOT convert to mph at storage; convert at display) |
| Distance | `km` (long), `m` (short) | `double` km |
| Range estimate | `km` | `double` km — `range_estimate_*_mi` columns store **miles** for the US-market narrative; this is an explicit deviation from VSS that's documented in `data-contracts.md` |
| Temperature | `Celsius` (renamed from `celsius` in v6.0) | `double` °C |
| Energy | `kWh` | `double` kWh |
| Power | `kW` | `double` kW |
| Voltage | `V` | `double` V |
| Current | `A` | `double` A |
| State of charge | `percent` (0–100) | `double` 0–100 |

**Pitfalls**:
- VSS uses `percent` (0–100), not 0.0–1.0. Don't normalize.
- VSS `Vehicle.Speed` is in km/h. The US-narrative columns
  (`total_miles_driven`, `range_estimate_*_mi`) are explicit
  deviations — call them out clearly in `data-contracts.md` with the
  `_mi` suffix.
- VSS v6.0 Celsius capitalization is mandatory in the unit field;
  legacy `celsius` (lowercase) is still readable but emits a
  deprecation warning.

## Edge-Case Taxonomy

Synthetic data MUST exhibit calibrated edge cases — 1–3% of rows per
product carry at least one of the six injection codes below. The
calibration is intentional, not random, so downstream tests are
deterministic. Each code defines: definition, target rate per
product, expected detector test, example row.

### `missing_required`
- **Definition**: A column declared `nullable: false` in the
  schema YAML is `NULL` in the row. Useful for testing downstream
  null-handling logic.
- **Target rate**: 0.5%–1.0% per product, per column eligible for
  injection (only columns flagged `edge_case_eligible: true` in the
  schema). Never inject into FK columns — that's `orphan_fk`'s
  job. Never inject into partition keys (would corrupt Iceberg
  layout).
- **Detector test**: `test_edge_case_injection.py::test_missing_required_rate`
  — counts NULLs per eligible column, asserts rate within 0.5–1.0%
  per column ± tolerance.
- **Example row** (charging_sessions): `start_soc_pct = NULL` while
  every other column is populated. Detector flags the row as
  `edge_case_codes=['missing_required']` if the test instrumentation
  is reading from a labeled fixture.

### `late_arrival`
- **Definition**: `(ingest_time - event_time) > 1 day`, i.e., a row
  whose source-truth event happened ≥24h before the loader wrote it.
  Models real-world stuck queues, edge-device buffering, and
  intermittent connectivity.
- **Target rate**: 0.3%–0.7% per product, on rows that have both
  `event_time` and `ingest_time` columns (most fact tables — but
  not `vehicle_identity`, which has no event_time).
- **Detector test**: `test_edge_case_injection.py::test_late_arrival_rate`
  — `SELECT COUNT(*) WHERE date_diff('day', event_time, ingest_time)
  > 1` divided by total row count, asserts rate within 0.3–0.7%.
- **Example row** (charging_sessions): `event_time =
  2025-09-15T08:00:00Z`, `ingest_time = 2025-09-18T03:14:00Z` (3 days
  late) — could correspond to a parked vehicle with no cellular
  signal until next charge.

### `schema_drift`
- **Definition**: A row carries an extra column not declared in the
  current schema YAML, OR a column with a value that fails the
  declared `pattern` (regex) on a string column. Tests downstream
  schema-evolution handling.
- **Target rate**: 0.2%–0.5% per product. Lower than other codes
  because schema drift bypasses Iceberg's schema enforcement; we
  inject it only at the synthetic-source level (raw parquet) for
  simulated downstream debugging.
- **Detector test**: `test_edge_case_injection.py::test_schema_drift_rate`
  — checks for known-extra columns (e.g., a `_legacy_field_v1` column
  appended by the generator on 0.2–0.5% of rows) AND for pattern
  violations on regex-validated columns. Asserts rate within bound.
- **Example row** (charging_sessions): an extra column
  `_legacy_field_v1: "deprecated_payload_marker"` appears alongside
  the standard schema. Iceberg ignores it on read; downstream
  Glue ETL or ad-hoc SQL `SELECT *` may surface it.
- **FK exclusion** (per fix-spec
  `2026-06-03-adp-charging-sessions-fk-drift-fix`): the injector
  excludes FK columns from the `string_eligible` candidate set —
  `fk_columns = {fk.column for fk in self.table.foreign_keys}` is
  built once and used as a filter in
  `EdgeCaseInjector.apply()` (see
  `source/lib/product_generator.py:148-156`). Without this exclusion,
  any FK column tagged `edge_case_eligible: true` (e.g.
  `charging_sessions.customer_id`) folds drift output into
  `orphan_fk`, violating the 0% counter-example contract. The
  symmetric exclusion already exists for `bad_pii` via the
  `pii_drift_target: true` opt-in flag. Regression guard:
  `tests/test_referential_integrity.py::test_no_drift_prefix_in_fk_columns`.

### `bad_pii`
- **Definition**: A PII-tagged column carries a value that LOOKS
  like the right shape but fails the documented regex (see
  `data-contracts.md` Identifier formats), OR a tagged-non-PII
  column carries a value matching a PII pattern (false positive
  for downstream Macie scans).
- **Target rate**: 0.1%–0.3% per PII-bearing product
  (`customer_360`, `customer_interactions`, `service_records`,
  `charging_sessions`).
- **Detector test**: `test_edge_case_injection.py::test_bad_pii_rate`
  — for each PII column, attempts the regex match and counts
  non-conforming rows.
- **Example row** (customer_360): `customer_id = "CUST-INVALID"`
  (right prefix, wrong format). Or: `email = "real-looking-name@spammy"`
  injected into a `comments` column that is not declared as
  PII-bearing — exercises the false-positive path of the Macie scan
  scope.

### `orphan_fk`
- **Definition**: A foreign-key column references a key (VIN,
  `customer_id`, `dealer_id`, `supplier_id`, `part_number`,
  `station_id`, `campaign_id`) that is NOT in the dimension catalog
  / parent table.
- **Target rate**: **0%** (counter-example). The integrity test
  asserts ZERO orphan FKs across all 9 products. This code exists in
  the taxonomy specifically so the test framework can deliberately
  inject one in a test fixture and verify the detector raises an
  alarm. PRODUCTION generators MUST emit zero orphans.
- **Detector test**: `test_referential_integrity.py::test_zero_orphan_fks`
  — for every FK in every product, `LEFT JOIN` against the dimension
  / parent and asserts no unmatched rows.
- **Example row** (charging_sessions): `vin = "1FA00000000000000"`
  (well-formed VIN regex match) but the VIN is not in the `vins`
  dimension catalog. The integrity test must FAIL on any such row.

> ⚠️  **CRITICAL**: `orphan_fk` is a counter-example. Real generators
> NEVER emit orphan FKs. The integrity assertion is the gate.
> `tasks.md` Group 2 dimension generator runs first, BEFORE any
> fact-table generator, exactly so this is enforced by construction.

### `outlier_value`
- **Definition**: A numeric column carries a value far outside the
  declared `range` (e.g., negative `kwh_delivered`, `soc_pct=120`,
  `duration_seconds=999_999_999`). Models sensor faults, encoding
  errors, and data-source bugs that ML and BI consumers must handle
  gracefully.
- **Target rate**: 0.2%–0.6% per product. Concentrate on
  metric-bearing columns (kWh, kW, power, distance, soc).
- **Detector test**: `test_edge_case_injection.py::test_outlier_rate`
  — for each numeric column with a declared `range: [min, max]` in
  the schema YAML, counts rows outside the range, asserts within
  0.2–0.6% of total.
- **Example row** (charging_sessions): `peak_power_kw = 9999.0`
  (DC-fast realistic max ~350 kW, so 9999 is ~30x out of band).
  Detector flags it.

### Calibration summary

Each row may carry ≥1 code (codes are not mutually exclusive). The
**aggregate** edge-case rate per product is 1–3% (PRD bound),
calculated as `1 - clean_rate` where a row is "clean" if it carries
zero codes.

A `decisions.md` entry will record the actual calibrated rates after
Group 3 generators are run; the rates here are **target ranges**
that the implementation may tune within bounds without spec
amendment, as long as the per-code lower bound > 0% (else the
detector test passes vacuously) and the aggregate stays within 1–3%.

Source: ADP spec `2026-05-28-adp-ev-startup-foundation/spec.md`
Source: ADP PRD `~/.kiro/portfolio/initiatives/2026-05-28-adp-ev-startup-foundation/prd.md`

## Open Research Questions

1. **VSS unit-deviation pattern.** ADP stores some columns in
   miles/Fahrenheit for the US-market narrative (e.g.,
   `range_estimate_start_mi`, `total_miles_driven`). VSS uses
   km/Celsius. The `_mi` / `_f` suffix is documented in
   `data-contracts.md`, but a future VSS-tools-driven validation
   harness should be aware that not every numeric column is
   VSS-conformant by design. Re-evaluate at v2 if a customer pushes
   for full SI conformance.
2. **Iceberg compaction cadence.** `OPTIMIZE` and `VACUUM`
   schedules are configured per-table via TBLPROPERTIES. Group 3
   generators land tables with a 7-day VACUUM threshold; Group 6
   adds the scheduled OPTIMIZE query. Tune after the Spark spike
   informs file-size targeting.
3. **PyIceberg 0.7 vs 0.8 transform support.** Bucketing transforms
   land in PyIceberg 0.8+. ADP v1 is on 0.7, so the pandas-tier
   generators write to bucketed tables via Glue Spark MERGE INTO or
   Athena CTAS, not via PyIceberg directly. Re-evaluate at v2.
4. **Bedrock KB chunk strategy.** Default chunk size for
   `vehicle_knowledge_base` is 512 tokens with 20% overlap. Tune
   after Group 4 reference-consumer notebook results.


---

## ADP PySpark via Glue (spec 2026-06-09-adp-pyspark-glue-products)

This section documents the AWS Glue 4.0 + boto3 + Athena APIs and CDK
constructor patterns the spec relies on. Verified 2026-06-09 against
boto3 1.40.0 / aws-cdk-lib 2.214.0 (CDK CLI 2.1126.0). Implementation
tasks in spec groups 2–7 reference this section by anchor — do not
write code against unverified APIs (per
`~/.kiro/steering/sdk-verification.md`).

### (a) `boto3.client('glue').create_job(...)`

Source: <https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glue/client/create_job.html>
Verified 2026-06-09 via the boto3 service model (`operation_model('CreateJob').input_shape.members`).

Required: `Name` (string), `Role` (string IAM ARN), `Command` (structure).

The `Command` structure for a Spark ETL job:

```python
Command={
    'Name': 'glueetl',                # required for Glue Spark ETL
    'ScriptLocation': 's3://<bucket>/<key>.py',  # required
    'PythonVersion': '3',             # Glue 4.0 → Python 3.10
}
```

Key optional kwargs we use:

| Kwarg | Type | Value (this spec) | Notes |
|---|---|---|---|
| `GlueVersion` | string | `'4.0'` | Locked per spec Decision; `'5.0'` deferred to a P3 follow-up |
| `WorkerType` | string | `'G.1X'` | 4 DPU/worker; sample-tier matches spike |
| `NumberOfWorkers` | integer | `2` | Sample-tier matches spike's 1124s for 10M rows |
| `Timeout` | integer | `30` | Minutes — locked per spec Constraint #6 |
| `MaxRetries` | integer | omit (default 0) | One-shot jobs; failures surface, not retry |
| `DefaultArguments` | map | see (e) below | Iceberg + CloudWatch + TempDir |
| `ExecutionProperty` | structure | `{'MaxConcurrentRuns': 1}` | One run at a time per job |
| `Connections` | structure | omit | No JDBC connections for the lake-only path |
| `Tags` | map | `{'adp:stage': '<stage>', 'adp:spec': '...'}` | Cost allocation |

`AllocatedCapacity` and `MaxCapacity` are **mutually exclusive with**
`NumberOfWorkers` + `WorkerType` — do NOT mix them.

Live-verified service model (boto3 1.40.0):

```
Name: string  JobMode: string  JobRunQueuingEnabled: boolean
Description: string  LogUri: string  Role: string  ExecutionProperty: structure
Command: structure  DefaultArguments: map  NonOverridableArguments: map
Connections: structure  MaxRetries: integer  AllocatedCapacity: integer
Timeout: integer  MaxCapacity: double  SecurityConfiguration: string
Tags: map  NotificationProperty: structure  GlueVersion: string
NumberOfWorkers: integer  WorkerType: string  CodeGenConfigurationNodes: map
ExecutionClass: string  SourceControlDetails: structure  MaintenanceWindow: string
```

### (b) `boto3.client('glue').start_job_run(...)`

Source: <https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glue/client/start_job_run.html>
Verified 2026-06-09.

Required: `JobName` (string).

Key optional kwargs:

- `Arguments` (map) — overrides for `DefaultArguments`. Forwarded to
  the Spark script as `--key value` CLI args. Both keys and values are
  strings; numeric values must be string-coerced (`str(rows)`).
- `Timeout` (integer) — minutes, overrides job-level timeout.
- `WorkerType`, `NumberOfWorkers` — overrides job-level shape.

Returns: `{'JobRunId': str}` (e.g. `'jr_abc123...'`).

Live-verified service model (boto3 1.40.0):

```
JobName: string  JobRunQueuingEnabled: boolean  JobRunId: string
Arguments: map  AllocatedCapacity: integer  Timeout: integer
MaxCapacity: double  SecurityConfiguration: string
NotificationProperty: structure  WorkerType: string
NumberOfWorkers: integer  ExecutionClass: string
ExecutionRoleSessionPolicy: string
```

### (c) `boto3.client('glue').get_job_run(...)`

Source: <https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glue/client/get_job_run.html>
Verified 2026-06-09.

Required: `JobName`, `RunId`.

Response payload `JobRun`:

- `JobRunState` — terminal: `SUCCEEDED`, `FAILED`, `TIMEOUT`, `STOPPED`;
  non-terminal: `STARTING`, `RUNNING`, `STOPPING`, `WAITING`.
- `ErrorMessage` — populated on `FAILED`/`TIMEOUT`.
- `LogGroupName` — exposes the run's CloudWatch log group prefix.
  Conventionally `/aws-glue/jobs/output` (driver+executor stdout) and
  `/aws-glue/jobs/error` (driver+executor stderr); the actual streams
  inside are keyed by `<JobRunId>`.
- `StartedOn`, `CompletedOn`, `ExecutionTime` — timing.

Live-verified service model: `JobName: string  RunId: string  PredecessorsIncluded: boolean`.

Polling pattern (matches `scripts/run-spark-spike.sh` lines 122–138):

```python
while True:
    state = glue.get_job_run(JobName=job_name, RunId=run_id)['JobRun']['JobRunState']
    if state in ('SUCCEEDED', 'FAILED', 'TIMEOUT', 'STOPPED'):
        break
    time.sleep(30)
```

### (d) `boto3.client('glue').delete_job(...)`

Source: <https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glue/client/delete_job.html>
Verified 2026-06-09.

Required: `JobName` only. Idempotency: NOT inherently idempotent — raises
`EntityNotFoundException` if absent. The orchestration script wraps in
`try/except botocore.exceptions.ClientError` and swallows `EntityNotFoundException`
(matches the spike harness's `aws glue delete-job ... 2>/dev/null || true`
pattern at line 41).

Live-verified service model: `JobName: string`.

### (e) Glue 4.0 `--datalake-formats=iceberg` and the canonical `DefaultArguments` block

Source (Glue 4.0 release): <https://docs.aws.amazon.com/glue/latest/dg/release-notes.html#release-notes-glue-4-0>
Source (Iceberg on Glue): <https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl-format-iceberg.html>
Verified 2026-06-09.

Setting `--datalake-formats: iceberg` causes Glue to:

1. Add the Iceberg Spark runtime JAR + Glue Catalog connector to the
   driver+executor classpath.
2. Auto-configure `spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions`
   and `spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog`
   so `dataframe.writeTo("glue_catalog.<db>.<table>")` resolves to a
   Glue-Catalog-backed Iceberg write.
3. Auto-register the table in Glue Catalog with parameter
   `table_type=ICEBERG` on first write.

Do NOT also pass `--conf spark.sql.catalog.glue_catalog=...` — it
collides with the auto-config and silently produces a non-Iceberg
parquet write (regression mode observed in the closed-spec spike's
earlier iterations).

The canonical `DefaultArguments` block this spec uses (matches the
existing working example at `platform-foundation/scripts/run-spark-spike.sh:96-101`):

```python
DefaultArguments={
    '--datalake-formats': 'iceberg',
    '--enable-metrics': 'true',
    '--enable-continuous-cloudwatch-log': 'true',
    '--enable-spark-ui': 'false',
    '--TempDir': f's3://{lake_bucket}/tmp/',
    '--extra-py-files': f's3://{lake_bucket}/scripts/lib/product_generator.py',
}
```

`--extra-py-files` makes the `EDGE_CASE_RATES` import from
`source/lib/product_generator.py` resolvable from the generator
scripts on Glue executors.

### (f) `boto3.client('athena').start_query_execution(...)` + `get_query_execution(...)`

Source: <https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/athena/client/start_query_execution.html>
Verified 2026-06-09.

Required: `QueryString`. Recommended for Iceberg writes:

```python
athena.start_query_execution(
    QueryString='SELECT COUNT(*) FROM adp_staging_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated',
    QueryExecutionContext={'Database': 'adp_staging_vehicle_telemetry_aggregated'},
    ResultConfiguration={
        'OutputLocation': f's3://{lake_bucket}/athena-results/',
    },
    WorkGroup='primary',
)
```

Returns `{'QueryExecutionId': str}`.

`get_query_execution(QueryExecutionId=...)` exposes:

- `QueryExecution.Status.State` — terminal: `SUCCEEDED`, `FAILED`, `CANCELLED`;
  non-terminal: `QUEUED`, `RUNNING`.
- `QueryExecution.Status.StateChangeReason` — populated on `FAILED`/`CANCELLED`.
- `QueryExecution.ResultConfiguration.OutputLocation` — full S3 URI
  of the result CSV.

Live-verified service model: `QueryString: string  ClientRequestToken: string
QueryExecutionContext: structure  ResultConfiguration: structure
WorkGroup: string  ExecutionParameters: list  ResultReuseConfiguration: structure`.

Result fetch via `get_query_results(QueryExecutionId=...)` returns the
`ResultSet.Rows` list; for `SELECT COUNT(*)` the count is in
`ResultSet.Rows[1].Data[0].VarCharValue` (row 0 is the column header).

### (g) `aws_cdk.aws_iam.Role` constructor (live-verified `inspect.signature()`)

Source: <https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_iam/Role.html>
Source: live `inspect.signature(iam.Role.__init__)`, verified 2026-06-09.
Reference pattern: `platform-foundation/stacks/optional/cms_ingest_stack.py`
lines 388–460 (`GlueMergeJobRole` — the canonical Spark-ETL role idiom in this repo).

```
Role(scope, id, *,
     assumed_by: IPrincipal,                              # required
     description: str | None = None,
     external_ids: Sequence[str] | None = None,
     inline_policies: Mapping[str, PolicyDocument] | None = None,
     managed_policies: Sequence[IManagedPolicy] | None = None,
     max_session_duration: Duration | None = None,
     path: str | None = None,
     permissions_boundary: IManagedPolicy | None = None,
     role_name: str | None = None)
```

`assumed_by` for a Glue ETL role:

```python
assumed_by=iam.ServicePrincipal('glue.amazonaws.com')
```

`role_name` for region-suffix discipline (per
`~/.kiro/steering/cross-region-namespace.md` Check 1):

```python
role_name=f"{_stage_name(stage, 'spark-etl-role')}-{Stack.of(self).region}"
# → adp-staging-foundation-spark-etl-role-us-east-1
```

`managed_policies` for the Glue baseline:

```python
managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name('service-role/AWSGlueServiceRole')]
```

For inline policies the cms_ingest pattern uses
`role.add_to_policy(iam.PolicyStatement(...))` after construction
rather than the `inline_policies` constructor kwarg — both are
equivalent in the synthesized template; we use the post-construction
pattern to match the codebase idiom.

### (h) `aws_cdk.aws_iam.PolicyStatement` constructor (live-verified)

Source: live `inspect.signature(iam.PolicyStatement.__init__)`, verified 2026-06-09.

```
PolicyStatement(*,
    actions: Sequence[str] | None = None,
    conditions: Mapping[str, Any] | None = None,
    effect: Effect | None = None,
    not_actions: Sequence[str] | None = None,
    not_principals: Sequence[IPrincipal] | None = None,
    not_resources: Sequence[str] | None = None,
    principals: Sequence[IPrincipal] | None = None,
    resources: Sequence[str] | None = None,
    sid: str | None = None)
```

For this spec's Spark ETL role, the inline statements (scoped
minimally — see `data_products_stack.py` for the live policy):

| Statement | Actions | Resources |
|---|---|---|
| Lake bucket read (list+get on `dimensions/`) | `s3:ListBucket`, `s3:GetObject`, `s3:GetBucketLocation` | bucket ARN + `/dimensions/*` (with `s3:prefix` Condition for ListBucket) |
| Lake bucket write (curated + scripts + tmp + athena-results) | `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`, `s3:AbortMultipartUpload` | `/curated/vehicle_telemetry_aggregated/*`, `/curated/energy_usage/*`, `/scripts/*`, `/tmp/*`, `/athena-results/*` |
| Glue Catalog scoped to 2 target databases | `glue:GetDatabase*`, `glue:GetTable*`, `glue:CreateTable`, `glue:UpdateTable`, `glue:GetPartition*`, `glue:CreatePartition`, `glue:UpdatePartition`, `glue:BatchCreatePartition` | catalog + `database/adp_{stage}_vehicle_telemetry_aggregated` + `database/adp_{stage}_energy_usage` + table-level wildcards |
| Athena (workgroup `primary` only) | `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults`, `athena:StopQueryExecution`, `athena:GetWorkGroup` | `arn:aws:athena:{region}:{account}:workgroup/primary` |
| CloudWatch Logs (Glue convention) | `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`, `logs:AssociateKmsKey` | `arn:aws:logs:{region}:{account}:log-group:/aws-glue/jobs/*` |
| KMS for the lake CMK | `kms:Encrypt`, `kms:Decrypt`, `kms:GenerateDataKey*`, `kms:DescribeKey`, `kms:ReEncrypt*` | lake KMS key ARN if known, else `*` with `kms:ViaService` Condition for `s3.{region}.amazonaws.com` and `glue.{region}.amazonaws.com` (matches `cms_ingest_stack.py:443-460`) |

NO `iam:PassRole` — Spark ETL does not need PassRole (we use the
service-principal-trust path, not delegated principal pass-through).

### (i) `aws_cdk.aws_glue.CfnJob` constructor

Source: <https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_glue/CfnJob.html>
Verified 2026-06-09 (constructor signature).

This spec deliberately does NOT use `CfnJob`. The 2 generator jobs
run **once** at sample scale; standing up CDK resources adds permanent
surface for transient compute. The spike-harness precedent
(`scripts/run-spark-spike.sh`) is one-shot boto3, and we follow that
convention.

If a recurring schedule (e.g., weekly OPTIMIZE/VACUUM) emerges, the
CDK-managed path becomes the right call — until then, no.

### (j) Source URLs + verification dates

All findings (a)–(i) verified 2026-06-09 against:

- boto3 1.40.0 (`pip show boto3`)
- aws-cdk-lib 2.214.0, CDK CLI 2.1126.0
- Live `inspect.signature()` on the CDK constructors
- Live `boto3.client(...).meta.service_model.operation_model(...).input_shape.members`
  on the Glue + Athena APIs
- AWS docs URLs cited inline per finding
- Cross-reference: `platform-foundation/scripts/run-spark-spike.sh`
  (the working spike harness — one of the few repository-local sources
  of truth for the Glue 4.0 + Iceberg DefaultArguments combination)

### Run results (sample tier, 2026-06-09)

To be filled in by Group 8 (T8.1) after the empirical Glue runs land
in groups 4 and 5.


## ADP PySpark via Glue 5.1 (spec 2026-06-09-adp-pyspark-glue-products) — UPDATED 2026-06-10

**User-directed scope change** 2026-06-10 bumped the locked Glue
version from 4.0 → 5.1 (current GA as of 2025-11-26 per the
[announcement](https://aws.amazon.com/about-aws/whats-new/2025/11/aws-glue-5-1/)).
The Glue 4.0 research above is preserved as historical record; this
section captures the 5.1 deltas. See also `decisions.md` 2026-06-10
entry for full rationale and risk-audit of the version change.

### What changed (vs Glue 4.0)

| Component | Glue 4.0 | Glue 5.1 |
|---|---|---|
| Spark | 3.3.0-amzn-1 | 3.5.6 |
| Python | 3.10 | 3.11 |
| Scala | 2.12 | 2.12.18 |
| Java | 8 | 17 |
| Hadoop | 3.3.3-amzn-0 | 3.4.1 |
| Iceberg library | 1.0.0 | 1.10.0 (format v3.0 supported) |
| Hudi | 0.12.1 | 1.0.2 |
| Delta Lake | 2.1.0 | 3.3.2 |
| Glue Data Catalog client | 3.7.0 | 4.9.0 |
| AWS SDK for Java | 1.12 | 2.35.5 |
| Bundled boto (in-job) | 1.26 | 1.40.61 |
| EMRFS | 2.54.0 | 2.73.0 (no longer default) |
| **Default S3 connector** | **EMRFS** | **S3A** (BREAKING — see finding (k)) |

Source: [AWS Glue 5.1 migration guide § Appendix A](https://docs.aws.amazon.com/glue/latest/dg/migrating-version-51.html#migrating-version-51-appendix-dependencies)
(verification date: 2026-06-10).

### Verified findings (deltas only — unchanged findings cite Glue 4.0 section above)

#### (a) `boto3.client('glue').create_job(...)` for Glue 5.1

The boto3 client signature is unchanged across Glue 4.0/5.0/5.1.
The only difference is the `GlueVersion` parameter value: pass
the literal string `'5.1'` (NOT `'5.1.0'`).

Per the [Glue 5.1 migration doc](https://docs.aws.amazon.com/glue/latest/dg/migrating-version-51.html#migrating-version-51-actions):

> In the API, choose **5.1** in the `GlueVersion` parameter in the
> CreateJob API operation.

Live verification (2026-06-10):
```python
>>> import boto3, inspect
>>> sig = inspect.signature(boto3.client('glue').create_job)
>>> 'GlueVersion' in str(sig)
True
```

The `GlueVersion` parameter is documented as a string; the API
accepts `'0.9'`, `'1.0'`, `'2.0'`, `'3.0'`, `'4.0'`, `'5.0'`,
`'5.1'`. As of the migration doc, **default for new jobs that
don't specify `GlueVersion` is now 5.1** — this spec passes
`'5.1'` explicitly to make the version contract auditable.

#### (b) `boto3.client('glue').start_job_run(...)`

Unchanged from Glue 4.0 finding above. Same `JobName` + `Arguments`
shape. Terminal `JobRunState` values identical.

#### (c) `boto3.client('glue').get_job_run(...)`

Unchanged. Terminal states (`SUCCEEDED`, `FAILED`, `TIMEOUT`,
`STOPPED`, `RUNNING`, `STARTING`, `STOPPING`) are identical to 4.0.

#### (d) `boto3.client('glue').delete_job(...)`

Unchanged.

#### (e) Glue 5.1 `--datalake-formats=iceberg` magic argument

Same magic-argument contract as 4.0 (auto-configures Spark
Iceberg classpath + catalog config), but the underlying Iceberg
library has bumped from 1.0.0 → **1.10.0**. Notable:

- Iceberg format **v2** remains the default `format-version` for
  newly-created tables (Iceberg upstream default; 1.10.0 honors it
  for backward compat).
- Iceberg format **v3.0** is opt-in via table property
  `format-version=3` or via Spark catalog conf
  `spark.sql.catalog.glue_catalog.write-format-version=3` —
  generators do NOT set this, so all writes land as v2.
- `createOrReplace()` (used by both generators) is atomic
  snapshot replacement, NOT merge-on-read — Iceberg v3.0
  deletion-vector defaults are inapplicable to this code path.

Canonical `DefaultArguments` block for the Glue 5.1 + Iceberg
path used by this spec:

```python
DefaultArguments = {
    "--datalake-formats": "iceberg",
    "--enable-metrics": "true",
    "--enable-continuous-cloudwatch-log": "true",
    "--enable-spark-ui": "false",
    "--TempDir": f"s3://{bucket}/tmp/",
    "--extra-py-files": f"s3://{bucket}/scripts/lib/product_generator.py",
    "--conf": f"spark.hadoop.fs.s3a.endpoint.region={region}",  # NEW for 5.1; see (k)
}
```

Source: [Glue 5.1 release notes](https://aws.amazon.com/about-aws/whats-new/2025/11/aws-glue-5-1/) +
existing working precedent at `platform-foundation/scripts/run-spark-spike.sh`
(4.0 variant; same default-arguments contract on 5.1 modulo (k))
+ live-verified by re-staging Glue jobs at 5.1 in this spec on
2026-06-10.

#### (f) Athena `start_query_execution` / `get_query_execution`

Unchanged from Glue 4.0 finding. **However**, see new finding (l)
below for an Iceberg v3 / Athena read incompatibility risk that
applies to the Phase 6 verification path.

#### (g) `aws_cdk.aws_iam.Role` — unchanged

The CDK construct is decoupled from the Glue runtime version. The
`adp-staging-foundation-spark-etl-role-us-east-1` role deployed in
Group 2 is reused as-is for Glue 5.1; no permission changes
required.

#### (h) `aws_cdk.aws_iam.PolicyStatement` — unchanged

Same minimum-IAM scope (S3 lake read/write, Glue catalog read/write
on the 2 target databases, Athena workgroup `primary`, CloudWatch
Logs `/aws-glue/jobs/*`, KMS lake-key `kms:ViaService`). No new
permissions required for Glue 5.1.

#### (i) `aws_cdk.aws_glue.CfnJob` — unchanged constructor signature

`GlueVersion` field accepts `'5.1'`. This spec deliberately does
NOT use CDK-managed Glue jobs (per spec Decision: one-shot boto3
jobs from a control script).

#### (j) Source URLs + verification dates

| Finding | Source | Date verified |
|---|---|---|
| (a) `create_job` accepts `GlueVersion='5.1'` | https://docs.aws.amazon.com/glue/latest/dg/migrating-version-51.html#migrating-version-51-actions | 2026-06-10 |
| (e) `--datalake-formats=iceberg` on 5.1 | https://docs.aws.amazon.com/glue/latest/dg/migrating-version-51.html (§ Appendix D) | 2026-06-10 |
| (k) S3A region default change | https://docs.aws.amazon.com/glue/latest/dg/migrating-version-51.html#migrating-version-51-from-50 | 2026-06-10 |
| (l) Iceberg v3 / Athena read | https://docs.aws.amazon.com/glue/latest/dg/migrating-version-51.html § "Apache Iceberg" | 2026-06-10 |

#### (k) NEW for 5.1 — S3A region conf REQUIREMENT

Glue 5.1 replaces EMRFS with S3A as the default S3 connector. Per
the [migration doc § "Migrating from AWS Glue 5.0 to AWS Glue 5.1"](https://docs.aws.amazon.com/glue/latest/dg/migrating-version-51.html#migrating-version-51-from-50):

> In AWS Glue 5.1, S3A filesystem has replaced EMRFS as the default
> S3 connector. If both `spark.hadoop.fs.s3a.endpoint` and
> `spark.hadoop.fs.s3a.endpoint.region` are not set, the default
> region used by S3A is `us-east-2`. This can cause issues, such
> as S3 upload timeout errors, especially for VPC jobs. To
> mitigate the issues caused by this change, set the
> `spark.hadoop.fs.s3a.endpoint.region` Spark configuration when
> using the S3A file system in AWS Glue 5.1.

**Mitigation in this spec**: the orchestration script
(`scripts/run-pyspark-products.py`) adds
`'--conf': f'spark.hadoop.fs.s3a.endpoint.region={region}'` to
DefaultArguments. Region is resolved live from the boto3 session
— **never** hardcoded. Verified 2026-06-10 via `aws glue get-job`
returning `Conf: "spark.hadoop.fs.s3a.endpoint.region=us-east-1"`
on both staged jobs.

**Alternative** (not used here, documented for completeness): pin
EMRFS as the S3 connector via:

```python
"--conf": (
    "spark.hadoop.fs.s3.impl=com.amazon.ws.emr.hadoop.fs.EmrFileSystem "
    "--conf spark.hadoop.fs.s3n.impl=com.amazon.ws.emr.hadoop.fs.EmrFileSystem "
    "--conf spark.hadoop.fs.AbstractFileSystem.s3.impl=org.apache.hadoop.fs.s3.EMRFSDelegate"
)
```

Rejected because S3A is the documented forward path; EMRFS-pinning
adds operational debt for a runtime that's increasingly the legacy
choice.

#### (l) NEW for 5.1 — Iceberg v3.0 / Athena read-incompatibility risk

Per the [Glue 5.1 migration doc § "Apache Iceberg"](https://docs.aws.amazon.com/glue/latest/dg/migrating-version-51.html#migrating-version-51-connector-driver-migration):

> Athena SQL compatibility — Cannot read Iceberg V3 tables created
> by EMR Spark due to error: `GENERIC_INTERNAL_ERROR: Cannot read
> unsupported version 3`

**Risk to this spec**: Phase 6 verification (T6.1) uses Athena to
re-run the contract queries. If our Glue 5.1 generators wrote
Iceberg v3 tables, Athena would fail to read them, and Phase 6
would FAIL.

**Mitigation analysis**:

1. **Default behavior**: Iceberg library 1.10.0 default
   `format-version` for new tables is **v2** (per Iceberg
   upstream defaults; v3 is opt-in only).
2. **Generator code**: both generators use
   `df.writeTo(...).using("iceberg").partitionedBy(...).createOrReplace()`
   — neither sets `format-version=3` as a table property nor sets
   the spark catalog conf for v3 writes.
3. **Inference**: writes will land as Iceberg v2 → Athena will
   read them.

**Empirical safety gate**: T4.1 step 5 (Athena `SELECT COUNT(*)`).
If Athena returns the documented `Cannot read unsupported version 3`
error, the contingency Spark conf to add is:

```python
"--conf": (
    f"spark.hadoop.fs.s3a.endpoint.region={region} "
    "--conf spark.sql.catalog.glue_catalog.write-format-version=2"
)
```

This explicitly pins format-version=2 on writeTo invocations
through the `glue_catalog` Iceberg catalog. Defer adding this
unless empirically required.

### Run results (sample tier, 2026-06-11 — Glue 5.1)

**Final empirical results from Group 4 + Group 5 (after 5 surgical fixes
detailed in `.kiro/specs/2026-06-09-adp-pyspark-glue-products/decisions.md`
2026-06-11 entry):**

| Metric | `vehicle_telemetry_aggregated` | `energy_usage` |
|---|---|---|
| Glue run elapsed | 240s | 361s |
| Iceberg table | ✓ Format=ICEBERG, Glue Catalog registered | ✓ Format=ICEBERG, Glue Catalog registered |
| Athena `SELECT COUNT(*)` | 10,000,000 | 10,000,000 |
| S3 parquet files | 1440 (90 dates × 16 buckets) | 91 (1/day × 90 days; no bucket transform) |
| Total bytes | 1.46 GiB | 1.01 GiB |
| bytes_per_row | 145.56 (within soft band [147,180]) | 108.91 (within broad band [50,500]) |
| Cost | ~$0.28 | ~$0.28 |

**Glue 5.1 winning config (locked for production-scale follow-up)**:

```bash
python3 scripts/run-pyspark-products.py \
    --stage staging --product both \
    --action stage-and-run \
    --rows 10000000 --days 90 --partitions 256 --seed 42 \
    --workers 4 --worker-type G.2X \
    --timeout-min 30 --wait
```

The default 2×G.1X / 64-partition config did NOT work for Iceberg V2
bucketed writes (off-heap pressure during the bucket(16, vin) shuffle
caused executor container kills). The winning config adds:
- `4 × G.2X` workers (8 DPU total, ~$0.28/run)
- `--partitions 256` for finer parallelism
- `spark.executor.memoryOverhead=6g` (off-heap headroom)
- `spark.sql.shuffle.partitions=400`

For production-scale (100M telemetry / 450M energy_usage), expect to
scale workers proportionally (e.g., `--workers 8 G.2X` for telemetry,
`--workers 16 G.2X` for energy_usage). Spike's 1124s baseline was for
plain parquet on 4.0; Glue 5.1's Iceberg writeTo path is similarly
linear.

**5 surgical fixes (under Constraint #2 relaxation 2026-06-11 — see
decisions.md for full diffs)**:

1. Generator `_LIB = Path(__file__)...parents[3]` IndexError on Glue's
   flat `/tmp/glue-job-XXX/` — wrapped in try/except.
2. Orchestration `--extra-py-files` now uploads + references both
   `product_generator.py` AND `schema_loader.py` (transitive import).
3. PyYAML installed via `--additional-python-modules pyyaml==6.0.2`
   (transitive dep of schema_loader).
4. Explicit Iceberg+GlueCatalog Spark conf block in `--conf` (Glue 5.1's
   `--datalake-formats=iceberg` magic loads classpath but doesn't
   auto-define the catalog name) + Lake Formation grants on the 2 target
   databases (LF blocks Iceberg writeTo with empty
   `CreateTableDefaultPermissions`).
5. `_load_vins` now does `.orderBy("vin")` before `.limit()` for
   deterministic VIN selection across the 5M-row dimensions parquet
   (avoids non-deterministic `dropDuplicates`+`limit` shuffle).


## ADP Vehicle Knowledge Base construct (spec 2026-06-16-adp-vehicle-knowledge-base)

Verified-API surface for the new `platform-foundation/stacks/vehicle_knowledge_base_stack.py`.
All findings here are referenced from spec.md § Design — implementation
tasks (authored separately as `tasks.md`) MUST cite this section, not
re-research APIs.

Verification date: 2026-06-16. CDK pinned at `aws-cdk-lib==2.255.0`
(per `platform-foundation/.venv` + closed cross-account-grants
`decisions.md` Q1).

### (a) `aws_bedrock.CfnKnowledgeBase` — vector KB construct

Source:
- AWS CFN: <https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrock-knowledgebase.html>
- AWS CDK Python: <https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_bedrock/CfnKnowledgeBase.html>
- AOSS prerequisites: <https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html>

```python
from aws_cdk import aws_bedrock as bedrock

kb = bedrock.CfnKnowledgeBase(
    self, "VehicleKB",
    name=f"adp-{stage}-vehicle-knowledge",
    description="Automotive technical reference — DTC, TSB, owner manual, ...",
    role_arn=kb_role.role_arn,
    knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
        type="VECTOR",
        vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
            embedding_model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0",
        ),
    ),
    storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
        type="OPENSEARCH_SERVERLESS",
        opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
            collection_arn=collection.attr_arn,                         # NOT placeholder
            field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                metadata_field="metadata",
                text_field="text",
                vector_field="vector",
            ),
            vector_index_name=f"adp-{stage}-vehicle-knowledge-index",
        ),
    ),
)
kb.add_dependency(index_custom_resource)
```

**Verified attrs available on `CfnKnowledgeBase`** (from closed grants
spec `decisions.md` Q2 — re-confirmed for this spec):

```
attr_created_at        attr_failure_reasons  attr_knowledge_base_arn
attr_knowledge_base_id attr_status           attr_updated_at
```

Use `attr_knowledge_base_arn` for `CfnResourcePolicy.resource_arn`.
Use `attr_knowledge_base_id` for the operator-facing CFN `Output` that
CVX wires via `-c adpKbId=<value>`.

**Pitfalls**:

- `CollectionArn` is **REQUIRED** — the legacy stack at
  `guidance-for-vehicle-knowledge-base/stacks/knowledge_base_stack.py:73`
  hard-codes `"PLACEHOLDER"`, which fails CFN validation. AOSS
  collection MUST be pre-created (CFN does not auto-provision the
  AOSS collection from KB).
- `VectorIndexName` is **REQUIRED** — index MUST be pre-created
  before KB enters ACTIVE status. Bedrock validates the index exists
  during the CFN create step.
- Updating any of `CollectionArn`, `FieldMapping`, `VectorIndexName`
  triggers REPLACEMENT (KB id changes — breaks downstream consumers).
  Pin these once at v1.

### (b) Titan v2 embedding-model ARN + dimensions

Source:
- <https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-titan-text-embeddings-v2.html>
- <https://aws.amazon.com/blogs/aws/amazon-titan-text-v2-now-available-in-amazon-bedrock-optimized-for-improving-rag/>

- **Model ID**: `amazon.titan-embed-text-v2:0`
- **Dimensions options**: 256 / 512 / **1024** (default). 256-dim
  retains ~97% accuracy of 1024 with 75% storage savings; 1024 is the
  default the existing artifacts producer emits as `embedding_model`
  metadata, so v1 stays at 1024 to match producer ↔ consumer.
- **ARN format**: `arn:aws:bedrock:{region}::foundation-model/amazon.titan-embed-text-v2:0`
  — embedding models are NOT inference-profile-scoped (no cross-region
  inference for embeddings), so the no-account foundation-model ARN is
  correct.
- **Distance metric**: AWS recommends Euclidean (`l2`) for floating-
  point Titan v2 vectors per
  <https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html>.

### (c) AOSS pre-creation prerequisites for Bedrock KB

Source: <https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html>
("Prerequisites for using a vector store you created"):

> 1. To configure permissions and create a vector search collection in
>    Amazon OpenSearch Serverless in the AWS Management Console, follow
>    steps 1 and 2 at [Working with vector search collections] ...
> 2. Once the collection is created, take note of the **Collection ARN**
>    for when you create the knowledge base.
> ...
> 4. Select the **Indexes** tab. Then choose **Create vector index**.
> ...
>    * **Engine** – The vector engine used for search. Select **faiss**.
>    * **Dimensions** – ... Titan V2 Embeddings - Text: **1,024, 512, and 256**
>    * **Distance metric** – ... We recommend using **Euclidean** for
>      floating-point vector embeddings.

CFN does not expose the AOSS index resource. The vector index MUST be
created via the OpenSearch REST API. CDK's standard pattern is a
Lambda-backed Custom Resource (see (e)).

### (d) `aws_opensearchserverless` constructs

Source:
- CFN: <https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_OpenSearchServerless.html>
- CDK Python: <https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_opensearchserverless.html>

```python
from aws_cdk import aws_opensearchserverless as oss
import json

COLLECTION_NAME = f"adp-{stage}-vehicle-knowledge"   # ≤32 chars, OK

# 1) Encryption policy (AWS-owned key for v1)
enc_policy = oss.CfnSecurityPolicy(
    self, "AossEncryptionPolicy",
    name=f"adp-{stage}-vkb-encryption",
    type="encryption",
    policy=json.dumps({
        "Rules": [{
            "ResourceType": "collection",
            "Resource": [f"collection/{COLLECTION_NAME}"],
        }],
        "AWSOwnedKey": True,
    }),
)

# 2) Network policy (public access in v1; private/VPC deferred)
net_policy = oss.CfnSecurityPolicy(
    self, "AossNetworkPolicy",
    name=f"adp-{stage}-vkb-network",
    type="network",
    policy=json.dumps([{
        "Rules": [
            {"ResourceType": "collection",
             "Resource": [f"collection/{COLLECTION_NAME}"]},
            {"ResourceType": "dashboard",
             "Resource": [f"collection/{COLLECTION_NAME}"]},
        ],
        "AllowFromPublic": True,
    }]),
)

# 3) Vector collection
collection = oss.CfnCollection(
    self, "AossCollection",
    name=COLLECTION_NAME,
    type="VECTORSEARCH",
    standby_replicas="DISABLED",                    # cost-min
)
collection.add_dependency(enc_policy)
collection.add_dependency(net_policy)

# 4) Data access policy
access_policy = oss.CfnAccessPolicy(
    self, "AossAccessPolicy",
    name=f"adp-{stage}-vkb-access",
    type="data",
    policy=json.dumps([{
        "Rules": [
            {"ResourceType": "index",
             "Resource": [f"index/{COLLECTION_NAME}/*"],
             "Permission": ["aoss:*"]},
            {"ResourceType": "collection",
             "Resource": [f"collection/{COLLECTION_NAME}"],
             "Permission": ["aoss:*"]},
        ],
        "Principal": [
            kb_role.role_arn,
            index_bootstrap_lambda_role.role_arn,
            # CDK exec role added if Phase A spike confirms admin needs.
        ],
    }]),
)
```

**Verified property names**:
- `CfnSecurityPolicy(name, type, policy[, description])` — `type` is
  `"encryption"` or `"network"` (NOT `"data"` — data access uses
  `CfnAccessPolicy`).
- `CfnCollection(name, type[, standby_replicas, description])` — `type`
  values: `"SEARCH"`, `"TIMESERIES"`, `"VECTORSEARCH"`. Use
  `"VECTORSEARCH"` for KB.
- `CfnAccessPolicy(name, type, policy[, description])` — `type` is
  `"data"`.
- All policies are JSON-document strings (NOT objects). Always use
  `json.dumps(...)` to serialize.

**Pitfalls**:
- AOSS policy `name` is account-region-unique. Stage-suffixing
  (`adp-{stage}-...`) is required to coexist staging+prod in the same
  account+region.
- Collection `name` ≤ 32 chars. `adp-staging-vehicle-knowledge` = 30
  chars (OK); `adp-prod-vehicle-knowledge` = 27 chars (OK).
- `standby_replicas="DISABLED"` reduces cost from 4-OCU to 2-OCU
  minimum but the floor is still ~$345/mo per stage.
- AOSS data access policy `Principal` accepts IAM ARNs (roles, users)
  AND `aws:` SAML federation principals. Phase A spike confirms whether
  the synth-time CFN exec role ARN is resolvable.

### (e) Vector index Custom Resource (Lambda + Provider framework)

CFN does not expose AOSS indexes. Pattern: `cr.Provider` + Lambda calling
the AOSS REST API with SigV4-signed requests.

Source: <https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.custom_resources.html>

```python
from aws_cdk import custom_resources as cr
from aws_cdk import aws_lambda as _lambda
from aws_cdk import Duration

# Lambda role with aoss:APIAccessAll on the collection
bootstrap_role = iam.Role(
    self, "AossIndexBootstrapRole",
    assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
    managed_policies=[
        iam.ManagedPolicy.from_aws_managed_policy_name(
            "service-role/AWSLambdaBasicExecutionRole")],
)
bootstrap_role.add_to_policy(iam.PolicyStatement(
    actions=["aoss:APIAccessAll"],
    resources=[collection.attr_arn]))

bootstrap_fn = _lambda.Function(
    self, "AossIndexBootstrap",
    runtime=_lambda.Runtime.PYTHON_3_12,
    handler="index.handler",
    code=_lambda.Code.from_asset("./lambda/aoss_index_bootstrap"),
    timeout=Duration.minutes(5),
    role=bootstrap_role,
    environment={
        "COLLECTION_ENDPOINT": collection.attr_collection_endpoint,
        "INDEX_NAME": f"adp-{stage}-vehicle-knowledge-index",
    },
)

provider = cr.Provider(
    self, "AossIndexProvider",
    on_event_handler=bootstrap_fn,
)

index_cr = CustomResource(
    self, "AossIndex",
    service_token=provider.service_token,
    properties={
        # CDK fingerprints these props; changing one triggers Update.
        "IndexName": f"adp-{stage}-vehicle-knowledge-index",
        "Dimensions": 1024,
    },
)
index_cr.node.add_dependency(access_policy)
index_cr.node.add_dependency(collection)
```

The Lambda handler (`./lambda/aoss_index_bootstrap/index.py`) — pinned
deps `boto3>=1.34`, `opensearch-py==2.6.0`, `requests-aws4auth==1.2.3`
(packaged via `aws_lambda.Code.from_asset` with `bundling=...` or a
zip layer). The PUT request body:

```json
{
  "settings": {
    "index": {"knn": true, "knn.algo_param.ef_search": 512}
  },
  "mappings": {
    "properties": {
      "vector":   {"type": "knn_vector", "dimension": 1024,
                   "method": {"engine": "faiss", "space_type": "l2",
                              "name": "hnsw", "parameters": {"ef_construction": 512, "m": 16}}},
      "text":     {"type": "text"},
      "metadata": {"type": "text", "index": false}
    }
  }
}
```

**Pitfalls**:
- IAM propagation delay: data access policy may not be effective the
  first time the Lambda calls AOSS. Use `tenacity` or hand-rolled
  retries with exponential backoff up to 5 minutes for 403 errors.
- 409 (index already exists) on Create is treated as success
  (idempotency).
- The `space_type` (`l2` vs `cosineil`) MUST match what Bedrock KB
  expects per the embedding model. Titan v2 + `l2` per AWS doc above.

### (f) `aws_bedrock.CfnDataSource` — S3 inclusion-prefix data source

```python
ds = bedrock.CfnDataSource(
    self, "VehicleKBSource",
    knowledge_base_id=kb.attr_knowledge_base_id,
    name="vehicle-knowledge-base-sources",
    description="ADP vehicle_knowledge_base chunked artifacts",
    data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
        type="S3",
        s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
            bucket_arn=f"arn:aws:s3:::{lake_bucket_name}",
            inclusion_prefixes=["knowledge/vehicle_knowledge_base/sources/"],
        ),
    ),
    vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
        chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
            chunking_strategy="FIXED_SIZE",
            fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                max_tokens=512,
                overlap_percentage=10,
            ),
        ),
    ),
)
```

The `chunkingStrategy=FIXED_SIZE` + `maxTokens=512` + `overlapPercentage=10`
matches the producer chunk shape (per `cvx-integration-contract.md § 5.2`
+ `vehicle_knowledge_base/schema.yaml` chunk constraints), so Bedrock
respects existing chunk boundaries instead of re-chunking.

**Ingestion is async** — `start_ingestion_job` (boto3) returns 202; poll
`get_ingestion_job` until `status=COMPLETE`. See "Bedrock Knowledge Base —
ingestion" earlier in this doc for the canonical pattern.

### (g) Cross-account `CfnResourcePolicy` (verbatim from closed grants spec)

Source (closed spec): `2026-06-09-adp-kb-cross-account-grants/decisions.md` Q1.

```python
def _attach_kb_resource_policy(self, kb_arn: str, principals: list[str]) -> None:
    if not principals:
        return                                    # single-account default
    bedrock.CfnResourcePolicy(
        self, "VehicleKBPolicy",
        resource_arn=kb_arn,                      # kb.attr_knowledge_base_arn
        policy_document=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "AllowCVXKbRetrieve",
                "Effect": "Allow",
                "Principal": {"AWS": principals},
                "Action": [
                    "bedrock-agent-runtime:Retrieve",
                    "bedrock-agent-runtime:RetrieveAndGenerate",
                ],
                "Resource": kb_arn,
            }],
        }),
    )
```

Verified class: `aws_bedrock.CfnResourcePolicy` (NOT `CfnKnowledgeBasePolicy`
— that name does not exist in `aws-cdk-lib==2.255.0`).

### (h) Source URLs + verification dates

| Topic | URL | Verified |
|---|---|---|
| `CfnKnowledgeBase` CFN ref | https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-bedrock-knowledgebase.html | 2026-06-16 |
| `OpenSearchServerlessConfiguration` | https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-bedrock-knowledgebase-opensearchserverlessconfiguration.html | 2026-06-16 |
| KB AOSS prerequisites | https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html | 2026-06-16 |
| KB security configurations | https://docs.aws.amazon.com/bedrock/latest/userguide/kb-create-security.html | 2026-06-16 |
| Titan v2 model card | https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-titan-text-embeddings-v2.html | 2026-06-16 |
| Titan v2 dimensions launch | https://aws.amazon.com/blogs/aws/amazon-titan-text-v2-now-available-in-amazon-bedrock-optimized-for-improving-rag/ | 2026-06-16 |
| AOSS CFN | https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/AWS_OpenSearchServerless.html | 2026-06-16 |
| AOSS CDK Python | https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_opensearchserverless.html | 2026-06-16 |
| Custom Resources CDK | https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.custom_resources.html | 2026-06-16 |
| Closed grants spec decisions | `automotive-data-platform-on-aws/.kiro/specs/2026-06-09-adp-kb-cross-account-grants/decisions.md` | 2026-06-09 (re-confirmed 2026-06-16) |

### (i) Phase-A spike notes (T1.1 — 2026-06-17)

Full resolution: `automotive-data-platform-on-aws/.kiro/specs/2026-06-16-adp-vehicle-knowledge-base/decisions.md`
`## 2026-06-17 — Phase A spike outputs (T1.1)`.

**Summary of 7 spike outputs:**

**1. Custom Resource shape — `cr.Provider` + Lambda (NOT `AwsCustomResource`)**

`AwsCustomResource` wraps a single SDK call; the AOSS index PUT
requires `opensearch-py` + `requests-aws4auth` over HTTP (no boto3
client for AOSS index admin). Full `cr.Provider` pattern confirmed:

```python
provider = cr.Provider(self, "AossIndexProvider", on_event_handler=bootstrap_fn)
index_cr = CustomResource(self, "AossIndex", service_token=provider.service_token,
    properties={"IndexName": index_name, "Dimensions": 1024})
```

`CfnCollection.attr_collection_endpoint` is confirmed present
(verified via `dir(o.CfnCollection)` 2026-06-17).

**2. Lambda-layer dep pins (all ≥7d quarantine as of 2026-06-17)**

```
boto3==1.40.0          # matches platform-foundation/requirements.txt
opensearch-py==2.6.0   # released 2024-05-28 — 389d before 2026-06-17
requests-aws4auth==1.2.3  # released 2023-05-03 — 776d before 2026-06-17
```

Verified via `.venv/bin/pip index versions opensearch-py` (latest=3.2.0;
2.6.0 in available list) and PyPI JSON API release timestamps.

**3. Data-access policy principal set — Q4 triple is sufficient**

Source: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-data-access.html
(2026-06-17). Principals must be IAM role ARNs within the same account.
The three principals (`kb_role`, `bootstrap_lambda_role`, `deploy_role_arn`)
are all same-account IAM role ARNs. `deploy_role_arn` is a synth-time
string literal (not a CFN token) — embeddable directly in the access
policy JSON.

**4. Collection-name lengths — both fit ≤32 chars**

```
$ python3 -c "print(len('adp-staging-vehicle-knowledge'), len('adp-prod-vehicle-knowledge'))"
29 26
```

**5. `kb.attr_knowledge_base_arn` — confirmed (citation from closed grants spec Q2)**

`attr_knowledge_base_arn` confirmed available on `aws_cdk.aws_bedrock.CfnKnowledgeBase`
in `aws-cdk-lib==2.255.0`. Cite closed spec; do not re-verify.

**6. Foundation-lake KMS posture — CMK; KB role needs explicit `kms:Decrypt`**

`foundation_stack.py` uses `s3.BucketEncryption.KMS` with `kms.Key(...)`.
The S3 L2 `grant_read()` does NOT add `kms:Decrypt` automatically —
an explicit `iam.PolicyStatement` is required. Constructor needs a
`lake_kms_key_arn: str` kwarg (mirrors `DataProductsStack`); wire via
`lake.kms_key.key_arn` in `app.py`.

**7. Deletion ordering — `RemovalPolicy.DESTROY` required on AOSS resources**

CFN does NOT infer reverse deletion order from `add_dependency`.
All AOSS resources (collection, enc_policy, net_policy, access_policy)
must set `apply_removal_policy(RemovalPolicy.DESTROY)` explicitly.
Operator pre-step: `stop-ingestion-job` before `cdk destroy` (documented
in T6.2 DEPLOYMENT.md runbook).

**CDK inspect output (verbatim, run 2026-06-17 from `platform-foundation/`):**

```
CfnKnowledgeBase: (self, scope: ..., id: str, *,
  knowledge_base_configuration: ..., name: str, role_arn: str,
  description: str | None = None,
  storage_configuration: ... | None = None,
  tags: Mapping[str, str] | None = None) -> None

CfnCollection: (self, scope: ..., id: str, *,
  name: str, collection_group_name: str | None = None,
  description: str | None = None, encryption_config: ... | None = None,
  standby_replicas: str | None = None,
  tags: Sequence[...] | None = None, type: str | None = None,
  vector_options: ... | None = None) -> None

CfnSecurityPolicy: (self, scope: ..., id: str, *,
  name: str, policy: str, type: str,
  description: str | None = None) -> None

CfnAccessPolicy: (self, scope: ..., id: str, *,
  name: str, policy: str, type: str,
  description: str | None = None) -> None

Provider: (self, scope: ..., id: str, *,
  on_event_handler: IFunction,
  disable_waiter_state_machine_logging: bool | None = None,
  ... [see decisions.md for full output] ...) -> None
```
