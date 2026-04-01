# TCO Optimization — Architecture Diagram Narrative

**Title:** Guidance for an Automotive Data Platform on AWS
**Subtitle:** Creating operational value from Fleet Cost Intelligence
**Tagline:** Build an agentic cost optimization pipeline that turns fleet spend data into autonomous savings

---

## Numbered Steps (left to right, top to bottom)

### 1 — Cost Data Ingestion

**Left column — four source categories:**

**Vehicle Telemetry** (existing CMS pipeline)
- Amazon MSK (`cms-telemetry-preprocessed` topic)
- Fuel consumption, EV energy, idle time, DTCs — derived from canonical signals

**Fuel & Energy**
- Fuel card transactions (WEX, Comdata, FleetCor)
- EV charging sessions (ChargePoint, EVgo, Electrify America)
- Bulk fuel / on-site depot inventory

**Maintenance & Repair**
- Fleet maintenance systems (Fleetio, TMT, Whip Around)
- Parts procurement, tire management, roadside assistance
- OEM service portals, warranty claims, recall service records

**Asset & Financial**
- Lease/finance providers (Element Fleet, ARI)
- Insurance premiums and claims
- Market pricing (Manheim, KBB/NADA) for buy/sell timing
- Registration, permits, tolls

---

### 2 — Cost Normalization & Processing (Amazon MSK + Apache Flink)

**Center — Flink applications:**

Source-specific normalizers convert each cost feed into canonical format:
- FuelCostNormalizer: `cms-cost-fuel` → `cms-cost-normalized`
- MaintenanceCostNormalizer: `cms-cost-maintenance` → `cms-cost-normalized`
- ChargingCostNormalizer: `cms-cost-charging` → `cms-cost-normalized`
- AssetCostNormalizer: `cms-cost-asset` → `cms-cost-normalized`

CostProcessor (single Flink job) reads two topics:
- `cms-telemetry-preprocessed` (canonical telemetry — existing)
- `cms-cost-normalized` (canonical cost data — from normalizers above)

Derives: fuel consumption (fuelLevel Δ × $/gal), EV energy (batterySoC Δ × $/kWh), idle cost (ignition + speed=0 × $/hr), cost per mile. Joins telemetry-derived costs with external cost data. Computes rolling baselines per vehicle and per fleet. Detects anomalies inline against baselines.

**Writes directly to three destinations (no extra Kafka topics):**
- Amazon S3 (Iceberg): historical cost data → `cms_cost_analytics` table
- Amazon ElastiCache (Redis): latest cost state per vehicle + per fleet
- Amazon DynamoDB: `cms-cost-transactions` (recent transactions) + anomaly flags

---

### 3 — Cost Data Lake & Visualization

**Storage and query layer:**

- Amazon S3 (Iceberg): `cms_cost_analytics` table, partitioned by fleetId + month
- AWS Glue Data Catalog: schema management for Iceberg tables
- AWS Lake Formation: row-level security per fleet (same as telemetry)
- Amazon Athena: ad-hoc cost queries, trend analysis, fleet comparisons
- Amazon ElastiCache (Redis): latest cost state (real-time reads for CMS UI)
- Amazon DynamoDB: cost transactions (recent), cost recommendations (agent output + HiL state)

Two query paths:
- Redis for real-time dashboard rendering (sub-millisecond)
- Athena over Iceberg for historical trends and drill-downs

---

### 4 — Agentic Intelligence

**Agent Core:**

- **Agent Core Gateway** (AWS Lambda) — entry point for all agent invocations. Three trigger paths: DynamoDB Streams (anomaly detected), EventBridge Schedule (daily lifecycle review), API Gateway (operator NL query from CMS UI)
- **Agentic Guardrails** (Amazon Bedrock Guardrails) — enforces tenant isolation (never leak cross-fleet data), cost thresholds for auto-approval, confidence requirements, denied actions
- **Amazon Bedrock Knowledge Base** — RAG-based semantic layer: schema documentation, business glossary, query cookbook, fleet operator playbook
- **Amazon Bedrock Agent (Cost)** — FleetCostAgent: single agent that diagnoses anomalies, recommends actions, optimizes lifecycle, and answers operator questions

Agent tools: query_cost_lake (Athena), get_vehicle_state (Redis), get_maintenance_history (DynamoDB), get_market_pricing (S3), get_fleet_baselines (Redis), write_recommendation (DynamoDB), update_thresholds (SSM)

---

### 5 — Fleet Operator Interface (CMS UI)

**Right column — human-in-the-loop:**

- Amazon CloudFront + Amazon S3: React application (Cloudscape design system)
- Amazon API Gateway + AWS Lambda: REST API for cost data
- Amazon Cognito: JWT auth with `custom:fleetIds` scoping

**UI Components:**
- **TCO Dashboard**: KPI cards, cost breakdown charts, trend lines, outlier tables
- **Vehicle Cost Tab**: per-vehicle cost history, breakdown, vs. fleet average
- **Action Queue**: agent recommendations awaiting approval (approve / reject / override)
- **Agent Activity Feed**: real-time view of what agents are detecting and recommending
- **Auto-approval Rules**: configurable thresholds for autonomous agent action

---

## Service Icons (for diagram creation)

| Step | AWS Services |
|------|-------------|
| 1 | Amazon MSK, Amazon S3, AWS Glue, Amazon EC2 (simulator) |
| 2 | Amazon Managed Service for Apache Flink, Amazon ElastiCache (Redis), Amazon MSK |
| 3 | Amazon S3 (Iceberg), AWS Lake Formation, Amazon Athena, AWS Glue Catalog, Amazon DynamoDB |
| 4 | Amazon Managed Service for Apache Flink, Amazon SageMaker |
| 5 | Amazon Bedrock, Amazon EventBridge, AWS Lambda, AWS Systems Manager |
| 6 | Amazon CloudFront, Amazon S3, Amazon API Gateway, AWS Lambda, Amazon Cognito |

---

## Diagram Layout Suggestion

Same dark background as predictive maintenance diagram. Numbered green circles (1-6).

```
Left column (1):          Center (2-3):              Right column (6):
┌─────────────┐     ┌──────────────────────┐    ┌─────────────────┐
│ MSK          │     │ Flink Cost Processor │    │ CloudFront      │
│ (telemetry)  │────→│                      │    │ CMS UI          │
│              │     │ Derive costs from    │    │                 │
│ S3           │     │ telemetry signals    │    │ TCO Dashboard   │
│ (CSV upload) │────→│                      │───→│ Action Queue    │
│              │     └──────────┬───────────┘    │ Agent Feed      │
│ Simulator    │                │                │ Auto-approve    │
│ (cost events)│────→     ┌─────┴─────┐          └────────▲────────┘
└─────────────┘      │           │                │
                  Redis      MSK topics            │
                  (latest)   (events +             │
                              anomalies)           │
                                │                  │
                     ┌──────────┴──────────┐       │
                     │ S3 Iceberg (3)      │       │
                     │ DynamoDB            │       │
                     │ Athena              │       │
                     └──────────┬──────────┘       │
                                │                  │
                     ┌──────────┴──────────┐       │
                     │ Monitor Agent (4)    │       │
                     │ Flink + SageMaker    │       │
                     └──────────┬──────────┘       │
                                │                  │
                     ┌──────────┴──────────┐       │
                     │ Diagnose + Recommend │       │
                     │ Agents (5)           │───────┘
                     │ Bedrock + EventBridge│
                     │ Learn Agent (Lambda) │
                     └─────────────────────┘
```
