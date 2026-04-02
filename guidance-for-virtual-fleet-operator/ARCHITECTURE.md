# Virtual Fleet Operator — Agent & Knowledge Base Architecture

---

## Agent Orchestration Flow

```
                    ┌─────────────────────────────────────┐
                    │         FLEET OPERATOR (Human)       │
                    │                                     │
                    │  "Why is VEH-0025 costing so much?" │
                    │  "Approve brake service for 12 vehs"│
                    │  "What does the warranty cover?"    │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │      SUPERVISOR AGENT (VFO)          │
                    │      Amazon Bedrock — Claude Sonnet 4│
                    │      Role: SUPERVISOR                │
                    │                                      │
                    │  1. Classifies intent                │
                    │  2. Selects specialist(s)            │
                    │  3. Delegates with context            │
                    │  4. Synthesizes cross-domain answer   │
                    │  5. Writes actions to queue           │
                    │                                      │
                    │  Direct tools:                        │
                    │  • get_fleet_summary                  │
                    │  • get_vehicles                       │
                    │  • get_safety_events                  │
                    │  • get_data_counts                    │
                    │  • search_documents (KB)              │
                    └──┬─────────┬─────────┬─────────┬─────┘
                       │         │         │         │
          ┌────────────▼──┐ ┌───▼────────┐│┌────────▼────────┐
          │  COST AGENT    │ │ REBALANCING││ │ RECALL/WARRANTY │
          │                │ │   AGENT    │││    AGENT         │
          │ "Analyze costs │ │            │││                  │
          │  for VEH-0025" │ │ "Check     │││ "Is this repair  │
          │                │ │  Region X  │││  under warranty?" │
          │ Tools:         │ │  util"     │││                  │
          │ • service_hist │ │            │││ Tools:           │
          │ • warranty_clm │ │ Tools:     │││ • warranty_claims│
          │ • vehicles     │ │ • fleet_sum│││ • service_hist   │
          │ • search_docs  │ │ • vehicles │││ • dtc_codes      │
          └───────┬────────┘ │ • trips    │││ • search_docs    │
                  │          └─────┬──────┘│└────────┬─────────┘
                  │                │       │         │
                  │          ┌─────▼───────▼┐        │
                  │          │  MAINTENANCE  │        │
                  │          │    AGENT      │        │
                  │          │              │        │
                  │          │ "What DTCs   │        │
                  │          │  are active  │        │
                  │          │  on VEH-0025"│        │
                  │          │              │        │
                  │          │ Tools:       │        │
                  │          │ • maint_alrt │        │
                  │          │ • dtc_codes  │        │
                  │          │ • telemetry  │        │
                  │          │ • service_hst│        │
                  │          └──────┬───────┘        │
                  │                 │                 │
                  └────────┬───────┴────────┬────────┘
                           │                │
                           ▼                ▼
              ┌─────────────────┐  ┌─────────────────┐
              │  STRUCTURED DATA │  │ KNOWLEDGE BASE   │
              │  (DynamoDB)      │  │ (S3 PDFs)        │
              └─────────────────┘  └─────────────────┘
```

---

## Knowledge Base Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE BASE (Amazon S3)                    │
│                    cms-prod-vfo-knowledge-base                   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                 SERVICE INVOICES (200 PDFs)              │    │
│  │                                                         │    │
│  │  INV-{serviceId}_{vehicleId}_{type}.pdf                 │    │
│  │                                                         │    │
│  │  ┌─────────────────────────────────────────────┐        │    │
│  │  │ FLEET SERVICE INVOICE                       │        │    │
│  │  │ Invoice #: INV-010d87a6                     │        │    │
│  │  │ Provider: Rush Truck Center — Dallas        │        │    │
│  │  │ Vehicle: VEH-0043 (Freightliner Cascadia)   │        │    │
│  │  │                                             │        │    │
│  │  │ PARTS & LABOR                               │        │    │
│  │  │ Starter Motor Assembly  P-STR-ASM  $285.00  │        │    │
│  │  │ Starter Solenoid        P-STR-SOL   $65.00  │        │    │
│  │  │ Labor (3.2 hrs @ $125/hr)          $400.00  │        │    │
│  │  │                                             │        │    │
│  │  │ Subtotal: $750.00                           │        │    │
│  │  │ Tax: $61.88                                 │        │    │
│  │  │ Warranty: -$0.00                            │        │    │
│  │  │ TOTAL: $811.88                              │        │    │
│  │  └─────────────────────────────────────────────┘        │    │
│  │                                                         │    │
│  │  Linked to: DynamoDB service-history record             │    │
│  │  (same serviceId, vehicleId, cost, provider)            │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                 WORK ORDERS (66 PDFs)                    │    │
│  │                                                         │    │
│  │  WO-{serviceId}_{vehicleId}_{type}.pdf                  │    │
│  │  • Work order number, priority, assigned technician      │    │
│  │  • Inspection checklist (fluids, tires, brakes, etc.)    │    │
│  │  • Labor hours, cost, customer/tech signatures           │    │
│  │  Linked to: every 3rd service-history record             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                WARRANTY CLAIMS (72 PDFs)                 │    │
│  │                                                         │    │
│  │  {claimId}_{vehicleId}.pdf                              │    │
│  │  • Claim ID, status (PAID/OPEN/DENIED/UNDER_REVIEW)     │    │
│  │  • Component, failure code, mileage at failure           │    │
│  │  • Claim amount, paid amount, warranty limit             │    │
│  │  • Evidence summary from telemetry/predictive model      │    │
│  │  Linked to: DynamoDB warranty-claims record              │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                PARTS LISTINGS (10 PDFs)                  │    │
│  │                                                         │    │
│  │  {service_type}_parts_catalog.pdf                       │    │
│  │  One per service type: OIL_CHANGE, BRAKE_PADS,          │    │
│  │  TRANSMISSION, STARTER_MOTOR, ALTERNATOR, etc.          │    │
│  │  • Part name, part number, list price, fleet price      │    │
│  │  • 15% fleet discount applied                           │    │
│  │  • Stock availability                                   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              FLEET OPERATIONS (5 Markdown docs)          │    │
│  │                                                         │    │
│  │  fleet-context/                                         │    │
│  │  ├── fleet-composition.md    (vehicles by fleet/make)   │    │
│  │  ├── fleet-kpis-and-targets.md (utilization, cost, etc)│    │
│  │  └── agent-glossary.md       (TCO, DTC, NHTSA, etc.)   │    │
│  │                                                         │    │
│  │  fleet-operations/                                      │    │
│  │  ├── cross-domain-escalation-playbook.md                │    │
│  │  │   Rule 1: Safety always wins                         │    │
│  │  │   Rule 2: Recall cascade → rebalance → cost → warr  │    │
│  │  │   Rule 3: Cost spike → check maintenance → DTC → tel│    │
│  │  │   Rule 4: Cross-domain plans require human approval  │    │
│  │  └── fleet-operations-handbook.md                       │    │
│  │      Daily ops, dispatch, incident response, reporting  │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Autonomous Monitoring & Action Pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS MONITORING                          │
│                                                                  │
│  Amazon EventBridge                                              │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │ Every 6 hours    │  │ Daily 6 AM ET    │                     │
│  │ Fleet monitoring │  │ Morning briefing │                     │
│  └────────┬─────────┘  └────────┬─────────┘                     │
│           └──────────┬──────────┘                                │
│                      ▼                                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              FLEET MONITOR (AWS Lambda)                    │   │
│  │              Timeout: 5 min | Memory: 512 MB              │   │
│  │                                                          │   │
│  │  For each domain (with 15s delay between calls):          │   │
│  │                                                          │   │
│  │  ┌─────────────┐  "Analyze critical maintenance issues"  │   │
│  │  │ Maintenance  │──────────────────────────────────────►  │   │
│  │  └─────────────┘                                    │     │   │
│  │  ┌─────────────┐  "Identify cost anomalies"        │     │   │
│  │  │ Cost         │──────────────────────────────►    │     │   │
│  │  └─────────────┘                              │    │     │   │
│  │  ┌─────────────┐  "Review safety events"      │    │     │   │
│  │  │ Safety       │────────────────────────►     │    │     │   │
│  │  └─────────────┘                         │    │    │     │   │
│  │  ┌─────────────┐  "Check utilization"    │    │    │     │   │
│  │  │ Utilization  │──────────────────►      │    │    │     │   │
│  │  └─────────────┘                    │    │    │    │     │   │
│  │  ┌─────────────┐  "Review warranty" │    │    │    │     │   │
│  │  │ Warranty     │────────────►       │    │    │    │     │   │
│  │  └─────────────┘              │    │    │    │    │     │   │
│  │                               ▼    ▼    ▼    ▼    ▼     │   │
│  │                        SUPERVISOR AGENT                  │   │
│  │                     (delegates to specialists)            │   │
│  │                               │                          │   │
│  └───────────────────────────────┼──────────────────────────┘   │
│                                  ▼                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              ACTION QUEUE (DynamoDB)                       │   │
│  │              cms-prod-vfo-action-queue                     │   │
│  │                                                          │   │
│  │  ┌────────┬────────────┬──────────┬───────────────────┐  │   │
│  │  │ Status │ Domain     │ Priority │ Agent Response     │  │   │
│  │  ├────────┼────────────┼──────────┼───────────────────┤  │   │
│  │  │PENDING │Maintenance │ HIGH     │ "VEH-0034 has     │  │   │
│  │  │        │            │          │  critical brake    │  │   │
│  │  │        │            │          │  alert. Recommend  │  │   │
│  │  │        │            │          │  immediate service"│  │   │
│  │  ├────────┼────────────┼──────────┼───────────────────┤  │   │
│  │  │PENDING │Cost        │ MEDIUM   │ "VEH-0006 battery │  │   │
│  │  │        │            │          │  replacement $662  │  │   │
│  │  │        │            │          │  — check warranty" │  │   │
│  │  ├────────┼────────────┼──────────┼───────────────────┤  │   │
│  │  │APPROVED│Safety      │ HIGH     │ "VEH-0049 speed   │  │   │
│  │  │        │            │          │  violations — flag │  │   │
│  │  │        │            │          │  for retraining"   │  │   │
│  │  ├────────┼────────────┼──────────┼───────────────────┤  │   │
│  │  │REJECTED│Utilization │ MEDIUM   │ "Transfer 3 vehs  │  │   │
│  │  │        │            │          │  from FLEET-005"   │  │   │
│  │  └────────┴────────────┴──────────┴───────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                  │                               │
│                                  ▼                               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              FLEET COMMAND CENTER (UI)                     │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────────────────────┐ │   │
│  │  │ Pending Actions                          12 pending │ │   │
│  │  │                                                     │ │   │
│  │  │ ⚠ HIGH  Maintenance  2026-03-31 19:36              │ │   │
│  │  │ VEH-0034 has critical brake alert...               │ │   │
│  │  │                          [Approve] [Reject]         │ │   │
│  │  │                                                     │ │   │
│  │  │ ℹ MED   Cost         2026-03-31 19:37              │ │   │
│  │  │ VEH-0006 battery replacement — check warranty...   │ │   │
│  │  │                          [Approve] [Reject]         │ │   │
│  │  └─────────────────────────────────────────────────────┘ │   │
│  │                                                          │   │
│  │  Operator clicks [Approve] → status = APPROVED           │   │
│  │  Operator clicks [Reject]  → status = REJECTED           │   │
│  │  Action moves to Agent Activity feed                      │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Cross-Domain Reasoning Example

```
Operator: "VEH-0025 had a starter motor repair last month. Was it covered under warranty?"

┌─────────────────────────────────────────────────────────────────┐
│ SUPERVISOR receives question                                     │
│                                                                 │
│ Intent: warranty eligibility check + service history lookup      │
│ Delegates to: Recall/Warranty Agent + Cost Agent                 │
└──────────┬──────────────────────────────────┬───────────────────┘
           │                                  │
           ▼                                  ▼
┌─────────────────────┐            ┌─────────────────────┐
│ RECALL/WARRANTY AGENT│            │ COST AGENT           │
│                     │            │                     │
│ 1. get_service_hist │            │ 1. search_documents │
│    (VEH-0025)       │            │    (service-invoices│
│    → Found: starter │            │     VEH-0025)       │
│    motor, $662,     │            │    → Found: INV-    │
│    no warranty      │            │    0ad0d582, $662   │
│                     │            │    Rush Truck Center│
│ 2. get_warranty_clms│            │                     │
│    → No claim filed │            │ 2. get_service_hist │
│                     │            │    → Provider: Rush │
│ 3. get_dtc_codes    │            │    Truck Center     │
│    (VEH-0025)       │            │    Dallas, 38922 mi │
│    → P0520 oil      │            │                     │
│    pressure sensor   │            │                     │
│                     │            │                     │
│ Response:           │            │ Response:           │
│ "No warranty claim  │            │ "Invoice INV-       │
│  was filed. Vehicle │            │  0ad0d582 shows     │
│  at 38,922 mi,      │            │  $662 at Rush Truck │
│  Ram warranty is    │            │  Center. No warranty│
│  36,000 mi — likely │            │  discount applied." │
│  out of coverage."  │            │                     │
└──────────┬──────────┘            └──────────┬──────────┘
           │                                  │
           └──────────────┬───────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ SUPERVISOR synthesizes:                                          │
│                                                                 │
│ "VEH-0025's starter motor repair on 2024-08-29 cost $662 at    │
│  Rush Truck Center Dallas. No warranty claim was filed. The     │
│  vehicle was at 38,922 miles — Ram's powertrain warranty covers │
│  up to 36,000 miles, so this repair was ~2,900 miles past       │
│  coverage. However, I found DTC P0520 (oil pressure sensor)     │
│  which may indicate a related issue. Recommendation: review     │
│  whether the starter failure was caused by the oil pressure     │
│  issue — if so, it may qualify for a goodwill warranty claim."  │
│                                                                 │
│ → Writes to Action Queue:                                        │
│   ACT-WARR-xxxx | PENDING | "Review VEH-0025 for goodwill      │
│   warranty claim — starter failure potentially related to       │
│   DTC P0520"                                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Structured ↔ Unstructured Data Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│   STRUCTURED (DynamoDB)              UNSTRUCTURED (S3 PDFs)     │
│                                                                 │
│   service-history table              service-invoices/          │
│   ┌──────────────────┐              ┌──────────────────┐       │
│   │ serviceId: 0ad0  │──────────────│ INV-0ad0_VEH-    │       │
│   │ vehicleId: 0025  │   same IDs   │ 0025_starter.pdf │       │
│   │ cost: $662       │──────────────│ Total: $662      │       │
│   │ provider: Rush   │              │ Parts: P-STR-ASM │       │
│   │ type: STARTER    │              │ Labor: 2.5 hrs   │       │
│   └──────────────────┘              └──────────────────┘       │
│          │                                    │                 │
│          │  Agent queries DDB                 │  Agent searches │
│          │  for quick lookups                 │  S3 for details │
│          │                                    │                 │
│          ▼                                    ▼                 │
│   "VEH-0025 had a                    "The invoice shows        │
│    starter repair,                    part P-STR-ASM at        │
│    $662, at Rush                      $285 + solenoid          │
│    Truck Center"                      P-STR-SOL at $65         │
│                                       + 2.5 hrs labor"         │
│                                                                 │
│   warranty-claims table              warranty-claims/           │
│   ┌──────────────────┐              ┌──────────────────┐       │
│   │ claimId: CLM-988 │──────────────│ CLM-2026-988_    │       │
│   │ vehicleId: 0005  │   same IDs   │ VEH-0005.pdf     │       │
│   │ status: PAID     │──────────────│ Status: PAID     │       │
│   │ amount: $947     │              │ Evidence: DTC    │       │
│   │ component: DEF   │              │ P20EE at 26881mi │       │
│   └──────────────────┘              └──────────────────┘       │
│                                                                 │
│   Vehicle detail page:                                          │
│   Service tab → "View PDF" → opens invoice in modal             │
│   Documents page → browse all PDFs by category                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Agent Decision Matrix

| Operator Question | Primary Agent | Secondary Agent(s) | Data Sources | Action Generated |
|---|---|---|---|---|
| "Why is VEH-0025 expensive?" | Cost | Maintenance | service_history, invoices, DTC | Review warranty eligibility |
| "Which vehicles need service?" | Maintenance | — | maintenance_alerts, DTC | Schedule critical repairs |
| "Is this repair under warranty?" | Recall/Warranty | Cost | warranty_claims, service_history, claim PDFs | File warranty claim |
| "Why is Region X underperforming?" | Rebalancing | Cost, Maintenance | vehicles, trips, alerts | Transfer vehicles |
| "What happened to VEH-0049?" | Maintenance | Safety | DTC, telemetry, safety_events | Driver retraining |
| "Show me the invoice for..." | Cost | — | S3 invoices (PDF) | — (informational) |
| "What are our fleet KPIs?" | Supervisor (direct) | — | fleet-context/KPIs.md | — (informational) |
| "What should I focus on today?" | Supervisor | All 4 specialists | All tables + KB | Prioritized action list |
