# Fleet Rebalancing — Architecture Diagram Build Guide (for Canva)

**Style:** Match predictive maintenance reference architecture (dark background #0E1220, AWS service icons, numbered green circles, pink/magenta flow boxes)

**Dimensions:** 20" × 11.25" (same as deck)

---

## Layout: Left-to-right flow, 5 numbered sections

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  Title bar (top)                                                                     │
│  "Guidance for an Automotive Data Platform on AWS"                                   │
│  "Creating operational value from Fleet Utilization Intelligence"                     │
│  "Build an agentic fleet rebalancing pipeline that optimizes vehicle placement"       │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                      │
│  ┌──────────┐    ┌──────────────────┐    ┌──────────────────┐                       │
│  │    1      │    │       2          │    │       3          │                       │
│  │  Fleet    │───→│  Utilization     │───→│  Data Lake &     │                       │
│  │  Data     │    │  Processing      │    │  Visualization   │                       │
│  │  Ingestion│    │                  │    │                  │                       │
│  └──────────┘    └──────────────────┘    └────────┬─────────┘                       │
│                                                    │                                 │
│                                                    │ DynamoDB Streams                │
│                                                    ▼                                 │
│                                           ┌──────────────────┐    ┌────────────────┐│
│                                           │       4          │    │      5         ││
│                                           │  Agentic         │───→│  Fleet         ││
│                                           │  Intelligence    │    │  Operator      ││
│                                           │                  │    │  Interface     ││
│                                           └──────────────────┘    └────────────────┘│
│                                                                                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│  Footer: aws logo · "Reviewed for technical accuracy March 2026"                     │
│  "© 2026, Amazon Web Services, Inc. or its affiliates. All rights reserved."         │
│  "AWS Reference Architecture"                                                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Section 1: Fleet Data Ingestion (green circle: 1)

**Service icons (left column, vertical stack):**

| Icon | Label | Sub-label |
|------|-------|-----------|
| Amazon MSK | Amazon MSK | cms-telemetry-preprocessed |
| Amazon DynamoDB | DynamoDB | Fleet Enrollment (vehicleId → fleetId → location) |
| Amazon S3 | Amazon S3 | Demand Signals (CSV upload, booking data) |
| Amazon DynamoDB | DynamoDB | Constraints (depots, capacity, maintenance, charging) |

**Arrows:** All four → into Section 2

---

## Section 2: Utilization Processing (green circle: 2)

**Contained in a pink/magenta bordered box (like the predictive maintenance training/inference boxes)**

**Top row: UtilizationProcessor**

| Icon | Label | Sub-label |
|------|-------|-----------|
| Apache Flink | Apache Flink | UtilizationProcessor |

Text below Flink icon:
- "Reads: telemetry (location, status, trips) + fleet enrollment"
- "Computes: per-vehicle, per-location, per-region utilization"
- "Detects: supply-demand imbalances"

**Bottom row: Demand Forecasting**

| Icon | Label | Sub-label |
|------|-------|-----------|
| Amazon SageMaker | Amazon SageMaker | Demand Forecasting (time series) |

Text below SageMaker icon:
- "7-day / 30-day predictions per location"
- "Seasonal patterns, event-driven demand"

**Arrows out:** → S3 Iceberg, → Redis, → DynamoDB (three outputs)

---

## Section 3: Utilization Data Lake & Visualization (green circle: 3)

**Service icons (vertical stack or 2×3 grid):**

| Icon | Label | Sub-label |
|------|-------|-----------|
| Amazon S3 | S3 Iceberg | cms_fleet_utilization · cms_demand_forecasts |
| AWS Lake Formation | Lake Formation | Row-level security per fleet |
| AWS Glue | Glue Catalog | Schema management |
| Amazon Athena | Amazon Athena | Utilization views · Supply-demand gap · Transfer costs · Rebalance history |
| Amazon ElastiCache | ElastiCache (Redis) | Real-time utilization per vehicle, location, region |
| Amazon DynamoDB | DynamoDB | Rebalance events · Imbalance flags · Recommendations |

**Arrow out:** DynamoDB → (labeled "DynamoDB Streams") → Section 4

---

## Section 4: Agentic Intelligence (green circle: 4)

**Service icons (5 icons):**

| Icon | Label | Sub-label |
|------|-------|-----------|
| AWS Lambda | Lambda | Agent Core Gateway |
| Amazon Bedrock | Bedrock Guardrails | Tenant isolation · Cost thresholds · Constraint enforcement |
| Amazon Bedrock | Bedrock Knowledge Base | Schema docs · Rebalancing playbook · Query cookbook |
| Amazon Bedrock | Bedrock Agent (Rebalancing) | Diagnose gaps · Recommend moves · Check constraints · Estimate costs |
| Amazon SageMaker | SageMaker | Anomaly Scoring (Phase 2) |

**Arrows:**
- Lambda → Bedrock Agent (trigger)
- Bedrock Agent → Athena (query utilization — dashed arrow back to Section 3)
- Bedrock Agent → Redis (get state + forecasts — dashed arrow back to Section 3)
- Bedrock Agent → DynamoDB Constraints (check constraints — dashed arrow back to Section 1)
- Bedrock Agent → DynamoDB Recommendations (write recommendation — arrow to Section 3)
- Bedrock Agent → Section 5 (recommendation to action queue)

---

## Section 5: Fleet Operator Interface (green circle: 5)

**Service icons:**

| Icon | Label | Sub-label |
|------|-------|-----------|
| Amazon CloudFront | CloudFront | CMS UI |
| Amazon API Gateway | API Gateway | REST API |
| Amazon Cognito | Cognito | JWT Auth · Fleet scoping |
| Amazon Location Service | Location Service | Map rendering · GEOSEARCH |

**Text callout box (right side):**

**Rebalancing Dashboard**
- Map view: vehicle locations color-coded by status
- Supply-demand heatmap: surplus vs. deficit by region
- Utilization KPIs: fleet-wide %, by region, by vehicle type
- Demand forecast overlay: next 7/30 days

**Action Queue**
- Agent-recommended moves with cost + revenue impact
- Approve / reject / modify
- Auto-approval rules

**Vehicle Availability**
- Filterable by type, fuel, range, maintenance status

---

## Color Palette

| Element | Color | Hex |
|---------|-------|-----|
| Background | Dark navy | #0E1220 |
| Card/box background | Darker navy | #161B2E |
| Section borders (processing boxes) | Magenta/pink | #F472B6 |
| Numbered circles | Green | #34D399 |
| Primary text | Light gray | #BEC8DC |
| Headings | White | #FFFFFF |
| Accent (arrows, highlights) | Cyan | #38BDF8 |
| AWS orange | Orange | #FF9900 |
| Agent accent | Purple | #8B5CF6 |

---

## Arrow Style

- Solid arrows: data flow (ingestion → processing → storage)
- Dashed arrows: agent queries back to data layer (agent → Athena, agent → Redis)
- Arrow color: #38BDF8 (cyan) for data flow, #8B5CF6 (purple) for agent interactions
- Arrow labels: small text describing what flows ("DynamoDB Streams", "write recommendation", "query utilization")
