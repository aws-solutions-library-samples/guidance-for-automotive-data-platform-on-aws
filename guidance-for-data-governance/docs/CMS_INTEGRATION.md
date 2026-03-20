# Integrating with Connected Mobility Guidance

This guide explains how to connect the CMS telemetry pipeline to the data governance framework so that vehicle telemetry is automatically classified and split into PII and anonymized data stores.

## Integration Architecture

```
CMS Pipeline (connected-mobility-guidance-on-aws)
    │
    EventDrivenTelemetryProcessor (Flink)
    │
    ├── Redis (latest state)
    ├── Per-fleet Kafka topics (real-time)
    └── S3 Iceberg sink ──────────────────────┐
        cms-telemetry-preprocessed             │
        partitioned by fleetId + day           │
                                               ▼
                              ┌────────────────────────────────┐
                              │  Governance Integration        │
                              │  (this repo)                   │
                              │                                │
                              │  Glue Job: classify + split    │
                              │    ├── PII fields → PII bucket │
                              │    └── Anonymized → Anon bucket│
                              │                                │
                              │  Macie: scan PII bucket daily  │
                              │  Lake Formation: enforce access │
                              │  CloudTrail: audit all access  │
                              └────────────────────────────────┘
                                               │
                              ┌────────────────┴───────────────┐
                              ▼                                ▼
                    PII Data Store                  Anonymized Data Store
                    (EU region only)                (cross-region via
                    - precise GPS                    resource links)
                    - VIN, driver ID                - hashed IDs
                    - license plates                - city-level GPS
                                                   - aggregated metrics
```

## Prerequisites

- Connected Mobility Guidance deployed with Flink pipeline running (Phase 1-5)
- Data Governance stack deployed (`make deploy` in this repo)
- CMS S3 Iceberg sink writing to a datalake bucket

## Option 1: EventBridge Scheduled Integration

The simplest approach — a Glue job runs on a schedule, reads new telemetry from the CMS S3 sink, and writes classified output to the governance buckets.

### Deploy

```bash
# Set the CMS source bucket (where Flink writes Iceberg data)
export CMS_DATALAKE_BUCKET=cms-${DEPLOYMENT_STAGE}-datalake-${AWS_ACCOUNT_ID}

# Deploy the integration Glue job
make deploy-cms-integration \
  DEPLOYMENT_STAGE=${STAGE} \
  AWS_REGION=${REGION} \
  CMS_SOURCE_BUCKET=${CMS_DATALAKE_BUCKET}
```

### How It Works

1. EventBridge triggers the `classify-and-split` Glue job every hour
2. The job reads new Parquet/Iceberg files from the CMS datalake bucket
3. For each record:
   - PII fields (VIN, precise GPS, driver ID, license plate) are written to the PII bucket
   - Anonymized fields (hashed VIN, city-level GPS, aggregated metrics) are written to the anonymized bucket
4. Both outputs are registered in the Glue Data Catalog
5. Macie scans the PII bucket daily to verify no PII leaked to the anonymized store
6. Lake Formation enforces access policies on both databases

## Option 2: Kafka Consumer Integration

For near-real-time classification — an ECS Fargate consumer reads directly from `cms-telemetry-preprocessed` and writes to both governance buckets with sub-minute latency.

### When to Use This

- You need anonymized data available within seconds (not hourly)
- You want to avoid the S3 intermediate step
- You have high-volume telemetry that benefits from streaming classification

### Deploy

```bash
make deploy-cms-streaming-integration \
  DEPLOYMENT_STAGE=${STAGE} \
  AWS_REGION=${REGION}
```

## Option 3: S3 Event-Driven Integration

For event-driven processing — an S3 event notification triggers a Lambda when new files land in the CMS datalake bucket.

### When to Use This

- You want processing triggered by data arrival (not on a schedule)
- Your telemetry volume is moderate (Lambda handles individual files)

### Deploy

```bash
make deploy-cms-event-integration \
  DEPLOYMENT_STAGE=${STAGE} \
  AWS_REGION=${REGION} \
  CMS_SOURCE_BUCKET=${CMS_DATALAKE_BUCKET}
```

## Verifying the Integration

After deployment, verify data flows correctly:

```bash
# Check PII bucket has data
aws s3 ls s3://adp-${STAGE}-pii-data-${ACCOUNT}-${REGION}/telemetry/ --region ${REGION}

# Check anonymized bucket has data
aws s3 ls s3://adp-${STAGE}-anonymized-data-${ACCOUNT}-${REGION}/anonymized/ --region ${REGION}

# Query anonymized data via Athena
aws athena start-query-execution \
  --query-string "SELECT COUNT(*) FROM adp_${STAGE}_anonymized.vehicle_telemetry_anonymized" \
  --result-configuration OutputLocation=s3://adp-${STAGE}-anonymized-data-${ACCOUNT}-${REGION}/athena-results/ \
  --region ${REGION}

# Verify no PII in anonymized store (Macie findings)
aws macie2 list-findings --region ${REGION} \
  --finding-criteria '{"criterion":{"resourcesAffected.s3Bucket.name":{"eq":["adp-'${STAGE}'-anonymized-data-'${ACCOUNT}'-'${REGION}'"]}}}'
```

## Field Classification

The integration classifies each telemetry field:

| Field | Classification | PII Store | Anonymized Store |
|-------|---------------|-----------|-----------------|
| `vehicleId` | PII | Original | SHA-256 hash (first 16 chars) |
| `vin` | PII | Original | SHA-256 hash (first 16 chars) |
| `driverId` | PII | Original | SHA-256 hash (first 16 chars) |
| `licensePlate` | PII | Original | Dropped |
| `lat` | PII | Full precision | Truncated to 2 decimals (~1km) |
| `lng` | PII | Full precision | Truncated to 2 decimals (~1km) |
| `timestamp` | Quasi-PII | Original | Rounded to 5-minute intervals |
| `speed` | Non-PII | Original | Original |
| `odometer` | Non-PII | Original | Original |
| `engineRPM` | Non-PII | Original | Original |
| `fuelLevel` | Non-PII | Original | Original |
| `tire_fl/fr/rl/rr` | Non-PII | Original | Original |
| `fleetId` | Non-PII | Original | Original |
| `source` | Non-PII | Original | Original |
