"""
CMS Telemetry Classification and Split — AWS Glue ETL Job

Reads normalized telemetry from the CMS Iceberg/S3 datalake sink,
classifies fields as PII or non-PII, and writes to separate governance
data stores.

Output:
  - PII bucket: full-fidelity records with all fields
  - Anonymized bucket: hashed IDs, truncated GPS, rounded timestamps
"""
import sys
import hashlib
import math
from datetime import datetime, timedelta
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, DoubleType

args = getResolvedOptions(sys.argv, [
    'JOB_NAME',
    'cms_source_bucket',
    'cms_source_prefix',
    'pii_bucket',
    'anonymized_bucket',
    'lookback_hours',
])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

LOOKBACK_HOURS = int(args.get('lookback_hours', '2'))

# ── UDFs ──────────────────────────────────────────────────────────

@F.udf(returnType=StringType())
def hash_sha256(value):
    if value is None:
        return None
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]

@F.udf(returnType=DoubleType())
def truncate_coord(value):
    if value is None:
        return None
    return math.floor(float(value) * 100) / 100

@F.udf(returnType=StringType())
def round_ts_5min(ts_ms):
    if ts_ms is None:
        return None
    interval = 5 * 60 * 1000
    return str((int(ts_ms) // interval) * interval)

# ── Read CMS telemetry from S3 ───────────────────────────────────

source_path = f"s3://{args['cms_source_bucket']}/{args['cms_source_prefix']}"
print(f"Reading from {source_path}")

try:
    source_df = spark.read.parquet(source_path)
except Exception:
    # Try Iceberg format
    source_df = spark.read.format("iceberg").load(source_path)

record_count = source_df.count()
print(f"Source records: {record_count}")

if record_count == 0:
    print("No records to process")
    job.commit()
    sys.exit(0)

# ── Write PII copy (full fidelity) ───────────────────────────────

pii_path = f"s3://{args['pii_bucket']}/telemetry/"
source_df.write \
    .mode('append') \
    .partitionBy('fleetId') \
    .parquet(pii_path)
print(f"PII records written to {pii_path}")

# ── Build anonymized copy ─────────────────────────────────────────

anon_df = source_df

# Hash PII identifiers
for field in ['vin', 'vehicleId', 'driverId']:
    if field in anon_df.columns:
        anon_df = anon_df.withColumn(field, hash_sha256(F.col(field)))

# Drop high-PII fields entirely
for field in ['licensePlate', 'driverName', 'driverEmail', 'driverPhone',
              'ownerName', 'ownerEmail', 'address']:
    if field in anon_df.columns:
        anon_df = anon_df.drop(field)

# Truncate GPS to city-level
for field in ['lat', 'lng']:
    if field in anon_df.columns:
        anon_df = anon_df.withColumn(field, truncate_coord(F.col(field)))

# Round timestamps to 5-minute intervals
if 'timestamp' in anon_df.columns:
    anon_df = anon_df.withColumn('timestamp', round_ts_5min(F.col('timestamp')))

# Add governance metadata
anon_df = anon_df.withColumn('_anonymized', F.lit(True))
anon_df = anon_df.withColumn('_classified_at', F.current_timestamp())

anon_path = f"s3://{args['anonymized_bucket']}/anonymized/telemetry/"
anon_df.write \
    .mode('append') \
    .partitionBy('fleetId') \
    .parquet(anon_path)
print(f"Anonymized records written to {anon_path}")

print(f"Classification complete: {record_count} records → PII + anonymized")
job.commit()
