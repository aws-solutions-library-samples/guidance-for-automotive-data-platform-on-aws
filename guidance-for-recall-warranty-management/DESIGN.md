# Recall & Warranty Management — Design Document

## ADP Data Product: `guidance-for-recall-warranty-management`

**Author:** Andrew Givens | **Date:** March 2026 | **Status:** Draft

---

## 1. Problem Statement

Fleet operators face two related but distinct operational headaches:

**Recalls:** When an OEM issues a recall, the fleet operator must identify which vehicles are affected, determine severity, schedule service at dealers, manage fleet coverage while vehicles are out, track completion, and prove compliance. Today this is manual — emails, spreadsheets, phone calls. Blanket recalls pull in vehicles that may not actually have the defect, wasting downtime on healthy assets.

**Warranty claims:** When a component fails under warranty, the fleet operator must document the failure, prove it's warranty-eligible, file the claim with the OEM, and track reimbursement. Most fleets leave money on the table because the process is too manual — technicians don't always know what's covered, claims get filed late or with incomplete documentation, and there's no systematic way to identify warranty-eligible failures across the fleet.

Both problems share root causes: data is scattered across OEM portals, dealer systems, maintenance records, and telemetry platforms. Coordination is manual. There's no single system that connects the recall/warranty notice to the vehicle's actual condition to the service scheduling to the compliance documentation.

---

## 2. Design Principles

1. **Build in the CMS UI** — recall and warranty views are new pages/components in the existing fleet operator interface
2. **Leverage existing infrastructure** — normalized telemetry, predictive maintenance alerts, fleet enrollment, Athena/Iceberg data lake
3. **Agent-first** — the Bedrock Agent monitors for recalls, cross-references telemetry, identifies affected vehicles, schedules service, files warranty claims, and tracks completion. Dashboard visualizes. Action queue approves.
4. **Blanket → targeted** — use telemetry data to distinguish vehicles that actually exhibit the defect from those that are just in the recall population

---

## 3. Architecture Overview

```
DATA SOURCES
├── Recall notices (new ingestion)
│   ├── OEM recall feeds → Kafka: cms-recall-notices
│   ├── NHTSA recall database → Lambda poller → Kafka: cms-recall-notices
│   └── Manual entry via CMS UI → DynamoDB
│
├── Warranty data (new ingestion)
│   ├── OEM warranty terms → S3 (coverage rules by component, mileage, age)
│   ├── Warranty claim history → CSV upload or API → Kafka: cms-warranty-claims
│   └── Parts catalog with warranty coverage → DynamoDB
│
├── Vehicle data (existing CMS pipeline)
│   ├── Normalized telemetry (cms-telemetry-preprocessed) — component health signals
│   ├── Predictive maintenance alerts — degradation patterns from tire/battery models
│   ├── Fleet enrollment — VIN, vehicle type, age, mileage
│   ├── Maintenance history — past service records, parts replaced
│   └── DTC codes — diagnostic trouble codes from telemetry
│
└── Dealer/service data
    ├── Dealer locations + parts availability → S3 or DynamoDB
    ├── Service scheduling availability → API or manual
    └── Service completion records → CSV upload or API

NORMALIZATION & PROCESSING (MSK + Flink)
├── RecallProcessor (Flink)
│   ├── Reads: cms-recall-notices + fleet enrollment
│   ├── Matches recall VIN ranges against fleet VIN database
│   ├── Cross-references telemetry to identify vehicles actually exhibiting defect
│   ├── Classifies: CONFIRMED (telemetry shows defect) vs. POPULATION (VIN match only)
│   ├── Assigns severity: GROUND_IMMEDIATELY / SCHEDULE_SOON / MONITOR
│   └── Writes directly to:
│       ├── S3 Iceberg: cms_recall_tracking (historical)
│       ├── Redis: active recall state per vehicle
│       └── DynamoDB: cms-recall-events (affected vehicles + severity + status)
│
├── WarrantyProcessor (Flink)
│   ├── Reads: cms-telemetry-preprocessed + maintenance events + warranty terms
│   ├── Detects component failures that match warranty coverage rules
│   ├── Validates: within mileage limit? Within age limit? Component covered?
│   ├── Flags warranty-eligible failures automatically
│   └── Writes directly to:
│       ├── S3 Iceberg: cms_warranty_tracking (historical)
│       ├── Redis: warranty state per vehicle
│       └── DynamoDB: cms-warranty-events (eligible failures + claim status)

DATA LAKE & VISUALIZATION
├── S3 Iceberg: cms_recall_tracking (partitioned by fleetId + recall_id)
├── S3 Iceberg: cms_warranty_tracking (partitioned by fleetId + month)
├── Athena views:
│   ├── v_active_recalls — open recalls with affected vehicle counts and completion %
│   ├── v_recall_vehicle_status — per-vehicle recall status (pending/scheduled/completed/exempt)
│   ├── v_warranty_eligible — vehicles with warranty-eligible failures not yet claimed
│   ├── v_warranty_claims — filed claims with status (submitted/approved/denied/paid)
│   ├── v_warranty_recovery — total $ recovered through warranty claims
│   ├── v_recall_compliance — audit-ready compliance report with timestamps
│   └── v_recall_fleet_impact — revenue impact of vehicles out for recall service
├── Lake Formation: row-level security per fleet
├── Redis: active recall + warranty state per vehicle
└── DynamoDB: recall events, warranty events, recommendations, service scheduling

AGENTIC INTELLIGENCE
├── Agent Core Gateway (Lambda) — triggers:
│   ├── DynamoDB Streams: new recall notice ingested
│   ├── DynamoDB Streams: warranty-eligible failure detected
│   ├── EventBridge Schedule: daily compliance review
│   └── CMS UI: operator asks "What's the status of recall X?"
│
├── Agentic Guardrails (Bedrock Guardrails)
│   ├── Tenant isolation (fleet-scoped)
│   ├── Safety recalls: never auto-exempt a vehicle from a safety recall
│   ├── Warranty claims: require human approval before filing with OEM
│   ├── Grounding decisions: require approval for GROUND_IMMEDIATELY actions
│   └── Compliance: never mark a recall complete without service record
│
├── Amazon Bedrock Knowledge Base
│   ├── Schema docs: recall tables, warranty tables, maintenance history
│   ├── Recall playbook: severity classification rules, scheduling priorities
│   ├── Warranty playbook: coverage rules, claim filing procedures, documentation requirements
│   ├── Query cookbook: example queries for recall status, warranty eligibility
│   └── Regulatory reference: NHTSA requirements, legal liability for safety recalls
│
├── Amazon Bedrock Agent (Recall & Warranty)
│   ├── Tools:
│   │   ├── match_recall_to_fleet (Athena) — VIN matching + telemetry cross-reference
│   │   ├── assess_vehicle_condition (Redis/DynamoDB) — telemetry signals for defect confirmation
│   │   ├── find_nearest_dealer (Lambda) — dealer location + parts availability + scheduling
│   │   ├── schedule_service (API/DynamoDB) — book appointment, update vehicle status
│   │   ├── check_warranty_eligibility (DynamoDB) — coverage rules vs. vehicle age/mileage/component
│   │   ├── draft_warranty_claim (DynamoDB) — pre-fill claim with telemetry evidence + service records
│   │   ├── trigger_fleet_rebalance (DynamoDB) — notify rebalancing agent to cover grounded vehicles
│   │   ├── write_recommendation (DynamoDB) — recall/warranty action with PENDING_APPROVAL
│   │   ├── generate_compliance_report (Athena) — audit-ready recall completion report
│   │   └── get_recall_status (Athena/DynamoDB) — current status of any recall across fleet
│   │
│   ├── Recall flow: notice → VIN match → telemetry cross-ref → severity → schedule → rebalance → track → compliance
│   ├── Warranty flow: failure detected → eligibility check → evidence gathering → draft claim → human approves → file → track payment
│   └── Learn: track claim approval rates, improve eligibility matching, optimize dealer selection

FLEET OPERATOR INTERFACE (CMS UI)
├── Recall Management Dashboard (/recall-management)
│   ├── Active Recalls: list of open recalls with affected count, completion %, severity
│   ├── Vehicle Status: per-vehicle recall status (pending/scheduled/completed/exempt)
│   ├── Compliance Tracker: % complete with deadline countdown
│   ├── Fleet Impact: vehicles currently out for recall service, revenue impact estimate
│   └── Map View: affected vehicles by location, nearest dealers with parts
│
├── Warranty Management Dashboard (/warranty-management)
│   ├── Eligible Failures: vehicles with warranty-eligible failures not yet claimed
│   ├── Open Claims: filed claims with status tracking
│   ├── Recovery Summary: total $ recovered MTD/YTD, claim approval rate
│   ├── Expiring Coverage: vehicles approaching warranty expiration with known issues
│   └── Claim Detail: pre-filled claim with telemetry evidence, service records, coverage proof
│
├── Action Queue (shared with other agents)
│   ├── Recall actions: ground vehicle, schedule service, exempt (with justification)
│   ├── Warranty actions: file claim, escalate denied claim, approve pre-filled claim
│   ├── Auto-approval rules:
│   │   ├── "Auto-schedule non-safety recalls at next regular service interval"
│   │   ├── "Auto-file warranty claims under $500 with confidence > 90%"
│   │   ├── "Always require approval for GROUND_IMMEDIATELY"
│   └── Rebalancing integration: when vehicles are grounded, auto-trigger rebalancing recommendation
│
└── Agent Activity Feed
    ├── "New recall: NHTSA #26-042 — brake actuator. 47 vehicles matched in your fleet."
    ├── "Telemetry cross-ref: 12 vehicles show early-stage wear. 35 VIN-match only."
    ├── "Recommended: Ground 12 immediately. Schedule 35 over next 2 weeks."
    ├── "Warranty: Vehicle X brake pad failure — covered under powertrain warranty (38K miles, limit 50K). Claim drafted."
    └── "Awaiting your approval →"
```

---

## 4. Key Differentiator: Blanket → Targeted Recalls

The biggest value-add is using telemetry to turn blanket recalls into targeted recalls:

```
Traditional (blanket):
  Recall notice → VIN match → 200 vehicles affected → all 200 go to dealer → 150 had no actual defect → wasted downtime

With telemetry cross-reference (targeted):
  Recall notice → VIN match → 200 vehicles in population
    → cross-reference telemetry signals for defect indicators
    → 47 vehicles show early-stage wear patterns (CONFIRMED)
    → 153 vehicles show no defect indicators (POPULATION only)
    → Ground 12 highest-severity CONFIRMED vehicles immediately
    → Schedule 35 remaining CONFIRMED for service over 2 weeks
    → Monitor 153 POPULATION vehicles — schedule only if telemetry changes
    → Result: 75% fewer unnecessary service pulls
```

This requires the telemetry normalization pipeline + predictive maintenance models to be in place — which is why this guidance builds on top of both.

---

## 5. Key Differentiator: Automatic Warranty Recovery

Most fleets leave warranty money on the table because:
- Technicians don't know what's covered
- Claims are filed late (after warranty expires)
- Documentation is incomplete (no telemetry evidence)
- Nobody systematically scans the fleet for warranty-eligible failures

The agent changes this:

```
Traditional:
  Part fails → technician replaces it → maybe someone checks if it's under warranty → maybe a claim gets filed → maybe it gets paid

With agent:
  Telemetry detects component degradation
    → agent checks warranty terms: component covered? Within mileage? Within age?
    → agent gathers evidence: telemetry data showing failure pattern, DTC codes, maintenance history
    → agent drafts claim with all required documentation pre-filled
    → operator reviews and approves in action queue
    → claim filed with OEM automatically
    → agent tracks status: submitted → approved → paid
    → agent flags expiring warranties: "Vehicle Y has 3 known issues, warranty expires in 60 days — file now"
```

---

## 6. Data Model

### DynamoDB: `cms-{stage}-recall-events`

| Key | Type | Description |
|-----|------|-------------|
| `recallId#vehicleId` (PK) | String | Composite key |
| `fleetId` (GSI) | String | Fleet scope |
| `recall_source` | String | NHTSA, OEM, manual |
| `recall_description` | String | What the recall is for |
| `severity` | String | GROUND_IMMEDIATELY / SCHEDULE_SOON / MONITOR |
| `match_type` | String | CONFIRMED (telemetry) / POPULATION (VIN only) |
| `status` | String | PENDING / SCHEDULED / IN_SERVICE / COMPLETED / EXEMPT |
| `dealer_id` | String | Assigned dealer |
| `scheduled_date` | String | Service appointment date |
| `completed_date` | String | Service completion date |
| `compliance_verified` | Boolean | Audit trail complete |

### DynamoDB: `cms-{stage}-warranty-events`

| Key | Type | Description |
|-----|------|-------------|
| `vehicleId#componentId#timestamp` (PK) | String | Composite key |
| `fleetId` (GSI) | String | Fleet scope |
| `component` | String | Failed component |
| `failure_type` | String | DTC code or description |
| `warranty_eligible` | Boolean | Meets coverage rules |
| `coverage_remaining` | Map | Miles remaining, days remaining |
| `claim_status` | String | NOT_FILED / DRAFTED / SUBMITTED / APPROVED / DENIED / PAID |
| `claim_amount` | Number | Claimed amount |
| `paid_amount` | Number | Reimbursed amount |
| `evidence` | Map | Telemetry data, DTC codes, service records |

### S3 Iceberg: `cms_recall_tracking`

```sql
CREATE TABLE cms_recall_tracking (
    recallId STRING,
    vehicleId STRING,
    fleetId STRING,
    vin STRING,
    recall_source STRING,
    severity STRING,
    match_type STRING,
    status STRING,
    scheduled_date DATE,
    completed_date DATE,
    dealer_id STRING,
    compliance_verified BOOLEAN,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)
PARTITIONED BY (fleetId, recallId)
```

### S3 Iceberg: `cms_warranty_tracking`

```sql
CREATE TABLE cms_warranty_tracking (
    vehicleId STRING,
    fleetId STRING,
    component STRING,
    failure_type STRING,
    warranty_eligible BOOLEAN,
    claim_status STRING,
    claim_amount DOUBLE,
    paid_amount DOUBLE,
    filed_date DATE,
    resolved_date DATE,
    evidence_summary STRING
)
PARTITIONED BY (fleetId, month(filed_date))
```

### Redis: Recall & Warranty State

```
vehicle:{vehicleId}:recall → {
    active_recalls: [{ recallId, severity, status, match_type }],
    recall_count: 2,
    grounded: false,
    last_updated
}

vehicle:{vehicleId}:warranty → {
    eligible_claims: [{ component, failure_type, coverage_remaining, claim_status }],
    total_recovered_ytd: 4200.00,
    expiring_soon: [{ component, days_remaining }],
    last_updated
}

fleet:{fleetId}:recall_summary → {
    active_recalls: 3,
    vehicles_affected: 47,
    vehicles_completed: 31,
    completion_pct: 66,
    vehicles_grounded: 4
}

fleet:{fleetId}:warranty_summary → {
    eligible_unfiled: 12,
    claims_open: 8,
    recovered_ytd: 142000.00,
    expiring_60d: 5
}
```

---

## 7. Semantic Layer

### Athena Views

| View | Purpose |
|------|---------|
| `v_active_recalls` | Open recalls with affected count, completion %, severity breakdown |
| `v_recall_vehicle_status` | Per-vehicle status across all active recalls |
| `v_warranty_eligible` | Vehicles with warranty-eligible failures not yet claimed |
| `v_warranty_claims` | Filed claims with status tracking |
| `v_warranty_recovery` | Total $ recovered by fleet, by month, by component |
| `v_recall_compliance` | Audit-ready report: recall → vehicles → service dates → completion |
| `v_recall_fleet_impact` | Revenue impact: vehicles out for service × daily revenue rate |
| `v_expiring_warranties` | Vehicles approaching warranty expiration with known issues |

### Bedrock Knowledge Base

| Document | Content |
|----------|---------|
| Schema docs | Recall tables, warranty tables, maintenance history — field definitions |
| Recall playbook | Severity classification, scheduling priorities, grounding criteria |
| Warranty playbook | Coverage rules by OEM, claim filing procedures, documentation requirements |
| Query cookbook | Example queries for recall status, warranty eligibility, compliance reports |
| Regulatory reference | NHTSA requirements, legal liability timelines, audit requirements |

### Agentic Guardrails

- Tenant isolation: fleet-scoped
- Safety recalls: never auto-exempt a vehicle — always require human review
- Grounding: GROUND_IMMEDIATELY requires operator approval before execution
- Warranty claims: require approval before filing with OEM (financial commitment)
- Compliance: never mark a recall complete without verified service record
- Evidence integrity: telemetry evidence attached to warranty claims must be unmodified

---

## 8. Cross-Agent Integration

This guidance connects to the other ADP data products:

| Integration | How |
|-------------|-----|
| **Predictive Maintenance** | Degradation alerts feed into warranty eligibility detection. Tire/battery/brake predictions identify failures before they happen — file warranty claims proactively. |
| **TCO Optimization** | Recall service costs and warranty recoveries flow into the cost data lake. Warranty recovery is a TCO line item (negative cost). |
| **Fleet Rebalancing** | When vehicles are grounded for recall, the rebalancing agent is notified to cover the gap. Recall service scheduling considers fleet coverage needs. |
| **Telemetry Normalization** | All telemetry cross-referencing depends on normalized, canonical signals. DTC codes from the normalization pipeline trigger warranty eligibility checks. |

---

## 9. Implementation Plan

### Phase 1 (4 weeks): Recall Management
- [ ] RecallProcessor Flink job (VIN matching + telemetry cross-reference)
- [ ] DynamoDB recall-events table + Iceberg recall_tracking schema
- [ ] Redis recall state per vehicle + fleet summary
- [ ] Athena views (active recalls, vehicle status, compliance)
- [ ] REST API endpoints in main_api Lambda
- [ ] CMS UI: Recall Management Dashboard
- [ ] CMS UI: Vehicle recall status tab
- [ ] Simulator: generate recall notices + affected vehicles
- [ ] NHTSA recall feed poller (Lambda + EventBridge)

### Phase 2 (4 weeks): Warranty Management
- [ ] WarrantyProcessor Flink job (failure detection + eligibility matching)
- [ ] Warranty terms data model (coverage rules by OEM/component/mileage/age)
- [ ] DynamoDB warranty-events table + Iceberg warranty_tracking schema
- [ ] Athena views (eligible failures, claims, recovery, expiring coverage)
- [ ] CMS UI: Warranty Management Dashboard
- [ ] CMS UI: Claim detail view with pre-filled evidence
- [ ] Simulator: generate warranty-eligible failures

### Phase 3 (4 weeks): Agentic + Integration
- [ ] Bedrock Agent (Recall & Warranty) with tools
- [ ] Bedrock Knowledge Base (playbooks, regulatory reference)
- [ ] Agentic Guardrails configuration
- [ ] Agent Core Gateway (Lambda triggers)
- [ ] CMS UI: Action Queue integration (recall + warranty actions)
- [ ] Auto-approval rules
- [ ] Cross-agent integration: rebalancing notification on grounding
- [ ] Cross-agent integration: warranty recovery → TCO cost lake
- [ ] Compliance report generation (audit-ready PDF export)

---

## 10. Architecture Diagram Narrative

**Title:** Guidance for an Automotive Data Platform on AWS
**Subtitle:** Creating operational value from Recall & Warranty Intelligence
**Tagline:** Build an agentic recall and warranty pipeline that turns blanket recalls into targeted service and manual claims into automatic recovery

### Steps:

**1 — Data Ingestion**
Recall notices arrive from OEM feeds and the NHTSA database via scheduled Lambda pollers. Warranty coverage terms are stored in DynamoDB and S3. Vehicle data — telemetry, DTCs, maintenance history, VIN, mileage — flows from the existing CMS normalization pipeline. Dealer locations and parts availability are maintained in DynamoDB.

**2 — Recall & Warranty Processing**
The RecallProcessor matches recall VIN ranges against the fleet, then cross-references telemetry signals to classify vehicles as CONFIRMED (defect detected) or POPULATION (VIN match only) and assigns severity. The WarrantyProcessor monitors component failures against coverage rules to flag warranty-eligible events. Both processors write directly to S3 Iceberg, Redis, and DynamoDB.

**3 — Data Lake & Visualization**
Historical recall and warranty data is stored in S3 Iceberg with Lake Formation tenant isolation. Athena views provide recall compliance status, warranty eligibility, claim tracking, recovery totals, and fleet impact analysis. Redis serves real-time recall and warranty state for dashboard rendering.

**4 — Agentic Intelligence**
The Agent Core Gateway routes recall notices, warranty-eligible failures, and operator questions to a Bedrock Agent. The agent retrieves context from a Knowledge Base containing recall playbooks, warranty coverage rules, and regulatory requirements. Bedrock Guardrails enforce safety recall protections, grounding approval requirements, and evidence integrity. The agent schedules service, drafts warranty claims, triggers fleet rebalancing, and generates compliance reports.

**5 — Fleet Operator Interface**
The CMS UI provides separate Recall and Warranty dashboards with active recall tracking, compliance progress, warranty-eligible failures, claim status, and recovery summaries. The Action Queue surfaces agent recommendations — ground vehicles, schedule service, file warranty claims — for operator approval. Auto-approval rules allow routine actions while requiring human review for safety-critical decisions.

### Service Icons per Step:

| Step | Services |
|------|----------|
| 1 | AWS Lambda, Amazon EventBridge, Amazon MSK, Amazon DynamoDB, Amazon S3 |
| 2 | Amazon Managed Service for Apache Flink, Amazon ElastiCache (Redis), Amazon DynamoDB |
| 3 | Amazon S3 (Iceberg), AWS Lake Formation, Amazon Athena, Amazon DynamoDB |
| 4 | AWS Lambda, Amazon Bedrock Guardrails, Amazon Bedrock Knowledge Base, Amazon Bedrock Agent |
| 5 | Amazon CloudFront, Amazon API Gateway, Amazon Cognito, Amazon Location Service |

---

## 11. Open Questions

1. **OEM recall feed format:** Is there a standard API/format, or is it OEM-specific? NHTSA has a public API — is that sufficient for the accelerator?
2. **Warranty terms complexity:** Coverage rules vary wildly by OEM. Do we model a generic coverage engine or OEM-specific adapters?
3. **Dealer integration:** How deep? Just location + parts availability, or actual appointment scheduling via API?
4. **Warranty claim filing:** Does the agent actually submit to the OEM portal, or just draft the claim for the operator to submit manually?
5. **Compliance reporting format:** Is there a standard format for recall compliance audits, or is it OEM/regulator-specific?
6. **Cross-fleet recalls:** If an operator manages multiple fleets, should recall tracking be fleet-scoped or operator-scoped?
