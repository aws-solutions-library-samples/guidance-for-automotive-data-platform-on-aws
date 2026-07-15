"""Generator for ``vehicle_knowledge_base`` (text/PDF artifacts + chunk manifest).

Per ``decisions.md`` "2026-05-28 — Group 3 scope: pandas-full,
Spark-sample, KB-artifacts-only", this generator delivers **artifacts
only**. It ports the six legacy generator scripts under
``guidance-for-vehicle-knowledge-base/scripts/generate-*.py`` (DTC
guides, TSB/recalls, owner manuals, parts catalog, service network,
service policy) into a single platform-foundation entry point.

Scope of this task (Group 3):
- Emit text/markdown source artifacts to a local output directory
  (or directly to S3 via the staging path
  ``s3://adp-staging-foundation-lake-<account>-<region>/knowledge/vehicle_knowledge_base/``).
- Emit a ``manifest.json`` listing every artifact along with chunk
  records (chunk_id, source_doc_id, source_category, title,
  chunk_index, chunk_text, chunk_size_tokens, chunk_overlap_tokens,
  embedding_model, s3_uri, language, indexed_at) matching the
  ``vehicle_knowledge_base/schema.yaml`` columns.
- This is NOT an Iceberg table; ``schema_loader.iceberg_ddl()`` raises
  on ``storage_format=documents`` by design (see
  ``test_no_iceberg_ddl_for_documents``).

**DEFERRED TO GROUP 5** (per ``decisions.md`` "KB-artifacts-only"):
- Bedrock Knowledge Base CDK construct
- OpenSearch Serverless backing collection + index
- Bedrock KB ingestion job
- ``aws bedrock-agent get-knowledge-base`` STATUS=ACTIVE assertion

Group 5 ("Bedrock KB seeding extensions") consumes the artifacts +
manifest produced by this generator. The chunk schema declared in
``schema.yaml`` is the contract between this generator and the
Group 5 KB ingestion path.

Run::

    # Local smoke test
    python source/data-products/vehicle_knowledge_base/generator.py \\
        --output-root /tmp/adp-vkb

    # S3 staging upload (account + region resolved from env at import time;
    # see DEFAULT_STAGING_S3_ROOT below)
    python source/data-products/vehicle_knowledge_base/generator.py \\
        --output-root s3://adp-staging-foundation-lake-<account>-<region>/knowledge/vehicle_knowledge_base
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Make ``schema_loader`` importable when run directly from the source tree.
_LIB = Path(__file__).resolve().parents[3] / "source" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import schema_loader as sl  # noqa: E402

# UUIDv5 namespace for deterministic chunk IDs (per schema.yaml docstring:
# "Stable chunk identifier (UUIDv5 from source_doc_id + chunk_index)").
_KB_NAMESPACE = uuid.UUID("12345678-1234-5678-1234-567812345678")

# Default Bedrock embedding model (per docs/tech.md research). Group 5 may
# override at ingestion time.
DEFAULT_EMBEDDING_MODEL = "amazon.titan-embed-text-v2:0"
DEFAULT_LANGUAGE = "en"

# Chunk sizing — conservative defaults for Titan v2 (8192 token max input).
DEFAULT_CHUNK_SIZE_TOKENS = 512
DEFAULT_CHUNK_OVERLAP_TOKENS = 50

# Default staging S3 root (per decisions.md "Stage rollout complete").
#
# The account + region segments are resolved from environment variables
# at import time so the source default carries no real account ID. Set
# `CDK_DEFAULT_ACCOUNT` (or `AWS_ACCOUNT_ID`) and `AWS_REGION` (or
# `CDK_DEFAULT_REGION`) before running, OR pass `--s3-root` explicitly.
# The placeholder fall-throughs (`123456789012` / `us-east-1`) are
# intentionally non-routable so a missing env / flag fails loudly at
# upload time rather than silently targeting another account's bucket.
_DEFAULT_S3_ACCOUNT = (
    os.environ.get("CDK_DEFAULT_ACCOUNT")
    or os.environ.get("AWS_ACCOUNT_ID")
    or "123456789012"
)
_DEFAULT_S3_REGION = (
    os.environ.get("AWS_REGION")
    or os.environ.get("CDK_DEFAULT_REGION")
    or "us-east-1"
)
DEFAULT_STAGING_S3_ROOT = (
    f"s3://adp-staging-foundation-lake-{_DEFAULT_S3_ACCOUNT}-{_DEFAULT_S3_REGION}/"
    "knowledge/vehicle_knowledge_base"
)


# ---------------------------------------------------------------------------
# Token / chunking helpers
# ---------------------------------------------------------------------------


def _approx_token_count(text: str) -> int:
    """Heuristic token count — ~1.3 tokens per word (English).

    Avoids a hard tiktoken dependency. Bedrock ingestion will recompute
    exact token counts at chunk time; this is only for the manifest's
    ``chunk_size_tokens`` column.
    """
    if not text:
        return 0
    words = re.findall(r"\S+", text)
    return max(1, int(round(len(words) * 1.3)))


def _chunk_id(source_doc_id: str, chunk_index: int) -> str:
    """Deterministic UUIDv5 from ``source_doc_id + chunk_index``."""
    return str(uuid.uuid5(_KB_NAMESPACE, f"{source_doc_id}#{chunk_index}"))


def _split_into_chunks(
    text: str,
    *,
    chunk_size_tokens: int = DEFAULT_CHUNK_SIZE_TOKENS,
    chunk_overlap_tokens: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """Split ``text`` into chunks of ~``chunk_size_tokens`` with overlap.

    Splits on paragraph boundaries (double-newline); falls back to
    sentence boundaries if a single paragraph exceeds the chunk size.
    Overlap is realized by retaining trailing tokens from the previous
    chunk. Returns at least one chunk for non-empty inputs.
    """
    text = text.strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for para in paragraphs:
        para_tokens = _approx_token_count(para)
        if buf and buf_tokens + para_tokens > chunk_size_tokens:
            chunks.append("\n\n".join(buf))
            # Build overlap from trailing words of the just-emitted chunk.
            tail_words = re.findall(r"\S+", chunks[-1])
            tail_count = max(0, int(chunk_overlap_tokens / 1.3))
            tail = " ".join(tail_words[-tail_count:]) if tail_count else ""
            buf = [tail] if tail else []
            buf_tokens = _approx_token_count(tail)
        if para_tokens > chunk_size_tokens:
            # Single paragraph too large — sentence-split it.
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                sent_tokens = _approx_token_count(sent)
                if buf and buf_tokens + sent_tokens > chunk_size_tokens:
                    chunks.append("\n\n".join(buf))
                    tail_words = re.findall(r"\S+", chunks[-1])
                    tail_count = max(0, int(chunk_overlap_tokens / 1.3))
                    tail = " ".join(tail_words[-tail_count:]) if tail_count else ""
                    buf = [tail] if tail else []
                    buf_tokens = _approx_token_count(tail)
                buf.append(sent)
                buf_tokens += sent_tokens
        else:
            buf.append(para)
            buf_tokens += para_tokens
    if buf:
        chunks.append("\n\n".join(buf).strip())
    return [c for c in chunks if c]


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Source artifact generators (ported from
# guidance-for-vehicle-knowledge-base/scripts/generate-*.py)
#
# Each generator returns a list of (relpath, source_doc_id, title,
# source_category, text_body) tuples. The generator runner writes the
# text body to disk under the output root, then chunks it and adds
# rows to the manifest.
# ---------------------------------------------------------------------------


# DTC families — abbreviated subset of the legacy generate-dtc-guides.py.
# (Full 50+ codes preserved for KB richness; clipped here to the most
# common Powertrain/Body/Chassis/Network exemplars to keep the module
# under a 32 KB review threshold while still exercising every category.)
_DTC_DEFINITIONS: list[tuple[str, str, str, list[str], list[str], str]] = [
    # Powertrain (P-codes)
    ("P0010", "Intake Camshaft Position Actuator Circuit (Bank 1)", "P2",
     ["engine", "valvetrain"],
     ["Faulty VVT solenoid (45%)", "Wiring harness damage (25%)",
      "Low oil pressure (20%)", "PCM fault (10%)"],
     "Your engine's variable valve timing system has a fault. You may "
     "notice slightly rough idle or reduced fuel economy. Safe to drive "
     "— schedule service within 1-2 weeks."),
    ("P0016", "Crankshaft/Camshaft Position Correlation (Bank 1)", "P1",
     ["engine", "timing"],
     ["Stretched timing chain (40%)", "Failed VVT actuator (25%)",
      "Cam/crank sensor fault (20%)", "Oil flow restriction (15%)"],
     "Your engine's timing is out of sync. You may hear a rattle on "
     "cold start or notice reduced power. Service within 48 hours — "
     "continued driving risks engine damage."),
    ("P0101", "Mass Air Flow Sensor Range/Performance", "P2",
     ["fuel", "intake"],
     ["Dirty MAF sensor (50%)", "Air filter restriction (20%)",
      "Intake leak after MAF (20%)", "Failed MAF (10%)"],
     "Your mass airflow sensor isn't reading correctly. You might "
     "notice hesitation or poor fuel economy."),
    ("P0128", "Coolant Thermostat Below Regulating Temperature", "P3",
     ["cooling", "engine"],
     ["Stuck-open thermostat (70%)", "Coolant temp sensor fault (20%)",
      "Low coolant level (10%)"],
     "Your engine isn't reaching normal operating temperature. Fix at "
     "next service."),
    ("P0217", "Engine Coolant Over Temperature", "P0",
     ["cooling", "engine"],
     ["Coolant leak (30%)", "Failed water pump (25%)",
      "Stuck thermostat (20%)", "Radiator blockage (15%)",
      "Fan failure (10%)"],
     "Your engine is overheating. Pull over safely and turn off the "
     "engine immediately. Do not open the radiator cap."),
    ("P0299", "Turbocharger/Supercharger Underboost", "P2",
     ["turbo", "intake"],
     ["Boost leak in intercooler piping (35%)", "Wastegate stuck open (25%)",
      "Failed boost pressure sensor (20%)", "Turbo bearing wear (15%)"],
     "Your turbocharger isn't producing full boost pressure. Reduced "
     "power, especially at higher speeds."),
    ("P0301", "Cylinder 1 Misfire Detected", "P1",
     ["ignition", "fuel"],
     ["Faulty spark plug (35%)", "Failed ignition coil (30%)",
      "Clogged fuel injector (20%)", "Low compression (10%)"],
     "Cylinder 1 is misfiring. If your check engine light is flashing, "
     "reduce speed and avoid hard acceleration."),
    ("P0442", "EVAP System Small Leak Detected", "P3",
     ["emissions", "evap"],
     ["Loose gas cap (50%)", "Cracked EVAP hose (25%)",
      "Failed purge valve (15%)", "Charcoal canister crack (10%)"],
     "A small leak was detected in your fuel vapor system. Check that "
     "your gas cap is tight."),
    ("P0700", "Transmission Control System Malfunction", "P1",
     ["transmission"],
     ["Internal transmission fault (35%)", "TCM communication error (25%)",
      "Solenoid failure (20%)", "Wiring issue (15%)", "Low fluid (5%)"],
     "Your transmission control system has flagged a fault. Service "
     "within 48 hours."),
    # Body (B-codes)
    ("B0015", "Passenger Frontal Airbag Deployment Control", "P0",
     ["airbag", "restraints"],
     ["Airbag module connector fault (35%)",
      "Passenger seat sensor (25%)",
      "Airbag control module (20%)", "Wiring harness (20%)"],
     "Your passenger airbag system has a fault — it may not deploy "
     "in a crash. Schedule immediate service."),
    ("B0028", "Driver Side Airbag Module", "P0",
     ["airbag", "restraints"],
     ["Clock spring failure (40%)", "Module connector (25%)",
      "Control unit fault (20%)", "Wiring (15%)"],
     "Your driver's side airbag has a fault. Critical safety issue."),
    ("B0100", "HVAC Blower Motor Control Circuit", "P3",
     ["hvac", "body"],
     ["Failed blower motor resistor (45%)",
      "Blower motor failure (30%)",
      "Wiring fault (15%)", "Control module (10%)"],
     "Your cabin blower motor has a fault. You may lose some or all "
     "fan speeds."),
    # Chassis (C-codes)
    ("C0040", "Right Front Wheel Speed Sensor Circuit", "P1",
     ["brakes", "abs"],
     ["Damaged sensor wiring (40%)", "Failed sensor (30%)",
      "Corroded connector (15%)", "Tone ring damage (10%)"],
     "Your right front ABS sensor has failed. ABS and stability "
     "control are disabled."),
    ("C0161", "Brake System Pressure Circuit", "P0",
     ["brakes"],
     ["Brake fluid leak (35%)", "Master cylinder failure (30%)",
      "Pressure sensor fault (20%)", "ABS modulator leak (15%)"],
     "Critical brake pressure loss detected. Pull over immediately."),
    # Network (U-codes)
    ("U0001", "High Speed CAN Communication Bus", "P1",
     ["network", "communication"],
     ["CAN bus wiring fault (35%)",
      "Failed module pulling bus down (25%)",
      "Connector corrosion (20%)", "Termination resistor (10%)"],
     "Your vehicle's main communication network has a fault. Multiple "
     "systems may be affected."),
    ("U0101", "Lost Communication with TCM", "P1",
     ["network", "transmission"],
     ["TCM failure (30%)", "CAN wiring to TCM (25%)",
      "TCM power/ground (20%)", "Connector (15%)"],
     "Communication with your transmission control module is lost."),
    ("U0121", "Lost Communication with ABS Module", "P1",
     ["network", "brakes"],
     ["ABS module failure (30%)", "CAN wiring fault (25%)",
      "Power supply to ABS (20%)", "Connector corrosion (15%)"],
     "Communication with your ABS module is lost. ABS, traction "
     "control, and stability control are all disabled."),
    # ------------------------------------------------------------------
    # Content-fill additions (2026-06-22, spec
    # 2026-06-22-adp-vkb-content-fill) — six codes referenced by the CVX
    # agent/eval surface but previously absent from the corpus. Content
    # normalized from the legacy CVX sources under
    # guidance-for-connected-vehicle-experience-on-aws/corpora/technical-reference/
    # into this template (systems + causes + driver message are
    # code-specific; diagnostic steps + repair estimate templated by
    # severity, matching the existing 17).
    # ------------------------------------------------------------------
    ("P0420", "Catalyst System Efficiency Below Threshold (Bank 1)", "P2",
     ["emissions", "exhaust", "powertrain"],
     ["Aged catalytic converter (60%)",
      "Faulty downstream O2 sensor (20%)",
      "Exhaust leak before catalyst (10%)",
      "Engine misfire damaging catalyst (5%)",
      "Incorrect or contaminated fuel (5%)"],
     "Your catalytic converter isn't cleaning exhaust gases as "
     "efficiently as it should. It won't affect how the car drives, "
     "but get it checked within a couple of weeks — especially before "
     "an emissions inspection."),
    ("P0300", "Random/Multiple Cylinder Misfire Detected", "P1",
     ["ignition", "fuel", "powertrain"],
     ["Worn spark plugs (30%)", "Ignition coil failure (20%)",
      "Fuel quality issue (20%)", "Low fuel pressure (15%)",
      "Vacuum leak (10%)", "Timing chain stretch (5%)"],
     "Your engine is misfiring across multiple cylinders. If the "
     "check engine light is flashing, pull over and stop driving — it "
     "can damage the catalytic converter. If steady, drive gently to a "
     "service center."),
    ("C0035", "Left Front Wheel Speed Sensor Circuit", "P1",
     ["brakes", "abs", "chassis"],
     ["Damaged sensor wiring (40%)", "Failed wheel speed sensor (30%)",
      "Corroded connector (15%)", "Excessive sensor air gap (10%)",
      "Damaged tone ring (5%)"],
     "Your ABS detected a problem with the left front wheel speed "
     "sensor. Regular brakes still work, but anti-lock braking and "
     "stability control are off. Avoid wet or icy roads and get it "
     "fixed within a day or two."),
    ("U0100", "Lost Communication with ECM/PCM", "P1",
     ["network", "communication", "powertrain"],
     ["CAN bus wiring fault (30%)", "ECM power/ground issue (25%)",
      "Failed ECM (20%)", "Water intrusion (15%)",
      "Aftermarket device interference (10%)"],
     "Your vehicle's main engine computer has lost communication with "
     "other systems. You may see multiple warning lights and reduced "
     "power. Get it to a service center today rather than continuing "
     "to drive."),
    ("P0171", "System Too Lean (Bank 1)", "P2",
     ["fuel", "intake", "powertrain"],
     ["Vacuum leak (40%)", "Dirty or failed MAF sensor (25%)",
      "Weak fuel pump (15%)", "Clogged fuel injector (10%)",
      "Exhaust leak before O2 sensor (10%)"],
     "Your engine is running with too much air and not enough fuel. "
     "You might notice rough idle or hesitation. Safe to drive short "
     "distances, but get it looked at this week."),
    ("B0001", "Driver Frontal Stage 1 Deployment Control", "P0",
     ["airbag", "restraints", "body"],
     ["Clock spring failure (35%)", "Airbag module connector (25%)",
      "Airbag control module fault (20%)",
      "Wiring harness damage (15%)",
      "Airbag previously deployed (5%)"],
     "Your vehicle has a critical fault with the driver's airbag — it "
     "may not deploy in a crash. Don't drive until it's inspected; "
     "arrange a tow or mobile service."),
]

_DIAGNOSTIC_STEPS = {
    "P0": "1. Verify code with freeze frame data\n"
          "2. Check related sensor wiring and connectors\n"
          "3. Test sensor output with scan tool live data\n"
          "4. Check for TSBs related to this code\n"
          "5. Perform component test per service manual",
    "P1": "1. Verify safety — is the vehicle safe to drive?\n"
          "2. Read freeze frame and all stored codes\n"
          "3. Check for obvious damage (wiring, leaks)\n"
          "4. Test affected system with scan tool\n"
          "5. Follow manufacturer diagnostic tree",
    "P2": "1. Read freeze frame data for conditions during fault\n"
          "2. Check for related codes that may indicate root cause\n"
          "3. Inspect wiring and connectors in affected circuit\n"
          "4. Test component operation with scan tool\n"
          "5. Clear code and road test to verify repair",
    "P3": "1. Verify code is current (not historical)\n"
          "2. Check for related codes\n"
          "3. Inspect obvious items (fluid levels, filters, caps)\n"
          "4. Clear code and monitor for return\n"
          "5. Address at next scheduled service if code returns",
}

_REPAIR_COSTS = {
    "P0": "$500-$3,000+ (safety-critical repairs)",
    "P1": "$200-$2,000 (urgent but not emergency)",
    "P2": "$100-$1,500 (routine repair)",
    "P3": "$50-$500 (minor or deferred)",
}


def generate_dtc_guides() -> list[tuple[str, str, str, str, str]]:
    """Return ``(relpath, source_doc_id, title, category, text)`` rows."""
    rows = []
    for code, title, severity, systems, causes, driver_msg in _DTC_DEFINITIONS:
        cause_lines = "\n".join(f"{i+1}. {c}" for i, c in enumerate(causes))
        body = (
            f"# {code} — {title}\n\n"
            f"## Summary\n"
            f"Diagnostic Trouble Code {code} indicates: {title.lower()}.\n\n"
            f"## Severity: {severity}\n"
            f"Systems affected: {', '.join(systems)}\n\n"
            f"## Common Causes (by likelihood)\n{cause_lines}\n\n"
            f"## Diagnostic Steps\n{_DIAGNOSTIC_STEPS[severity]}\n\n"
            f"## Driver Communication\n> \"{driver_msg}\"\n\n"
            f"## Repair Estimate\n{_REPAIR_COSTS[severity]}\n"
        )
        rows.append((
            f"sources/dtc-guides/dtc-{code}.md",
            f"DTC-{code}",
            f"{code} — {title}",
            "dtc_guide",
            body,
        ))
    return rows


# ---------------------------------------------------------------------------
# TSBs and Recalls
# ---------------------------------------------------------------------------

_TSBS: list[tuple[str, str, str, str, str, str]] = [
    ("2024-EN-0112", "Engine Oil Consumption Above Normal",
     "2019-2023 Chevrolet Equinox 1.5T",
     "Some vehicles may consume more than 1 quart of oil per "
     "3,000 miles due to piston ring design.",
     "Replace piston rings with updated design (GM P/N 12710344). "
     "Labor: 8.5 hours.",
     "Powertrain warranty (5yr/60k) or Customer Satisfaction "
     "Program 22-NA-189 (7yr/84k)."),
    ("2024-EN-0298", "Turbo Wastegate Rattle on Cold Start",
     "2020-2024 Ford Transit 2.0L EcoBoost",
     "Audible rattle from turbocharger area for 5-30 seconds after "
     "cold start below 40°F.",
     "Replace wastegate actuator with revised part "
     "(Ford P/N LK4Z-6K682-A). Labor: 1.2 hours.",
     "Bumper-to-bumper (3yr/36k)."),
    ("2024-TR-0445", "Harsh 1-2 Shift Under Light Throttle",
     "2021-2024 RAM ProMaster 3.6L",
     "Transmission may exhibit a firm 1-2 upshift at light throttle "
     "between 15-25 mph.",
     "Reflash TCM with updated calibration (software level AA). "
     "Labor: 0.5 hours.",
     "Powertrain warranty (5yr/60k)."),
    ("2024-BR-0567", "Rear Brake Caliper Slide Pin Seizure",
     "2020-2023 Toyota RAV4",
     "Rear brake calipers may develop seized slide pins causing "
     "uneven pad wear and brake pull.",
     "Clean and re-lubricate slide pins. Replace pins if scored. "
     "Labor: 1.0 hours per side.",
     "Bumper-to-bumper (3yr/36k) or Toyota CSP ZLR (5yr/60k)."),
    ("2024-EL-0089", "Infotainment Screen Intermittent Black",
     "2022-2024 Chevrolet Equinox",
     "Touchscreen may go black intermittently while driving. Audio "
     "continues to function.",
     "Replace infotainment display module (GM P/N 84983018). "
     "Labor: 1.5 hours.",
     "Bumper-to-bumper (3yr/36k)."),
]

_RECALLS: list[tuple[str, str, str, str, str, str, str, str]] = [
    ("24V-234", "Brake Booster Vacuum Hose May Disconnect",
     "2022-2023 Ford Transit Connect",
     "2024-02-15", "45,000",
     "The brake booster vacuum hose may disconnect from the intake "
     "manifold fitting, resulting in reduced brake assist.",
     "Dealers will install a revised hose clamp and inspect the hose "
     "for damage. Repair time: 0.5 hours.",
     "If brake pedal feels hard, pull over safely. Vehicle can still "
     "be stopped but requires significantly more pedal pressure."),
    ("24V-456", "Seat Belt Pretensioner May Not Deploy",
     "2021-2022 Chevrolet Equinox",
     "2024-04-10", "180,000",
     "Front seat belt pretensioners may not activate in a frontal "
     "collision due to a software calibration error.",
     "Dealers will update the restraints control module software. "
     "Repair time: 0.3 hours.",
     "Seat belts still function as standard 3-point belts."),
    ("24V-678", "Fuel Rail Pressure Sensor Leak",
     "2023-2024 RAM ProMaster 3.6L",
     "2024-06-01", "28,000",
     "The fuel rail pressure sensor may develop a fuel leak at the "
     "sensor-to-rail interface.",
     "Dealers will inspect and re-torque the fuel rail pressure "
     "sensor. Repair time: 0.8 hours.",
     "If you smell fuel or see fuel near the engine, do not drive."),
    ("24V-112", "Engine Cooling Fan May Not Activate",
     "2022-2024 Toyota RAV4 Hybrid",
     "2024-01-30", "67,000",
     "Engine cooling fan relay may fail in the open position, "
     "preventing the fan from activating.",
     "Dealers will replace the cooling fan relay and inspect wiring "
     "harness. Repair time: 0.5 hours.",
     "Monitor temperature gauge. If it rises above normal, turn on "
     "the heater and pull over."),
]


def generate_tsb_recalls() -> list[tuple[str, str, str, str, str]]:
    rows = []
    for tsb_id, title, applies, condition, correction, warranty in _TSBS:
        body = (
            f"# TSB {tsb_id}: {title}\n\n"
            f"**Applies to:** {applies}\n\n"
            f"## Condition\n{condition}\n\n"
            f"## Correction\n{correction}\n\n"
            f"## Warranty Coverage\n{warranty}\n"
        )
        rows.append((
            f"sources/tsb-recalls/tsb-{tsb_id}.md",
            f"TSB-{tsb_id}",
            f"TSB {tsb_id}: {title}",
            "tsb_recall",
            body,
        ))
    for camp, title, applies, date, count, defect, remedy, interim in _RECALLS:
        body = (
            f"# NHTSA Safety Recall {camp}\n\n"
            f"## {title}\n\n"
            f"**Affected Vehicles:** {applies}\n"
            f"**Date Issued:** {date}\n"
            f"**Estimated Affected:** {count} vehicles\n\n"
            f"## Defect Description\n{defect}\n\n"
            f"## Remedy\n{remedy}\n\n"
            f"## Interim Driver Guidance\n{interim}\n"
        )
        rows.append((
            f"sources/tsb-recalls/recall-{camp}.md",
            f"RECALL-{camp}",
            f"NHTSA Recall {camp}: {title}",
            "tsb_recall",
            body,
        ))
    return rows


# ---------------------------------------------------------------------------
# Owner manuals
# ---------------------------------------------------------------------------

_VEHICLES = [
    ("chevrolet-equinox-2022", "2022 Chevrolet Equinox 1.5L Turbo",
     "5W-30 Dexos1 Gen3", "6.0 qt", "DEX-COOL",
     "35 PSI", "225/65R17", "3,500 lb"),
    ("ford-transit-2023", "2023 Ford Transit 2.0L EcoBoost",
     "5W-30 Full Synthetic", "6.5 qt", "Motorcraft Orange",
     "80 PSI (rear loaded)", "235/65R16C", "7,500 lb"),
    ("ram-promaster-2022", "2022 RAM ProMaster 3.6L V6",
     "5W-20 Full Synthetic", "5.9 qt", "OAT 50/50",
     "62 PSI (rear loaded)", "225/75R16C", "6,800 lb"),
    ("toyota-rav4-2023", "2023 Toyota RAV4 2.5L",
     "0W-20 Synthetic", "4.8 qt", "Toyota Super Long Life",
     "35 PSI", "225/65R17", "3,500 lb"),
    ("ford-escape-2021", "2021 Ford Escape 1.5L EcoBoost",
     "5W-30 Full Synthetic", "5.7 qt", "Motorcraft Orange",
     "35 PSI", "225/65R17", "2,000 lb"),
]

_MAINTENANCE_INTERVALS = [
    (5000, "Oil and filter change, tire rotation, multi-point inspection"),
    (15000, "Engine air filter inspection, cabin air filter replacement"),
    (30000, "Engine air filter replacement, brake fluid test"),
    (60000, "Spark plugs (iridium), brake fluid flush, coolant flush"),
    (100000, "Major service: spark plugs, all fluids, belts, hoses"),
]


def _owner_manual_body(slug: str, name: str, oil: str, oil_cap: str,
                       coolant: str, tire_psi: str, tire_size: str,
                       tow_cap: str) -> str:
    sched = "\n".join(
        f"- {miles:,} mi: {items}" for miles, items in _MAINTENANCE_INTERVALS
    )
    return (
        f"# {name} — Owner Quick Reference\n\n"
        f"## Fluid Specifications\n"
        f"- Engine Oil: {oil}, capacity {oil_cap}\n"
        f"- Coolant: {coolant}\n"
        f"- Brake Fluid: DOT 4\n\n"
        f"## Tire Information\n"
        f"- Recommended pressure (cold): {tire_psi}\n"
        f"- Tire size: {tire_size}\n"
        f"- Rotation interval: every 5,000 miles\n\n"
        f"## Towing\n"
        f"- Maximum tow capacity: {tow_cap}\n"
        f"- Tongue weight: 10% of trailer weight\n\n"
        f"## Maintenance Schedule\n{sched}\n\n"
        f"## Warning Light Quick Reference\n"
        f"- Red oil can: stop immediately. Check oil level.\n"
        f"- Red thermometer: pull over. Engine overheating.\n"
        f"- Yellow check engine: schedule service. Flashing → reduce "
        f"speed immediately.\n"
        f"- Yellow TPMS: check tire pressures, inflate to {tire_psi}.\n\n"
        f"## Emergency Procedures\n"
        f"### Engine Overheating\n"
        f"1. Turn off A/C, turn heater to maximum\n"
        f"2. Pull over safely when possible\n"
        f"3. Let engine idle 2-3 minutes, then turn off\n"
        f"4. Wait 15 minutes before opening hood\n\n"
        f"### Brake Failure\n"
        f"1. Pump brake pedal rapidly\n"
        f"2. Apply parking brake gradually\n"
        f"3. Downshift to lower gear\n"
        f"4. Steer toward soft barriers if needed\n"
    )


_WARNING_LIGHTS_BODY = (
    "# Dashboard Warning Lights — Universal Guide\n\n"
    "## Critical (Red) — Immediate Action Required\n\n"
    "### Oil Pressure Warning\n"
    "Engine oil pressure is critically low. STOP immediately. Turn off "
    "engine. Check oil level. Risk: engine seizure within minutes.\n\n"
    "### Temperature Warning\n"
    "Engine coolant temperature is dangerously high. Pull over safely. "
    "Turn off A/C, turn on heater. Let cool 15 min.\n\n"
    "### Brake System Warning\n"
    "Brake fluid low, system pressure loss, or parking brake engaged. "
    "If pedal feels soft, stop driving.\n\n"
    "### Airbag/SRS Warning\n"
    "Supplemental restraint system fault. Airbag may not deploy in "
    "crash. Schedule immediate service.\n\n"
    "## Warning (Amber/Yellow) — Service Soon\n\n"
    "### Check Engine / MIL\n"
    "Steady: schedule service within 1-2 weeks. Flashing: active "
    "misfire — reduce speed, avoid hard acceleration, service ASAP.\n\n"
    "### ABS Warning\n"
    "Anti-lock brake system disabled. Normal brakes work. Service "
    "within 48 hours.\n\n"
    "### TPMS (Tire Pressure)\n"
    "One or more tires below recommended pressure. Check all tires "
    "including spare.\n\n"
    "### Battery/Charging\n"
    "Charging system not maintaining voltage. Drive directly to "
    "service within 20-30 minutes.\n"
)


def generate_owner_manuals() -> list[tuple[str, str, str, str, str]]:
    rows = []
    for slug, name, oil, oil_cap, coolant, psi, size, tow in _VEHICLES:
        body = _owner_manual_body(slug, name, oil, oil_cap, coolant,
                                  psi, size, tow)
        rows.append((
            f"sources/owner-manuals/{slug}.md",
            f"MANUAL-{slug.upper()}",
            f"{name} — Owner Reference",
            "owner_manual",
            body,
        ))
    rows.append((
        "sources/owner-manuals/warning-lights-universal.md",
        "MANUAL-WARNING-LIGHTS-UNIVERSAL",
        "Universal Dashboard Warning Lights Guide",
        "owner_manual",
        _WARNING_LIGHTS_BODY,
    ))
    return rows


# ---------------------------------------------------------------------------
# Parts catalog (narrative form for KB ingest)
# ---------------------------------------------------------------------------

_PARTS_CATEGORIES: list[tuple[str, list[tuple[str, str, str, str]]]] = [
    ("brakes", [
        ("BRK-FP-001", "Front Brake Pad Set (Ceramic)",
         "$45-$189", "ACDelco"),
        ("BRK-FP-002", "Front Brake Pad Set (Semi-Metallic)",
         "$35-$95", "Wagner"),
        ("BRK-RT-001", "Front Brake Rotor", "$55-$145", "ACDelco"),
        ("BRK-CL-001", "Brake Caliper (Reman)", "$85-$250", "Cardone"),
        ("BRK-FL-001", "Brake Fluid DOT 4 (1L)", "$8-$18", "Valvoline"),
    ]),
    ("engine", [
        ("ENG-OIL-001", "Full Synthetic 5W-30 (5qt)",
         "$28-$45", "Mobil 1"),
        ("ENG-FLT-001", "Oil Filter", "$8-$22", "Fram"),
        ("ENG-SPK-001", "Spark Plug (Iridium)", "$8-$18", "NGK"),
        ("ENG-WP-001", "Water Pump", "$85-$280", "GMB"),
        ("ENG-ALT-001", "Alternator (Reman)", "$180-$450", "Denso"),
    ]),
    ("electrical", [
        ("ELC-BAT-001", "Battery (Group 48, 700 CCA)",
         "$120-$220", "Interstate"),
        ("ELC-O2-001", "O2 Sensor (Upstream)", "$45-$180", "Denso"),
        ("ELC-MAF-001", "Mass Air Flow Sensor", "$85-$280", "Denso"),
    ]),
    ("suspension", [
        ("SUS-STR-001", "Front Strut Assembly (Complete)",
         "$150-$380", "Monroe"),
        ("SUS-BRG-001", "Wheel Bearing & Hub Assembly (Front)",
         "$85-$250", "Timken"),
    ]),
    ("hvac", [
        ("HVC-CAB-001", "Cabin Air Filter", "$12-$30", "Fram"),
        ("HVC-CMP-001", "A/C Compressor (Reman)",
         "$280-$650", "Denso"),
    ]),
]


def generate_parts_catalog() -> list[tuple[str, str, str, str, str]]:
    """Emit one narrative document per parts category for KB-friendly ingest.

    The original ``generate-parts-catalog.py`` produced a single
    ``parts_catalog.json``. For Bedrock KB ingestion we produce
    per-category markdown narratives so chunking respects category
    boundaries.
    """
    rows = []
    for category, parts in _PARTS_CATEGORIES:
        lines = [f"# Parts Catalog: {category.title()}\n"]
        lines.append(
            f"This category covers {len(parts)} commonly-stocked "
            f"parts in the {category} domain. Pricing reflects fleet "
            f"tier-1/tier-2/tier-3 ranges (USD).\n"
        )
        for pn, desc, price, supplier in parts:
            lines.append(
                f"## {pn} — {desc}\n"
                f"- Price range: {price}\n"
                f"- Supplier: {supplier}\n"
                f"- Warranty: 24 months (Reman parts: 12 months)\n"
                f"- Compatible makes: Chevrolet, Ford, RAM, Toyota\n"
            )
        rows.append((
            f"sources/parts-catalog/{category}.md",
            f"PARTS-{category.upper()}",
            f"Parts Catalog — {category.title()}",
            "parts_catalog",
            "\n".join(lines),
        ))
    return rows


# ---------------------------------------------------------------------------
# Service network
# ---------------------------------------------------------------------------

_SERVICE_CENTERS = [
    ("Rush Truck Center — Dallas", "Dallas", "TX",
     "fleet-service", ["Chevrolet", "Ford", "RAM"]),
    ("Penske Truck Leasing — Chicago", "Chicago", "IL",
     "fleet-service", ["Ford", "RAM", "Chevrolet"]),
    ("Ryder Maintenance — Atlanta", "Atlanta", "GA",
     "fleet-service", ["Ford", "RAM", "Toyota"]),
    ("Hendrick Chevrolet — Charlotte", "Charlotte", "NC",
     "dealer", ["Chevrolet"]),
    ("AutoNation Ford — Denver", "Denver", "CO",
     "dealer", ["Ford"]),
    ("Larry H. Miller Toyota — Salt Lake City", "Salt Lake City", "UT",
     "dealer", ["Toyota"]),
    ("Galpin Ford — Los Angeles", "Los Angeles", "CA",
     "dealer", ["Ford"]),
    ("Longo Toyota — Los Angeles", "Los Angeles", "CA",
     "dealer", ["Toyota"]),
    ("Firestone Complete Auto Care — Miami", "Miami", "FL",
     "independent", ["Chevrolet", "Ford", "RAM", "Toyota"]),
    ("Jiffy Lube — Seattle", "Seattle", "WA",
     "quick-service", ["Chevrolet", "Ford", "RAM", "Toyota"]),
    ("Caliber Collision — Denver", "Denver", "CO",
     "body-shop", ["Chevrolet", "Ford", "RAM", "Toyota"]),
]

_CAPABILITIES = {
    "fleet-service": "oil-change, brakes, tires, transmission, engine, "
                     "electrical, hvac, suspension, diagnostics, "
                     "fleet-maintenance-program",
    "dealer": "oil-change, brakes, tires, transmission, engine, "
              "electrical, hvac, suspension, diagnostics, "
              "warranty-repair, recall-service, body-work",
    "independent": "oil-change, brakes, tires, electrical, hvac, "
                   "suspension, diagnostics",
    "quick-service": "oil-change, tires, filters, wipers, battery",
    "body-shop": "body-work, paint, glass, dent-repair, "
                 "frame-straightening",
}


def generate_service_network() -> list[tuple[str, str, str, str, str]]:
    rows = []
    # One overview document grouping all centers by type.
    by_type: dict[str, list] = {}
    for name, city, state, ctype, brands in _SERVICE_CENTERS:
        by_type.setdefault(ctype, []).append((name, city, state, brands))
    for ctype, centers in by_type.items():
        lines = [f"# Service Network: {ctype.replace('-', ' ').title()}\n"]
        lines.append(
            f"Capabilities: {_CAPABILITIES[ctype]}\n"
            f"Number of centers in this tier: {len(centers)}\n"
        )
        for name, city, state, brands in centers:
            lines.append(
                f"## {name}\n"
                f"- Location: {city}, {state}\n"
                f"- Brands serviced: {', '.join(brands)}\n"
                f"- Type: {ctype}\n"
            )
        rows.append((
            f"sources/service-network/{ctype}.md",
            f"NETWORK-{ctype.upper()}",
            f"Service Network — {ctype.replace('-', ' ').title()}",
            "service_network",
            "\n".join(lines),
        ))
    return rows


# ---------------------------------------------------------------------------
# Service policy
# ---------------------------------------------------------------------------

_SERVICE_POLICY_DOCS: list[tuple[str, str, str]] = [
    ("warranty-coverage-matrix",
     "Warranty Coverage Matrix",
     "# Warranty Coverage Matrix\n\n"
     "## Standard Coverage (New Vehicle)\n\n"
     "- Bumper-to-Bumper: 3 years / 36,000 mi — all components except "
     "wear items\n"
     "- Powertrain: 5 years / 60,000 mi — engine, transmission, "
     "transfer case, drive axles\n"
     "- Emissions (Federal): 8 years / 80,000 mi — catalytic "
     "converter, ECM/PCM, O2 sensors\n"
     "- Emissions (CARB states): 15 years / 150,000 mi\n"
     "- Corrosion (perforation): 6 years / unlimited\n"
     "- EV/Hybrid Battery: 8 years / 100,000 mi — battery below "
     "70% capacity\n"
     "- EV/Hybrid Powertrain: 8 years / 100,000 mi — electric motor, "
     "inverter, onboard charger\n\n"
     "## Wear Items (NOT covered under warranty)\n\n"
     "- Brake pads: 30,000-70,000 mi\n"
     "- Tires: 40,000-60,000 mi\n"
     "- Wiper blades: 6-12 months\n"
     "- Light bulbs: varies\n"
     "- Filters (air, cabin): 15,000-30,000 mi\n\n"
     "## Fleet Extended Coverage Options\n\n"
     "- Fleet Basic: 5 years / 100,000 mi, $100 deductible — "
     "powertrain + A/C + electrical\n"
     "- Fleet Plus: 6 years / 125,000 mi, $50 deductible — basic + "
     "suspension + steering + brakes\n"
     "- Fleet Premium: 7 years / 150,000 mi, $0 deductible — "
     "comprehensive (excludes wear items)\n"),
    ("labor-rates-by-region",
     "Authorized Service Center Labor Rates",
     "# Labor Rates by Region (2024)\n\n"
     "- Northeast (NY, NJ, CT, MA): $165/hr standard, $135/hr fleet, "
     "$225/hr emergency\n"
     "- Southeast (FL, GA, NC, SC): $140/hr standard, $115/hr fleet, "
     "$195/hr emergency\n"
     "- Midwest (IL, OH, MI, IN): $145/hr standard, $120/hr fleet, "
     "$200/hr emergency\n"
     "- Southwest (TX, AZ, NM): $150/hr standard, $125/hr fleet, "
     "$210/hr emergency\n"
     "- West Coast (CA, WA, OR): $175/hr standard, $145/hr fleet, "
     "$240/hr emergency\n"
     "- Mountain (CO, UT, MT): $140/hr standard, $115/hr fleet, "
     "$195/hr emergency\n\n"
     "## Fleet Discount Eligibility\n"
     "- Minimum 10 vehicles enrolled in fleet program\n"
     "- All vehicles must have current maintenance records\n"
     "- Discount applies to labor only (parts at standard pricing)\n"
     "- Emergency rate applies outside 7am-7pm M-F\n\n"
     "## Mobile Service Rates\n"
     "- Dispatch fee: $75 (waived for P0 escalations)\n"
     "- Labor: standard rate + 15%\n"
     "- Available for: oil changes, tire rotation, battery, minor "
     "electrical\n"),
    ("escalation-playbook",
     "Escalation Playbook — When and How to Escalate",
     "# Escalation Playbook\n\n"
     "## Decision Matrix\n\n"
     "- Airbag fault (B0001-B0099): P0 — auto-escalate, voice "
     "callback + roadside\n"
     "- Brake system critical (C0161): P0 — auto-escalate\n"
     "- Engine overheating (P0217): P0 — auto-escalate\n"
     "- Driver requests human: any severity — chat transfer\n"
     "- ABS disabled (C0035-C0265): P1 — offer escalation\n"
     "- Flashing CEL (active misfire): P1 — offer escalation\n"
     "- Steady CEL (emissions): P2 — schedule service\n"
     "- TPMS warning (1-3 PSI low): P3 — inform only\n\n"
     "## Escalation Channels by Priority\n\n"
     "### P0 — Critical (< 5 min response)\n"
     "1. AI agent immediately escalates (no driver confirmation)\n"
     "2. Connect outbound voice call to driver's phone\n"
     "3. Roadside assistance dispatched simultaneously\n"
     "4. P0 queue: 24/7, target answer time < 30 seconds\n\n"
     "### P1 — Urgent (< 15 min response)\n"
     "1. AI agent offers escalation to driver\n"
     "2. If accepted: connect chat transfer with full context\n"
     "3. P1 queue: 24/7, target answer time < 2 minutes\n\n"
     "## Context Handoff Requirements\n\n"
     "When escalating, the AI agent MUST provide:\n"
     "- Vehicle ID and VIN\n"
     "- Active DTC codes with severity\n"
     "- Conversation summary (last 3-5 exchanges)\n"
     "- Triage classification and reasoning\n"
     "- Driver's stated concern in their own words\n"),
    ("parts-coverage-tiers",
     "Parts Coverage Tiers and Pricing",
     "# Parts Coverage Tiers\n\n"
     "## Tier 1: OEM Genuine\n"
     "- Manufacturer original parts\n"
     "- Required for warranty claims\n"
     "- Highest cost, longest part warranty (24 months)\n"
     "- Required for: safety systems, emissions, powertrain under "
     "warranty\n\n"
     "## Tier 2: OEM Equivalent\n"
     "- Certified aftermarket meeting OEM specifications\n"
     "- 15-25% cost savings vs Tier 1\n"
     "- Acceptable for: non-warranty repairs, fleet standard "
     "maintenance\n\n"
     "## Tier 3: Fleet Standard\n"
     "- Quality aftermarket parts\n"
     "- 30-50% cost savings vs Tier 1\n"
     "- Acceptable for: wear items, maintenance parts, non-critical "
     "components\n"),
]


def generate_service_policy() -> list[tuple[str, str, str, str, str]]:
    rows = []
    for slug, title, body in _SERVICE_POLICY_DOCS:
        rows.append((
            f"sources/service-policy/{slug}.md",
            f"POLICY-{slug.upper()}",
            title,
            "service_policy",
            body,
        ))
    return rows


# ---------------------------------------------------------------------------
# EV-startup narrative seeds (charging + OTA) — required by schema enum.
# Group 5 KB extensions will replace these with summaries derived from
# real charging_sessions / ota_campaigns parquet output.
# ---------------------------------------------------------------------------

_CHARGING_NARRATIVES: list[tuple[str, str, str]] = [
    ("home-l2-baseline",
     "Home L2 Charging Baseline",
     "# Home L2 Charging — Baseline Behavior\n\n"
     "Home Level-2 charging accounts for ~56% of all charging "
     "sessions on the platform. Typical session: 4-8 hours, 7-11.5 "
     "kW peak power, 30-80 kWh delivered. Home sessions are private "
     "by default — latitude/longitude are not recorded. Cost basis "
     "is the customer's residential utility rate, defaulting to "
     "~$0.13/kWh. Interrupted home sessions are dominated by "
     "user_unplug events; station_fault and network_drop are rare.\n"),
    ("public-dc-fast-network-mix",
     "Public DC Fast Charging — Network Mix",
     "# Public DC Fast Charging — Network Mix\n\n"
     "DC Fast charging accounts for ~25% of sessions. The four "
     "primary networks: Tesla Supercharger (~20%, NACS connector), "
     "Electrify America (~20%, CCS1), EVgo (~10%, CCS1), "
     "ChargePoint (~10%, J1772). Typical session: 15-60 minutes, "
     "50-250 kW peak, 20-80 kWh delivered. Cost basis ~$0.45/kWh. "
     "Interrupt mix on public stations is more diverse: ~20% "
     "station_fault, ~15% vehicle_fault, ~10% network_drop.\n"),
    ("charging-issue-triage",
     "Charging Issue Triage Patterns",
     "# Charging Issue Triage\n\n"
     "Common customer-reported charging issues and their typical "
     "root causes:\n\n"
     "- 'Charge port won't engage': inspect connector pins, lubricate "
     "latch, check pilot signal wiring. ~70% resolved at first visit.\n"
     "- 'Charging stops at low SoC': review thermal logs — cold "
     "soak below 0°C trips battery thermal limits.\n"
     "- 'Slow public DC fast charging': confirm network and connector "
     "match (NACS vs CCS1), check station max power vs vehicle max "
     "charging rate.\n"
     "- 'Range loss after charging': linked to state-of-health "
     "decline; trigger SoH diagnostic if ≥5% drop in 30 days.\n"),
]

_OTA_NARRATIVES: list[tuple[str, str, str]] = [
    ("ota-rollout-typical",
     "OTA Campaign — Typical Rollout Curve",
     "# OTA Campaign Rollout — Typical Curve\n\n"
     "Standard OTA campaigns reach ~60% adoption within 7 days of "
     "dispatch and ~85% within 30 days. Failure rate "
     "(download_failed + install_failed combined) targets 7%. "
     "Decline-by-user rate ~3%. Rollback rate <0.5%. Phased rollout "
     "uses canary cohort (5%) → broad (50%) → full (100%) over "
     "14-21 days for standard categories.\n\n"
     "Categories and severity mix:\n"
     "- safety_recall: 10% of campaigns; 40% critical / 40% high; "
     "no phased rollout (immediate broad release)\n"
     "- security_patch: 20%; 30% high / 50% medium\n"
     "- bug_fix: 30%; 50% medium / 30% low\n"
     "- feature_add: 30%; 50% low / 30% medium\n"
     "- performance: 10%; 60% low / 30% medium\n"),
    ("ota-failure-modes",
     "OTA Failure Modes and Remediation",
     "# OTA Failure Modes\n\n"
     "Top failure reasons for OTA dispatches:\n\n"
     "- download_failed: weak cellular/WiFi during dispatch window. "
     "Auto-retry next dispatch window. ~75% resolve on retry.\n"
     "- install_failed: insufficient battery (<25% SoC) or vehicle "
     "in motion. Auto-retry when conditions met.\n"
     "- declined_by_user: customer postponed via in-vehicle prompt. "
     "Re-prompt after 7 days.\n"
     "- rolled_back: post-install regression detected by health "
     "monitor. Auto-rollback to prior firmware. Escalate to "
     "engineering for root-cause review.\n\n"
     "Linked customer-experience signal: customers with one or more "
     "install_failed dispatches in the last 30 days have a "
     "higher-than-baseline rate of mobile_app_charging_issue "
     "interactions in the following 60 days.\n"),
]


def generate_ev_narratives() -> list[tuple[str, str, str, str, str]]:
    rows = []
    for slug, title, body in _CHARGING_NARRATIVES:
        rows.append((
            f"sources/charging-narratives/{slug}.md",
            f"CHARGE-{slug.upper()}",
            title,
            "charging_narrative",
            body,
        ))
    for slug, title, body in _OTA_NARRATIVES:
        rows.append((
            f"sources/ota-rollout-summaries/{slug}.md",
            f"OTA-{slug.upper()}",
            title,
            "ota_rollout_summary",
            body,
        ))
    return rows


# ---------------------------------------------------------------------------
# Runner — orchestrates artifact emission + manifest construction
# ---------------------------------------------------------------------------


_GENERATORS: list[tuple[str, callable]] = [
    ("dtc_guides", generate_dtc_guides),
    ("tsb_recalls", generate_tsb_recalls),
    ("owner_manuals", generate_owner_manuals),
    ("parts_catalog", generate_parts_catalog),
    ("service_network", generate_service_network),
    ("service_policy", generate_service_policy),
    ("ev_narratives", generate_ev_narratives),
]


def _resolve_s3_uri(s3_root: str | None, relpath: str) -> str:
    """Build the S3 URI for a given source artifact relpath."""
    if not s3_root:
        return f"file://{relpath}"
    if not s3_root.startswith("s3://"):
        return f"file://{relpath}"
    root = s3_root.rstrip("/")
    return f"{root}/{relpath}"


def run(
    *,
    output_root: Path | str,
    s3_root: str | None = None,
    region: str = "us-east-1",
    chunk_size_tokens: int = DEFAULT_CHUNK_SIZE_TOKENS,
    chunk_overlap_tokens: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    upload: bool = False,
) -> dict:
    """Generate all KB artifacts and the chunk manifest.

    Parameters
    ----------
    output_root
        Local directory under which ``sources/`` and ``manifest.json``
        are written. Created if missing.
    s3_root
        Optional ``s3://bucket/prefix`` used to populate each chunk's
        ``s3_uri`` column. Defaults to the staging path declared in
        ``DEFAULT_STAGING_S3_ROOT``.
    upload
        When True, upload the local ``output_root`` tree to ``s3_root``
        after generation. Requires boto3 + AWS credentials.

    Returns
    -------
    dict
        Manifest summary (also written to ``<output_root>/manifest.json``).
    """
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if s3_root is None:
        s3_root = DEFAULT_STAGING_S3_ROOT

    # Sanity-check the schema column contract before doing any work —
    # if schema.yaml drifts, surface the failure here rather than
    # silently emitting a manifest that won't ingest.
    schema = sl.load_schema("vehicle_knowledge_base", kind="product")
    table = schema.first_table()
    if table.storage_format != "documents":
        raise RuntimeError(
            f"vehicle_knowledge_base.storage_format must be 'documents', "
            f"got {table.storage_format!r}"
        )
    required_cols = {
        "chunk_id", "source_doc_id", "source_category", "title",
        "chunk_index", "chunk_text", "chunk_size_tokens",
        "chunk_overlap_tokens", "embedding_model", "s3_uri",
        "language", "indexed_at",
    }
    have = {c.name for c in table.columns}
    missing = required_cols - have
    if missing:
        raise RuntimeError(
            f"schema.yaml is missing required columns: "
            f"{sorted(missing)}"
        )

    enum_values = set(table.column_by_name("source_category").enum_values or ())

    started = time.time()
    chunks: list[dict] = []
    artifact_records: list[dict] = []
    indexed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for gen_name, gen_fn in _GENERATORS:
        for relpath, source_doc_id, title, category, body in gen_fn():
            if category not in enum_values:
                raise RuntimeError(
                    f"{gen_name} produced an unsupported source_category "
                    f"{category!r}; allowed values: {sorted(enum_values)}"
                )
            local_path = output_root / relpath
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(body, encoding="utf-8")
            # R2 (spec 2026-06-22-adp-vkb-content-fill): emit a Bedrock KB
            # metadata sidecar carrying source_category so persona-scoped
            # consumers (CVX PERSONA_KB_FILTERS) can filter retrievals.
            # Bedrock natively treats `<file>.metadata.json` as metadata, not
            # a standalone document. The value vocabulary is the schema enum
            # (already underscored — `dtc_guide`, `tsb_recall`, ...) which
            # matches the CVX filter contract exactly.
            sidecar_path = local_path.with_name(local_path.name + ".metadata.json")
            sidecar_path.write_text(
                json.dumps(
                    {"metadataAttributes": {"source_category": category}},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            artifact_records.append({
                "relpath": relpath,
                "source_doc_id": source_doc_id,
                "title": title,
                "category": category,
                "size_bytes": local_path.stat().st_size,
                "sha256": _sha256_path(local_path),
            })
            s3_uri = _resolve_s3_uri(s3_root, relpath)
            for idx, chunk_text in enumerate(_split_into_chunks(
                body,
                chunk_size_tokens=chunk_size_tokens,
                chunk_overlap_tokens=chunk_overlap_tokens,
            )):
                chunks.append({
                    "chunk_id": _chunk_id(source_doc_id, idx),
                    "source_doc_id": source_doc_id,
                    "source_category": category,
                    "title": title,
                    "chunk_index": idx,
                    "chunk_text": chunk_text,
                    "chunk_size_tokens": _approx_token_count(chunk_text),
                    "chunk_overlap_tokens": chunk_overlap_tokens,
                    "embedding_model": embedding_model,
                    "s3_uri": s3_uri,
                    "language": DEFAULT_LANGUAGE,
                    "indexed_at": indexed_at,
                })

    elapsed = round(time.time() - started, 3)
    by_category: dict[str, int] = {}
    for c in chunks:
        by_category[c["source_category"]] = by_category.get(
            c["source_category"], 0) + 1

    manifest = {
        "product": "vehicle_knowledge_base",
        "table": "vehicle_knowledge_base",
        "storage_format": "documents",
        "generated_at_utc": indexed_at,
        "elapsed_seconds": elapsed,
        "embedding_model": embedding_model,
        "chunk_size_tokens": chunk_size_tokens,
        "chunk_overlap_tokens": chunk_overlap_tokens,
        "s3_root": s3_root,
        "artifact_count": len(artifact_records),
        "chunk_count": len(chunks),
        "chunks_by_category": by_category,
        "artifacts": artifact_records,
        "chunks": chunks,
        "bedrock_kb_status": "DEFERRED_TO_GROUP_5",
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    summary = {
        "product": "vehicle_knowledge_base",
        "output_root": str(output_root),
        "s3_root": s3_root,
        "artifact_count": len(artifact_records),
        "chunk_count": len(chunks),
        "chunks_by_category": by_category,
        "elapsed_seconds": elapsed,
        "manifest_path": str(manifest_path),
        "uploaded": False,
    }

    if upload:
        if not s3_root or not s3_root.startswith("s3://"):
            raise ValueError(
                "upload=True requires s3_root to be an s3:// URI"
            )
        # Lazy import — keep boto3 off the import path for offline use.
        sys.path.insert(0, str(_LIB))
        from product_generator import upload_to_s3  # noqa: E402
        files_uploaded = upload_to_s3(
            output_root, s3_root, region=region
        )
        summary["uploaded"] = True
        summary["files_uploaded"] = files_uploaded

    return summary


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate vehicle_knowledge_base text/PDF artifacts "
                    "and chunk manifest for Bedrock KB ingestion "
                    "(deferred to Group 5)."
    )
    p.add_argument(
        "--output-root", default="curated/vehicle_knowledge_base",
        help="Local directory for artifacts + manifest "
             "(default: curated/vehicle_knowledge_base).",
    )
    p.add_argument(
        "--s3-root", default=None,
        help=f"s3://bucket/prefix used in each chunk's s3_uri. "
             f"Defaults to {DEFAULT_STAGING_S3_ROOT}.",
    )
    p.add_argument(
        "--region", default="us-east-1",
        help="AWS region for S3 upload (default: us-east-1).",
    )
    p.add_argument(
        "--upload", action="store_true",
        help="Upload generated artifacts to s3_root after generation.",
    )
    p.add_argument(
        "--chunk-size-tokens", type=int,
        default=DEFAULT_CHUNK_SIZE_TOKENS,
        help=f"Approx tokens per chunk "
             f"(default: {DEFAULT_CHUNK_SIZE_TOKENS}).",
    )
    p.add_argument(
        "--chunk-overlap-tokens", type=int,
        default=DEFAULT_CHUNK_OVERLAP_TOKENS,
        help=f"Approx token overlap between adjacent chunks "
             f"(default: {DEFAULT_CHUNK_OVERLAP_TOKENS}).",
    )
    p.add_argument(
        "--embedding-model", default=DEFAULT_EMBEDDING_MODEL,
        help=f"Bedrock embedding model id "
             f"(default: {DEFAULT_EMBEDDING_MODEL}).",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv else None)
    summary = run(
        output_root=args.output_root,
        s3_root=args.s3_root,
        region=args.region,
        chunk_size_tokens=args.chunk_size_tokens,
        chunk_overlap_tokens=args.chunk_overlap_tokens,
        embedding_model=args.embedding_model,
        upload=args.upload,
    )
    # Compact summary on stdout — full manifest lives in manifest.json
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
