# Telemetry Normalization — Architecture Guide

## Problem

Fleet operators manage vehicles from multiple telemetry sources: OEM cloud-to-cloud APIs, AWS IoT FleetWise (CAN bus), and direct MQTT connections. Each source uses different signal names, units, encodings, authentication mechanisms, and delivery patterns. Without normalization, every downstream application must handle every source format individually.

## Solution

A normalization layer that converts all telemetry sources into a single canonical format before any downstream processing occurs. The signal catalog is the contract — every source maps to the same field names and units.

---

## 1. Cloud-to-Cloud OEM Integration

### The Challenge

Each OEM exposes vehicle telemetry through their own cloud API with proprietary authentication, data formats, and delivery mechanisms. A fleet with vehicles from multiple manufacturers needs a single integration point.

### Authentication Patterns

OEM cloud APIs use standard OAuth 2.0 flows, but the specifics vary:

| Pattern | Flow | Use Case |
|---------|------|----------|
| REST Polling | OAuth 2.0 `client_credentials` → poll REST endpoints on a schedule | OEMs that expose request/response APIs |
| Push/Streaming | OAuth 2.0 partner token exchange → OEM pushes to your endpoint via WebSocket or webhook | OEMs that push telemetry in real-time |

Credentials (client ID, client secret, token endpoints) are stored in AWS Secrets Manager. Each OEM connector authenticates independently and writes raw telemetry to a shared Kafka topic (`cms-telemetry-oem`) with an `oem_source` field identifying the origin.

### Connector Architecture

```
┌─────────────────────────────────────────────────────────┐
│  OEM Connectors                                         │
│                                                         │
│  REST Polling Connector (Lambda + EventBridge)          │
│    • Scheduled invocation (e.g., every 5 minutes)       │
│    • Authenticate via OAuth 2.0 client_credentials      │
│    • Poll OEM REST API for latest telemetry             │
│    • Write raw JSON to Kafka: cms-telemetry-oem         │
│                                                         │
│  Streaming Connector (ECS Fargate)                      │
│    • Long-running receiver service                      │
│    • OEM pushes data via WebSocket/protobuf             │
│    • Decode wire format, write to Kafka                 │
│    • Requires public endpoint (ALB + TLS)               │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
                  cms-telemetry-oem (Kafka)
                  with oem_source field
```

### Transform Manifests

Each OEM's data is normalized using a **transform manifest** — a JSON configuration that maps OEM-specific field names, paths, and units to the canonical schema. No code changes are required to add a new OEM; only a new manifest.

```json
{
  "source_name": "<oem-identifier>",
  "vehicle_id_extraction": {
    "strategy": "json_path",
    "path": "<path-to-vehicle-id>"
  },
  "signal_mappings": [
    {
      "source_signal": "SPEED",
      "cms_field": "speed",
      "source_path": "data.speedValue",
      "unit_conversion": "mps_to_mph",
      "data_type": "float"
    }
  ]
}
```

Manifests are stored in S3 and loaded by the OEM preprocessor at runtime. The OEM Integration Wizard in the CMS UI can auto-generate manifests from sample telemetry data.

---

## 2. Normalization Pipeline

### Source-Specific Preprocessing

Three Flink preprocessors handle the different wire formats, all outputting the same canonical JSON:

```
INGESTION (source-specific Kafka topics)
├── cms-telemetry-raw          ← Direct/MQTT (gzip+base64 JSON)
├── fw-telemetry-raw           ← FleetWise Edge (protobuf, snappy)
└── cms-telemetry-oem          ← OEM cloud-to-cloud (raw OEM JSON)

PREPROCESSING (source-specific → canonical JSON)
├── SimulatorPreprocessor      : decompress only (already uses canonical fields)
├── FWTelemetryProcessor       : decode protobuf → VSS path → canonical field
└── OEMTelemetryProcessor      : apply transform manifest → canonical field

All three output to: cms-telemetry-preprocessed
```

### Signal Catalog as the Contract

The signal catalog DynamoDB table defines every canonical signal:

| Field | Example | Purpose |
|-------|---------|---------|
| `signal_group` | `core_telemetry` | Partition key |
| `signal_name` | `VehicleSpeed` | Human-readable name |
| `json_field` | `speed` | Canonical field name in all normalized messages |
| `unit` | `mph` | Canonical unit |
| `data_type` | `float` | Expected type |

Every preprocessor maps its source signals to `json_field` values. This is the normalization target.

### Canonical Message Format

Every message on `cms-telemetry-preprocessed`:

```json
{
  "vehicleId": "VEH-001",
  "timestamp": 1710764400000,
  "source": "simulator | fleetwise | oem",
  "speed": 65.2,
  "odometer": 45230.1,
  "lat": 47.6062,
  "lng": -122.3321,
  "heading": 180.5,
  "ignitionOn": true,
  "engineRPM": 2100,
  "fuelLevel": 72.3,
  "tire_fl": 35.2,
  "tire_fr": 34.8
}
```

Field names are `json_field` values from the signal catalog. Units are canonical (mph, °F, PSI, miles). Not all fields are present in every message — availability depends on the source.

### Unit Conversions

Applied by preprocessors during normalization:

| Conversion | Formula | When Used |
|-----------|---------|-----------|
| m/s → mph | `× 2.23694` | OEM speed in metric |
| km/h → mph | `× 0.621371` | OEM speed in km/h |
| km → miles | `× 0.621371` | OEM odometer |
| °C → °F | `(× 9/5) + 32` | OEM temperature |
| kPa → PSI | `× 0.145038` | OEM tire pressure (kPa) |
| bar → PSI | `× 14.5038` | OEM tire pressure (bar) |
| m/s² → g | `÷ 9.80665` | OEM acceleration |

---

## 3. Data Storage & Analytics

### Routing

The `EventDrivenTelemetryProcessor` (Flink) reads from `cms-telemetry-preprocessed` and routes each message to multiple destinations:

```
cms-telemetry-preprocessed
    │
    ├── Redis — latest vehicle state (signals, geo index, sparkline streams)
    ├── cms-telemetry-processed — persistence
    ├── cms-telemetry-trips — trip processor
    ├── cms-telemetry-safety — safety event detection
    ├── cms-telemetry-maintenance — maintenance alert generation
    ├── cms-fleet-{fleetId}-telemetry — per-fleet real-time feed
    └── S3 Iceberg sink — historical analytics (partitioned by fleetId + day)
```

### Fleet Enrollment & Tenant Isolation

Each vehicle is enrolled in exactly one fleet. The enrollment table maps `vehicleId → fleetId`. The Flink processor looks up this mapping (Redis-cached, DynamoDB fallback) to:

- Route messages to per-fleet Kafka topics
- Inject `fleetId` into the message payload
- Partition S3 data by fleet for Lake Formation row-level security

### Iceberg Tables

Normalized telemetry is stored in Iceberg format for Athena queries:

```sql
CREATE TABLE cms_normalized_telemetry (
    vehicleId STRING, fleetId STRING, timestamp_ms BIGINT,
    source STRING, speed DOUBLE, odometer DOUBLE,
    lat DOUBLE, lng DOUBLE, heading DOUBLE,
    ignitionOn BOOLEAN, engineRPM DOUBLE, fuelLevel DOUBLE,
    tire_fl DOUBLE, tire_fr DOUBLE, tire_rl DOUBLE, tire_rr DOUBLE,
    tripId STRING, driverId STRING
)
PARTITIONED BY (fleetId, days(from_unixtime(timestamp_ms/1000)))
```

Partitioned by `fleetId` first, then day — Lake Formation enforces row-level security so fleet operators can only query their own fleet's partitions.

### Pre-Built Athena Queries

| Query | Purpose |
|-------|---------|
| `fleet_utilization.sql` | Daily active vehicles, trips, miles, avg speed per fleet |
| `normalized_trips.sql` | Trip history across all sources |
| `oem_signal_coverage.sql` | Which signals each source provides |
| `vehicle_health_snapshot.sql` | Latest telemetry per vehicle |

---

## 4. Real-Time Telemetry Distribution

Fleet operators need live telemetry for their enrolled vehicles. The distribution layer pushes FleetWise Edge telemetry to connected consumers via WebSocket.

### Why FWE Data Only

FleetWise Edge provides high-frequency, low-latency telemetry directly from the vehicle's CAN bus (sub-second updates). OEM cloud-to-cloud data is polled on longer intervals (minutes) and is better served via the REST API or Athena queries. Real-time push is most valuable for the live, high-frequency FWE stream.

### Architecture

```
EventDrivenTelemetryProcessor (Flink)
    │
    │  Filters source=fleetwise messages
    │  Looks up vehicleId → fleetId from enrollment table
    │
    ├── cms-fleet-{fleetId}-telemetry (per-fleet Kafka topic)
    │
    └── ECS Fargate Consumer (ws-fanout)
            │  Regex subscribe: cms-fleet-.*-telemetry
            │  Query DDB fleetId-index → active WebSocket connections
            │  Push to each connection via API Gateway Management API
            │
            ▼
        API Gateway WebSocket API
            │  wss://{endpoint}/live?fleetId={id}&token={jwt}
            │
            ▼
        External Consumer Applications
            Fleet operator dashboards, mobile apps, partner integrations
```

### Security

- WebSocket `$connect` validates the JWT and checks `custom:fleetIds` claim
- Platform admins can subscribe to any fleet
- Fleet operators/viewers can only subscribe to their assigned fleets
- Connections auto-expire after 24 hours

### Components

| Component | Purpose |
|-----------|---------|
| WebSocket API Gateway | Endpoint for external consumers |
| WS Handler Lambda | Connection management, JWT validation |
| WS Connections Table | DDB with `fleetId-index` GSI |
| Fanout Consumer | ECS Fargate — Kafka→WebSocket bridge |

### REST API Fallback

For consumers that don't support WebSocket, or for OEM-sourced data, latest vehicle state is available via REST:

```
GET /api/v1/vehicles/{vehicleId}     → latest telemetry (any source)
GET /api/v1/vehicles/locations       → all vehicle positions
```

These endpoints return data from Redis and include telemetry from all sources (FWE, OEM, simulator).

---

## 5. Tenant Access Model

Three Cognito groups control access across all consumption layers:

| Role | Data Scope | Capabilities |
|------|-----------|-------------|
| Platform Admin | All fleets | Full system access, OEM connector management, user management |
| Fleet Operator | Own fleet(s) | View vehicles/trips/telemetry, subscribe to real-time feed, manage drivers |
| Fleet Viewer | Own fleet(s) | Read-only dashboard access |

The API Lambda extracts `cognito:groups` and `custom:fleetIds` from the JWT and filters every query. Lake Formation enforces the same boundaries on Athena. WebSocket connections are scoped by `fleetId` at connect time.

---

## 6. Adding a New OEM

No code changes required — only configuration:

1. Create a transform manifest JSON mapping the OEM's signals to canonical `json_field` values
2. Upload to S3: `s3://{manifests-bucket}/transforms/{oem}-transform.json`
3. Build a connector:
   - **REST polling OEM**: Lambda + EventBridge schedule
   - **Streaming/push OEM**: ECS Fargate receiver with public ALB
4. Store OAuth credentials in Secrets Manager
5. Connector writes raw OEM JSON to `cms-telemetry-oem` Kafka topic with `oem_source` field
6. `OEMTelemetryProcessor` automatically loads the manifest and normalizes

The OEM Integration Wizard in the CMS UI can auto-generate transform manifests from sample telemetry data uploaded by the platform admin.

---

## 7. Deployment

### Prerequisites (CMS Pipeline)

The following must be deployed from `connected-mobility-guidance-on-aws` before deploying this data product:

```bash
cd connected-mobility-guidance-on-aws/deployment

# Phase 1: Storage (DynamoDB tables), IoT Core, UI (API Gateway, Cognito, WebSocket, CloudFront)
make phase1 DEPLOYMENT_STAGE=prod AWS_REGION=us-east-2

# Seed fleet enrollment data
make seed-fleet-enrollment DEPLOYMENT_STAGE=prod AWS_REGION=us-east-2

# Phase 3: MSK cluster (Kafka + VPC + Redis)
make phase3 DEPLOYMENT_STAGE=prod AWS_REGION=us-east-2

# Phase 3b: IoT Core → MSK telemetry routing
make phase3b DEPLOYMENT_STAGE=prod AWS_REGION=us-east-2

# Phase 4: Flink applications (preprocessors + EventDrivenTelemetryProcessor)
make phase4 DEPLOYMENT_STAGE=prod AWS_REGION=us-east-2

# Phase 5: Configure Flink with MSK bootstrap servers + enrollment table
make configure-flink DEPLOYMENT_STAGE=prod AWS_REGION=us-east-2
```

### ADP Data Product (this repo)
```bash
cd automotive-data-platform-on-aws/guidance-for-telemetry-normalization

# Deploy WebSocket fanout service (Kafka → WebSocket bridge)
./deploy.sh --stage prod --region us-east-2

# Create Glue database for Iceberg tables
aws glue create-database --database-input '{"Name": "cms_telemetry"}' --region us-east-2

# Run Iceberg DDL via Athena — see datasource/telemetry-lake/iceberg_tables.sql
# Apply Lake Formation policies — see datasource/telemetry-lake/lake_formation_policies.json
```
