# Virtual Fleet Operator — Knowledge Base Design Document

## ADP Data Product: `guidance-for-virtual-fleet-operator`

**Author:** Andrew Givens | **Date:** March 2026 | **Status:** Draft

---

## 1. Purpose

The Virtual Fleet Operator Knowledge Base provides the Bedrock Agent with comprehensive fleet context beyond what's available in structured DynamoDB tables. It combines:

- **Unstructured documents** — service invoices (PDFs), OEM service manuals, recall bulletins, warranty policy documents, fleet operating procedures
- **Structured exports** — fleet configuration, vehicle specs, cost summaries, compliance reports
- **Operational playbooks** — cross-domain decision frameworks, escalation rules, SOP for common scenarios

This enables the agent to answer questions like "What does the service manual say about brake actuator replacement intervals?" or "Show me the invoice for VEH-0025's last repair" or "What's our warranty policy for DEF pump failures?" — questions that require document understanding, not just database queries.

---

## 2. Knowledge Base Architecture

```
S3: cms-prod-vfo-knowledge-base/
│
├── service-invoices/              ← PDF invoices from service providers
│   ├── INV-2026-001_VEH-0025_starter-motor.pdf
│   ├── INV-2026-002_VEH-0012_brake-pads.pdf
│   ├── INV-2026-003_VEH-0038_transmission.pdf
│   └── ... (one per completed service record)
│
├── service-manuals/               ← OEM maintenance/repair manuals
│   ├── freightliner-cascadia-2023-service-manual.pdf
│   ├── ram-1500-2021-maintenance-guide.pdf
│   ├── toyota-tundra-2022-service-manual.pdf
│   ├── ford-f150-lightning-2024-ev-service-guide.pdf
│   └── kenworth-t680-2023-maintenance-intervals.pdf
│
├── recall-bulletins/              ← NHTSA recall notices + OEM TSBs
│   ├── NHTSA-2026-0847-brake-actuator-recall.pdf
│   ├── NHTSA-2025-1234-airbag-inflator.pdf
│   ├── TSB-FCA-2026-001-def-pump-update.pdf
│   └── TSB-TOYOTA-2025-089-battery-management.pdf
│
├── warranty-policies/             ← OEM warranty terms + fleet agreements
│   ├── freightliner-powertrain-warranty-2023.pdf
│   ├── ram-commercial-fleet-warranty-program.pdf
│   ├── toyota-commercial-vehicle-warranty.pdf
│   ├── ford-ev-battery-warranty-terms.pdf
│   └── fleet-extended-warranty-agreement-2026.pdf
│
├── fleet-operations/              ← SOPs, playbooks, policies
│   ├── fleet-operations-handbook.pdf
│   ├── cross-domain-escalation-playbook.pdf
│   ├── cost-optimization-guidelines.pdf
│   ├── vehicle-lifecycle-management-policy.pdf
│   ├── driver-safety-program-manual.pdf
│   └── ev-charging-operations-guide.pdf
│
├── compliance-reports/            ← DOT, FMCSA, emissions reports
│   ├── dot-annual-inspection-report-2025.pdf
│   ├── fmcsa-compliance-review-2025.pdf
│   ├── emissions-compliance-q1-2026.pdf
│   └── hours-of-service-audit-2025.pdf
│
├── cost-reports/                  ← Monthly/quarterly cost summaries
│   ├── fleet-tco-report-q4-2025.pdf
│   ├── fleet-tco-report-q1-2026.pdf
│   ├── fuel-cost-analysis-march-2026.pdf
│   ├── maintenance-cost-trend-2025-2026.pdf
│   └── insurance-renewal-summary-2026.pdf
│
└── fleet-context/                 ← Structured context documents
    ├── fleet-composition.md       ← Vehicle types, counts, regions
    ├── fleet-kpis-and-targets.md  ← Target utilization, cost/mile, etc.
    ├── vendor-directory.md        ← Service providers, parts suppliers
    ├── regional-operations.md     ← Region configs, demand patterns
    └── agent-glossary.md          ← Cross-domain terminology
```

---

## 3. Document Types & Content

### 3a. Service Invoices (PDFs)

Generated from completed service history records. Each invoice includes:
- Invoice number, date, service provider
- Vehicle ID, VIN, make/model/year, mileage
- Service description, parts replaced, labor hours
- Line items with part numbers and costs
- Total cost, warranty applied (Y/N), warranty amount
- Technician notes, next service recommendation

**Source:** Generated from `cms-prod-storage-service-history` DynamoDB table (552 records)

**Example questions the agent can answer:**
- "Show me the invoice for VEH-0025's starter motor repair"
- "How much did we spend on brake repairs across all vehicles last quarter?"
- "Which service provider charges the most for oil changes?"

### 3b. OEM Service Manuals (PDFs)

Maintenance and repair guides for each vehicle make/model in the fleet:
- Scheduled maintenance intervals (oil, brakes, tires, transmission, etc.)
- Repair procedures for common failures
- Torque specs, fluid capacities, part numbers
- Diagnostic trouble code (DTC) reference tables
- EV-specific: battery management, charging system, motor service

**Fleet vehicle makes:** Freightliner, Ram, Toyota, Ford, Kenworth

**Example questions:**
- "What's the recommended brake pad replacement interval for a 2023 Freightliner Cascadia?"
- "What does DTC P20EE mean on a Toyota Tundra?"
- "What's the battery replacement procedure for a Ford F-150 Lightning?"

### 3c. Recall Bulletins

NHTSA recall notices and OEM Technical Service Bulletins (TSBs):
- Recall number, affected vehicles (VIN ranges), defect description
- Remedy procedure, parts required, estimated repair time
- Safety risk assessment, compliance deadline
- TSBs for known issues not yet at recall level

**Example questions:**
- "What vehicles are affected by the brake actuator recall?"
- "What's the remedy procedure for NHTSA-2026-0847?"
- "Are there any open TSBs for our Ram 1500 fleet?"

### 3d. Warranty Policies

OEM warranty terms and fleet-specific warranty agreements:
- Powertrain warranty coverage (mileage/time limits)
- Component-specific coverage (battery, emissions, electrical)
- Fleet extended warranty program terms
- Claim filing procedures and required documentation
- Exclusions and limitations

**Example questions:**
- "Is the DEF pump covered under Toyota's powertrain warranty at 29,000 miles?"
- "What documentation do I need to file a warranty claim for brake actuator failure?"
- "When does our extended warranty agreement expire?"

### 3e. Fleet Operations Documents

Standard operating procedures and operational playbooks:
- **Fleet Operations Handbook** — daily operations, dispatch procedures, driver protocols
- **Cross-Domain Escalation Playbook** — when recall impacts utilization, when cost spikes trigger investigation, when safety overrides cost optimization
- **Cost Optimization Guidelines** — fuel purchasing strategy, maintenance vs. replacement thresholds, EV charging optimization
- **Vehicle Lifecycle Policy** — acquisition criteria, replacement triggers, disposal procedures
- **Driver Safety Program** — scoring methodology, training requirements, incident response
- **EV Charging Operations** — charging schedules, rate optimization, infrastructure management

### 3f. Compliance Reports

Regulatory compliance documentation:
- DOT annual inspection results
- FMCSA compliance reviews
- Emissions testing reports
- Hours of service audit results

### 3g. Cost Reports

Financial analysis documents:
- Quarterly TCO reports with category breakdowns
- Fuel cost analysis with regional pricing trends
- Maintenance cost trends and forecasts
- Insurance renewal summaries

### 3h. Fleet Context (Markdown)

Structured context documents that give the agent fleet-specific knowledge:

**fleet-composition.md:**
```
Fleet: Munich Operations (FLEET-001 through FLEET-005)
Total vehicles: 50
- FLEET-001 (Munich Metro): 12 vehicles, mixed ICE/EV, urban delivery
- FLEET-002 (Bavaria Regional): 10 vehicles, Class 8 trucks, long-haul
- FLEET-003 (Service Fleet): 8 vehicles, Ram 1500, field service
- FLEET-004 (EV Pilot): 10 vehicles, Ford F-150 Lightning, last-mile
- FLEET-005 (Heavy Duty): 10 vehicles, Freightliner/Kenworth, freight
```

**fleet-kpis-and-targets.md:**
```
Utilization target: 82%
Cost per mile target: $0.70
Maintenance ratio target: <30% of total cost
Safety score target: >85/100
Recall compliance: 100% within 30 days
Warranty recovery target: >90% of eligible claims filed
```

---

## 4. Knowledge Base Configuration

### Bedrock KB Settings

| Setting | Value |
|---------|-------|
| Data source | S3: `cms-prod-vfo-knowledge-base` |
| Embedding model | Amazon Titan Embeddings V2 |
| Vector store | Amazon OpenSearch Serverless |
| Chunking strategy | Hierarchical (parent: 1500 tokens, child: 300 tokens) |
| Parsing | Bedrock Data Automation (for PDFs with tables/invoices) |
| Metadata | Vehicle ID, document type, date, fleet ID |

### Metadata Filtering

Each document gets metadata tags enabling filtered retrieval:
```json
{
  "documentType": "service-invoice",
  "vehicleId": "VEH-0025",
  "fleetId": "FLEET-003",
  "date": "2024-08-29",
  "serviceType": "STARTER_MOTOR",
  "provider": "Rush Truck Center — Dallas"
}
```

This lets the agent scope KB queries: "Show me invoices for FLEET-003 vehicles" retrieves only relevant documents.

---

## 5. Document Generation Plan

### Auto-generated from existing data:

| Document Type | Source | Count | Method |
|--------------|--------|-------|--------|
| Service invoices | `service-history` table (552 records) | ~552 PDFs | Python script → ReportLab PDF |
| Warranty claim docs | `warranty-claims` table (31 records) | ~31 PDFs | Python script → ReportLab PDF |
| DTC diagnostic reports | `dtc-history` table (644 records) | ~50 PDFs (grouped by vehicle) | Python script |
| Fleet composition | `vehicles` + `fleets` tables | 1 markdown | Python script |
| Fleet KPIs | Hardcoded targets | 1 markdown | Manual |

### Manually created (realistic samples):

| Document Type | Count | Method |
|--------------|-------|--------|
| OEM service manuals | 5 (one per make) | AI-generated, 20-30 pages each |
| Recall bulletins | 3-4 | AI-generated, NHTSA format |
| Warranty policies | 5 (one per OEM) | AI-generated |
| Fleet operations handbook | 1 | AI-generated, 15-20 pages |
| Cross-domain playbook | 1 | AI-generated from design doc |
| Cost optimization guidelines | 1 | AI-generated |
| Compliance reports | 3-4 | AI-generated |
| Cost reports | 3-4 | AI-generated |

### Total: ~650+ documents (PDFs + markdown)

---

## 6. Implementation Plan

### Phase 1: S3 bucket + invoice generation (Day 1)
- [ ] Create S3 bucket `cms-prod-vfo-knowledge-base`
- [ ] Python script to generate service invoice PDFs from DynamoDB
- [ ] Python script to generate warranty claim PDFs
- [ ] Python script to export fleet context markdown files
- [ ] Upload all generated documents to S3

### Phase 2: Manual documents (Day 1-2)
- [ ] Generate OEM service manuals (5 PDFs)
- [ ] Generate recall bulletins (3-4 PDFs)
- [ ] Generate warranty policy documents (5 PDFs)
- [ ] Generate fleet operations handbook
- [ ] Generate cross-domain escalation playbook
- [ ] Generate cost/compliance reports

### Phase 3: Bedrock KB creation (Day 2)
- [ ] Create OpenSearch Serverless collection
- [ ] Create Bedrock Knowledge Base with S3 data source
- [ ] Configure chunking, parsing, and metadata
- [ ] Sync data source
- [ ] Attach KB to Virtual Fleet Operator agent
- [ ] Test retrieval queries

### Phase 4: Agent integration (Day 2-3)
- [ ] Update agent instruction to reference KB capabilities
- [ ] Test document retrieval: "Show me the invoice for..."
- [ ] Test manual queries: "What does the service manual say about..."
- [ ] Test cross-reference: "Is this repair covered under warranty?"
- [ ] Test cost analysis: "What did we spend on brake repairs last quarter?"

---

## 7. Example Agent Interactions with KB

**Invoice lookup:**
```
Operator: "Show me the last service invoice for VEH-0025"
Agent: [queries KB with filter vehicleId=VEH-0025, documentType=service-invoice]
→ Returns invoice INV-2026-001: Starter motor replacement at Rush Truck Center Dallas,
  $662, 2.5 labor hours, no warranty applied. Mileage: 38,922.
```

**Service manual reference:**
```
Operator: "What's the recommended maintenance schedule for our Freightliner Cascadia trucks?"
Agent: [queries KB for freightliner-cascadia service manual]
→ Returns maintenance intervals: oil change every 35K miles, brake inspection every 50K,
  transmission service every 150K, DPF cleaning every 200K...
```

**Cross-reference (structured + unstructured):**
```
Operator: "VEH-0005 had a DEF pump failure. Is it covered under warranty?"
Agent: [queries DynamoDB for vehicle details: Toyota Tundra, 29,381 miles]
       [queries KB for Toyota warranty policy]
       [queries KB for warranty claim CLM-2026-988]
→ "Yes. VEH-0005's DEF pump failure at 29,381 miles is within Toyota's powertrain
   warranty (50,000 miles). Claim CLM-2026-988 was filed on 2025-05-17 and paid
   $947 on 2025-06-18. The warranty policy document confirms DEF system components
   are covered under the emissions warranty."
```

**Cost analysis with documents:**
```
Operator: "How much did we spend on brake repairs this quarter? Show me the invoices."
Agent: [queries DynamoDB service-history for brake-related services]
       [queries KB for matching invoices]
→ "5 brake repairs this quarter totaling $4,230. Top cost: VEH-0012 brake pad
   replacement at $1,890 (Fleet Service Center Munich). I've found 5 matching
   invoices — the highest cost was INV-2026-002 which included rotor resurfacing."
```
