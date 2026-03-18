# Telemetry Normalization — Architecture Guide

## Problem

Fleet operators manage vehicles from multiple sources: OEM cloud APIs (Ford, Tesla), AWS IoT FleetWise (CAN bus), and direct MQTT connections (simulators, aftermarket devices). Each source uses different signal names, units, encodings, and delivery mechanisms. Without normalization, downstream applications (trip analytics, safety alerts, maintenance predictions) must handle every source format individually.

## Solution

A normalization layer that converts all telemetry sources into a single canonical format before any downstream processing occurs. The signal catalog DynamoDB table is the contract — every source maps to the same `json_field` names and units.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  INGESTION (source-specific Kafka topics)                            │
│                                                                      │
│  IoT Core ──→ cms-telemetry-raw          (gzip+base64 JSON)         │
│  FleetWise ──→ fw-telemetry-raw          (protobuf, snappy)         │
│  OEM APIs ──→ cms-telemetry-oem          (raw OEM JSON)             │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  NORMALIZATION (Flink preprocessors → canonical JSON)                │
│                                                                      │
│  SimulatorPreprocessor    : decompress gzip+base64                   │
│  FWTelemetryProcessor     : decode protobuf → VSS path → json_field  │
│  OEMTelemetryProcessor    : apply transform manifest → json_field    │
│                                                                      │
│  All three output to: cms-telemetry-preprocessed                     │
└──────────────┬───────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  ROUTING & DISTRIBUTION (EventDrivenTelemetryProcessor)              │
│                                                                      │
│  ┌─→ Redis (vehicle state, geo index, sparkline streams)             │
│  ├─→ cms-telemetry-processed (persistence)                           │
│  ├─→ cms-telemetry-trips / safety / maintenance (domain processors)  │
│  ├─→ cms-fleet-{fleetId}-telemetry (per-fleet real-time feed)        │
│  └─→ S3 Iceberg sink (historical analytics, partitioned by fleetId)  │
└──────────────────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  CONSUMPTION                                                         │
│                                                                      │
│  CMS UI (WebSocket) ← per-fleet Kafka topic ← live telemetry        │
│  REST API            ← Redis latest state    ← vehicle snapshots     │
│  Athena              ← Iceberg tables        ← historical analytics  │
└──────────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### Signal Catalog as the Contract

The `cms-{stage}-signal-catalog` DynamoDB table defines every canonical signal:

| Field | Example | Purpose |
|-------|---------|---------|
| `signal_group` | `core_telemetry` | Partition key |
| `signal_name` | `VehicleSpeed` | Human-readable name |
| `json_field` | `speed` | Canonical field name in all normalized messages |
| `unit` | `mph` | Canonical unit |

Every preprocessor maps its source signals to `json_field` values. The OEM Integration Wizard validates transform manifests against this catalog at generation time.

### Transform Manifests (OEM Path)

OEM data arrives as JSON with OEM-specific field names and units. A transform manifest defines the mapping:

```json
{
  "source_name": "ford",
  "signal_mappings": [
    {
      "source_signal": "SPEED",
      "cms_field": "speed",
      "source_path": "typedData.speedValue.speed",
      "unit_conversion": "mps_to_mph"
    }
  ]
}
```

Manifests are stored in S3 and loaded by `OEMTelemetryProcessor` at runtime. New OEMs are added by creating a new manifest — no code changes required.

### Decoder Manifests (FleetWise Path)

FleetWise uses integer signal IDs on the wire. The decoder manifest maps `signalId → VSS path`, then the signal catalog maps `VSS path → json_field`. Two-step mapping because FleetWise uses a binary wire format.

### Per-Fleet Distribution

`EventDrivenTelemetryProcessor` looks up each vehicle's `fleetId` from the enrollment table (Redis-cached, DynamoDB fallback) and writes to `cms-fleet-{fleetId}-telemetry`. Fleet operators connect via WebSocket and receive only their fleet's data.

### Tenant Isolation

Three Cognito groups control access:

| Role | Data Scope | Write Access |
|------|-----------|-------------|
| Platform Admin | All fleets | Full |
| Fleet Operator | Own fleet(s) | Vehicles, drivers |
| Fleet Viewer | Own fleet(s) | Read-only |

The API Lambda extracts `cognito:groups` and `custom:fleetIds` from the JWT and filters every query. Lake Formation row-level security enforces the same boundaries on Athena queries.

## Components Across Repos

### connected-mobility-guidance-on-aws (Processing Pipeline)

| Component | Technology | Purpose |
|-----------|-----------|---------|
| SimulatorPreprocessor | Flink (Java) | Decompress simulator data |
| FWTelemetryProcessor | Flink (Java) | Decode FleetWise protobuf |
| OEMTelemetryProcessor | Flink (Java) | Apply OEM transform manifests |
| EventDrivenTelemetryProcessor | Flink (Java) | Redis write, domain routing, per-fleet distribution |
| CMS UI | React + CloudScape | Fleet portal with role-based views |
| Fleet API | Lambda (Python) | CRUD + authorization enforcement |
| WebSocket API | API Gateway WebSocket + Lambda | Real-time telemetry push |
| Signal Catalog | DynamoDB | Canonical signal definitions |
| Fleet Enrollment | DynamoDB | Vehicle → fleet mapping |
| Transform Manifests | S3 | OEM signal mapping configs |

### automotive-data-platform-on-aws (Data Product)

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Iceberg Tables | Glue + S3 | Normalized telemetry + trips (partitioned by fleetId) |
| Athena Queries | Athena | Fleet utilization, trip history, signal coverage, vehicle health |
| Lake Formation Policies | Lake Formation | Row-level security by fleetId |

## Canonical Message Format

Every message on `cms-telemetry-preprocessed` and per-fleet topics:

```json
{
  "vehicleId": "VEH-001",
  "fleetId": "FLEET-001",
  "timestamp": 1710764400000,
  "source": "simulator | fleetwise | oem",
  "oem": "ford | tesla | null",
  "speed": 65.2,
  "odometer": 45230.1,
  "lat": 47.6062,
  "lng": -122.3321,
  "heading": 180.5,
  "ignitionOn": true,
  "engineRPM": 2100,
  "engineTemp": 195.0,
  "fuelLevel": 72.3,
  "batteryVoltage": 13.8,
  "tire_fl": 35.2,
  "tire_fr": 34.8,
  "tire_rl": 33.1,
  "tire_rr": 33.5,
  "tripId": "TRIP-abc123",
  "driverId": "DRV-456"
}
```

Units: mph, miles, °F, PSI. Field names match `json_field` in the signal catalog.

## Unit Conversions

Applied by preprocessors during normalization:

| Conversion | Formula | Source |
|-----------|---------|--------|
| `mps_to_mph` | `× 2.23694` | Ford speed |
| `km_to_miles` | `× 0.621371` | Ford odometer |
| `C_to_F` | `(× 9/5) + 32` | Ford/Tesla temp |
| `kpa_to_psi` | `× 0.145038` | Ford tire pressure |
| `bar_to_psi` | `× 14.5038` | Tesla tire pressure |
| `mps2_to_g` | `÷ 9.80665` | Tesla acceleration |

## Deployment

### Prerequisites
- Connected Mobility Guidance deployed (Flink pipeline, MSK, Redis, CMS UI)
- S3 datalake bucket from CMS storage stack

### CMS Pipeline (connected-mobility-guidance-on-aws)
```bash
cd deployment
make phase1          # Storage + UI (includes enrollment table, Cognito groups, WebSocket API)
make seed-fleet-enrollment   # Backfill enrollment table
make phase4          # Flink apps
make configure-flink # Configure with enrollment table
```

### ADP Data Product (this repo)
```bash
# Create Glue database
aws glue create-database --database-input '{"Name": "cms_telemetry"}'

# Run Iceberg DDL via Athena
# See datasource/telemetry-lake/iceberg_tables.sql
```

## Adding a New OEM

1. Create a transform manifest JSON mapping OEM signals to `json_field` values
2. Upload to S3: `s3://{manifests-bucket}/transforms/{oem}-transform.json`
3. Build a connector (Lambda for REST polling, ECS Fargate for WebSocket/streaming)
4. Connector writes raw OEM JSON to `cms-telemetry-oem` Kafka topic with `oem_source` field
5. `OEMTelemetryProcessor` automatically picks up the manifest and normalizes

No Flink code changes required — the transform manifest is the only configuration.
