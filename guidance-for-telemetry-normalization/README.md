# Telemetry Normalization — ADP Data Product

A use case for the Automotive Data Platform that provides normalized fleet telemetry as a queryable data product.

## What This Provides

- **Iceberg tables** for normalized telemetry and trip data, partitioned by `fleetId` for tenant isolation
- **Athena queries** for fleet utilization, trip analytics, signal coverage, and vehicle health
- **Lake Formation policies** for row-level security by fleet

## Data Flow

```
CMS Pipeline (connected-mobility-guidance-on-aws)
  → Flink processors normalize telemetry from all sources
  → S3 sink writes to datalake bucket (partitioned by fleetId + day)
  → Glue crawler registers Iceberg tables
  → Fleet operators query via Athena (scoped by fleetId)
```

## Prerequisites

- Connected Mobility Guidance deployed with Flink pipeline running
- S3 datalake bucket created by CMS storage stack
- Glue database for Iceberg tables

## Setup

1. Create the Glue database:
```bash
aws glue create-database --database-input '{"Name": "cms_telemetry"}'
```

2. Run the Iceberg DDL (replace `${DATALAKE_BUCKET}`):
```bash
# Execute via Athena
aws athena start-query-execution \
  --query-string "$(cat datasource/telemetry-lake/iceberg_tables.sql)" \
  --result-configuration OutputLocation=s3://${DATALAKE_BUCKET}/athena-results/
```

3. Apply Lake Formation policies per the templates in `datasource/telemetry-lake/lake_formation_policies.json`

## Athena Queries

| Query | Purpose |
|-------|---------|
| `fleet_utilization.sql` | Daily metrics per fleet (active vehicles, trips, miles, avg speed) |
| `normalized_trips.sql` | Trip history across all sources for a fleet |
| `oem_signal_coverage.sql` | Signal availability by source/OEM |
| `vehicle_health_snapshot.sql` | Latest telemetry per vehicle in a fleet |

All queries accept `${FLEET_ID}` as a parameter for fleet scoping.
