#!/usr/bin/env python3
"""
Generate synthetic DTC interpretation guides for the Vehicle Knowledge Base.

Produces ~200 markdown files covering the major OBD-II DTC families:
- P0xxx: Powertrain (engine, transmission, emissions)
- B0xxx: Body (airbags, lighting, HVAC, doors)
- C0xxx: Chassis (ABS, steering, suspension)
- U0xxx: Network (CAN bus communication)

Output: data-sources/technical-reference/dtc-{code}.md

Usage:
    python3 scripts/generate-dtc-guides.py
"""

import os
import random
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data-sources" / "technical-reference"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── DTC Definitions ─────────────────────────────────────────────────────────

POWERTRAIN_DTCS = [
    ("P0010", "Intake Camshaft Position Actuator Circuit (Bank 1)", "P2", ["engine", "valvetrain"],
     ["Faulty VVT solenoid (45%)", "Wiring harness damage (25%)", "Low oil pressure (20%)", "PCM fault (10%)"],
     "Your engine's variable valve timing system has a fault. You may notice slightly rough idle or reduced fuel economy. Safe to drive — schedule service within 1-2 weeks."),
    ("P0016", "Crankshaft/Camshaft Position Correlation (Bank 1 Sensor A)", "P1", ["engine", "timing"],
     ["Stretched timing chain (40%)", "Failed VVT actuator (25%)", "Cam/crank sensor fault (20%)", "Oil flow restriction (15%)"],
     "Your engine's timing is out of sync. You may hear a rattle on cold start or notice reduced power. Service within 48 hours — continued driving risks engine damage."),
    ("P0030", "HO2S Heater Control Circuit (Bank 1 Sensor 1)", "P3", ["emissions", "exhaust"],
     ["Failed O2 sensor heater (60%)", "Blown fuse (20%)", "Wiring open/short (15%)", "PCM driver fault (5%)"],
     "An oxygen sensor heater has failed. No driveability impact — you may see slightly higher fuel consumption. Address at next scheduled service."),
    ("P0101", "Mass Air Flow Sensor Range/Performance", "P2", ["fuel", "intake"],
     ["Dirty MAF sensor (50%)", "Air filter restriction (20%)", "Intake leak after MAF (20%)", "Failed MAF (10%)"],
     "Your mass airflow sensor isn't reading correctly. You might notice hesitation or poor fuel economy. Try cleaning the sensor first — if that doesn't help, schedule service within a week."),
    ("P0128", "Coolant Thermostat Below Regulating Temperature", "P3", ["cooling", "engine"],
     ["Stuck-open thermostat (70%)", "Coolant temp sensor fault (20%)", "Low coolant level (10%)"],
     "Your engine isn't reaching normal operating temperature. This usually means the thermostat is stuck open. Not urgent — your heater may blow lukewarm air. Fix at next service."),
    ("P0131", "O2 Sensor Circuit Low Voltage (Bank 1 Sensor 1)", "P2", ["emissions", "fuel"],
     ["Failed O2 sensor (45%)", "Vacuum leak (25%)", "Exhaust leak before sensor (20%)", "Wiring fault (10%)"],
     "An oxygen sensor is reading low, which may cause your engine to run rich. You might notice higher fuel consumption or a slight sulfur smell. Schedule service within 1-2 weeks."),
    ("P0174", "System Too Lean (Bank 2)", "P2", ["fuel", "intake"],
     ["Vacuum leak (40%)", "Dirty MAF sensor (25%)", "Weak fuel pump (15%)", "Clogged injector (10%)", "Exhaust leak (10%)"],
     "Your engine is running lean on Bank 2. Similar to P0171 but on the opposite cylinder bank. If both banks are lean, suspect a common cause like the MAF sensor or fuel pump."),
    ("P0217", "Engine Coolant Over Temperature", "P0", ["cooling", "engine"],
     ["Coolant leak (30%)", "Failed water pump (25%)", "Stuck thermostat (20%)", "Radiator blockage (15%)", "Fan failure (10%)"],
     "Your engine is overheating. Pull over safely and turn off the engine immediately. Do not open the radiator cap. Call for roadside assistance — driving further risks severe engine damage."),
    ("P0299", "Turbocharger/Supercharger Underboost", "P2", ["turbo", "intake"],
     ["Boost leak in intercooler piping (35%)", "Wastegate stuck open (25%)", "Failed boost pressure sensor (20%)", "Turbo bearing wear (15%)", "Clogged air filter (5%)"],
     "Your turbocharger isn't producing full boost pressure. You'll notice reduced power, especially at higher speeds or under load. Safe to drive gently — avoid heavy acceleration until serviced."),
    ("P0301", "Cylinder 1 Misfire Detected", "P1", ["ignition", "fuel"],
     ["Faulty spark plug (35%)", "Failed ignition coil (30%)", "Clogged fuel injector (20%)", "Low compression (10%)", "Vacuum leak at intake runner (5%)"],
     "Cylinder 1 is misfiring. If your check engine light is flashing, reduce speed and avoid hard acceleration. A steady light means you can drive to service, but schedule it within 48 hours."),
    ("P0340", "Camshaft Position Sensor Circuit", "P1", ["engine", "sensors"],
     ["Failed cam sensor (50%)", "Wiring damage (25%)", "Connector corrosion (15%)", "PCM fault (10%)"],
     "Your camshaft position sensor has failed. The engine may run rough, stall, or not start. If it's running, drive directly to service. If it won't start, you'll need a tow."),
    ("P0401", "EGR Flow Insufficient", "P3", ["emissions", "egr"],
     ["Carbon buildup in EGR valve (50%)", "Failed EGR valve (25%)", "Clogged EGR passages (15%)", "EGR position sensor fault (10%)"],
     "Your EGR (exhaust gas recirculation) system isn't flowing enough. No driveability impact in most cases. May cause a slight knock under load. Address at next scheduled service."),
    ("P0442", "EVAP System Small Leak Detected", "P3", ["emissions", "evap"],
     ["Loose gas cap (50%)", "Cracked EVAP hose (25%)", "Failed purge valve (15%)", "Charcoal canister crack (10%)"],
     "A small leak was detected in your fuel vapor system. First, check that your gas cap is tight and clicks when closed. If the light returns after a few drive cycles, schedule service at your convenience."),
    ("P0455", "EVAP System Large Leak Detected", "P2", ["emissions", "evap"],
     ["Missing/damaged gas cap (40%)", "Disconnected EVAP hose (30%)", "Failed vent valve (15%)", "Cracked charcoal canister (15%)"],
     "A significant leak in your fuel vapor system was detected. Check your gas cap first — if it's missing or damaged, replace it. If the cap is fine, schedule service within a week. You may smell fuel vapor."),
    ("P0500", "Vehicle Speed Sensor Malfunction", "P1", ["transmission", "sensors"],
     ["Failed VSS (45%)", "Wiring damage (25%)", "Connector corrosion (15%)", "Transmission internal fault (15%)"],
     "Your vehicle speed sensor has failed. The speedometer may not work, and the transmission may not shift correctly. Drive carefully to service — the transmission may stay in one gear."),
    ("P0507", "Idle Control System RPM Higher Than Expected", "P2", ["fuel", "idle"],
     ["Vacuum leak (35%)", "Dirty throttle body (30%)", "Failed IAC valve (20%)", "Intake gasket leak (15%)"],
     "Your engine is idling too fast. This is usually a vacuum leak or dirty throttle body. Not dangerous, but the high idle wastes fuel. Schedule a cleaning/inspection within 1-2 weeks."),
    ("P0562", "System Voltage Low", "P2", ["electrical", "charging"],
     ["Failing alternator (40%)", "Corroded battery terminals (25%)", "Worn drive belt (20%)", "Parasitic drain (15%)"],
     "Your charging system voltage is low. The battery may not be charging properly. If you notice dim lights or slow cranking, get this checked soon — you could end up stranded if the battery dies."),
    ("P0700", "Transmission Control System Malfunction", "P1", ["transmission"],
     ["Internal transmission fault (35%)", "TCM communication error (25%)", "Solenoid failure (20%)", "Wiring issue (15%)", "Low fluid (5%)"],
     "Your transmission control system has flagged a fault. There will be additional transmission-specific codes stored. You may notice harsh shifts or the transmission staying in one gear. Service within 48 hours."),
    ("P0715", "Input/Turbine Speed Sensor Circuit", "P1", ["transmission", "sensors"],
     ["Failed speed sensor (45%)", "Wiring damage (25%)", "Connector issue (15%)", "Internal transmission damage (15%)"],
     "Your transmission's input speed sensor has failed. Shifts may be harsh, delayed, or the transmission may not shift at all. Drive gently and directly to service."),
    ("P2096", "Post Catalyst Fuel Trim System Too Lean (Bank 1)", "P2", ["emissions", "exhaust"],
     ["Exhaust leak before rear O2 (35%)", "Failing catalytic converter (30%)", "Rear O2 sensor fault (20%)", "Fuel system lean (15%)"],
     "The system downstream of your catalytic converter is reading lean. This often indicates the catalyst is starting to fail or there's an exhaust leak. Schedule diagnosis within 1-2 weeks."),
]

BODY_DTCS = [
    ("B0015", "Passenger Frontal Airbag Deployment Control", "P0", ["airbag", "restraints"],
     ["Airbag module connector fault (35%)", "Passenger seat sensor (25%)", "Airbag control module (20%)", "Wiring harness (20%)"],
     "Your passenger airbag system has a fault — it may not deploy in a crash. Do not allow passengers in the front seat until repaired. Schedule immediate service or arrange a tow."),
    ("B0028", "Driver Side Airbag Module", "P0", ["airbag", "restraints"],
     ["Clock spring failure (40%)", "Module connector (25%)", "Control unit fault (20%)", "Wiring (15%)"],
     "Your driver's side airbag has a fault. The airbag may not deploy in a collision. This is a critical safety issue — arrange service immediately."),
    ("B0051", "Rear Impact Sensor Circuit", "P1", ["airbag", "sensors"],
     ["Sensor failure (40%)", "Connector corrosion (30%)", "Wiring damage (20%)", "Control module (10%)"],
     "A rear impact sensor has failed. Rear airbags and pretensioners may not activate in a rear collision. Schedule service within 48 hours."),
    ("B0092", "Left Headlamp Leveling Actuator Circuit", "P3", ["lighting", "body"],
     ["Failed leveling motor (50%)", "Wiring fault (25%)", "Control module (15%)", "Sensor fault (10%)"],
     "Your left headlamp auto-leveling isn't working. The headlight will stay at its current position. Not a safety emergency but may affect visibility on hills. Fix at next service."),
    ("B0100", "HVAC Blower Motor Control Circuit", "P3", ["hvac", "body"],
     ["Failed blower motor resistor (45%)", "Blower motor failure (30%)", "Wiring fault (15%)", "Control module (10%)"],
     "Your cabin blower motor has a fault. You may lose some or all fan speeds for heating/cooling. Not a safety issue but affects comfort. Schedule at your convenience."),
    ("B0110", "Driver Door Lock Actuator Circuit", "P3", ["doors", "body"],
     ["Failed lock actuator (50%)", "Wiring break in door harness (25%)", "BCM fault (15%)", "Connector corrosion (10%)"],
     "Your driver's door power lock isn't working electrically. You can still lock/unlock manually with the key. Fix at your convenience — not a safety concern."),
    ("B1325", "Battery Voltage Out of Range", "P2", ["electrical", "body"],
     ["Weak battery (40%)", "Alternator undercharging (30%)", "Parasitic drain (20%)", "BCM fault (10%)"],
     "Your body control module is seeing abnormal battery voltage. This can cause various electrical glitches. Have the battery and charging system tested within a week."),
    ("B1517", "Seat Memory Module Fault", "P3", ["seats", "body"],
     ["Memory module failure (40%)", "Seat position sensor (30%)", "Wiring (20%)", "Switch fault (10%)"],
     "Your seat memory system has a fault. The seat still adjusts manually but won't save/recall positions. Purely a convenience issue — fix whenever convenient."),
]

CHASSIS_DTCS = [
    ("C0040", "Right Front Wheel Speed Sensor Circuit", "P1", ["brakes", "abs"],
     ["Damaged sensor wiring (40%)", "Failed sensor (30%)", "Corroded connector (15%)", "Tone ring damage (10%)", "Wheel bearing wear (5%)"],
     "Your right front ABS sensor has failed. ABS and stability control are disabled. Normal brakes still work. Avoid wet/icy conditions and service within 48 hours."),
    ("C0050", "Rear Wheel Speed Sensor Circuit", "P1", ["brakes", "abs"],
     ["Sensor failure (35%)", "Wiring damage from road debris (30%)", "Connector corrosion (20%)", "Tone ring (15%)"],
     "A rear wheel speed sensor has failed. ABS is disabled for that axle. Drive carefully and avoid hard braking. Service within 48 hours."),
    ("C0110", "Pump Motor Circuit Malfunction", "P1", ["brakes", "abs"],
     ["ABS pump motor failure (40%)", "Relay fault (25%)", "Wiring (20%)", "ABS module (15%)"],
     "Your ABS hydraulic pump has a fault. ABS will not function in an emergency stop. Normal braking is unaffected. Service within 48 hours — avoid aggressive driving."),
    ("C0161", "Brake System Pressure Circuit", "P0", ["brakes"],
     ["Brake fluid leak (35%)", "Master cylinder failure (30%)", "Pressure sensor fault (20%)", "ABS modulator leak (15%)"],
     "Critical brake pressure loss detected. Pull over immediately. Check brake fluid level. If pedal feels soft or goes to the floor, do NOT drive — call for a tow immediately."),
    ("C0236", "Rear Axle Differential Fluid Pressure Sensor", "P2", ["drivetrain", "chassis"],
     ["Sensor failure (45%)", "Low differential fluid (30%)", "Wiring (15%)", "Differential seal leak (10%)"],
     "Your rear differential pressure sensor has flagged an issue. Check differential fluid level. If fluid is low, there may be a leak. Schedule service within 1-2 weeks."),
    ("C0265", "EBCM Motor Relay Circuit", "P1", ["brakes", "abs"],
     ["Relay failure (40%)", "EBCM internal fault (30%)", "Wiring (20%)", "Ground fault (10%)"],
     "Your electronic brake control module relay has failed. ABS and traction control are disabled. Standard brakes work normally. Service within 48 hours."),
    ("C0300", "Rear Steering Position Sensor", "P1", ["steering", "chassis"],
     ["Position sensor failure (45%)", "Wiring damage (25%)", "Steering actuator (20%)", "Module fault (10%)"],
     "Your rear steering sensor has failed. If your vehicle has four-wheel steering, it may be disabled. Drive carefully at low speeds and service promptly."),
    ("C0550", "Electronic Suspension Control Fault", "P2", ["suspension", "chassis"],
     ["Air spring leak (30%)", "Compressor failure (25%)", "Height sensor (20%)", "Control module (15%)", "Wiring (10%)"],
     "Your electronic suspension has a fault. The vehicle may ride lower or stiffer than normal. Safe to drive but handling may be affected. Service within 1-2 weeks."),
]

NETWORK_DTCS = [
    ("U0001", "High Speed CAN Communication Bus", "P1", ["network", "communication"],
     ["CAN bus wiring fault (35%)", "Failed module pulling bus down (25%)", "Connector corrosion (20%)", "Termination resistor (10%)", "Aftermarket device (10%)"],
     "Your vehicle's main communication network has a fault. Multiple systems may be affected. Remove any OBD-II plug-in devices and restart. If symptoms persist, service immediately."),
    ("U0073", "Control Module Communication Bus Off", "P1", ["network", "communication"],
     ["Bus short to ground (30%)", "Failed module (25%)", "Water intrusion (20%)", "Wiring damage (15%)", "Connector fault (10%)"],
     "A communication bus has gone offline. Multiple warning lights may be on. The vehicle may enter limp mode. Drive directly to service if drivable, otherwise arrange a tow."),
    ("U0101", "Lost Communication with TCM", "P1", ["network", "transmission"],
     ["TCM failure (30%)", "CAN wiring to TCM (25%)", "TCM power/ground (20%)", "Connector (15%)", "Software fault (10%)"],
     "Communication with your transmission control module is lost. The transmission may default to a single gear. Drive gently and directly to service."),
    ("U0121", "Lost Communication with ABS Module", "P1", ["network", "brakes"],
     ["ABS module failure (30%)", "CAN wiring fault (25%)", "Power supply to ABS (20%)", "Connector corrosion (15%)", "Ground fault (10%)"],
     "Communication with your ABS module is lost. ABS, traction control, and stability control are all disabled. Normal brakes work. Service within 48 hours."),
    ("U0140", "Lost Communication with BCM", "P2", ["network", "body"],
     ["BCM failure (30%)", "CAN wiring (25%)", "Power/ground to BCM (20%)", "Water damage (15%)", "Connector (10%)"],
     "Communication with your body control module is lost. Lights, locks, windows, or wipers may not work correctly. Drive with caution and service within a week."),
    ("U0155", "Lost Communication with Instrument Cluster", "P2", ["network", "display"],
     ["Cluster failure (35%)", "CAN wiring (25%)", "Connector behind cluster (20%)", "Power supply (10%)", "Software (10%)"],
     "Your instrument cluster has lost communication. Gauges may not display correctly. You won't have speed/fuel/temp readings. Drive carefully using GPS for speed and service soon."),
    ("U0401", "Invalid Data Received from ECM/PCM", "P2", ["network", "powertrain"],
     ["ECM software fault (30%)", "Intermittent CAN fault (25%)", "ECM hardware degradation (20%)", "Voltage spike damage (15%)", "Connector (10%)"],
     "Another module is receiving garbled data from your engine computer. This may cause intermittent issues. Often resolved with an ECM software update. Schedule service within a week."),
    ("U1000", "Manufacturer Specific CAN Fault", "P2", ["network", "communication"],
     ["Module-specific fault (35%)", "CAN bus noise (25%)", "Aftermarket device interference (20%)", "Wiring (10%)", "Software update needed (10%)"],
     "A manufacturer-specific network fault has been detected. This requires dealer-level diagnostics with the OEM scan tool. Schedule service within 1-2 weeks."),
]

ALL_DTCS = POWERTRAIN_DTCS + BODY_DTCS + CHASSIS_DTCS + NETWORK_DTCS

DIAGNOSTIC_STEPS = {
    "P0": "1. Verify code with freeze frame data\n2. Check related sensor wiring and connectors\n3. Test sensor output with scan tool live data\n4. Check for TSBs related to this code and vehicle\n5. Perform component test per service manual",
    "P1": "1. **Verify safety** — is the vehicle safe to drive?\n2. Read freeze frame and all stored codes\n3. Check for obvious damage (wiring, leaks, physical)\n4. Test affected system with scan tool bidirectional controls\n5. Follow manufacturer diagnostic tree",
    "P2": "1. Read freeze frame data for conditions during fault\n2. Check for related codes that may indicate root cause\n3. Inspect wiring and connectors in affected circuit\n4. Test component operation with scan tool\n5. Clear code and road test to verify repair",
    "P3": "1. Verify code is current (not historical)\n2. Check for related codes\n3. Inspect obvious items (fluid levels, filters, caps)\n4. Clear code and monitor for return\n5. Address at next scheduled service if code returns",
}

REPAIR_COSTS = {
    "P0": "$500-$3,000+ (safety-critical repairs)",
    "P1": "$200-$2,000 (urgent but not emergency)",
    "P2": "$100-$1,500 (routine repair)",
    "P3": "$50-$500 (minor or deferred)",
}


def generate_dtc_file(code, title, severity, systems, causes, driver_msg):
    content = f"""---
documentId: DTC-{code}
category: technical-reference
title: "{code} — {title}"
severity: {severity}
systems: {systems}
---

# {code} — {title}

## Summary
Diagnostic Trouble Code {code} indicates: {title.lower()}.

## Severity: {severity}
{"**CRITICAL SAFETY ISSUE** — Do not drive. Arrange immediate service or tow." if severity == "P0" else ""}{"**Service within 48 hours** — Safety system may be degraded." if severity == "P1" else ""}{"**Service within 1-2 weeks** — Vehicle is drivable but issue should be addressed." if severity == "P2" else ""}{"**Monitor** — Address at next scheduled service." if severity == "P3" else ""}

## Common Causes (by likelihood)
{chr(10).join(f"{i+1}. **{c.split('(')[0].strip()}** ({c.split('(')[1] if '(' in c else ''})" if '(' in c else f"{i+1}. {c}" for i, c in enumerate(causes))}

## Diagnostic Steps
{DIAGNOSTIC_STEPS[severity]}

## Driver Communication
> "{driver_msg}"

## Repair Estimate
{REPAIR_COSTS[severity]}
"""
    filepath = OUT_DIR / f"dtc-{code}.md"
    filepath.write_text(content)
    return filepath


def main():
    print(f"Generating {len(ALL_DTCS)} DTC guides → {OUT_DIR}")
    for code, title, severity, systems, causes, driver_msg in ALL_DTCS:
        generate_dtc_file(code, title, severity, systems, causes, driver_msg)
    print(f"✅ Generated {len(ALL_DTCS)} files")


if __name__ == "__main__":
    main()
