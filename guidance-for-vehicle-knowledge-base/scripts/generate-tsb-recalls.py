#!/usr/bin/env python3
"""Generate synthetic TSBs and recall bulletins for the Vehicle Knowledge Base."""

from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data-sources" / "tsb-recalls"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TSBS = [
    ("2024-EN-0112", "Engine Oil Consumption Above Normal", "2019-2023 Chevrolet Equinox 1.5T",
     "Some vehicles may consume more than 1 quart of oil per 3,000 miles due to piston ring design.",
     "Replace piston rings with updated design (GM P/N 12710344). Requires engine partial disassembly. Labor: 8.5 hours.",
     "Powertrain warranty (5yr/60k) or Customer Satisfaction Program 22-NA-189 (7yr/84k)."),
    ("2024-EN-0298", "Turbo Wastegate Rattle on Cold Start", "2020-2024 Ford Transit 2.0L EcoBoost",
     "Audible rattle from turbocharger area for 5-30 seconds after cold start below 40°F.",
     "Replace wastegate actuator with revised part (Ford P/N LK4Z-6K682-A). Labor: 1.2 hours.",
     "Bumper-to-bumper (3yr/36k). No customer satisfaction program."),
    ("2024-TR-0445", "Harsh 1-2 Shift Under Light Throttle", "2021-2024 RAM ProMaster 3.6L",
     "Transmission may exhibit a firm 1-2 upshift at light throttle between 15-25 mph.",
     "Reflash TCM with updated calibration (software level AA). No parts required. Labor: 0.5 hours.",
     "Powertrain warranty (5yr/60k)."),
    ("2024-BR-0567", "Rear Brake Caliper Slide Pin Seizure", "2020-2023 Toyota RAV4",
     "Rear brake calipers may develop seized slide pins causing uneven pad wear and brake pull.",
     "Clean and re-lubricate slide pins. Replace pins if scored (Toyota P/N 47721-42030). Inspect pads — replace if wear difference exceeds 2mm. Labor: 1.0 hours per side.",
     "Bumper-to-bumper (3yr/36k) or Toyota Customer Support Program ZLR (5yr/60k)."),
    ("2024-EL-0089", "Infotainment Screen Intermittent Black", "2022-2024 Chevrolet Equinox",
     "Touchscreen may go black intermittently while driving. Audio continues to function.",
     "Replace infotainment display module (GM P/N 84983018). Requires recalibration after install. Labor: 1.5 hours.",
     "Bumper-to-bumper (3yr/36k)."),
    ("2023-SU-0334", "Front Strut Mount Clunk Over Bumps", "2019-2022 Ford Escape",
     "Clunking noise from front suspension when driving over bumps at low speed.",
     "Replace front strut mount bearings with updated design (Ford P/N LJ6Z-18183-A). Labor: 2.0 hours per side.",
     "Bumper-to-bumper (3yr/36k). Ford Extended Service Plan covers if purchased."),
    ("2024-CL-0201", "A/C Compressor Clutch Engagement Noise", "2021-2024 Chevrolet Equinox",
     "Single click/clunk when A/C compressor engages, especially noticeable at idle.",
     "Install compressor clutch damper kit (GM P/N 84612987). No compressor replacement needed. Labor: 0.8 hours.",
     "Bumper-to-bumper (3yr/36k)."),
    ("2024-ST-0178", "Power Steering Assist Reduced Message", "2020-2023 Chevrolet Equinox",
     "Driver may see 'Power Steering Assist Reduced' message with DTC C0545. Steering still functions but requires more effort.",
     "Replace steering column torque sensor (GM P/N 84754321). Requires steering column partial disassembly and recalibration. Labor: 2.5 hours.",
     "Powertrain warranty (5yr/60k) — steering is covered under powertrain on this platform."),
]

RECALLS = [
    ("24V-234", "Brake Booster Vacuum Hose May Disconnect", "2022-2023 Ford Transit Connect",
     "2024-02-15", "45,000",
     "The brake booster vacuum hose may disconnect from the intake manifold fitting, resulting in reduced brake assist. Increased pedal effort required to stop.",
     "Dealers will install a revised hose clamp and inspect the hose for damage. Replace hose if cracked. Repair time: 0.5 hours.",
     "If brake pedal feels hard or requires excessive force, pull over safely. Vehicle can still be stopped but requires significantly more pedal pressure."),
    ("24V-456", "Seat Belt Pretensioner May Not Deploy", "2021-2022 Chevrolet Equinox",
     "2024-04-10", "180,000",
     "Front seat belt pretensioners may not activate in a frontal collision due to a software calibration error in the restraints control module.",
     "Dealers will update the restraints control module software. No hardware replacement needed. Repair time: 0.3 hours.",
     "Seat belts still function as standard 3-point belts. Only the pretensioner (which pulls the belt tight in a crash) is affected."),
    ("24V-678", "Fuel Rail Pressure Sensor Leak", "2023-2024 RAM ProMaster 3.6L",
     "2024-06-01", "28,000",
     "The fuel rail pressure sensor may develop a fuel leak at the sensor-to-rail interface due to insufficient torque during assembly. Fuel odor or visible fuel near the engine.",
     "Dealers will inspect and re-torque the fuel rail pressure sensor. Replace sensor and O-ring if leak is confirmed. Repair time: 0.8 hours.",
     "If you smell fuel or see fuel near the engine, do not drive. Park outdoors away from ignition sources and contact your dealer for towing."),
    ("23V-891", "Rear Suspension Trailing Arm Bolt", "2020-2022 Ford Escape",
     "2023-11-20", "95,000",
     "Rear suspension trailing arm bolt may loosen over time due to insufficient thread-locking compound applied during assembly. May cause clunking noise and rear wheel misalignment.",
     "Dealers will remove trailing arm bolts, clean threads, apply thread-locking compound, and re-torque to specification. Inspect trailing arm bushings. Repair time: 1.0 hour.",
     "If you notice a clunking from the rear or the vehicle pulling to one side, reduce speed and avoid sharp turns. Schedule service promptly."),
    ("24V-112", "Engine Cooling Fan May Not Activate", "2022-2024 Toyota RAV4 Hybrid",
     "2024-01-30", "67,000",
     "Engine cooling fan relay may fail in the open position, preventing the fan from activating. Engine may overheat in stop-and-go traffic or at idle.",
     "Dealers will replace the cooling fan relay and inspect wiring harness for heat damage. Repair time: 0.5 hours.",
     "Monitor temperature gauge. If it rises above normal, turn on the heater to maximum and pull over. Do not continue driving if the gauge enters the red zone."),
]


def generate_tsb(tsb_id, title, applies_to, condition, correction, warranty):
    content = f"""---
documentId: TSB-{tsb_id}
category: tsb-recalls
type: technical-service-bulletin
title: "TSB {tsb_id}: {title}"
applies_to: [{applies_to}]
---

# TSB {tsb_id}: {title}

**Applies to:** {applies_to}

## Condition
{condition}

## Correction
{correction}

## Warranty Coverage
{warranty}

## Driver Communication
> "There's a known issue with your vehicle that matches what you're describing. A Technical Service Bulletin has been issued with a fix. {'This should be covered under your warranty.' if 'warranty' in warranty.lower() else 'Let me check your warranty coverage.'} Would you like me to schedule the repair?"
"""
    (OUT_DIR / f"tsb-{tsb_id}.md").write_text(content)


def generate_recall(campaign, title, applies_to, date, affected_count, defect, remedy, interim):
    content = f"""---
documentId: RECALL-{campaign}
category: tsb-recalls
type: safety-recall
title: "NHTSA Recall {campaign}: {title}"
nhtsa_campaign: "{campaign}"
applies_to: [{applies_to}]
date_issued: "{date}"
---

# NHTSA Safety Recall {campaign}

## {title}

**Affected Vehicles:** {applies_to}
**Date Issued:** {date}
**Estimated Affected:** {affected_count} vehicles

## Defect Description
{defect}

## Remedy
{remedy}

## Interim Driver Guidance
{interim}

## Driver Communication
> "Your vehicle is affected by a safety recall — {campaign}. {defect.split('.')[0]}. The repair is free at any authorized dealer. Would you like me to help schedule an appointment?"
"""
    (OUT_DIR / f"recall-{campaign}.md").write_text(content)


def main():
    print(f"Generating TSBs and recalls → {OUT_DIR}")
    for tsb in TSBS:
        generate_tsb(*tsb)
    for recall in RECALLS:
        generate_recall(*recall)
    print(f"✅ Generated {len(TSBS)} TSBs + {len(RECALLS)} recalls")


if __name__ == "__main__":
    main()
