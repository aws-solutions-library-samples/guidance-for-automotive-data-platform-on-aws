#!/usr/bin/env python3
"""Generate synthetic owner manual excerpts and maintenance schedules."""

from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data-sources" / "owner-manuals"
OUT_DIR.mkdir(parents=True, exist_ok=True)

VEHICLES = [
    ("chevrolet-equinox-2022", "2022 Chevrolet Equinox 1.5L Turbo", "5W-30 Dexos1 Gen3", "6.0 qt", "DEX-COOL", "35 PSI", "225/65R17", "3,500 lb"),
    ("ford-transit-2023", "2023 Ford Transit 2.0L EcoBoost", "5W-30 Full Synthetic", "6.5 qt", "Motorcraft Orange", "80 PSI (rear loaded)", "235/65R16C", "7,500 lb"),
    ("ram-promaster-2022", "2022 RAM ProMaster 3.6L V6", "5W-20 Full Synthetic", "5.9 qt", "OAT 50/50", "62 PSI (rear loaded)", "225/75R16C", "6,800 lb"),
    ("toyota-rav4-2023", "2023 Toyota RAV4 2.5L", "0W-20 Synthetic", "4.8 qt", "Toyota Super Long Life", "35 PSI", "225/65R17", "3,500 lb"),
    ("ford-escape-2021", "2021 Ford Escape 1.5L EcoBoost", "5W-30 Full Synthetic", "5.7 qt", "Motorcraft Orange", "35 PSI", "225/65R17", "2,000 lb"),
]

MAINTENANCE_INTERVALS = [
    (5000, "Oil and filter change, tire rotation, multi-point inspection"),
    (10000, "Cabin air filter inspection, brake inspection"),
    (15000, "Engine air filter inspection, cabin air filter replacement"),
    (30000, "Engine air filter replacement, brake fluid test, spark plug inspection (copper)"),
    (45000, "Transmission fluid inspection, coolant test, drive belt inspection"),
    (60000, "Spark plugs (iridium), brake fluid flush, coolant flush, transmission service"),
    (75000, "Drive belt replacement, timing belt inspection (if equipped)"),
    (100000, "Major service: spark plugs, all fluids, belts, hoses, suspension inspection"),
]


def generate_vehicle_manual(slug, name, oil, oil_cap, coolant, tire_psi, tire_size, tow_cap):
    content = f"""---
documentId: MANUAL-{slug.upper()}
category: owner-manuals
title: "{name} — Owner Reference"
vehicle: {name}
---

# {name} — Owner Quick Reference

## Fluid Specifications

| Fluid | Specification | Capacity |
|-------|--------------|----------|
| Engine Oil | {oil} | {oil_cap} |
| Coolant | {coolant} | See reservoir marks |
| Brake Fluid | DOT 4 | As needed |
| Windshield Washer | -20°F rated | 1.0 gallon |

## Tire Information

| Spec | Value |
|------|-------|
| Recommended Pressure (cold) | {tire_psi} |
| Tire Size | {tire_size} |
| Rotation Interval | Every 5,000 miles |
| Replace At | 4/32" tread (fleet) / 2/32" (legal min) |

## Towing

| Spec | Value |
|------|-------|
| Maximum Tow Capacity | {tow_cap} |
| Tongue Weight | 10% of trailer weight |
| Trailer Brakes Required | Above 1,500 lb |

## Maintenance Schedule

| Mileage | Service Items |
|---------|--------------|
"""
    for miles, items in MAINTENANCE_INTERVALS:
        content += f"| {miles:,} mi | {items} |\n"

    content += f"""
## Warning Light Quick Reference

- **Red oil can**: Stop immediately. Check oil level.
- **Red thermometer**: Pull over. Engine overheating.
- **Yellow check engine**: Schedule service. If flashing, reduce speed immediately.
- **Yellow TPMS**: Check tire pressures. Inflate to {tire_psi}.
- **Red battery**: Charging system fault. Drive to service within 30 minutes.

## Emergency Procedures

### Engine Overheating
1. Turn off A/C, turn heater to maximum
2. Pull over safely when possible
3. Let engine idle 2-3 minutes, then turn off
4. Wait 15 minutes before opening hood
5. Check coolant level (DO NOT open cap while hot)

### Brake Failure
1. Pump brake pedal rapidly
2. Apply parking brake gradually
3. Downshift to lower gear
4. Steer toward soft barriers if needed
5. Turn off engine only after stopped
"""
    (OUT_DIR / f"{slug}.md").write_text(content)


def generate_warning_lights():
    content = """---
documentId: MANUAL-WARNING-LIGHTS-UNIVERSAL
category: owner-manuals
title: "Universal Dashboard Warning Lights Guide"
---

# Dashboard Warning Lights — Universal Guide

## Critical (Red) — Immediate Action Required

### Oil Pressure Warning
**Symbol:** Oil can / oil drop
**Meaning:** Engine oil pressure is critically low
**Action:** STOP immediately. Turn off engine. Check oil level. Do NOT drive.
**Risk:** Engine seizure within minutes if ignored.

### Temperature Warning
**Symbol:** Thermometer in liquid
**Meaning:** Engine coolant temperature is dangerously high
**Action:** Pull over safely. Turn off A/C, turn on heater. Let cool 15 min.
**Risk:** Head gasket failure, warped cylinder head.

### Brake System Warning
**Symbol:** Circle with "BRAKE" or exclamation mark
**Meaning:** Brake fluid low, system pressure loss, or parking brake engaged
**Action:** Check if parking brake is released. If pedal feels soft, stop driving.
**Risk:** Reduced or complete loss of braking ability.

### Airbag/SRS Warning
**Symbol:** Person with circle (airbag)
**Meaning:** Supplemental restraint system fault
**Action:** Airbag may not deploy in crash. Schedule immediate service.
**Risk:** No airbag protection in collision.

## Warning (Amber/Yellow) — Service Soon

### Check Engine / MIL
**Symbol:** Engine outline
**Meaning:** Emissions or powertrain fault detected
**Steady:** Schedule service within 1-2 weeks
**Flashing:** Active misfire — reduce speed, avoid hard acceleration, service ASAP
**Risk (flashing):** Catalytic converter damage.

### ABS Warning
**Symbol:** Circle with "ABS"
**Meaning:** Anti-lock brake system disabled
**Action:** Normal brakes work. Avoid hard braking on wet/icy surfaces. Service within 48h.

### Traction/Stability Control
**Symbol:** Car with wavy lines
**Meaning:** System disabled or actively intervening
**Blinking:** System working (normal in slippery conditions)
**Steady:** System fault — service within 1 week

### TPMS (Tire Pressure)
**Symbol:** Tire cross-section with exclamation mark
**Meaning:** One or more tires below recommended pressure
**Action:** Check all tires including spare. Inflate to door placard spec.
**If rapid loss:** Do not drive. Inspect for puncture.

### Battery/Charging
**Symbol:** Battery outline
**Meaning:** Charging system not maintaining voltage
**Action:** Turn off non-essential electronics. Drive directly to service (within 20-30 min).
**Risk:** Battery will die, vehicle will stall.
"""
    (OUT_DIR / "warning-lights-universal.md").write_text(content)


def main():
    print(f"Generating owner manuals → {OUT_DIR}")
    for v in VEHICLES:
        generate_vehicle_manual(*v)
    generate_warning_lights()
    print(f"✅ Generated {len(VEHICLES)} vehicle manuals + 1 warning lights guide")


if __name__ == "__main__":
    main()
