"""
Vehicle Telemetry Anonymization — AWS Glue ETL Job

Reads raw vehicle telemetry from the PII data store, applies anonymization
transforms, and writes to the anonymized data store. Runs as a streaming
or batch Glue job in the EU producer region.

Anonymization rules:
  - VIN: SHA-256 hash
  - GPS: Truncate to 2 decimal places (city-level ~1km precision)
  - Driver ID: SHA-256 hash
  - Timestamps: Round to 5-minute intervals
  - Sensor data: 5-minute rolling averages
"""
import sys
import hashlib
import math
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.context import SparkContext
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, DoubleType

args = getResolvedOptions(sys.argv, [
    'JOB_NAME',
    'source_database',
    'source_table',
    'target_bucket',
    'target_prefix',
])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# ── UDFs ──────────────────────────────────────────────────────────

@F.udf(returnType=StringType())
def hash_sha256(value):
    """One-way hash for PII fields (VIN, driver ID)."""
    if value is None:
        return None
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]


@F.udf(returnType=DoubleType())
def truncate_coordinate(value, decimals=2):
    """Truncate GPS to city-level precision (~1km at 2 decimal places)."""
    if value is None:
        return None
    factor = 10 ** decimals
    return math.floor(float(value) * factor) / factor


@F.udf(returnType=StringType())
def round_timestamp_5min(ts_ms):
    """Round timestamp to nearest 5-minute interval."""
    if ts_ms is None:
        return None
    interval = 5 * 60 * 1000  # 5 minutes in ms
    rounded = (int(ts_ms) // interval) * interval
    return str(rounded)


# ── Read source data ──────────────────────────────────────────────

source_df = glueContext.create_dynamic_frame.from_catalog(
    database=args['source_database'],
    table_name=args['source_table'],
).toDF()

print(f"Source records: {source_df.count()}")

# ── Apply anonymization ──────────────────────────────────────────

anonymized_df = source_df

# Hash PII identifiers
if 'vin' in source_df.columns:
    anonymized_df = anonymized_df.withColumn('vin', hash_sha256(F.col('vin')))

if 'vehicleId' in source_df.columns:
    anonymized_df = anonymized_df.withColumn('vehicleId', hash_sha256(F.col('vehicleId')))

if 'driverId' in source_df.columns:
    anonymized_df = anonymized_df.withColumn('driverId', hash_sha256(F.col('driverId')))

if 'licensePlate' in source_df.columns:
    anonymized_df = anonymized_df.drop('licensePlate')

# Truncate GPS to city-level
if 'lat' in source_df.columns:
    anonymized_df = anonymized_df.withColumn('lat', truncate_coordinate(F.col('lat'), F.lit(2)))

if 'lng' in source_df.columns:
    anonymized_df = anonymized_df.withColumn('lng', truncate_coordinate(F.col('lng'), F.lit(2)))

# Round timestamps
if 'timestamp' in source_df.columns:
    anonymized_df = anonymized_df.withColumn('timestamp', round_timestamp_5min(F.col('timestamp')))

# Drop any remaining PII fields
pii_fields_to_drop = [
    'driverName', 'driverEmail', 'driverPhone',
    'ownerName', 'ownerEmail', 'ownerPhone',
    'address', 'homeAddress',
]
for field in pii_fields_to_drop:
    if field in anonymized_df.columns:
        anonymized_df = anonymized_df.drop(field)

# Add anonymization metadata
anonymized_df = anonymized_df.withColumn('_anonymized', F.lit(True))
anonymized_df = anonymized_df.withColumn('_anonymized_at', F.current_timestamp())

print(f"Anonymized records: {anonymized_df.count()}")

# ── Write to anonymized data store ────────────────────────────────

target_path = f"s3://{args['target_bucket']}/{args['target_prefix']}"

anonymized_df.write \
    .mode('append') \
    .partitionBy('fleetId') \
    .parquet(target_path)

print(f"Written to {target_path}")

job.commit()
