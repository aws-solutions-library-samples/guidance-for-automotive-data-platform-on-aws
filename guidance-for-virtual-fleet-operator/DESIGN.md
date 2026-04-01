# Virtual Fleet Operator — Design Document

## ADP Data Product: `guidance-for-virtual-fleet-operator`

**Author:** Andrew Givens | **Date:** March 2026 | **Status:** Draft

---

## 1. Problem Statement

We've built four domain-specific capabilities: predictive maintenance, TCO optimization, fleet rebalancing, and recall & warranty management. Each has its own Flink processor, data lake, Bedrock Agent, and CMS UI views. Individually, they're powerful. Together, they're disconnected.

A real fleet operator doesn't think in silos. When a recall drops, they're simultaneously thinking about: which vehicles are affected (recall), how to cover the gap (rebalancing), what it costs (TCO), and whether the failed parts are under warranty (warranty). Today, that requires four dashboards, four mental models, and a human brain to connect the dots.

The Virtual Fleet Operator is the orchestration layer that ties all four agents into a single, unified intelligence — one agent that can reason across the entire fleet, coordinate actions across domains, and answer any question by synthesizing all available data.

---

## 2. Architecture Decision: Multi-Agent Router vs. Super-Agent

### Option A: Multi-Agent Router
A lightweight router agent that receives every request, classifies it by domain, and delegates to the appropriate specialist agent (Cost, Rebalancing, Recall, Warranty). For cross-domain questions, the router calls multiple agents and synthesizes their responses.

```
Operator question → Router Agent → classify intent
    ├── Cost question → Cost Agent → response
    ├── Rebalancing question → Rebalancing Agent → response
    ├── Recall question → Recall Agent → response
    ├── Cross-domain → Cost Agent + Rebalancing Agent → Router synthesizes
    └── "What's happening?" → All agents → Router synthesizes
```

**Pros:** Each agent stays focused, easier to test/debug individually, can evolve independently
**Cons:** Extra latency for cross-domain, router needs to understand all domains to classify correctly, synthesis quality depends on router

### Option B: Super-Agent with All Tools
One Bedrock Agent with access to every tool from every domain. It reasons across all data sources in a single invocation.

```
Operator question → Virtual Fleet Operator Agent → reasons across all tools
    ├── query_cost_lake (Athena)
    ├── query_utilization (Athena)
    ├── get_recall_status (DynamoDB)
    ├── check_warranty_eligibility (DynamoDB)
    ├── get_vehicle_state (Redis)
    ├── get_demand_forecast (Redis/S3)
    ├── estimate_transfer_cost (Lambda)
    ├── find_nearest_dealer (Lambda)
    ├── write_recommendation (DynamoDB)
    └── ... all tools from all agents
```

**Pros:** Single invocation, agent sees everything at once, natural cross-domain reasoning
**Cons:** Large tool set (15+ tools), complex system prompt, harder to test, single point of failure

### Option C: Supervisor Agent + Specialist Agents (Recommended)
A supervisor agent that understands the full fleet context and delegates to specialist agents as sub-agents. The supervisor maintains conversation state and synthesizes across domains.

```
Operator question → Supervisor Agent (Virtual Fleet Operator)
    │
    ├── Understands full fleet context (unified KB)
    ├── Maintains conversation state
    ├── Delegates to specialists:
    │   ├── invoke_cost_agent(question) → Cost Agent → structured response
    │   ├── invoke_rebalance_agent(question) → Rebalancing Agent → structured response
    │   ├── invoke_recall_agent(question) → Recall Agent → structured response
    │   └── invoke_warranty_agent(question) → Warranty Agent → structured response
    │
    ├── Synthesizes responses across domains
    ├── Identifies cross-domain actions (recall → rebalance → TCO impact)
    └── Writes unified recommendations to action queue
```

**Pros:** Best of both — specialists stay focused, supervisor handles cross-domain reasoning, each agent can be tested independently, supervisor KB provides unified context
**Cons:** Slightly more complex setup, need to define inter-agent communication format

**Recommendation: Option C.** Bedrock Agents supports multi-agent collaboration. The supervisor is the "Virtual Fleet Operator" — it's the one the CMS UI talks to. The specialist agents are the ones we've already designed.

---

## 3. Architecture Overview

```
TRIGGERS
├── CMS UI: operator asks a question or requests fleet status
├── EventBridge Schedule: daily fleet health review
├── DynamoDB Streams: any domain agent flags a cross-domain event
└── Anomaly cascade: one agent's output triggers another agent's input

SUPERVISOR AGENT (Virtual Fleet Operator)
├── Amazon Bedrock Agent with sub-agent invocation tools
├── Unified Knowledge Base:
│   ├── Fleet operations glossary (cross-domain definitions)
│   ├── Cross-domain playbook ("when recall + rebalancing + TCO intersect, do X")
│   ├── Escalation rules (when to involve human, when to auto-act)
│   └── Fleet context (operator preferences, fleet composition, regional constraints)
│
├── Supervisor tools:
│   ├── invoke_cost_agent(question) → delegates to Cost Agent
│   ├── invoke_rebalance_agent(question) → delegates to Rebalancing Agent
│   ├── invoke_recall_agent(question) → delegates to Recall & Warranty Agent
│   ├── get_fleet_overview (Redis) → unified fleet health snapshot
│   ├── get_active_recommendations (DynamoDB) → pending actions across all domains
│   ├── write_unified_recommendation (DynamoDB) → cross-domain action plan
│   └── generate_fleet_report (Athena) → synthesized fleet health report
│
├── Agentic Guardrails:
│   ├── Tenant isolation (fleet-scoped across all sub-agents)
│   ├── Cross-domain action approval: always require human review for actions spanning multiple domains
│   ├── Cost ceiling: total recommended spend across all domains can't exceed configurable threshold without approval
│   └── Safety override: safety-related actions (recall grounding) always take priority over cost/utilization optimization

SPECIALIST AGENTS (existing, no changes)
├── Cost Agent → tools: query_cost_lake, get_vehicle_state, write_recommendation, etc.
├── Rebalancing Agent → tools: query_utilization, get_demand_forecast, estimate_transfer_cost, etc.
└── Recall & Warranty Agent → tools: match_recall, check_warranty, schedule_service, draft_claim, etc.

SHARED STATE
├── Redis: unified vehicle state (telemetry + cost + utilization + recall + warranty)
├── DynamoDB: unified action queue (recommendations from all agents, tagged by domain)
├── S3 Iceberg: all domain-specific tables queryable via Athena
└── Bedrock Knowledge Base: unified KB accessible by supervisor + all specialists

CMS UI
├── Fleet Command Center (/fleet-command)
│   ├── Unified fleet health score
│   ├── Cross-domain alert summary
│   ├── NL query interface ("What's happening with my fleet?")
│   └── Agent activity across all domains
│
├── Unified Action Queue
│   ├── All recommendations from all agents in one view
│   ├── Cross-domain action plans (recall + rebalance + TCO as one package)
│   ├── Priority ranking across domains
│   └── Approve/reject individual actions or entire plans
│
└── Conversational Interface
    ├── Chat with the Virtual Fleet Operator
    ├── Ask any question — agent routes to the right specialist(s)
    ├── Follow-up questions maintain context
    └── "Show me" → agent generates visualizations from data
```

---

## 4. Cross-Domain Scenarios

### Scenario 1: Recall Cascade

```
1. Recall notice arrives: brake actuator, 200 vehicles in fleet
2. Supervisor receives event, delegates to Recall Agent
3. Recall Agent: VIN match → telemetry cross-ref → 47 confirmed, 12 critical
4. Supervisor recognizes cross-domain impact:
   a. Delegates to Rebalancing Agent: "12 vehicles grounding in Region X, cover the gap"
   b. Rebalancing Agent: recommends moving 10 vehicles from Region Y (surplus)
   c. Delegates to Cost Agent: "Estimate total impact of this recall"
   d. Cost Agent: service cost $48K + revenue loss $86K + transfer cost $3K = $137K total
   e. Delegates to Warranty Agent: "Are the brake actuators under warranty?"
   f. Warranty Agent: 38 of 47 vehicles covered, estimated recovery $31K
5. Supervisor synthesizes into unified action plan:
   - Ground 12 vehicles (safety)
   - Schedule 35 for service over 2 weeks
   - Move 10 vehicles from Region Y to cover
   - File 38 warranty claims (est. recovery $31K)
   - Net cost impact: $137K - $31K = $106K
6. Writes to unified action queue → operator sees one plan, approves all at once
```

### Scenario 2: Operator Question

```
Operator: "Why is my fleet underperforming this month?"

1. Supervisor delegates to all specialists in parallel:
   a. Cost Agent: "Fleet spend up 18% — maintenance spike in Region X (8 unplanned repairs)"
   b. Rebalancing Agent: "Region X utilization dropped to 61% — 15 vehicles idle"
   c. Recall Agent: "Active recall affecting 23 vehicles in Region X — 12 still pending service"
   
2. Supervisor synthesizes:
   "Region X is the primary driver. A brake recall has 23 vehicles affected — 12 still 
   pending service, which is depressing utilization (61% vs. 82% fleet average). The 8 
   unplanned repairs are brake-related failures on vehicles not yet serviced for the recall. 
   Warranty Agent confirms 6 of 8 repairs are warranty-eligible ($12K recovery).
   
   Recommended actions:
   1. Expedite recall service for remaining 12 vehicles (schedule this week)
   2. File 6 warranty claims for brake repairs ($12K)
   3. Move 8 vehicles from Region Y to cover Region X gap
   
   Estimated impact: utilization recovers to 78% within 2 weeks, $12K warranty recovery, 
   $24K/week revenue recovery from improved utilization."
```

### Scenario 3: Daily Fleet Health Review

```
EventBridge triggers daily review at 6 AM:

1. Supervisor calls get_fleet_overview → unified health snapshot
2. Identifies top issues across all domains:
   - 3 cost anomalies (Cost Agent)
   - 2 locations with utilization below threshold (Rebalancing Agent)
   - 1 recall with overdue vehicles (Recall Agent)
   - 4 warranty claims expiring in 30 days (Warranty Agent)
3. Generates daily briefing → pushed to CMS UI Fleet Command Center
4. Critical items auto-create recommendations in action queue
5. Operator opens CMS UI in the morning → sees prioritized action list
```

---

## 5. CMS UI: Fleet Command Center

### New Page: `/fleet-command`

This is the "home screen" for the Virtual Fleet Operator — the single view that replaces checking four separate dashboards.

**Components:**

- `FleetHealthScore` — single number (0-100) synthesized from utilization, cost trends, recall compliance, maintenance health. Color-coded: green/yellow/red.
- `CrossDomainAlertSummary` — top 5 issues across all domains, ranked by impact. Each links to the relevant domain dashboard.
- `NLQueryInterface` — chat box. "What's happening with my fleet?" / "Why is Region X over budget?" / "What should I do about the brake recall?"
- `UnifiedActionQueue` — all pending recommendations from all agents. Can filter by domain. Cross-domain plans grouped together.
- `AgentActivityTimeline` — chronological feed of all agent activity across all domains.
- `DailyBriefing` — auto-generated morning summary from the daily health review.

### Conversational Interface

The NL query box is the primary interaction model. The operator types a question, the Virtual Fleet Operator routes to the right specialist(s), and returns a synthesized answer with recommended actions.

Follow-up questions maintain context:
```
Operator: "What's happening in Region X?"
Agent: [synthesized response across all domains]
Operator: "Schedule the recall service for those 12 vehicles"
Agent: [finds nearest dealers, checks parts, proposes schedule] → action queue
Operator: "Approve"
Agent: [executes]
```

---

## 6. Semantic Layer

### Unified Knowledge Base

The supervisor agent has its own KB that sits above the specialist KBs:

| Document | Content |
|----------|---------|
| Fleet operations glossary | Cross-domain definitions: "fleet health score," "cross-domain impact," "cascade event" |
| Cross-domain playbook | "When a recall grounds vehicles: trigger rebalancing, estimate TCO impact, check warranty" |
| Escalation rules | "Safety actions always override cost optimization. Cross-domain plans require human approval." |
| Synthesis patterns | How to combine responses from multiple specialists into a coherent answer |
| Operator preferences | Per-fleet configuration: risk tolerance, auto-approval thresholds, priority weighting |

### Unified Guardrails

- All specialist guardrails still apply (tenant isolation, safety overrides, etc.)
- Additional: cross-domain action plans always require human approval
- Additional: total recommended spend across all domains capped at configurable threshold
- Additional: safety-related actions (recall grounding) always take priority over cost/utilization optimization
- Additional: supervisor cannot override a specialist's guardrail (e.g., can't auto-exempt a safety recall to improve utilization)

---

## 7. Implementation Plan

### Phase 1 (2 weeks): Unified UI
- [ ] Fleet Command Center page in CMS UI
- [ ] Unified action queue (aggregate from all domain DynamoDB tables)
- [ ] Fleet health score calculation (Lambda — weighted average across domains)
- [ ] Cross-domain alert summary widget
- [ ] Daily briefing generation (Lambda + scheduled)

### Phase 2 (4 weeks): Supervisor Agent
- [ ] Bedrock Agent (Virtual Fleet Operator) with sub-agent invocation tools
- [ ] Unified Knowledge Base (cross-domain playbook, synthesis patterns)
- [ ] Unified Guardrails
- [ ] NL query interface in CMS UI
- [ ] Cross-domain scenario handling (recall cascade, operator questions)
- [ ] Conversational context management

### Phase 3 (2 weeks): Polish
- [ ] Daily health review automation (EventBridge → supervisor → briefing)
- [ ] Cross-domain action plan grouping in action queue
- [ ] Agent activity timeline (unified across all domains)
- [ ] Operator preference configuration (risk tolerance, priority weighting)
- [ ] Feedback loop: operator satisfaction tracking on agent responses

---

## 8. Dependencies

| Dependency | Required For |
|-----------|-------------|
| `guidance-for-telemetry-normalization` | All telemetry data |
| `guidance-for-predictive-maintenance` | Maintenance predictions feeding into all agents |
| `guidance-for-tco-optimization` | Cost Agent |
| `guidance-for-fleet-rebalancing` | Rebalancing Agent |
| `guidance-for-recall-warranty-management` | Recall & Warranty Agent |
| CMS UI | Fleet Command Center, unified action queue, NL interface |

The Virtual Fleet Operator is the capstone — it requires all other guidances to be deployed first. It adds the orchestration layer on top.

---

## 9. Open Questions

1. **Latency:** Multi-agent invocation adds latency. Is 5-10 seconds acceptable for cross-domain questions? Can we parallelize specialist calls?
2. **Context window:** The supervisor needs to hold context from multiple specialists. Will this exceed Bedrock context limits for complex scenarios?
3. **Conflict resolution:** What if the Cost Agent recommends keeping a vehicle in service (save money) but the Recall Agent recommends grounding it (safety)? Safety wins — but how explicit do we make the reasoning?
4. **Conversation persistence:** How long does conversational context persist? Per session? Per day? Stored in DynamoDB?
5. **Fleet health score weighting:** How to weight utilization vs. cost vs. recall compliance vs. maintenance health? Configurable per operator?
