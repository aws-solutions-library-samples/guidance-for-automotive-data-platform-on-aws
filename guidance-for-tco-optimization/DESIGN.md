# TCO Optimization — Design Document

## ADP Data Product: `guidance-for-tco-optimization`

**Author:** Andrew Givens | **Date:** March 2026 | **Status:** Draft

---

## 1. Problem Statement

Fleet operators lack unified visibility into total cost of ownership. Cost data is fragmented across fuel card providers, maintenance management systems, telematics platforms, insurance carriers, and EV charging networks. Without a single view, operators can't identify cost outliers, forecast spend, or make data-driven lifecycle decisions.

The CMS UI already provides real-time fleet monitoring, trip analytics, alerts, and vehicle management. TCO optimization extends this by adding a cost intelligence layer directly into the fleet operator's existing workflow — no separate QuickSight dashboard, no context switching.

---

## 2. Design Principles

1. **Build in the CMS UI** — fleet operators already live here. TCO views are new pages/components in the existing React app, not a separate tool.
2. **Leverage existing infrastructure** — normalized telemetry (from `guidance-for-telemetry-normalization`), Redis vehicle state, DynamoDB tables, Athena/Iceberg data lake, Cognito auth, API Gateway.
3. **Cost data as a data product** — Iceberg tables with fleet-level partitioning and Lake Formation tenant isolation, same pattern as telemetry normalization.
4. **Start simple, add ML later** — Phase 1 is visibility (dashboards, queries). Phase 2 adds anomaly detection and forecasting. Phase 3 adds agentic cost optimization.

---

## 3. Architecture Overview

```
COST DATA SOURCES
├── Telemetry-derived costs
│   ├── Fuel consumption (from normalized telemetry: fuel level + odometer + GPS)
│   ├── EV energy consumption (from normalized telemetry: battery SoC + charging events)
│   └── Idle time / inefficient routing (from trip analytics)
│
├── External cost feeds (new ingestion)
│   ├── Fuel card transactions → Lambda poller → Kafka: cms-cost-fuel
│   ├── Maintenance work orders → Lambda poller → Kafka: cms-cost-maintenance
│   ├── EV charging sessions → Lambda poller → Kafka: cms-cost-charging
│   └── Insurance/lease data → Batch CSV upload → S3 → Glue ETL → Kafka: cms-cost-asset
│
└── Derived costs (computed)
    ├── Depreciation (age, mileage, market value curves)
    ├── Cost per mile (total cost / odometer delta)
    └── Predictive maintenance savings (predicted vs. actual)

NORMALIZATION & PROCESSING (MSK + Flink)
├── Source-specific Flink normalizers
│   ├── FuelCostNormalizer: cms-cost-fuel → cms-cost-normalized
│   ├── MaintenanceCostNormalizer: cms-cost-maintenance → cms-cost-normalized
│   ├── ChargingCostNormalizer: cms-cost-charging → cms-cost-normalized
│   └── AssetCostNormalizer: cms-cost-asset → cms-cost-normalized
│
└── CostProcessor (single Flink job)
    ├── Reads: cms-telemetry-preprocessed + cms-cost-normalized
    ├── Derives: fuel consumption, EV energy, idle cost, cost/mile
    ├── Joins telemetry-derived + external cost data
    ├── Computes rolling baselines per vehicle and fleet
    ├── Detects anomalies inline against baselines
    └── Writes directly to:
        ├── S3 Iceberg: cms_cost_analytics (historical)
        ├── Redis: latest cost state per vehicle + fleet
        └── DynamoDB: cms-cost-transactions + anomaly flags

DATA LAKE & VISUALIZATION
├── S3 Iceberg: cms_cost_analytics (partitioned by fleetId + month)
├── Glue Data Catalog: schema management
├── Lake Formation: row-level security per fleet
├── Athena: ad-hoc queries, trends, comparisons
├── Redis: real-time cost state
└── DynamoDB: recent transactions + agent recommendations

AGENTIC INTELLIGENCE
├── DynamoDB Streams / EventBridge: anomaly flags trigger agent pipeline
├── Diagnose Agent (Bedrock): root cause analysis across cost + telemetry + maintenance data
├── Recommend Agent (Bedrock): actionable recommendations with cost estimates
├── Lifecycle Agent (Bedrock): buy/sell/hold optimization against market data
└── Learn Agent (Lambda): outcome tracking, threshold updates, model retraining

CONSUMPTION (CMS UI)
├── Fleet TCO Dashboard (new page)
├── Vehicle Cost Detail (new tab on vehicle detail page)
├── Action Queue (agent recommendations + HiL approval)
├── Agent Activity Feed (real-time agent monitoring)
├── Auto-approval Rules (configurable per fleet)
└── REST API endpoints (new routes in main_api Lambda)
```

---

## 4. CMS UI Integration — Costs as the Aggregation Layer

The Costs page does not own operational data — it aggregates from other domains. Each source page owns its data and operations; Costs provides the financial intelligence view.

### Data Flow into Costs

| Cost Category | Source Page | How It Gets to Costs |
|---|---|---|
| Fuel spend | Energy | CostProcessor reads `fuelLevel` + `odometer` from telemetry → derives gallons × $/gal |
| EV charging | Energy | CostProcessor reads `batterySoC` deltas → derives kWh × $/kWh |
| Idle costs | Energy | CostProcessor reads `ignitionOn` + `speed=0` → derives idle hours × fuel burn rate |
| Maintenance spend | Service | Work order costs from DynamoDB `cms-cost-transactions` (CSV upload or service system) |
| Recall service costs | Service | Recall service costs + estimated revenue loss from grounded vehicles |
| Warranty recovery | Warranty | Claim payments as negative cost line item from `cms-warranty-events` |
| Insurance | External | CSV upload → Glue ETL → Iceberg |
| Depreciation | External | Age/mileage curves or market-based pricing (CSV upload) |
| Transfer costs | Rebalancing | Vehicle move costs from `cms-rebalance-recommendations` (executed moves) |
| Toll costs | External | CSV upload (PrePass, Bestpass) |

### Cross-Page Links

The Costs dashboard links back to source pages for drill-down:
- "Maintenance: $48,200 MTD" → links to Service page filtered to this month
- "Warranty recovered: $4,200" → links to Warranty page claims view
- "Fuel spend: $128,400" → links to Energy page fuel breakdown
- "Transfer costs: $3,200" → links to Rebalancing page executed moves

### New Pages / Components

#### 4a. Fleet TCO Dashboard (`/fleet-costs`)
**Location:** New top-level nav item in CMS UI sidebar

**Components:**
- `FleetCostOverview` — KPI cards: total fleet cost (MTD), cost/mile, cost/vehicle, maintenance ratio
- `CostBreakdownChart` — stacked bar chart: fuel, maintenance, insurance, depreciation, charging by month
- `CostTrendLine` — line chart: total cost trend over 3/6/12 months with forecast line (Phase 2)
- `CostOutliersTable` — table of vehicles with cost > 1.5× fleet average, sortable by category
- `FleetComparisonWidget` — compare two fleets side by side on cost metrics

**Data source:** REST API → Lambda → Athena (Iceberg) for historical, Redis for current state

#### 4b. Vehicle Cost Tab (`/vehicles/:id/costs`)
**Location:** New tab on existing vehicle detail page (alongside telemetry, trips, alerts)

**Components:**
- `VehicleCostSummary` — KPI cards: this vehicle's cost/mile, maintenance spend, fuel spend, vs. fleet average
- `VehicleCostHistory` — timeline of cost events (fuel fills, maintenance work orders, charging sessions)
- `VehicleCostBreakdown` — pie chart: cost category breakdown for this vehicle
- `MaintenanceForecast` — predicted next maintenance cost based on telemetry + history (Phase 2)

**Data source:** REST API → Lambda → DynamoDB (recent) + Athena (historical)

#### 4c. Cost Alerts Integration
**Location:** Existing alerts page + alert management system

**New alert types:**
- `COST_ANOMALY` — vehicle cost/mile exceeds fleet threshold
- `MAINTENANCE_SPIKE` — maintenance spend for vehicle exceeds 2× rolling average
- `FUEL_EFFICIENCY_DROP` — fuel consumption per mile degrades beyond threshold
- `CHARGING_COST_SPIKE` — EV charging cost exceeds optimal schedule

**Integration:** Flink cost processor → Kafka `cms-cost-alerts` → existing alarm_recorder Lambda → DynamoDB alerts table → CMS UI alerts page

### Existing Components to Extend

- **Dashboard page:** Add cost KPI widget to existing fleet dashboard
- **Vehicle detail page:** Add "Costs" tab
- **Alerts page:** New cost alert category filter
- **Fleet list page:** Add cost/mile column

---

## 5. Data Model

### DynamoDB: `cms-{stage}-cost-transactions`

| Key | Type | Description |
|-----|------|-------------|
| `vehicleId` (PK) | String | Vehicle identifier |
| `timestamp#category` (SK) | String | Composite: ISO timestamp + cost category |
| `fleetId` | String | Fleet for tenant isolation (GSI) |
| `category` | String | `fuel`, `maintenance`, `charging`, `insurance`, `depreciation` |
| `amount` | Number | Cost in USD |
| `unit_cost` | Number | Cost per unit ($/gallon, $/kWh, etc.) |
| `quantity` | Number | Units consumed |
| `source` | String | Data source identifier |
| `metadata` | Map | Category-specific details |

**GSI:** `fleetId-timestamp-index` for fleet-level queries

### S3 Iceberg: `cms_cost_analytics`

```sql
CREATE TABLE cms_cost_analytics (
    vehicleId STRING,
    fleetId STRING,
    date DATE,
    category STRING,
    total_cost DOUBLE,
    cost_per_mile DOUBLE,
    odometer_delta DOUBLE,
    fuel_gallons DOUBLE,
    fuel_cost DOUBLE,
    maintenance_cost DOUBLE,
    charging_kwh DOUBLE,
    charging_cost DOUBLE,
    insurance_cost DOUBLE,
    depreciation_cost DOUBLE,
    idle_hours DOUBLE,
    efficiency_score DOUBLE
)
PARTITIONED BY (fleetId, month(date))
```

### Redis: Cost State

```
vehicle:{vehicleId}:cost → {
    cost_per_mile_30d: 0.72,
    fuel_rate_mpg: 6.8,
    maintenance_mtd: 450.00,
    total_cost_mtd: 3200.00,
    fleet_avg_cost_per_mile: 0.65,
    cost_anomaly: false,
    last_updated: 1711324800000
}
```

---

## 6. API Endpoints

Added to existing `main_api` Lambda:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/fleets/{fleetId}/costs` | Fleet cost summary (MTD, YTD, by category) |
| `GET` | `/api/v1/fleets/{fleetId}/costs/trend` | Monthly cost trend (3/6/12 months) |
| `GET` | `/api/v1/fleets/{fleetId}/costs/outliers` | Vehicles exceeding cost thresholds |
| `GET` | `/api/v1/fleets/{fleetId}/costs/comparison` | Compare two fleets |
| `GET` | `/api/v1/vehicles/{vehicleId}/costs` | Vehicle cost summary |
| `GET` | `/api/v1/vehicles/{vehicleId}/costs/history` | Vehicle cost transaction history |
| `POST` | `/api/v1/costs/upload` | Batch upload cost data (CSV) |

All endpoints enforce Cognito JWT + `custom:fleetIds` scoping.

---

## 7. Cost Data Ingestion

### Simulated Data (demo-ready out of the box)

Extend the existing CMS simulation service to generate realistic cost events alongside telemetry:

- **Fuel transactions:** random fuel fills correlated with vehicle odometer + fuel level drops, realistic pricing by region
- **Maintenance work orders:** scheduled maintenance at mileage intervals + unplanned repairs triggered by predictive maintenance alerts
- **EV charging sessions:** charging events correlated with battery SoC drops, variable $/kWh by time of day
- **Insurance/depreciation:** monthly fixed costs per vehicle based on vehicle type and age

The simulator already generates telemetry for the fleet — cost events are a natural extension. This means the TCO dashboard is fully functional the moment you deploy, with no external data sources required.

**Implementation:** New `CostEventGenerator` class in the simulation service, triggered alongside telemetry generation. Writes cost events to Kafka `cms-cost-transactions` topic → Flink cost processor → DynamoDB + Iceberg.

### CSV / S3 Upload (real data)

For customers ready to use their own data:

- **CMS UI upload:** drag-and-drop CSV on the Fleet TCO Dashboard page
- **S3 drop:** place CSV files in `s3://{bucket}/cost-uploads/{fleetId}/` — Glue ETL picks up automatically
- **Standard schema:** `vehicleId, date, category, amount, description, quantity, unit_cost`
- **Category values:** `fuel`, `maintenance`, `charging`, `insurance`, `depreciation`, `labor`, `other`

CSV upload works with any provider — fleet operators export from their fuel card portal (WEX, Comdata, FleetCor), maintenance system (Fleetio, TMT), or charging network (ChargePoint, EVgo) and upload. No API integration needed.

**Telemetry-derived costs (automatic, no upload needed):**

In addition to simulated and uploaded data, the Flink cost processor automatically derives costs from normalized telemetry:
- Fuel consumption: `fuelLevel` signal deltas + odometer → estimated gallons consumed × configurable $/gallon
- EV energy: `batterySoC` deltas during charging events → estimated kWh × configurable $/kWh
- Idle time: `ignitionOn` + `speed == 0` duration → estimated idle fuel cost

These telemetry-derived costs provide a baseline TCO view even if the customer hasn't uploaded any external cost data yet.

### Real-World Cost Data Sources (full inventory)

For customers building production integrations, these are the cost data sources a fleet operator typically manages:

**Fuel & Energy:**
- Fuel cards: WEX, Comdata, FleetCor, Fuelman — transaction-level (gallons, price, location, driver, vehicle)
- EV charging networks: ChargePoint, EVgo, Electrify America, Tesla Supercharger — session data (kWh, cost, duration)
- IFTA fuel tax reporting for cross-state tax obligations
- Bulk fuel: on-site fueling depots with tank-level inventory

**Maintenance & Repair:**
- Fleet maintenance systems: Fleetio, TMT FleetMaintenance, RTA Fleet Management, Whip Around
- Dealer/OEM service portals: warranty claims, recall service records, OEM service schedules
- Parts procurement: Genuine Parts/NAPA, FleetPride, TRP
- Tire management: Bridgestone, Michelin fleet programs — cost per tire, retread tracking
- Roadside assistance: FleetNet America, etc.

**Insurance & Risk:**
- Insurance carriers: premiums, claims history, deductibles (per-vehicle or per-fleet)
- Telematics-based insurance (UBI): driving behavior affects premiums
- Accident/incident data: repair costs, liability, downtime

**Asset & Financial:**
- Lease/finance: Element Fleet, ARI, Donlen — monthly lease costs, residual value schedules
- Depreciation: book value (straight-line or market-based)
- Registration & compliance: state fees, DOT inspections, permits
- Auction/resale: Manheim, ADESA — market pricing for buy/sell timing

**Labor & Operations:**
- Payroll/HR: driver wages, overtime, per diem
- Dispatch/TMS: Samsara, Omnitracs, Trimble — route efficiency, deadhead miles
- Toll management: PrePass, Bestpass — toll costs per vehicle per route

**Market & External:**
- Fuel price feeds: OPIS, GasBuddy, EIA — regional pricing for benchmarking
- Weather data: impacts on fuel efficiency, tire wear, accident risk
- Used vehicle market: KBB, NADA, Manheim Market Report — residual value benchmarking
- Regulatory: emissions credit pricing, EV incentive programs, CARB compliance costs

---

## 8. Agentic Core Architecture

### Design Philosophy

The TCO system is agent-first, dashboard-second. Agents do the work — monitoring, detecting, diagnosing, recommending. The CMS UI is the human-in-the-loop verification layer where operators review, approve, or override agent decisions. The dashboard visualizes what the agents are seeing and doing.

```
                    ┌─────────────────────────────┐
                    │     CMS UI (HiL Layer)       │
                    │                              │
                    │  Dashboard = what agents see  │
                    │  Action queue = what agents   │
                    │    want to do (pending        │
                    │    human approval)            │
                    │  History = what agents did    │
                    └──────────────┬───────────────┘
                                   │ approve / reject / override
                                   ▼
┌──────────────────────────────────────────────────────────────┐
│                    Agent Orchestrator                         │
│              (Step Functions + EventBridge)                   │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Monitor  │  │ Diagnose │  │ Recommend│  │ Learn    │    │
│  │ Agent    │→ │ Agent    │→ │ Agent    │→ │ Agent    │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└──────────────────────────────────────────────────────────────┘
                                   ▲
                    ┌──────────────┴───────────────┐
                    │       Cost Data Layer         │
                    │  Kafka · Redis · DynamoDB ·   │
                    │  Iceberg · Telemetry          │
                    └──────────────────────────────┘
```

### The Four Agents

#### Monitor Agent (always running)
**Trigger:** Continuous — processes every cost event as it arrives via Kafka

**What it does:**
- Watches cost streams in real time (fuel transactions, maintenance events, charging sessions, telemetry-derived costs)
- Maintains per-vehicle and per-fleet cost baselines in Redis
- Detects deviations: cost/mile spike, maintenance frequency increase, fuel efficiency drop, charging cost anomaly
- Applies both static thresholds (configurable) and ML-based dynamic thresholds (Phase 2)

**Output:** Cost anomaly events → Kafka `cms-cost-anomalies` → triggers Diagnose Agent

**Implementation:** Flink job (extends the cost processor) + SageMaker endpoint for anomaly scoring

#### Diagnose Agent (event-driven)
**Trigger:** Cost anomaly event from Monitor Agent

**What it does:**
- Receives an anomaly (e.g., "Vehicle X cost/mile jumped 40% this week")
- Queries across data sources to find root cause:
  - Maintenance history: any recent unplanned repairs?
  - Telemetry: driving behavior changes? Route changes? Idle time increase?
  - Predictive maintenance alerts: is there an active tire/battery/brake degradation?
  - Fuel data: price spike in region, or actual consumption increase?
  - Fleet context: is this vehicle-specific or fleet-wide?
- Produces a structured diagnosis with confidence score

**Output:** Diagnosis record → DynamoDB `cms-cost-diagnoses` → triggers Recommend Agent

**Implementation:** Bedrock Agent (Claude) with tool access to Athena (cost lake), DynamoDB (maintenance history, alerts), Redis (vehicle state)

#### Recommend Agent (event-driven)
**Trigger:** Diagnosis from Diagnose Agent

**What it does:**
- Takes the diagnosis and generates actionable recommendations:
  - "Schedule preventive maintenance for Vehicle X — brake wear detected, estimated $800 repair vs. $2,400 if it fails"
  - "Reassign Vehicle Y from Route A to Route B — fuel cost 22% lower due to terrain"
  - "Vehicle Z TCO trajectory exceeds replacement threshold — recommend retire at next service interval"
  - "Shift EV charging for Fleet B to off-peak hours — estimated $340/month savings"
- Estimates cost impact of each recommendation
- Assigns priority (critical / high / medium / low)

**Output:** Recommendation → DynamoDB `cms-cost-recommendations` with status `PENDING_APPROVAL`

**Implementation:** Bedrock Agent with cost optimization prompts + access to cost data + fleet constraints

#### Learn Agent (batch, daily)
**Trigger:** EventBridge daily schedule

**What it does:**
- Reviews completed recommendations: was the action taken? What was the actual cost impact?
- Compares predicted savings vs. actual savings
- Updates Monitor Agent thresholds based on outcomes (tighten thresholds that catch real issues, loosen ones that generate false positives)
- Retrains anomaly detection model with new data (weekly)
- Generates fleet-level insights: "This month, agent recommendations saved an estimated $X across Y actions"

**Output:** Updated thresholds in SSM Parameter Store, model retraining trigger, monthly insights report

**Implementation:** Lambda + SageMaker retraining pipeline + Bedrock for insight generation

#### Lifecycle Agent (event-driven + scheduled)
**Trigger:** Monthly schedule + on-demand from operator queries

**Why this requires agentic AI:**
A fleet of 10M+ vehicles generates billions of data points across telemetry, maintenance history, fuel consumption, battery health, market pricing, and depreciation curves. No human can synthesize this across every vehicle to find the optimal buy/sell/hold decision. An agent can — continuously, for every vehicle, simultaneously.

**What it does:**

Buy timing optimization:
- Ingests market pricing data (auction results, OEM incentive programs, seasonal trends)
- Correlates with fleet demand forecasts — which vehicle types will you need, where, and when?
- Recommends optimal purchase windows: "Class 8 trucks are 12% below 12-month average in Q1 — buy window for Region X fleet expansion"
- For EVs: tracks federal/state incentive deadlines, battery pricing trends, model year transitions

Sell timing optimization:
- Monitors per-vehicle residual value trajectory using maintenance history, mileage, telemetry-derived condition scores
- Compares against market residual values (auction data, KBB/NADA equivalent feeds)
- Detects the inflection point where holding costs exceed residual value decline
- For EVs: battery SoH is the key driver — "Battery at 78% SoH, sell before 75% threshold where residual drops 20%"
- Recommends: "List Vehicle X now — residual value $32K today, projected $26K in 6 months based on maintenance trajectory"

Hold vs. replace analysis:
- Calculates per-vehicle TCO trajectory: maintenance cost curve (rising) vs. replacement depreciation cost (new vehicle)
- Identifies the crossover point where replacing is cheaper than maintaining
- Factors in: downtime cost of aging vehicles, fuel efficiency degradation, compliance risk
- "Vehicle Y crossover in 4 months — replacement saves $8,200/year in maintenance + downtime"

Fleet mix optimization:
- Analyzes TCO per route: ICE vs. EV factoring fuel/charging costs, range requirements, infrastructure availability
- Recommends fleet composition changes: "Convert Route A to EV — $14K/year savings per vehicle, charging infrastructure ROI in 18 months"
- Seasonal adjustments: "Add 15 vehicles to Region B for Q4 demand surge — lease vs. buy analysis attached"

**The scale argument:**
- A human analyst can maybe evaluate 50 vehicles per week for lifecycle decisions
- The Lifecycle Agent evaluates every vehicle in the fleet, every day, against current market conditions
- At 10M vehicles, that's 10M buy/sell/hold decisions continuously optimized — impossible without agentic AI
- The agent doesn't just flag — it synthesizes telemetry + maintenance + market data + fleet demand into a specific, costed recommendation

**Output:** Lifecycle recommendations → DynamoDB `cms-cost-recommendations` with category `LIFECYCLE` + status `PENDING_APPROVAL`

**Implementation:** Bedrock Agent with access to cost lake (Athena), vehicle state (Redis), market data (S3), fleet demand forecasts (SageMaker)

### Human-in-the-Loop (HiL) in the CMS UI

#### Action Queue (`/fleet-costs/actions`)
New page in CMS UI — the operator's inbox for agent recommendations.

| Column | Description |
|--------|-------------|
| Priority | Critical / High / Medium / Low |
| Vehicle | Affected vehicle(s) |
| Recommendation | What the agent wants to do |
| Diagnosis | Why (linked to full diagnosis) |
| Estimated Impact | Projected cost savings |
| Confidence | Agent's confidence score |
| Status | Pending / Approved / Rejected / Auto-approved |
| Actions | Approve / Reject / Override / Snooze |

**Auto-approval rules:** Operators can configure thresholds for auto-approval:
- "Auto-approve maintenance scheduling recommendations with confidence > 90% and cost < $500"
- "Auto-approve EV charge schedule changes"
- "Always require approval for vehicle retirement recommendations"

Stored in DynamoDB `cms-cost-approval-rules` per fleet.

#### Agent Activity Feed
Sidebar widget on the Fleet TCO Dashboard showing real-time agent activity:
- "Monitor Agent detected fuel cost anomaly on VEH-042 (12:34 PM)"
- "Diagnose Agent identified root cause: route change increased mileage 18% (12:35 PM)"
- "Recommend Agent: reassign to original route, est. savings $220/month (12:35 PM)"
- "Awaiting your approval →"

#### Diagnosis Detail View
When an operator clicks into a recommendation, they see the full agent reasoning:
- What was detected (the anomaly)
- What data the agent queried (telemetry, maintenance, fuel, routes)
- What it concluded (root cause + confidence)
- What it recommends (action + estimated impact)
- What happens if you do nothing (projected cost trajectory)

This is the transparency layer — the operator can see exactly why the agent made the recommendation and decide whether to trust it.

### Agent State Management

```
DynamoDB Tables:
├── cms-cost-anomalies        — Monitor Agent output
├── cms-cost-diagnoses         — Diagnose Agent output (linked to anomaly)
├── cms-cost-recommendations   — Recommend Agent output (linked to diagnosis)
│   └── status: PENDING_APPROVAL | APPROVED | REJECTED | AUTO_APPROVED | EXECUTED | EXPIRED
├── cms-cost-approval-rules    — Per-fleet auto-approval configuration
└── cms-cost-agent-metrics     — Learn Agent tracking (predicted vs. actual)
```

Each record links back: recommendation → diagnosis → anomaly → original cost event. Full audit trail.

### Phased Rollout of Agentic Capabilities

**Phase 1 (build with the dashboard):**
- Monitor Agent: static thresholds only, generates cost alerts
- No Diagnose/Recommend/Learn yet
- Action queue UI is built but shows alerts, not recommendations
- This means the UI and data model are agent-ready from day one

**Phase 2 (add intelligence):**
- Monitor Agent: ML-based dynamic thresholds (SageMaker RCF)
- Diagnose Agent: Bedrock Agent with data source access
- Recommend Agent: generates recommendations with cost estimates
- Action queue becomes the real HiL approval workflow
- Auto-approval rules configurable

**Phase 3 (close the loop):**
- Learn Agent: tracks outcomes, adjusts thresholds, retrains models
- Agent-to-agent communication: Diagnose Agent can ask Monitor Agent for historical context
- NL queries: "Why is Region X over budget?" → Diagnose Agent investigates on demand
- Fully autonomous mode available (all auto-approve) for operators who trust the system

---

## 9. Semantic Layer

The Bedrock Agent needs to understand the data — what tables exist, what columns mean, what relationships are, what "normal" looks like. Without a semantic layer, the agent guesses at SQL and misinterprets fields.

### Layer 1: Athena Views (encode business logic in SQL)

Pre-built views that turn raw Iceberg tables into business-meaningful datasets. The agent queries views first, raw tables only when views don't cover it.

| View | Purpose |
|------|---------|
| `v_fleet_tco_summary` | Pre-joined, pre-aggregated fleet cost by category (MTD, YTD) |
| `v_vehicle_cost_outliers` | Vehicles exceeding fleet average thresholds, ranked by severity |
| `v_cost_trend_monthly` | Monthly rollups by category for trend analysis |
| `v_lifecycle_candidates` | Vehicles approaching hold-vs-replace crossover point |
| `v_maintenance_forecast` | Predicted vs. actual maintenance cost per vehicle |
| `v_fleet_comparison` | Side-by-side cost metrics for two fleets |
| `v_cost_by_route` | Cost per mile by route for ICE vs. EV comparison |

### Layer 2: Bedrock Knowledge Base (RAG for context)

S3-backed knowledge base that the agent retrieves from when it needs to understand what something means.

| Document | Content |
|----------|---------|
| Schema documentation | What each table/column means in business terms, not just technical types |
| Business glossary | TCO definition, cost category rules, what counts as "unplanned maintenance" |
| Query cookbook | Example queries with explanations — few-shot patterns the agent can adapt |
| Fleet operator playbook | "When you see X, investigate Y" — domain expertise encoded as documents |
| Threshold definitions | What's "normal" by vehicle type, fleet, region, season |

### Layer 3: Agentic Guardrails (Amazon Bedrock Guardrails)

Enforced at the Bedrock Guardrails level — not just prompt instructions:

- Tenant isolation: never return data from a fleet the operator doesn't have access to
- Cost thresholds: recommendations exceeding configurable amount require human approval
- Confidence requirements: low-confidence diagnoses are flagged, not acted on
- Denied actions: certain actions (vehicle retirement, fleet-wide changes) always require human approval
- Content filters: prevent hallucinated financial figures or fabricated data

### How It Fits Together

```
Operator asks: "Why is Region X over budget?"
    │
    ▼
Bedrock Agent receives question
    │
    ├── Retrieves context from Knowledge Base: "TCO includes fuel, maintenance, charging, insurance, depreciation"
    ├── Queries v_fleet_tco_summary via Athena: Region X fuel +18%, maintenance +22%
    ├── Queries v_cost_trend_monthly: maintenance spike started 6 weeks ago
    ├── Queries get_maintenance_history: 8 vehicles with unplanned brake repairs
    ├── Queries get_vehicle_state: those 8 vehicles show hard braking events up 200%
    ├── Retrieves playbook from KB: "maintenance spike + driving behavior = driver coaching opportunity"
    │
    ▼
Agent responds: "Region X is $42K over budget MTD. Root causes: fuel prices up 12% (market, uncontrollable)
and 8 vehicles with repeated brake repairs driven by aggressive driving patterns. Recommendation: enroll
drivers on routes 14, 22, 31 in safety coaching program. Estimated savings: $6,800/month."
    │
    ▼
Recommendation written to DynamoDB → appears in CMS UI action queue → operator approves
```

---

## 10. Implementation Plan

### Phase 1 (4 weeks): Visibility
- [ ] DynamoDB cost_transactions table + Iceberg schema
- [ ] Flink cost processor (telemetry-derived fuel/energy/idle)
- [ ] CSV upload endpoint + Glue ETL
- [ ] REST API endpoints in main_api Lambda
- [ ] CMS UI: Fleet TCO Dashboard page
- [ ] CMS UI: Vehicle Cost tab
- [ ] CMS UI: Cost KPI widget on main dashboard
- [ ] Cost alerts integration (anomaly thresholds — static)

### Phase 2 (4 weeks): Intelligence
- [ ] Fuel card API connector (WEX or FleetCor)
- [ ] EV charging API connector (ChargePoint)
- [ ] SageMaker cost anomaly detection model
- [ ] Maintenance cost forecasting model
- [ ] CMS UI: Cost trend forecasting chart
- [ ] CMS UI: Maintenance forecast widget
- [ ] Dynamic cost alert thresholds (ML-driven)

### Phase 3 (4 weeks): Agentic
- [ ] Cost anomaly agent (Bedrock Agents)
- [ ] Lifecycle agent
- [ ] NL cost queries in CMS UI
- [ ] EV charge schedule optimization
- [ ] Agent action integration (auto-schedule maintenance, adjust routes)

---

## 10. Integration with OEM Normalization Pipeline

### How TCO Connects

The TCO system is a downstream consumer of the existing normalization pipeline — it does NOT modify or fork the telemetry flow.

```
EXISTING PIPELINE (no changes)
cms-telemetry-preprocessed (canonical JSON)
    │
    └── EventDrivenTelemetryProcessor routes to:
        ├── cms-telemetry-processed     (Redis + DDB)
        ├── cms-telemetry-trips         (TripProcessor)
        ├── cms-telemetry-safety        (SafetyProcessor)
        ├── cms-telemetry-maintenance   (MaintenanceProcessor)
        ├── cms-fleet-{fleetId}-telemetry (WebSocket)
        └── S3 Iceberg sink

NEW FOR TCO (additive only)
cms-telemetry-preprocessed (same topic, new consumer group)
    │
    └── CostProcessor (new Flink job, consumer group: cms-cost-processor)
        ├── Reads: speed, fuelLevel, odometer, batterySoC, ignitionOn
        ├── Computes: fuel consumption, energy usage, idle time, cost/mile
        ├── Writes to:
        │   ├── Redis: vehicle:{vehicleId}:cost hash (latest cost state)
        │   ├── Kafka: cms-cost-events (cost events for downstream agents)
        │   └── Kafka: cms-cost-anomalies (when thresholds exceeded)
        │
cms-cost-events
    │
    └── S3 Iceberg sink → cms_cost_analytics table (same sink pattern as telemetry)

cms-cost-anomalies
    │
    └── Diagnose Agent (Bedrock) → Recommend Agent → Action Queue (CMS UI)
```

### What We Reuse (no changes needed)

| Component | How TCO Uses It |
|-----------|----------------|
| `cms-telemetry-preprocessed` topic | CostProcessor reads canonical signals (new consumer group, no impact on existing consumers) |
| Signal catalog DynamoDB table | CostProcessor looks up `fuelLevel`, `batterySoC`, `odometer`, `speed`, `ignitionOn` by `json_field` |
| Redis vehicle state | Add `vehicle:{vehicleId}:cost` hash alongside existing `vehicle:{vehicleId}:state` hash |
| Fleet enrollment table | CostProcessor uses same `vehicleId → fleetId` lookup for fleet-scoped cost partitioning |
| Lake Formation policies | Same row-level security pattern — cost Iceberg tables partitioned by `fleetId` |
| Cognito auth + `custom:fleetIds` | Cost API endpoints use same JWT scoping as telemetry endpoints |
| S3 Iceberg sink pattern | Cost data uses same Flink S3 sink approach, separate table (`cms_cost_analytics`) |
| CMS UI (main_api Lambda) | New `/costs` routes added to existing Lambda, same auth middleware |
| Existing alerts system (alarm_recorder) | Cost alerts flow through same DynamoDB alerts table + CMS UI alerts page |

### What We Add (new components)

| Component | Purpose |
|-----------|---------|
| CostProcessor Flink job | Derives fuel/energy/idle costs from telemetry, joins with external cost data, writes to S3 + Redis + DynamoDB |
| Source-specific Flink normalizers | FuelCostNormalizer, MaintenanceCostNormalizer, ChargingCostNormalizer, AssetCostNormalizer |
| `cms-cost-normalized` Kafka topic | Canonical cost format (intermediate, consumed by CostProcessor) |
| `cms-cost-transactions` DynamoDB table | Recent cost transactions + anomaly flags (triggers agents via DynamoDB Streams) |
| `cms_cost_analytics` Iceberg table | Historical cost data for Athena queries |
| `cms-cost-recommendations` DynamoDB table | Agent recommendations + HiL approval state |
| Cost UI components | New pages/tabs in CMS UI React app |
| CSV upload Glue ETL | S3 → normalize → Kafka source topics for uploaded cost data |

### Redis Key Structure

Existing (unchanged):
```
vehicle:{vehicleId}:state → { speed, lat, lng, fuelLevel, ... }
vehicle:{vehicleId}:geo   → GEOADD for proximity queries
```

New (additive):
```
vehicle:{vehicleId}:cost → {
    cost_per_mile_30d, fuel_rate_mpg, maintenance_mtd,
    total_cost_mtd, fleet_avg_cost_per_mile, cost_anomaly,
    last_updated
}
fleet:{fleetId}:cost → {
    total_cost_mtd, avg_cost_per_mile, vehicle_count,
    top_cost_category, anomaly_count
}
```

CMS UI REST API reads from both `:state` and `:cost` hashes to render the vehicle detail page with telemetry + cost in a single view.

### CSV Upload Path

```
CMS UI upload → S3: s3://{bucket}/cost-uploads/{fleetId}/{filename}.csv
    │
    └── S3 event → Glue ETL job
        ├── Validates schema (vehicleId, date, category, amount, ...)
        ├── Validates fleetId matches uploader's Cognito fleetIds claim
        ├── Normalizes categories to standard enum
        ├── Writes to DynamoDB cms-cost-transactions (recent)
        └── Writes to S3 Iceberg cms_cost_analytics (historical)
```

Same S3 → Glue → Iceberg pattern used by the telemetry normalization data product. Lake Formation enforces that uploaded data is only visible to the uploading fleet's operators.

| Dependency | Repo | Required For |
|-----------|------|-------------|
| CMS core (storage, IoT, MSK, Flink) | `connected-mobility-guidance-on-aws` | All phases |
| CMS UI | `connected-mobility-guidance-on-aws/modules/cms_ui` | All phases |
| Telemetry normalization | `automotive-data-platform-on-aws/guidance-for-telemetry-normalization` | Telemetry-derived costs |
| Predictive maintenance | `automotive-data-platform-on-aws/guidance-for-predictive-maintenance` | Maintenance forecasting (Phase 2) |

---

## 11. Open Questions

1. **Fuel card provider priority:** WEX, Comdata, or FleetCor first? Or generic CSV to start?
2. **Currency handling:** USD only for v1, or multi-currency from the start?
3. **Depreciation model:** straight-line, declining balance, or market-value based?
4. **Cost allocation:** how to handle shared costs (insurance per fleet vs. per vehicle)?
5. **Historical data backfill:** how far back do we need cost data for meaningful trends?
