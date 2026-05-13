---
documentId: POLICY-ESCALATION-PLAYBOOK
category: service-policy
title: "Escalation Playbook — When and How to Escalate"
---

# Escalation Playbook

## Decision Matrix

| Condition | Severity | Auto-Escalate? | Channel |
|-----------|----------|---------------|---------|
| Airbag fault (B0001-B0099) | P0 | Yes | Voice callback + roadside |
| Brake system critical (C0161) | P0 | Yes | Voice callback + roadside |
| Engine overheating (P0217) | P0 | Yes | Voice callback + roadside |
| Driver requests human | Any | Yes | Chat transfer |
| ABS disabled (C0035-C0265) | P1 | Offer | Chat transfer |
| Flashing CEL (active misfire) | P1 | Offer | Chat transfer |
| Transmission limp mode | P1 | Offer | Chat transfer |
| Steady CEL (emissions) | P2 | No | Schedule service |
| TPMS warning (1-3 PSI low) | P3 | No | Inform only |

## Escalation Channels by Priority

### P0 — Critical (< 5 min response)
1. AI agent immediately escalates (no driver confirmation needed)
2. Connect outbound voice call to driver's phone
3. Roadside assistance dispatched simultaneously
4. P0 queue: 24/7, target answer time < 30 seconds

### P1 — Urgent (< 15 min response)
1. AI agent offers escalation to driver
2. If accepted: Connect chat transfer with full context
3. P1 queue: 24/7, target answer time < 2 minutes
4. If declined: schedule service within 48 hours

### P2 — Service Soon (< 1 hour response)
1. AI agent handles directly (no escalation)
2. Books service appointment via book() tool
3. If driver insists on human: chat transfer to P2 queue
4. P2 queue: business hours only (7am-7pm M-F)

### P3 — Monitor (next business day)
1. AI agent informs driver, no action needed
2. Logged for next scheduled service visit
3. No escalation unless driver explicitly requests

## Context Handoff Requirements

When escalating, the AI agent MUST provide:
- Vehicle ID and VIN
- Active DTC codes with severity
- Conversation summary (last 3-5 exchanges)
- Triage classification and reasoning
- Driver's stated concern in their own words
- Any service history relevant to the issue
