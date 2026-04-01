# Dynamic Fleet Rebalancing — Design Document

## ADP Data Product: `guidance-for-fleet-rebalancing`

**Author:** Andrew Givens | **Date:** March 2026 | **Status:** Draft

---

## 1. Problem Statement

Fleet operators manage thousands of vehicles across regions, routes, and customer segments. Demand fluctuates by season, day of week, geography, and customer behavior. Static vehicle allocation — assigning vehicles to locations based on historical averages — leaves assets idle in low-demand areas while high-demand areas are short. The difference between 70% and 85% utilization is the difference between loss and profit.

Today, rebalancing decisions are manual, slow, and based on lagging indicators. A regional manager looks at last week's utilization report, makes a gut call, and moves vehicles. By the time the move happens, demand has shifted again.

Fleet operators need a system that continuously monitors demand signals, predicts where assets are needed before the gap appears, and recommends (or executes) rebalancing moves — factoring in cost, distance, vehicle type, and operational constraints.

---

## 2. Design Principles

1. **Build in the CMS UI** — rebalancing views are new pages/components in the existing fleet operator interface
2. **Leverage existing infrastructure** — normalized telemetry, Redis vehicle state, DynamoDB fleet enrollment, Athena/Iceberg data lake, Cognito auth
3. **Agent-first, dashboard-second** — the Bedrock Agent does the analysis and recommends moves. The dashboard visualizes what the agent sees. The action queue is where operators approve.
4. **Start with visibility, graduate to autonomous** — Phase 1 shows utilization gaps. Phase 2 recommends moves. Phase 3 auto-executes approved move patterns.

---

## 3. Architecture Overview

```
DATA SOURCES
├── Vehicle telemetry (existing CMS pipeline)
│   ├── Location (GPS lat/lng from cms-telemetry-preprocessed)
│   ├── Status (ignitionOn, speed — idle vs. in-use vs. in-transit)
│   └── Odometer / trip data (from TripProcessor)
│
├── Fleet operations data (existing CMS)
│   ├── Fleet enrollment table (vehicleId → fleetId → location/region)
│   ├── Vehicle metadata (type, capacity, fuel type ICE/BEV, range)
│   └── Driver assignments
│
├── Demand signals (new ingestion)
│   ├── Reservation/booking data → Kafka: cms-rebalance-demand
│   ├── Historical utilization patterns → S3 Iceberg (from telemetry)
│   └── External demand indicators (events, weather, seasonal) → S3
│
└── Constraint data
    ├── Depot/hub locations and capacity
    ├── Transfer costs (driver time, fuel, deadhead miles)
    ├── Maintenance schedule (vehicles due for service can't be moved)
    └── Regulatory (hours of service, cross-state requirements)

NORMALIZATION & PROCESSING (MSK + Flink)
├── UtilizationProcessor (Flink)
│   ├── Reads: cms-telemetry-preprocessed + fleet enrollment
│   ├── Computes: per-vehicle utilization (active hours / available hours)
│   ├── Computes: per-location utilization (vehicles in use / vehicles assigned)
│   ├── Computes: per-region supply-demand gap
│   └── Writes directly to:
│       ├── S3 Iceberg: cms_fleet_utilization (historical)
│       ├── Redis: latest utilization state per vehicle, location, region
│       └── DynamoDB: cms-rebalance-events (utilization gaps + imbalance flags)
│
├── DemandForecastProcessor (Flink or batch)
│   ├── Reads: historical utilization + demand signals
│   ├── Produces: 24hr / 7-day / 30-day demand forecasts per location
│   └── Writes to: S3 + Redis

DATA LAKE & VISUALIZATION
├── S3 Iceberg: cms_fleet_utilization (partitioned by fleetId + region + day)
├── S3 Iceberg: cms_demand_forecasts (partitioned by fleetId + location + date)
├── Athena views:
│   ├── v_utilization_by_location — current + historical utilization per hub/depot
│   ├── v_supply_demand_gap — locations with surplus vs. deficit
│   ├── v_rebalance_history — past moves and their impact
│   ├── v_vehicle_availability — vehicles available for rebalancing (not in service, not in maintenance)
│   └── v_transfer_cost_estimate — estimated cost to move vehicle A from location X to Y
├── Lake Formation: row-level security per fleet
├── Redis: real-time utilization state
└── DynamoDB: rebalance events, recommendations, move history

AGENTIC INTELLIGENCE
├── Agent Core Gateway (Lambda) — triggers:
│   ├── DynamoDB Streams: imbalance flag detected
│   ├── EventBridge Schedule: daily demand forecast review
│   └── CMS UI: operator asks "Where should I move vehicles?"
│
├── Agentic Guardrails (Bedrock Guardrails)
│   ├── Tenant isolation (fleet-scoped)
│   ├── Move cost thresholds (auto-approve under $X)
│   ├── Never move vehicles in active maintenance
│   └── Respect hours-of-service constraints
│
├── Amazon Bedrock Knowledge Base
│   ├── Schema docs: utilization tables, demand forecasts, constraint data
│   ├── Business glossary: utilization %, supply-demand gap, deadhead miles
│   ├── Rebalancing playbook: "when surplus > 20% and deficit > 15%, recommend move"
│   └── Query cookbook: example Athena queries for common rebalancing scenarios
│
├── Amazon Bedrock Agent (Rebalancing)
│   ├── Tools:
│   │   ├── query_utilization (Athena) — current + historical utilization
│   │   ├── get_demand_forecast (Redis/S3) — predicted demand by location
│   │   ├── get_vehicle_availability (DynamoDB) — which vehicles can move
│   │   ├── estimate_transfer_cost (Lambda) — cost to move vehicle A→B
│   │   ├── check_constraints (DynamoDB) — maintenance schedule, driver HOS
│   │   ├── write_recommendation (DynamoDB) — rebalance move with PENDING_APPROVAL
│   │   └── execute_move (API) — update fleet enrollment when auto-approved
│   │
│   ├── Diagnose: "Location X has 30% surplus, Location Y has 25% deficit"
│   ├── Recommend: "Move 8 vehicles (type: Class 8, ICE) from X→Y, est. cost $2,400, est. revenue recovery $18K/week"
│   └── Learn: track actual utilization after moves, improve forecast accuracy
│
└── Amazon SageMaker — demand forecasting model (time series)

FLEET OPERATOR INTERFACE (CMS UI)
├── Fleet Rebalancing Dashboard (/fleet-rebalancing)
│   ├── Map view: vehicle locations color-coded by utilization (red=idle, green=active)
│   ├── Supply-demand heatmap: surplus/deficit by region
│   ├── Utilization KPIs: fleet-wide %, by region, by vehicle type
│   └── Demand forecast overlay: predicted demand next 7/30 days
│
├── Rebalance Action Queue
│   ├── Agent-recommended moves with cost estimate + revenue impact
│   ├── Approve / reject / modify (change vehicle count, timing)
│   ├── Auto-approval rules: "auto-approve moves under $1K with confidence > 85%"
│   └── Move history: past rebalancing actions + actual impact
│
├── Vehicle Availability View
│   ├── Which vehicles are available for rebalancing
│   ├── Filter by: type, fuel, range, maintenance status, location
│   └── Drag-and-drop assignment (manual override)
│
└── Agent Activity Feed
    ├── "Detected: Location X surplus 12 vehicles (utilization 52%)"
    ├── "Forecast: Location Y demand increasing 35% next 7 days (seasonal)"
    ├── "Recommended: Move 8 vehicles X→Y, est. $2,400 transfer, $18K/week recovery"
    └── "Awaiting your approval →"
```

---

## 4. CMS UI Integration

### New Pages / Components

#### 4a. Fleet Rebalancing Dashboard (`/fleet-rebalancing`)
**Location:** New top-level nav item in CMS UI sidebar

**Components:**
- `UtilizationMap` — map view with vehicle markers color-coded by status (idle/active/in-transit/maintenance). Uses existing Amazon Location Service integration + Redis GEOSEARCH.
- `SupplyDemandHeatmap` — regional overlay showing surplus (blue) vs. deficit (red) zones
- `UtilizationKPIs` — KPI cards: fleet-wide utilization %, vehicles idle, vehicles in deficit regions, forecast accuracy
- `DemandForecastChart` — line chart: predicted vs. actual demand by location, 7/30 day view
- `RebalanceRecommendations` — agent-recommended moves, inline approve/reject

#### 4b. Rebalance Action Queue (`/fleet-rebalancing/actions`)
**Location:** Sub-page of rebalancing dashboard

| Column | Description |
|--------|-------------|
| Priority | Critical / High / Medium / Low |
| From → To | Source and destination locations |
| Vehicles | Count and type (Class 8 ICE, Medium Duty BEV, etc.) |
| Transfer Cost | Estimated cost of the move |
| Revenue Impact | Estimated revenue recovery from improved utilization |
| Confidence | Agent's confidence in the demand forecast |
| Status | Pending / Approved / Rejected / Auto-approved / Executed |
| Actions | Approve / Reject / Modify / Snooze |

**Auto-approval rules:** configurable per fleet:
- "Auto-approve moves under $1,000 with confidence > 85%"
- "Auto-approve within-region moves (same depot network)"
- "Always require approval for cross-region or cross-state moves"

#### 4c. Vehicle Availability View
**Location:** Tab on rebalancing dashboard

- Filterable table of vehicles available for rebalancing
- Excludes: vehicles in active trips, in maintenance, under recall
- Shows: current location, vehicle type, fuel type, range (BEV), days idle
- Manual override: drag-and-drop or select + assign to destination

---

## 5. Data Model

### DynamoDB: `cms-{stage}-rebalance-events`

| Key | Type | Description |
|-----|------|-------------|
| `locationId` (PK) | String | Hub/depot/region identifier |
| `timestamp` (SK) | String | ISO timestamp |
| `fleetId` | String | Fleet for tenant isolation (GSI) |
| `utilization_pct` | Number | Current utilization percentage |
| `vehicle_count` | Number | Vehicles assigned to location |
| `active_count` | Number | Vehicles currently in use |
| `idle_count` | Number | Vehicles idle |
| `surplus_deficit` | Number | Positive = surplus, negative = deficit |
| `imbalance_flag` | Boolean | True when threshold exceeded |

### DynamoDB: `cms-{stage}-rebalance-recommendations`

| Key | Type | Description |
|-----|------|-------------|
| `recommendationId` (PK) | String | Unique ID |
| `fleetId` (GSI) | String | Fleet scope |
| `from_location` | String | Source location |
| `to_location` | String | Destination location |
| `vehicle_count` | Number | Vehicles to move |
| `vehicle_type` | String | Vehicle type filter |
| `transfer_cost` | Number | Estimated cost |
| `revenue_impact` | Number | Estimated revenue recovery |
| `confidence` | Number | Agent confidence score |
| `status` | String | PENDING_APPROVAL / APPROVED / REJECTED / AUTO_APPROVED / EXECUTED |
| `created_at` | String | Timestamp |
| `approved_by` | String | Operator who approved (or "AUTO") |
| `actual_impact` | Map | Post-move utilization change (filled by Learn cycle) |

### S3 Iceberg: `cms_fleet_utilization`

```sql
CREATE TABLE cms_fleet_utilization (
    vehicleId STRING,
    fleetId STRING,
    locationId STRING,
    region STRING,
    date DATE,
    active_hours DOUBLE,
    available_hours DOUBLE,
    utilization_pct DOUBLE,
    idle_hours DOUBLE,
    trips_completed INT,
    miles_driven DOUBLE,
    revenue_generated DOUBLE
)
PARTITIONED BY (fleetId, region, day(date))
```

### S3 Iceberg: `cms_demand_forecasts`

```sql
CREATE TABLE cms_demand_forecasts (
    fleetId STRING,
    locationId STRING,
    forecast_date DATE,
    forecast_horizon STRING,
    predicted_demand INT,
    actual_demand INT,
    confidence DOUBLE,
    model_version STRING,
    generated_at TIMESTAMP
)
PARTITIONED BY (fleetId, month(forecast_date))
```

### Redis: Utilization State

```
location:{locationId}:utilization → {
    vehicle_count, active_count, idle_count,
    utilization_pct, surplus_deficit,
    imbalance_flag, last_updated
}

region:{regionId}:utilization → {
    total_vehicles, total_active, total_idle,
    avg_utilization_pct, locations_in_deficit,
    locations_in_surplus, last_updated
}

vehicle:{vehicleId}:availability → {
    status: active | idle | in_transit | maintenance | recall,
    current_location, idle_since, available_for_rebalance,
    last_updated
}
```

---

## 6. Semantic Layer

### Athena Views

| View | Purpose |
|------|---------|
| `v_utilization_by_location` | Current + 30-day rolling utilization per hub/depot |
| `v_supply_demand_gap` | Locations ranked by surplus/deficit severity |
| `v_rebalance_history` | Past moves with before/after utilization + actual revenue impact |
| `v_vehicle_availability` | Vehicles available for rebalancing (not active, not in maintenance/recall) |
| `v_transfer_cost_estimate` | Estimated cost to move between location pairs (distance × $/mile + driver time) |
| `v_demand_forecast_accuracy` | Predicted vs. actual demand — tracks forecast model performance |
| `v_utilization_by_vehicle_type` | Utilization breakdown by ICE vs. BEV, Class 8 vs. Medium Duty |

### Bedrock Knowledge Base

| Document | Content |
|----------|---------|
| Schema documentation | Utilization tables, forecast tables, constraint data — what each field means |
| Business glossary | Utilization %, supply-demand gap, deadhead miles, transfer cost, revenue recovery |
| Rebalancing playbook | Decision rules: "surplus > 20% AND deficit > 15% in adjacent region → recommend move" |
| Query cookbook | Example Athena queries for common rebalancing scenarios |
| Constraint reference | Maintenance windows, HOS rules, cross-state requirements, depot capacity limits |

### Agentic Guardrails

- Tenant isolation: fleet-scoped, never recommend moves across fleet boundaries
- Cost thresholds: auto-approve under configurable amount, require approval above
- Constraint enforcement: never move vehicles in active maintenance, under recall, or with HOS violations
- Vehicle type matching: don't recommend moving a BEV to a location without charging infrastructure
- Confidence floor: don't recommend moves based on forecasts with confidence < 70%

---

## 7. Cost Data Ingestion

### Simulated Data (demo-ready)

Extend the CMS simulation service:
- Generate vehicles distributed across 5-10 hub locations with varying utilization
- Simulate demand fluctuations: weekday/weekend patterns, seasonal surges, event-driven spikes
- Generate idle periods, trip completions, and location changes
- Produce reservation/booking events for demand signal ingestion

### Real Data

- **Telemetry-derived (automatic):** vehicle location, status, idle time — all from existing normalized telemetry
- **Fleet enrollment (existing):** vehicle-to-location assignments from DynamoDB
- **Reservation/booking data (CSV upload):** demand signals from booking systems
- **Depot/hub configuration (CSV upload):** location metadata, capacity, charging infrastructure

---

## 8. Agentic Core

### Amazon Bedrock Agent (Rebalancing)

Single agent with tools:

| Tool | Service | Purpose |
|------|---------|---------|
| `query_utilization` | Athena | Current + historical utilization by location/region |
| `get_demand_forecast` | Redis / S3 | Predicted demand by location for next 7/30 days |
| `get_vehicle_availability` | DynamoDB | Which vehicles can be moved (filters out maintenance, recall, active) |
| `estimate_transfer_cost` | Lambda | Distance-based cost estimate for moving vehicles between locations |
| `check_constraints` | DynamoDB | Maintenance schedule, driver HOS, depot capacity, charging infra |
| `write_recommendation` | DynamoDB | Write rebalance recommendation with PENDING_APPROVAL status |
| `execute_move` | Lambda → DynamoDB | Update fleet enrollment when move is approved |
| `get_move_history` | Athena | Past rebalancing moves and their actual impact |

### Example Agent Flow — Imbalance Detected

```
1. DynamoDB Stream: Location X imbalance_flag = true (utilization 52%, 12 vehicles idle)
2. Lambda trigger → invokes Bedrock Agent with context
3. Agent calls query_utilization → confirms X at 52%, adjacent Location Y at 94%
4. Agent calls get_demand_forecast → Y demand increasing 35% next 7 days (seasonal)
5. Agent calls get_vehicle_availability → 10 vehicles at X available (2 in maintenance)
6. Agent calls estimate_transfer_cost → X→Y: $300/vehicle, 8 vehicles = $2,400
7. Agent calls check_constraints → no HOS issues, Y has capacity, charging available for BEVs
8. Agent reasons: move 8 vehicles, est. revenue recovery $18K/week, ROI in 2 days
9. Agent calls write_recommendation → DynamoDB with PENDING_APPROVAL
10. CMS UI shows in action queue → operator approves → execute_move updates enrollment
```

### Example Agent Flow — Operator Question

```
Operator: "Which locations are overstaffed this week?"

1. Agent calls query_utilization → v_supply_demand_gap view
2. Agent calls get_demand_forecast → next 7 days by location
3. Agent responds: "3 locations with surplus: Denver (8 idle, 58% util), 
   Phoenix (5 idle, 64% util), Portland (4 idle, 61% util). 
   Denver surplus expected to persist — seasonal demand drop. 
   Phoenix temporary — event next week will absorb. 
   Recommend moving 6 vehicles from Denver to Dallas (deficit, 91% util)."
```

---

## 9. Implementation Plan

### Phase 1 (4 weeks): Visibility
- [ ] UtilizationProcessor Flink job (telemetry → utilization metrics)
- [ ] DynamoDB rebalance-events table + Iceberg utilization schema
- [ ] Redis utilization state (location, region, vehicle availability)
- [ ] Athena views (utilization by location, supply-demand gap, vehicle availability)
- [ ] REST API endpoints in main_api Lambda
- [ ] CMS UI: Rebalancing Dashboard with map + utilization KPIs
- [ ] CMS UI: Vehicle Availability view
- [ ] Simulator: multi-location fleet with demand variation

### Phase 2 (4 weeks): Intelligence
- [ ] Demand forecasting model (SageMaker — time series)
- [ ] Bedrock Knowledge Base (schema docs, glossary, playbook)
- [ ] Bedrock Agent (Rebalancing) with tools
- [ ] Agentic Guardrails configuration
- [ ] Agent Core Gateway (Lambda triggers)
- [ ] CMS UI: Action Queue with approve/reject/modify
- [ ] CMS UI: Demand forecast overlay on map
- [ ] Transfer cost estimation Lambda

### Phase 3 (4 weeks): Autonomous
- [ ] Auto-approval rules (configurable per fleet)
- [ ] Execute_move tool (auto-update fleet enrollment)
- [ ] Learn cycle: track actual utilization post-move, improve forecasts
- [ ] Agent Activity Feed in CMS UI
- [ ] Cross-fleet rebalancing (for operators managing multiple fleets)
- [ ] BEV-specific constraints (charging infrastructure availability at destination)

---

## 10. Integration with Existing Pipeline

### What We Reuse (no changes needed)

| Component | How Rebalancing Uses It |
|-----------|------------------------|
| `cms-telemetry-preprocessed` | UtilizationProcessor reads location + status signals |
| Redis vehicle state | Extend with `:availability` hash |
| Fleet enrollment DynamoDB | Source of vehicle-to-location assignments + target for move execution |
| Lake Formation | Same row-level security per fleet |
| Cognito auth | Same JWT scoping |
| CMS UI (main_api Lambda) | New `/rebalancing` routes |
| Amazon Location Service | Map rendering in CMS UI (already integrated) |

### What We Add

| Component | Purpose |
|-----------|---------|
| UtilizationProcessor (Flink) | Derives utilization metrics from telemetry |
| DemandForecastProcessor (Flink/batch) | Produces demand forecasts |
| `cms-rebalance-events` DynamoDB table | Utilization events + imbalance flags |
| `cms-rebalance-recommendations` DynamoDB table | Agent recommendations + HiL state |
| `cms_fleet_utilization` Iceberg table | Historical utilization data |
| `cms_demand_forecasts` Iceberg table | Forecast data + accuracy tracking |
| Bedrock Agent (Rebalancing) | Single agent with rebalancing tools |
| Bedrock Knowledge Base | Semantic context for rebalancing domain |
| SageMaker demand forecast model | Time series forecasting |
| Rebalancing UI components | New pages/tabs in CMS UI |

---

## 11. Architecture Diagram Narrative

**Title:** Guidance for an Automotive Data Platform on AWS
**Subtitle:** Creating operational value from Fleet Utilization Intelligence
**Tagline:** Build an agentic fleet rebalancing pipeline that optimizes vehicle placement across locations

### Steps:

**1 — Fleet Data Ingestion**
Vehicle telemetry from the existing CMS normalization pipeline provides real-time location, status, and trip data. Fleet enrollment tables define vehicle-to-location assignments. Demand signals arrive from booking systems via CSV upload or Kafka. Constraint data — depot capacity, maintenance schedules, charging infrastructure — is stored in DynamoDB and S3.

**2 — Utilization Processing**
A Flink UtilizationProcessor reads normalized telemetry and computes per-vehicle, per-location, and per-region utilization metrics in real time. A demand forecasting model produces 7-day and 30-day predictions by location. The processor writes directly to S3 Iceberg for historical analysis, Redis for real-time state, and DynamoDB for utilization events and imbalance flags.

**3 — Utilization Data Lake & Visualization**
Historical utilization and forecast data is stored in S3 Iceberg tables with Lake Formation tenant isolation. Athena views encode business logic — supply-demand gaps, vehicle availability, transfer cost estimates, and rebalance history with actual impact. Redis serves real-time utilization state for dashboard rendering.

**4 — Agentic Intelligence**
The Agent Core Gateway routes imbalance events, scheduled reviews, and operator questions to a Bedrock Agent. The agent retrieves context from a Knowledge Base, queries utilization and forecast data, checks constraints, estimates transfer costs, and writes rebalancing recommendations. Bedrock Guardrails enforce tenant isolation, cost thresholds, and constraint compliance.

**5 — Fleet Operator Interface**
The CMS UI provides a map-based rebalancing dashboard with vehicle locations, supply-demand heatmaps, and demand forecast overlays. The Action Queue surfaces agent-recommended moves for approval with cost estimates and revenue impact projections. Auto-approval rules let operators configure which moves the agent can execute autonomously.

### Service Icons per Step:

| Step | Services |
|------|----------|
| 1 | Amazon MSK, Amazon DynamoDB, Amazon S3 |
| 2 | Amazon Managed Service for Apache Flink, Amazon ElastiCache (Redis), Amazon SageMaker |
| 3 | Amazon S3 (Iceberg), AWS Lake Formation, Amazon Athena, Amazon DynamoDB |
| 4 | AWS Lambda, Amazon Bedrock Guardrails, Amazon Bedrock Knowledge Base, Amazon Bedrock Agent, Amazon SageMaker |
| 5 | Amazon CloudFront, Amazon API Gateway, Amazon Cognito, Amazon Location Service |

---

## 12. Open Questions

1. **Location granularity:** hub/depot level, city level, or region level? Probably configurable.
2. **Demand signal sources:** what booking/reservation systems do target customers use?
3. **Transfer execution:** does the system just update the enrollment table, or does it need to dispatch a driver/tow?
4. **Cross-fleet rebalancing:** can an operator managing multiple fleets move vehicles between them?
5. **BEV range constraints:** how to factor remaining range into rebalancing decisions (can the vehicle make the transfer trip)?
6. **Revenue attribution:** how to calculate revenue recovery from a rebalancing move? Need booking/rental rate data.
