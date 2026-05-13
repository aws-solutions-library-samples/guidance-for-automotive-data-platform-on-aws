#!/usr/bin/env python3
"""Generate service policy and warranty coverage data for the Vehicle Knowledge Base."""

from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data-sources" / "service-policy"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FILES = {
"warranty-coverage-matrix.md": """---
documentId: POLICY-WARRANTY-MATRIX
category: service-policy
title: "Warranty Coverage Matrix"
---

# Warranty Coverage Matrix

## Standard Coverage (New Vehicle)

| Coverage Type | Duration | Mileage | What's Covered |
|--------------|----------|---------|----------------|
| Bumper-to-Bumper | 3 years | 36,000 mi | All components except wear items |
| Powertrain | 5 years | 60,000 mi | Engine, transmission, transfer case, drive axles |
| Emissions (Federal) | 8 years | 80,000 mi | Catalytic converter, ECM/PCM, O2 sensors |
| Emissions (CARB states) | 15 years | 150,000 mi | Extended emissions components |
| Corrosion (perforation) | 6 years | Unlimited | Rust-through of body panels |
| EV/Hybrid Battery | 8 years | 100,000 mi | Battery below 70% capacity |
| EV/Hybrid Powertrain | 8 years | 100,000 mi | Electric motor, inverter, onboard charger |

## Wear Items (NOT covered under warranty)

| Item | Expected Life | Replacement Indicator |
|------|--------------|----------------------|
| Brake pads | 30,000-70,000 mi | Thickness < 3mm or wear indicator contact |
| Tires | 40,000-60,000 mi | Tread depth < 4/32" (fleet) |
| Wiper blades | 6-12 months | Streaking, chattering, torn rubber |
| Light bulbs | Varies | Burned out |
| Filters (air, cabin) | 15,000-30,000 mi | Per maintenance schedule |
| Clutch (manual trans) | 60,000-100,000 mi | Slipping, hard engagement |

## Fleet Extended Coverage Options

| Plan | Duration | Mileage | Deductible | Covers |
|------|----------|---------|-----------|--------|
| Fleet Basic | 5 years | 100,000 mi | $100 | Powertrain + A/C + electrical |
| Fleet Plus | 6 years | 125,000 mi | $50 | Basic + suspension + steering + brakes |
| Fleet Premium | 7 years | 150,000 mi | $0 | Comprehensive (excludes wear items) |

## Warranty Claim Process

1. Driver reports issue via AI agent or service advisor
2. Agent triages severity and checks warranty eligibility
3. If covered: schedule at authorized service center, no cost to driver
4. If not covered: provide repair estimate, offer fleet discount pricing
5. Parts: OEM genuine required for warranty claims
""",

"labor-rates-by-region.md": """---
documentId: POLICY-LABOR-RATES
category: service-policy
title: "Authorized Service Center Labor Rates"
---

# Authorized Service Center Labor Rates

## Regional Labor Rates (2024)

| Region | Standard Rate | Fleet Discount Rate | Emergency/After-Hours |
|--------|--------------|--------------------|-----------------------|
| Northeast (NY, NJ, CT, MA) | $165/hr | $135/hr | $225/hr |
| Southeast (FL, GA, NC, SC) | $140/hr | $115/hr | $195/hr |
| Midwest (IL, OH, MI, IN) | $145/hr | $120/hr | $200/hr |
| Southwest (TX, AZ, NM) | $150/hr | $125/hr | $210/hr |
| West Coast (CA, WA, OR) | $175/hr | $145/hr | $240/hr |
| Mountain (CO, UT, MT) | $140/hr | $115/hr | $195/hr |

## Fleet Discount Eligibility
- Minimum 10 vehicles enrolled in fleet program
- All vehicles must have current maintenance records
- Discount applies to labor only (parts at standard pricing)
- Emergency rate applies outside 7am-7pm M-F

## Mobile Service Rates
- Dispatch fee: $75 (waived for P0 escalations)
- Labor: Standard rate + 15%
- Available for: oil changes, tire rotation, battery, minor electrical
- NOT available for: engine/transmission, brake system, A/C, body work
""",

"escalation-playbook.md": """---
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
""",

"parts-coverage-tiers.md": """---
documentId: POLICY-PARTS-TIERS
category: service-policy
title: "Parts Coverage Tiers and Pricing"
---

# Parts Coverage Tiers

## Tier Definitions

### Tier 1: OEM Genuine
- Manufacturer original parts
- Required for warranty claims
- Highest cost, longest warranty on part (typically 24 months)
- Required for: safety systems, emissions, powertrain under warranty

### Tier 2: OEM Equivalent
- Certified aftermarket meeting OEM specifications
- Same fit, form, function as OEM
- 15-25% cost savings vs Tier 1
- Acceptable for: non-warranty repairs, fleet standard maintenance

### Tier 3: Fleet Standard
- Quality aftermarket parts
- Meets or exceeds OE performance specifications
- 30-50% cost savings vs Tier 1
- Acceptable for: wear items, maintenance parts, non-critical components

## Parts Tier by Component Category

| Component | Warranty Repair | Fleet Standard | Notes |
|-----------|----------------|---------------|-------|
| Brake pads | Tier 1 | Tier 2 or 3 | Tier 3 acceptable for routine replacement |
| Brake rotors | Tier 1 | Tier 2 | Must meet minimum thickness spec |
| Oil filter | Tier 1 | Tier 2 | Must meet OE filtration spec |
| Air filter | Any | Tier 3 | Performance equivalent acceptable |
| Spark plugs | Tier 1 | Tier 2 | Must match OE heat range and gap |
| Battery | Tier 1 | Tier 2 | Must meet CCA and reserve capacity |
| Tires | N/A | Tier 2 | Fleet-approved brands only |
| Sensors (O2, MAF) | Tier 1 | Tier 1 or 2 | Aftermarket sensors often unreliable |
| Catalytic converter | Tier 1 | Tier 1 | Emissions warranty requires OEM |
| Alternator | Tier 1 | Tier 2 | Remanufactured OEM acceptable |
| Starter motor | Tier 1 | Tier 2 | Remanufactured OEM acceptable |

## Fleet Pricing (approximate savings vs MSRP)

| Tier | Discount vs MSRP | Typical Markup |
|------|-----------------|----------------|
| Tier 1 (OEM) | 15-20% fleet discount | Cost + 25% |
| Tier 2 (Equivalent) | 30-40% vs OEM MSRP | Cost + 20% |
| Tier 3 (Standard) | 50-60% vs OEM MSRP | Cost + 15% |
""",
}


def main():
    print(f"Generating service policy docs → {OUT_DIR}")
    for filename, content in FILES.items():
        (OUT_DIR / filename).write_text(content)
    print(f"✅ Generated {len(FILES)} service policy documents")


if __name__ == "__main__":
    main()
