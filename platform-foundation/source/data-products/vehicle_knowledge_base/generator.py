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
    # P2, NOT P0, despite being a restraints code. CMS's deterministic health
    # scorer classifies B1234 as MEDIUM (-8), and the sibling airbag codes above
    # are P0 because they are deployment-control faults — the airbag may fail to
    # fire. An occupant-classification mismatch is different in kind: the
    # restraint works, but the system cannot reliably decide which occupant it is
    # protecting. Grading it P0 here would have the knowledge base tell the agent
    # "critical, immediate service" while the classifier says MEDIUM, and the
    # classifier is the authority on severity — see
    # ~/.kiro/steering/agentic-tiers.md on safety classification staying
    # deterministic. Verified mapping from codes present in both systems:
    # P0217 CRITICAL -> P0, P0420 MEDIUM -> P2.
    ("B1234", "Occupant Classification System Mismatch", "P2",
     ["airbag", "restraints", "seats"],
     ["Occupant classification sensor/mat fault (40%)",
      "Seat wiring or connector damage (25%)",
      "Calibration lost after seat service or replacement (20%)",
      "Restraints control module fault (15%)"],
     "Your front passenger seat's occupant-classification system cannot "
     "reliably tell what is in the seat, so the passenger airbag may not be "
     "enabled or suppressed as intended. The airbag warning light or passenger "
     "airbag status indicator may be lit or show the wrong state. The vehicle "
     "is safe to drive and other restraints are unaffected — schedule service "
     "to have the seat sensor and calibration checked."),
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
# Parts catalog (per-SKU KB documents derived from adp_parts_domain seed)
# ---------------------------------------------------------------------------
# G5.T1 (spec 2026-08-26-adp-dealer-domain, Group 5): replaced the prior
# category-narrative approach (5 docs) with one document per SKU (~500 docs).
#
# SOURCE DECISION: reads directly from
# ``scripts/parts_seed_fixtures/parts_catalog.json`` (the canonical Group 3
# fixture, 586 records).  A prior version imported ``generate_catalog()``
# from ``seed_parts_catalog.py`` because the fixture had only 86 records;
# that threshold was well below the >= 400-document requirement.  The fixture
# was regenerated as part of the G5.T1 hand-off (2026-09-09) and now contains
# 586 SKUs, comfortably above the >= 400 threshold.  Reading the fixture
# directly honours the Accept literal ("reads from
# platform-foundation/scripts/parts_seed_fixtures/*.json") and avoids the
# circular import path that caused occasional sys.path side-effects.
#
# COMPATIBILITY CONTRACT (R2d, three live CVX consumers):
#   The sidecar value ``source_category: "parts_catalog"`` is written by
#   run() in this module (unchanged code path at ~line 2620).  This function
#   returns the literal string ``"parts_catalog"`` (underscore, not hyphen)
#   as its fourth tuple element, exactly as the prior version did.  Do NOT
#   alter that value.  The S3 prefix ``sources/parts-catalog/`` (hyphenated)
#   is independent by design — the two are NOT unified.
#
# IDEMPOTENCY: filenames are deterministic (sku-<sanitised_part_number>.md),
# so re-runs overwrite in place.


def _sanitise_part_number(pn: str) -> str:
    """Return a filesystem-safe slug from a part number string."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", pn).lower()


def _generate_sku_body(rec: dict) -> str:
    """Build a markdown document body for a single parts-catalog SKU record."""
    lines = [
        f"# Parts Catalog SKU: {rec['part_number']}\n",
        f"**Part Number:** {rec['part_number']}  ",
        f"**Terminology:** {rec['part_terminology_name']} (`{rec['part_terminology_id']}`)  ",
        f"**Brand ID:** {rec['brand_aaia_id']}  ",
        f"**Description:** {rec['description']}\n",
    ]
    lines.append("## Packaging")
    lines.append(
        f"- Unit of measure: {rec['package_unit_of_measure']}"
        f" (qty per application: {rec['quantity_per_application']})"
    )
    lines.append(f"- Package weight: {rec['package_weight']} kg")
    lines.append(
        f"- Dimensions (H×W×L): "
        f"{rec['package_height']}×{rec['package_width']}×{rec['package_length']} cm"
    )
    if rec.get("hazardous_material_code"):
        lines.append(f"- **Hazardous material code:** {rec['hazardous_material_code']}")
    if rec.get("superseded_part_number"):
        lines.append(
            f"\n**Supersedes:** {rec['superseded_part_number']}  "
            "(Refer to interchange table for full chain.)"
        )
    attrs = rec.get("extended_attributes") or []
    if attrs:
        lines.append("\n## Extended Attributes")
        for attr in attrs:
            lines.append(
                f"- {attr['attribute_name']}"
                f" (`{attr['attribute_id']}`): {attr['attribute_value']}"
            )
    lines.append(
        f"\n**Access channel:** {rec.get('access_channel', 'franchise')}  "
        f"**Tenant:** {rec.get('tenant_id', 'dms-reference')}"
    )
    return "\n".join(lines)


def _load_seed_catalog() -> list[dict]:
    """Load parts catalog records from scripts/parts_seed_fixtures/parts_catalog.json.

    Reads the canonical Group 3 fixture (586 records) directly, satisfying
    the G5.T1 Accept literal: "reads from platform-foundation/scripts/
    parts_seed_fixtures/*.json".  The import of seed_parts_catalog.generate_catalog()
    was the previous approach when the fixture had only 86 records; that
    comment's rationale is now superseded — see the SOURCE DECISION block above.
    """
    _fixture = Path(__file__).resolve().parents[3] / "scripts" / "parts_seed_fixtures" / "parts_catalog.json"
    if not _fixture.exists():
        raise FileNotFoundError(
            f"parts_catalog.json fixture not found at {_fixture}. "
            "Run seed_parts_catalog.py --dry-run > scripts/parts_seed_fixtures/parts_catalog.json "
            "to regenerate."
        )
    import json as _json  # noqa: PLC0415
    return _json.loads(_fixture.read_text(encoding="utf-8"))


def generate_parts_catalog() -> list[tuple[str, str, str, str, str]]:
    """Emit one markdown document per SKU (~500 docs) for KB-friendly ingest.

    G5.T1 supersession of the prior 5-category-narrative approach.

    COMPATIBILITY CONTRACT (R2d):
      The fourth element of every tuple is exactly ``"parts_catalog"``
      (underscore).  The run() sidecar writer at ~line 2620 of this module
      passes that value through unchanged to the ``.metadata.json`` file.
      Three live CVX consumers filter on ``source_category = "parts_catalog"``;
      any drift in this value silently breaks all three.
    """
    records = _load_seed_catalog()
    rows: list[tuple[str, str, str, str, str]] = []
    for rec in records:
        slug = _sanitise_part_number(rec["part_number"])
        relpath = f"sources/parts-catalog/sku-{slug}.md"
        source_doc_id = f"PARTS-SKU-{rec['part_number']}"
        title = f"Parts Catalog: {rec['part_terminology_name']} — {rec['part_number']}"
        body = _generate_sku_body(rec)
        rows.append((relpath, source_doc_id, title, "parts_catalog", body))
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
# Dealer bulletin seeds — urgent, routine, and informational bulletins.
# G4.T2 (adp-dealer-domain spec): two new KB source categories added here.
# ---------------------------------------------------------------------------

_DEALER_BULLETINS: list[tuple[str, str, str]] = [
    # Urgent / safety recall bulletins (12)
    ("db-urgent-brake-fluid-contamination",
     "Urgent: Brake Fluid Contamination — Immediate Service Required",
     "# Urgent Dealer Bulletin: Brake Fluid Contamination\n\n"
     "**Type:** Urgent — Immediate Service Required\n"
     "**Program:** DB-2024-BR-001\n\n"
     "## Summary\n\n"
     "Certain vehicles may have received brake fluid that does not meet "
     "minimum boiling-point specifications during production. Affected "
     "vehicles exhibit reduced stopping distance and premature ABS "
     "activation under hard braking.\n\n"
     "## Affected Population\n\n"
     "Model years 2022–2024 with brake fluid fill date codes "
     "DMS-BR-0041 through DMS-BR-0055. Verify via VIN lookup in "
     "service portal.\n\n"
     "## Required Action\n\n"
     "1. Flush and replace brake fluid using approved fluid "
     "(part DMS-PT-00441)\n"
     "2. Inspect brake calipers for corrosion — replace if pitting "
     "present (part DMS-PT-00442)\n"
     "3. Test pedal feel under simulated stop conditions before "
     "returning vehicle\n\n"
     "## Warranty Consideration\n\n"
     "Covered under emission + powertrain warranty per DTC C0035 "
     "warranty claim process. Labor op: LBR-BRAKE-FLUID-FLUSH-001.\n\n"
     "## Parts Required\n\n"
     "- DMS-PT-00441 Brake Fluid DOT 4+ 1L (qty 1–2 per vehicle)\n"
     "- DMS-PT-00442 Brake Caliper Seal Kit (as needed)\n"),
    ("db-urgent-eps-software-update",
     "Urgent: Electric Power Steering Software Update",
     "# Urgent Dealer Bulletin: Electric Power Steering Software Update\n\n"
     "**Type:** Urgent\n"
     "**Program:** DB-2024-EPS-007\n\n"
     "## Summary\n\n"
     "A software defect in the EPS control module may cause intermittent "
     "loss of steering assist at highway speeds above 65 mph when "
     "ambient temperature exceeds 38°C.\n\n"
     "## Affected Vehicles\n\n"
     "Model years 2023–2024 equipped with EPS module revision "
     "DMS-VCFG-0312 through DMS-VCFG-0398.\n\n"
     "## Corrective Action\n\n"
     "Flash EPS module to software version EPS-SW-2024-R3. "
     "Reprogramming kit: DMS-PT-00318. "
     "Estimated labor: 0.8 hr.\n\n"
     "## Post-Repair Validation\n\n"
     "Perform steering feel test per validation procedure VP-EPS-2024. "
     "If steering remains heavy or unresponsive after reflash, "
     "replace EPS motor assembly (DMS-PT-00319).\n"),
    ("db-urgent-hvac-refrigerant-leak",
     "Urgent: HVAC Refrigerant Leak at Evaporator — Customer Notification Required",
     "# Urgent Dealer Bulletin: HVAC Refrigerant Leak\n\n"
     "**Type:** Urgent — Customer Notification\n"
     "**Program:** DB-2024-HVAC-003\n\n"
     "## Issue\n\n"
     "Evaporator core pinhole leaks have been reported on vehicles "
     "with build dates between 2023-Q2 and 2024-Q1. Refrigerant "
     "loss leads to reduced A/C cooling and, in enclosed spaces, "
     "potential R-1234yf exposure above OSHA PEL.\n\n"
     "## Identification\n\n"
     "Check evaporator outlet temperature differential < 5°C at "
     "max A/C setting indicates likely leak. UV dye test kit "
     "DMS-PT-00561 confirms leak location.\n\n"
     "## Repair\n\n"
     "Replace evaporator core assembly (DMS-PT-00562). "
     "Evacuate and recharge to specification: 650g ± 15g R-1234yf. "
     "Labor: 3.2 hr.\n"),
    ("db-urgent-fuel-pump-relay",
     "Urgent: Fuel Pump Relay Thermal Failure",
     "# Urgent Dealer Bulletin: Fuel Pump Relay Thermal Failure\n\n"
     "**Type:** Urgent\n"
     "**Program:** DB-2024-FP-002\n\n"
     "## Background\n\n"
     "Fuel pump relay contacts may weld under sustained high current "
     "draw in high-ambient-temperature conditions. Welded contacts "
     "leave the fuel pump energized after key-off, draining the "
     "12V battery and in rare cases causing thermal events near the "
     "fuel pump module.\n\n"
     "## Action\n\n"
     "Replace fuel pump relay (DMS-PT-00203) and inspect fuel pump "
     "module harness connector for heat damage. Replace harness "
     "if insulation cracking present (DMS-PT-00204).\n\n"
     "## Labor\n\n"
     "Relay replacement: 0.3 hr. Full inspection: 0.8 hr.\n"),
    ("db-urgent-tpms-sensor-battery-depletion",
     "Urgent: TPMS Sensor Battery Depletion — Silent Failure",
     "# Urgent Dealer Bulletin: TPMS Sensor Battery Depletion\n\n"
     "**Type:** Urgent\n"
     "**Program:** DB-2024-TPMS-004\n\n"
     "## Issue\n\n"
     "TPMS sensors (supplier batch DMS-PT-00610 through DMS-PT-00649) "
     "exhibit premature battery depletion at 30–40 months, well below "
     "the 7-year rated service life. Silent failure means the TPMS "
     "warning lamp does not illuminate — the system appears functional "
     "but tire pressure is not being monitored.\n\n"
     "## Detection\n\n"
     "Scan TPMS module for sensors reporting battery-low status. "
     "Any sensor with < 20% reported capacity in this batch requires "
     "proactive replacement.\n\n"
     "## Replacement Part\n\n"
     "DMS-PT-00651 (universal TPMS sensor, pre-programmed for this "
     "platform). Relearn procedure: TPMS-RELEARN-2024-R1.\n"),
    ("db-urgent-abs-module-grounding",
     "Urgent: ABS Module Grounding Strap Corrosion",
     "# Urgent Dealer Bulletin: ABS Module Grounding Strap Corrosion\n\n"
     "**Type:** Urgent\n"
     "**Program:** DB-2024-ABS-006\n\n"
     "## Issue\n\n"
     "Corrosion at the ABS module chassis grounding strap increases "
     "ground resistance, causing intermittent ABS system disable "
     "warning. In cold-climate regions with road-salt use, corrosion "
     "can propagate to the module connector.\n\n"
     "## Inspection\n\n"
     "Check resistance between ABS module chassis ground and battery "
     "negative — must be ≤ 0.1 Ω. Values above 0.3 Ω indicate "
     "corrosion requiring immediate attention.\n\n"
     "## Repair\n\n"
     "Clean ground strap with wire brush and apply dielectric grease "
     "(DMS-PT-00711). Replace strap if wire gauge is reduced > 15% "
     "(DMS-PT-00712). Labor: 0.5 hr.\n"),
    ("db-urgent-ev-battery-thermal-precondition",
     "Urgent: EV Battery Thermal Preconditioning Fault in Sub-Zero Conditions",
     "# Urgent Dealer Bulletin: EV Battery Thermal Preconditioning\n\n"
     "**Type:** Urgent\n"
     "**Program:** DB-2024-EV-009\n\n"
     "## Issue\n\n"
     "In ambient temperatures below −15°C, the battery thermal "
     "management system may not complete its preconditioning cycle "
     "before the customer initiates a DC fast-charge session. "
     "Charging at sub-optimal battery temperature triggers "
     "overcurrent protection, limiting charge to 10 kW instead "
     "of the rated 150 kW.\n\n"
     "## Corrective Action\n\n"
     "Update BMS firmware to version BMS-FW-2024-R7 (part "
     "DMS-PT-00901). Estimated flash time: 22 minutes.\n\n"
     "## Customer Communication\n\n"
     "Advise customers in affected regions to pre-condition the "
     "battery remotely via the connected-vehicle app 30 minutes "
     "before DC fast charging below −10°C.\n"),
    ("db-urgent-windshield-wiper-motor",
     "Urgent: Windshield Wiper Motor Seizure at High Wash Fluid Load",
     "# Urgent Dealer Bulletin: Windshield Wiper Motor Seizure\n\n"
     "**Type:** Urgent\n"
     "**Program:** DB-2024-WW-010\n\n"
     "## Issue\n\n"
     "Wiper motor seizure has been reported when wash fluid and "
     "ice buildup combine at the wiper park position during "
     "temperatures below −5°C. The motor draws excess current "
     "and trips the wiper fuse, leaving the driver without wipers.\n\n"
     "## Prevention\n\n"
     "Apply wiper arm-to-glass anti-freeze treatment (DMS-PT-00321) "
     "during seasonal service. Replace wiper motor if resistance "
     "below rated spec (DMS-PT-00322). Labor: 0.6 hr.\n"),
    ("db-urgent-charging-port-latch-release",
     "Urgent: Charging Port Latch Release Mechanism Binding",
     "# Urgent Dealer Bulletin: Charging Port Latch Release Binding\n\n"
     "**Type:** Urgent — EV Platform\n"
     "**Program:** DB-2024-CP-011\n\n"
     "## Issue\n\n"
     "Charging port latch release actuator may bind after extended "
     "exposure to road grime and moisture, preventing plug removal "
     "without manual override. Repeated override attempts can "
     "damage the latch mechanism.\n\n"
     "## Repair\n\n"
     "Clean latch mechanism and apply EV-rated lubricant "
     "(DMS-PT-00411). If actuator is damaged, replace charging "
     "port assembly (DMS-PT-00412). Labor: 1.1 hr.\n"),
    ("db-urgent-seat-belt-pretensioner",
     "Urgent: Seat Belt Pretensioner Non-Deployment Risk",
     "# Urgent Dealer Bulletin: Seat Belt Pretensioner\n\n"
     "**Type:** Urgent — Safety Critical\n"
     "**Program:** DB-2024-SB-013\n\n"
     "## Issue\n\n"
     "Front seat belt pretensioners (lot DMS-PT-00811 through "
     "DMS-PT-00830) may exhibit a 2–4% non-deployment rate in "
     "moderate frontal crash events (25–35 mph equivalent barrier "
     "impact). Cause is a gas generant mixture issue from a "
     "specific production batch.\n\n"
     "## Action\n\n"
     "Replace both front seat belt assemblies on affected vehicles. "
     "New assembly: DMS-PT-00831. Labor: 0.9 hr per side.\n\n"
     "## Documentation\n\n"
     "Record the lot numbers of removed pretensioners on the "
     "repair order for regulatory reporting.\n"),
    ("db-urgent-coolant-bypass-valve",
     "Urgent: Engine Coolant Bypass Valve Sticking Closed",
     "# Urgent Dealer Bulletin: Coolant Bypass Valve Failure\n\n"
     "**Type:** Urgent\n"
     "**Program:** DB-2024-CO-015\n\n"
     "## Issue\n\n"
     "Coolant bypass valve (part suffix DMS-PT-00531) manufactured "
     "between 2023-08 and 2024-03 may stick in the closed position "
     "after extended highway driving. This routes all coolant through "
     "the heater core bypass, causing rapid coolant temperature rise "
     "and DTC P0217 (Engine Coolant Over Temperature) with risk of "
     "engine damage.\n\n"
     "## Action\n\n"
     "Replace bypass valve with revised part DMS-PT-00532 on all "
     "affected vehicles. Flush cooling system and refill with "
     "approved coolant (DMS-PT-00533). Labor: 1.4 hr.\n"),
    ("db-urgent-oil-separator-clogging",
     "Urgent: PCV Oil Separator Clogging — Engine Oil Dilution",
     "# Urgent Dealer Bulletin: PCV Oil Separator Clogging\n\n"
     "**Type:** Urgent\n"
     "**Program:** DB-2024-PCV-018\n\n"
     "## Issue\n\n"
     "PCV oil separator screens clog prematurely in high-idle "
     "duty-cycle fleets (delivery, rideshare). Clogged separators "
     "allow engine oil mist to enter the intake, causing oil "
     "dilution with fuel and elevated oil consumption.\n\n"
     "## Inspection Trigger\n\n"
     "Any vehicle with > 15,000 km since last PCV service OR "
     "presenting oil consumption > 0.5 L / 1,000 km.\n\n"
     "## Action\n\n"
     "Replace PCV oil separator assembly (DMS-PT-00551). "
     "Inspect intake manifold for oil residue. Labor: 0.9 hr.\n"),

    # Routine program update bulletins (16)
    ("db-routine-multipoint-inspection-checklist",
     "Routine: Multi-Point Inspection Checklist Update — Fleet Version",
     "# Routine Dealer Bulletin: Multi-Point Inspection Checklist\n\n"
     "**Type:** Routine Program Update\n"
     "**Program:** DB-2024-RP-101\n\n"
     "## Overview\n\n"
     "The fleet-optimized multi-point inspection checklist has been "
     "updated to include DMS-specific inspection line items for "
     "connected-vehicle telematics hardware and OTA module integrity.\n\n"
     "## Key Changes\n\n"
     "1. Added telematics module antenna connection torque check "
     "(5 Nm, DMS-VCFG-0100 vehicles and later)\n"
     "2. Added EV battery thermal management hose routing visual "
     "check (EV models)\n"
     "3. Updated tire pressure specification to reference vehicle "
     "label rather than a fixed table (resolves DMS-VCFG-variant "
     "pressure discrepancy)\n"
     "4. Added cabin air filter replacement reminder at 25,000 km "
     "(DMS-PT-00101)\n\n"
     "## Effective Date\n\n"
     "2024-10-01 for all certified service lanes.\n"),
    ("db-routine-oil-viscosity-update",
     "Routine: Engine Oil Viscosity Specification Update",
     "# Routine Dealer Bulletin: Engine Oil Viscosity\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-102\n\n"
     "## Background\n\n"
     "Turbocharged 1.5L and 2.0L engines in model years 2023+ "
     "benefit from low-viscosity full-synthetic oil to reduce "
     "turbocharger bearing wear at cold start.\n\n"
     "## Updated Specification\n\n"
     "- Previous: 5W-30 synthetic\n"
     "- Updated: 0W-20 full synthetic (DMS-PT-00201)\n\n"
     "## Notes\n\n"
     "Existing inventory of 5W-30 (DMS-PT-00202) is approved through "
     "end of 2024 stock. Order 0W-20 for new stock going forward.\n"),
    ("db-routine-brake-fluid-change-interval",
     "Routine: Brake Fluid Change Interval Reduction for Fleet Vehicles",
     "# Routine Dealer Bulletin: Brake Fluid Change Interval\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-103\n\n"
     "## Rationale\n\n"
     "Fleet vehicles with high brake utilization (delivery, rideshare) "
     "accumulate moisture in brake fluid significantly faster than "
     "personal vehicles. Analysis of warranty claims shows brake "
     "caliper corrosion onset correlates with water content > 3%.\n\n"
     "## Updated Interval\n\n"
     "- Standard vehicles: every 24 months or 40,000 km\n"
     "- High-duty-cycle fleet vehicles: every 12 months or 25,000 km\n\n"
     "## Approved Fluid\n\n"
     "DMS-PT-00441 DOT 4+ for all platforms.\n"),
    ("db-routine-telematics-firmware-rollout",
     "Routine: Telematics Firmware Rollout — Q4 2024",
     "# Routine Dealer Bulletin: Telematics Firmware Q4 2024\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-105\n\n"
     "## Changes in Firmware Rev TM-FW-2024-Q4\n\n"
     "1. Improved GPS fix acquisition in urban canyon conditions "
     "(TTFF reduced by 35%)\n"
     "2. Added OTA download retry logic with exponential backoff\n"
     "3. Fixed false DTC C0035 report from wheel speed sensor "
     "interrupt handler race condition (firmware defect, not "
     "hardware — no part replacement needed)\n\n"
     "## Rollout\n\n"
     "OTA push to all connected vehicles starting 2024-11-01. "
     "Dealer reflash required only for vehicles not connected to "
     "cellular network (kit: DMS-PT-00601). Labor: 0.2 hr.\n"),
    ("db-routine-alignment-spec-addendum",
     "Routine: Wheel Alignment Specification Addendum — Staggered Fitment",
     "# Routine Dealer Bulletin: Wheel Alignment Specification\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-106\n\n"
     "## Overview\n\n"
     "Vehicles with staggered-fitment wheels (wider rear than front) "
     "require adjusted rear camber limits to avoid irregular tire "
     "wear on low-profile performance tires.\n\n"
     "## Revised Rear Camber Limit\n\n"
     "- Previous: −0.5° to −1.5°\n"
     "- Revised: −0.75° to −1.25° (tighter band for even wear)\n\n"
     "## Identification\n\n"
     "Staggered fitment vehicles are identified by vehicle config "
     "DMS-VCFG-0200 through DMS-VCFG-0249 in the service portal.\n"),
    ("db-routine-hvac-filter-replacement-reminder",
     "Routine: Cabin Air Filter Replacement — Extended-Interval Part Available",
     "# Routine Dealer Bulletin: Cabin Air Filter\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-108\n\n"
     "## New Part\n\n"
     "A high-capacity HEPA-grade cabin air filter is now available "
     "(DMS-PT-00101H). The extended-interval part is rated for "
     "35,000 km vs 25,000 km for the standard filter (DMS-PT-00101).\n\n"
     "## Recommendation\n\n"
     "Offer the HEPA-grade filter at every service visit for fleet "
     "vehicles operating in high-particulate environments. "
     "Suitable for vehicles with build config DMS-VCFG-0050+.\n"),
    ("db-routine-ev-charge-port-inspection",
     "Routine: EV Charge Port Condition Inspection Protocol",
     "# Routine Dealer Bulletin: EV Charge Port Inspection\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-110\n\n"
     "## Background\n\n"
     "Customer reports of slow charging are frequently resolved by "
     "cleaning the charge port contacts and replacing the gasket.\n\n"
     "## Inspection Protocol\n\n"
     "1. Inspect charge port contacts for corrosion or deformation\n"
     "2. Clean with EV contact cleaner (DMS-PT-00413)\n"
     "3. Replace gasket if cracking or compression set present "
     "(DMS-PT-00414)\n"
     "4. Test with calibrated charge unit to verify 50+ kW acceptance "
     "before returning vehicle\n\n"
     "## Interval\n\n"
     "Every 20,000 km for vehicles in maritime or high-humidity climates.\n"),
    ("db-routine-battery-health-report-at-service",
     "Routine: EV Battery Health Report Required at Every Service Visit",
     "# Routine Dealer Bulletin: EV Battery Health Reporting\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-112\n\n"
     "## Requirement\n\n"
     "Starting 2024-10-01, a battery state-of-health (SoH) report "
     "must be printed and given to the customer at every service "
     "visit for EV/hybrid vehicles. Fleet operators receive "
     "consolidated reports via the DMS fleet portal.\n\n"
     "## Process\n\n"
     "1. Connect diagnostic tool to vehicle OBD-II port\n"
     "2. Run BMS health scan (procedure BMS-HEALTH-2024)\n"
     "3. Print SoH report — record SoH % and pack capacity Ah\n"
     "4. If SoH < 75%, escalate to warranty claim assessment\n"),
    ("db-routine-transmission-fluid-ev-check",
     "Routine: Transaxle Fluid Inspection for Single-Speed EV Drive Units",
     "# Routine Dealer Bulletin: EV Transaxle Fluid\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-115\n\n"
     "## Background\n\n"
     "Single-speed EV transaxles do not require periodic fluid "
     "changes under normal conditions; however, fluid inspection "
     "for metal particulate contamination is now required at "
     "100,000 km or 5 years, whichever comes first.\n\n"
     "## Inspection\n\n"
     "Use magnetic drain plug inspection kit DMS-PT-00701. "
     "Particulate level above threshold (> 5 mg / 100 mL) "
     "indicates bearing wear — drain, flush, and refill with "
     "EV transaxle fluid DMS-PT-00702. Labor: 0.4 hr.\n"),
    ("db-routine-door-latch-lubrication",
     "Routine: Door Latch and Striker Lubrication at High-Cycle Intervals",
     "# Routine Dealer Bulletin: Door Latch Lubrication\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-117\n\n"
     "## Background\n\n"
     "Fleet vehicles with > 50,000 door cycles (rideshare, shared "
     "mobility) exhibit accelerated door latch wear. Periodic "
     "lubrication extends service life and prevents intermittent "
     "door-ajar warnings.\n\n"
     "## Service Item\n\n"
     "Apply door latch lubricant (DMS-PT-00801) to all door latch "
     "mechanisms and strikers at 80,000 km and every 40,000 km "
     "thereafter. Labor: 0.4 hr.\n"),
    ("db-routine-powertrain-mount-torque-check",
     "Routine: Powertrain Mount Torque Re-Check at High-Mileage Interval",
     "# Routine Dealer Bulletin: Powertrain Mount Torque\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-119\n\n"
     "## Background\n\n"
     "Vibration from high-duty-cycle fleet use may cause powertrain "
     "mount bolt self-loosening after 80,000+ km. Loose mounts "
     "increase NVH and can cause secondary wiring chafe.\n\n"
     "## Procedure\n\n"
     "Torque all powertrain mounts to specification (see vehicle-"
     "specific service manual for DMS-VCFG variant torque values). "
     "Typical: front mount 70 Nm, rear mount 65 Nm. Labor: 0.3 hr.\n"),
    ("db-routine-sunroof-drain-flush",
     "Routine: Sunroof Drain Tube Flush at Annual Service",
     "# Routine Dealer Bulletin: Sunroof Drain Tube\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-121\n\n"
     "## Background\n\n"
     "Sunroof drain tubes commonly accumulate leaf debris and "
     "bio-film, especially in vehicles parked outdoors. Blocked "
     "drains cause water ingress that can short interior electronics.\n\n"
     "## Procedure\n\n"
     "Flush all four sunroof drain tubes with compressed air or "
     "soft brush (DMS-PT-00801B) at every annual service. "
     "If flow rate < 200 mL / 30 s per tube, clean with drain "
     "cleaning solution DMS-PT-00802. Labor: 0.3 hr.\n"),
    ("db-routine-headliner-tsb-adhesive",
     "Routine: Headliner Adhesive Re-Bond Procedure",
     "# Routine Dealer Bulletin: Headliner Re-Bond\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-123\n\n"
     "## Issue\n\n"
     "In high-humidity environments, headliner adhesive may soften "
     "and allow sagging of the headliner material at the sunroof "
     "opening perimeter.\n\n"
     "## Procedure\n\n"
     "Apply re-bond adhesive (DMS-PT-00901B) at the affected "
     "perimeter under moderate heat (60°C, 5 minutes with heat gun). "
     "Re-bond kit DMS-PT-00902 includes all required materials. "
     "Labor: 0.7 hr.\n"),
    ("db-routine-camera-calibration-after-glass",
     "Routine: Forward Camera Recalibration Required After Windshield Replacement",
     "# Routine Dealer Bulletin: Forward Camera Calibration\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-125\n\n"
     "## Requirement\n\n"
     "Any vehicle with ADAS features (forward collision warning, "
     "lane keeping assist) requires forward camera static calibration "
     "after windshield replacement. Failure to calibrate can result "
     "in misaligned collision warnings.\n\n"
     "## Procedure\n\n"
     "Use calibration target kit DMS-PT-00621 and ADAS calibration "
     "software v3.4+ per procedure ADAS-CAL-2024. Minimum workshop "
     "lighting: 500 lux. Labor: 1.0 hr.\n"),
    ("db-routine-ride-height-calibration-ev",
     "Routine: Air Suspension Ride Height Calibration After Battery Service",
     "# Routine Dealer Bulletin: Air Suspension Calibration\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-127\n\n"
     "## Requirement\n\n"
     "Vehicles with air suspension must have ride height recalibrated "
     "after any high-voltage battery service that requires battery "
     "pack removal. Battery removal changes the vehicle mass "
     "temporarily; the suspension ECU stores an incorrect learned "
     "height offset.\n\n"
     "## Procedure\n\n"
     "Run ride height learn procedure (SUSP-LEARN-2024) after "
     "reinstalling the battery pack and confirming vehicle is "
     "at kerb weight (no passengers, full washer fluid). "
     "Labor: 0.2 hr.\n"),
    ("db-routine-12v-battery-state-check",
     "Routine: 12V Auxiliary Battery State-of-Health Check at Service",
     "# Routine Dealer Bulletin: 12V Battery Health Check\n\n"
     "**Type:** Routine\n"
     "**Program:** DB-2024-RP-129\n\n"
     "## Background\n\n"
     "12V auxiliary batteries in EV/hybrid vehicles experience "
     "frequent shallow cycling from power-net loads (telematics, "
     "alarm). This cycling pattern reduces lead-acid battery "
     "lifespan to 2–3 years vs 4–5 years in ICE vehicles.\n\n"
     "## Requirement\n\n"
     "Test 12V battery cold cranking amps (CCA) at every service "
     "using calibrated tester DMS-PT-00901C. Replace if CCA < 70% "
     "of rated specification (replacement: DMS-PT-00902C). "
     "Labor: 0.3 hr.\n"),

    # Informational bulletins (12)
    ("db-info-fleet-maintenance-window-guidelines",
     "Informational: Recommended Fleet Maintenance Window Guidelines",
     "# Informational Bulletin: Fleet Maintenance Windows\n\n"
     "**Type:** Informational\n"
     "**Program:** DB-2024-INFO-201\n\n"
     "## Overview\n\n"
     "This bulletin provides recommended service scheduling windows "
     "for fleet vehicles to minimize operational downtime while "
     "maintaining safety-critical service intervals.\n\n"
     "## Recommendations\n\n"
     "- Oil service: no later than 500 km beyond interval\n"
     "- Brake pad replacement: begin scheduling at 30% remaining "
     "wear; hard deadline at 15%\n"
     "- EV battery health check: annually, or 25,000 km\n"
     "- Tire rotation: every 10,000–12,000 km for even wear on "
     "fleet duty cycles\n"
     "- Cabin filter: 25,000 km standard (35,000 km HEPA)\n\n"
     "## Fleet Portal Integration\n\n"
     "Fleet operators can configure automated service reminders "
     "via the DMS fleet portal maintenance scheduling module.\n"),
    ("db-info-connected-vehicle-data-privacy",
     "Informational: Connected Vehicle Data Collection — Privacy Disclosure",
     "# Informational Bulletin: Connected Vehicle Data Privacy\n\n"
     "**Type:** Informational\n"
     "**Program:** DB-2024-INFO-202\n\n"
     "## Purpose\n\n"
     "This bulletin describes the categories of data collected by "
     "the vehicle's onboard telematics module and transmitted to "
     "the fleet management platform.\n\n"
     "## Data Collected\n\n"
     "- Vehicle location (GPS coordinates) — fleet portal only\n"
     "- Vehicle speed and acceleration profile — anonymized "
     "aggregate in platform analytics\n"
     "- DTC event codes and occurrence timestamps\n"
     "- OTA software update status\n"
     "- Battery state of health (EV/hybrid)\n"
     "- Charging session metadata (start, stop, kWh, port type)\n\n"
     "## Not Collected\n\n"
     "No audio, video, biometric, or passenger identity data "
     "is collected by the telematics module.\n\n"
     "## Customer Notice\n\n"
     "Provide the connected vehicle data privacy summary to all "
     "new vehicle owners at delivery.\n"),
    ("db-info-ota-campaign-rollout-process",
     "Informational: OTA Campaign Rollout Process for Dealers",
     "# Informational Bulletin: OTA Campaign Rollout\n\n"
     "**Type:** Informational\n"
     "**Program:** DB-2024-INFO-203\n\n"
     "## How OTA Campaigns Work\n\n"
     "1. Manufacturer publishes an OTA campaign to the fleet platform\n"
     "2. Vehicles are enrolled in the campaign via VIN-based targeting\n"
     "3. The vehicle downloads the update package during a connected "
     "idle period (typically overnight)\n"
     "4. The vehicle installs the update on next key-on after download\n"
     "5. Installation status is reported to the fleet portal within "
     "15 minutes of completion\n\n"
     "## Dealer Role\n\n"
     "Dealers do not need to action OTA campaigns unless:\n"
     "- A vehicle fails to download after 14 days (use dealer "
     "reflash kit DMS-PT-00601)\n"
     "- A vehicle reports an installation failure DTC\n"
     "- A customer requests in-dealership installation\n"),
    ("db-info-ev-range-anxiety-customer-guidance",
     "Informational: EV Range — Customer Guidance for Service Advisors",
     "# Informational Bulletin: EV Range Advisory\n\n"
     "**Type:** Informational\n"
     "**Program:** DB-2024-INFO-205\n\n"
     "## Common Customer Concerns\n\n"
     "**\"My range display is wrong.\"**\n"
     "The range estimate adapts to recent driving patterns. Heavy "
     "HVAC use, highway speeds, and cold weather all reduce range. "
     "Advise the customer that the estimate will stabilize after "
     "2–3 consistent charging cycles.\n\n"
     "**\"My battery lost range permanently.\"**\n"
     "Battery SoH degradation below 90% is expected at 3–5 years. "
     "Permanent range reduction indicates SoH below 80%, which "
     "qualifies for warranty assessment if within the 8-year / "
     "100,000 km window.\n\n"
     "**\"Fast charging is slower than last month.\"**\n"
     "Charge acceptance above 80% SoC intentionally decreases. "
     "If slow charging below 50% SoC, check for cooling system "
     "faults (see DB-2024-EV-009).\n"),
    ("db-info-diagnostic-loaner-ev-program",
     "Informational: Diagnostic Loaner EV Program Guidelines",
     "# Informational Bulletin: Diagnostic Loaner EV\n\n"
     "**Type:** Informational\n"
     "**Program:** DB-2024-INFO-207\n\n"
     "## Overview\n\n"
     "The loaner EV program allows dealers to provide "
     "same-platform EVs to customers whose vehicles are in "
     "service for > 2 days on warranty work.\n\n"
     "## Eligibility\n\n"
     "- Vehicle is within warranty period\n"
     "- Work order duration estimated > 48 hours\n"
     "- Loaner EV available in the dealer's loaner fleet\n\n"
     "## Administration\n\n"
     "Administer through the DMS fleet portal loaner management "
     "module. Warranty claim includes loaner days at the approved "
     "daily rate (see warranty rate schedule).\n"),
    ("db-info-summer-cooling-system-prep",
     "Informational: Summer Pre-Season Cooling System Preparation",
     "# Informational Bulletin: Summer Cooling Prep\n\n"
     "**Type:** Informational — Seasonal\n"
     "**Program:** DB-2024-INFO-209\n\n"
     "## Checklist for Service Advisors\n\n"
     "Before the summer peak, service advisors should proactively "
     "offer cooling system inspection for any vehicle with:\n\n"
     "- Coolant at 4+ years or 80,000+ km\n"
     "- History of overheating DTCs (P0217)\n"
     "- EV/hybrid: battery cooling loop not serviced in 2+ years\n\n"
     "## Service Items\n\n"
     "- Coolant flush and refill (DMS-PT-00533)\n"
     "- Radiator cap pressure test\n"
     "- EV battery cooling line leak check\n"
     "- Cabin A/C performance test (output temp ≤ 10°C below ambient)\n"),
    ("db-info-key-fob-battery-proactive-replacement",
     "Informational: Key Fob Battery Proactive Replacement",
     "# Informational Bulletin: Key Fob Battery\n\n"
     "**Type:** Informational\n"
     "**Program:** DB-2024-INFO-211\n\n"
     "## Recommendation\n\n"
     "Key fob batteries in high-usage fleet vehicles may deplete "
     "in as little as 14 months. Proactive replacement prevents "
     "stranded vehicle events.\n\n"
     "## Replacement\n\n"
     "CR2032 battery (DMS-PT-00091). Recommend replacement every "
     "12 months on vehicles with > 200 key-cycle operations per "
     "day (rideshare, delivery, rental). Customer notification "
     "via DMS portal threshold alert at 20% battery level.\n"),
    ("db-info-winter-readiness-fleet",
     "Informational: Winter Readiness Program for Fleet Operators",
     "# Informational Bulletin: Winter Fleet Readiness\n\n"
     "**Type:** Informational — Seasonal\n"
     "**Program:** DB-2024-INFO-213\n\n"
     "## Pre-Winter Service Checklist\n\n"
     "- Install winter tires (minimum 4mm tread depth)\n"
     "- Test battery CCA (see DB-2024-RP-129)\n"
     "- Check coolant freeze protection to −40°C\n"
     "- Test block heater if equipped\n"
     "- Test EV battery preconditioning (see DB-2024-EV-009)\n"
     "- Replace wiper blades with winter-grade (DMS-PT-00321W)\n"
     "- Apply brake dust shields if operating on salted roads\n\n"
     "## EV Winter Range Expectation\n\n"
     "Fleet operators should plan for 20–35% range reduction at "
     "−10°C. Overnight thermal preconditioning via scheduled "
     "departure time partially offsets this reduction.\n"),
    ("db-info-new-diagnostic-tool-update",
     "Informational: New Diagnostic Tool Software Update — Version 12.4",
     "# Informational Bulletin: Diagnostic Tool Update\n\n"
     "**Type:** Informational\n"
     "**Program:** DB-2024-INFO-215\n\n"
     "## What's New in Version 12.4\n\n"
     "1. Added support for BMS health scan (procedure BMS-HEALTH-2024)\n"
     "2. Added EPS module flash for DB-2024-EPS-007 reflash\n"
     "3. Added TPMS sensor battery status readout for batch "
     "DMS-PT-00610 through DMS-PT-00649\n"
     "4. Updated wheel alignment spec tables for all DMS-VCFG variants\n"
     "5. Fixed false live-data timeout on slow-responding "
     "ABS modules\n\n"
     "## Download\n\n"
     "Available via dealer diagnostic portal under Software Updates. "
     "Recommend update before any session involving EV or ADAS work.\n"),
    ("db-info-fleet-operator-api-integration",
     "Informational: Fleet Operator API Integration Guide",
     "# Informational Bulletin: Fleet Operator API\n\n"
     "**Type:** Informational\n"
     "**Program:** DB-2024-INFO-217\n\n"
     "## Overview\n\n"
     "Fleet operators can integrate the DMS fleet management platform "
     "API to pull vehicle telematics, service records, and DTC "
     "event history into their own fleet management systems.\n\n"
     "## Available Endpoints\n\n"
     "- `GET /fleet/{fleet_id}/vehicles` — vehicle list with status\n"
     "- `GET /fleet/{fleet_id}/dtc-events` — DTC history, 90-day rolling\n"
     "- `GET /fleet/{fleet_id}/service-records` — service history\n"
     "- `POST /fleet/{fleet_id}/service-request` — create service request\n\n"
     "## Authentication\n\n"
     "OAuth 2.0 client credentials flow. Contact DMS dealer support "
     "for API credentials provisioning.\n"),
    ("db-info-warranty-claim-submission-tips",
     "Informational: Warranty Claim Submission Best Practices",
     "# Informational Bulletin: Warranty Claim Submission\n\n"
     "**Type:** Informational\n"
     "**Program:** DB-2024-INFO-219\n\n"
     "## Common Submission Errors\n\n"
     "1. **Missing labor operation code** — every claim must include "
     "a valid labor op code from the current schedule\n"
     "2. **DTC not documented on repair order** — the DTC code that "
     "triggered the warranty work must appear on the RO, not just "
     "the verbal description\n"
     "3. **Customer signature missing** — required for all claims "
     "involving part replacement > $250 retail value\n"
     "4. **Part not returned** — core return required within 10 "
     "business days for all core-tracked parts\n\n"
     "## Processing Time\n\n"
     "Standard claims: 5–7 business days\n"
     "Complex technical review required: 15–20 business days\n"),
    ("db-info-parts-return-policy-update",
     "Informational: Parts Return Policy — Electrical Components Update",
     "# Informational Bulletin: Parts Return Policy\n\n"
     "**Type:** Informational\n"
     "**Program:** DB-2024-INFO-221\n\n"
     "## Change\n\n"
     "Effective 2024-10-01, all electrical components "
     "(sensors, control modules, actuators) are non-returnable "
     "after installation. This includes TPMS sensors, ABS modules, "
     "and telematics units.\n\n"
     "## Rationale\n\n"
     "Installed electrical components exhibit latent failure modes "
     "from static discharge or wiring harness damage that may not "
     "be visible at time of return.\n\n"
     "## Exception\n\n"
     "Components returned under warranty claim (not exchange) are "
     "still eligible for warranty core return per existing process.\n"),
]


def generate_dealer_bulletins() -> list[tuple[str, str, str, str, str]]:
    """Emit dealer bulletin documents — urgent, routine, and informational.

    Returns ``(relpath, source_doc_id, title, category, text)`` rows.
    source_category is exactly ``"dealer_bulletin"`` on every row, matching
    the enum value added to schema.yaml in G4.T1.
    """
    rows = []
    for slug, title, body in _DEALER_BULLETINS:
        rows.append((
            f"sources/dealer-bulletins/{slug}.md",
            f"DB-{slug.upper()}",
            title,
            "dealer_bulletin",
            body,
        ))
    return rows


# ---------------------------------------------------------------------------
# Warranty policy seeds — DTC + labor-op combination requirements.
# References the six existing DTCs by ID only; does not re-seed DTC guides.
# ---------------------------------------------------------------------------

_WARRANTY_POLICY_DOCS: list[tuple[str, str, str]] = [
    # Overview documents
    ("warranty-claim-submission-overview",
     "Warranty Claim Submission Overview",
     "# Warranty Claim Submission Overview\n\n"
     "## Purpose\n\n"
     "This document defines the submission requirements for warranty "
     "claims arising from diagnostic trouble codes, component failures, "
     "and recall-related repairs. All claims must include a valid DTC "
     "code, labor operation code, and supporting documentation.\n\n"
     "## Required Fields\n\n"
     "- **VIN** — 17-character vehicle identification number\n"
     "- **DTC Code** — diagnostic trouble code triggering the claim\n"
     "- **Labor Operation Code** — from the current labor rate schedule\n"
     "- **Parts Used** — DMS-prefixed part numbers with quantities\n"
     "- **Mileage at Repair** — odometer reading at date of service\n"
     "- **Customer Signature** — required for all claims > $250 retail\n\n"
     "## Coverage Periods\n\n"
     "- Bumper-to-Bumper: 3 years / 36,000 mi\n"
     "- Powertrain: 5 years / 60,000 mi\n"
     "- Emissions (Federal): 8 years / 80,000 mi\n"
     "- EV/Hybrid Battery: 8 years / 100,000 mi (below 70% SoH)\n\n"
     "## Processing SLA\n\n"
     "Standard claims: 5–7 business days.\n"
     "Technical review required: 15–20 business days.\n"),
    ("warranty-coverage-period-matrix",
     "Warranty Coverage Period Matrix by Component Class",
     "# Warranty Coverage Period Matrix\n\n"
     "## Component Classes and Coverage Windows\n\n"
     "| Component Class | Coverage Period | Notes |\n"
     "|---|---|---|\n"
     "| Powertrain (engine, transmission) | 5y / 60,000 mi | Includes "
     "turbocharger |\n"
     "| Emissions components (catalytic converter, ECM) | 8y / 80,000 mi "
     "| Federal requirement |\n"
     "| CARB-state emissions | 15y / 150,000 mi | Applicable in "
     "CARB-compliant states |\n"
     "| EV/Hybrid battery | 8y / 100,000 mi | Below 70% SoH threshold |\n"
     "| EV/Hybrid powertrain | 8y / 100,000 mi | Motor, inverter, charger |\n"
     "| Chassis/suspension | 3y / 36,000 mi B-t-B | Includes ABS module |\n"
     "| Safety systems | 3y / 36,000 mi B-t-B | Airbag, pretensioner |\n"
     "| Corrosion (perforation) | 6y / unlimited | Excludes surface rust |\n\n"
     "## Wear Items (Excluded)\n\n"
     "Brake pads, tires, filters, wiper blades, light bulbs.\n"),
    ("warranty-labor-rate-schedule",
     "Warranty Labor Rate Schedule — Effective 2024-Q4",
     "# Warranty Labor Rate Schedule\n\n"
     "## Overview\n\n"
     "Labor rates are reimbursed at the dealer's published retail "
     "labor rate for warranty claims, subject to the maximum "
     "allowable time (MAT) for each labor operation.\n\n"
     "## Selected Labor Operations\n\n"
     "| Labor Op Code | Description | MAT (hours) |\n"
     "|---|---|---|\n"
     "| LBR-ENG-OIL-001 | Engine oil and filter service | 0.4 |\n"
     "| LBR-BRAKE-FLUID-FLUSH-001 | Brake fluid flush (4-wheel) | 0.8 |\n"
     "| LBR-EPS-FLASH-007 | EPS module reflash | 0.8 |\n"
     "| LBR-BMS-HEALTH-001 | BMS health scan and report | 0.3 |\n"
     "| LBR-TPMS-REPLACE-001 | TPMS sensor replacement (1 wheel) | 0.3 |\n"
     "| LBR-HVAC-EVAP-001 | Evaporator core replacement | 3.2 |\n"
     "| LBR-FUEL-PUMP-RELAY-001 | Fuel pump relay replacement | 0.3 |\n"
     "| LBR-ABS-GROUND-001 | ABS module ground strap | 0.5 |\n"
     "| LBR-EV-BMS-FLASH-001 | BMS firmware update | 0.5 |\n"
     "| LBR-WIPER-MOTOR-001 | Wiper motor replacement | 0.6 |\n"
     "| LBR-EV-CP-LATCH-001 | Charge port latch replacement | 1.1 |\n"
     "| LBR-SEATBELT-PRETENS-001 | Seat belt pretensioner replacement | 1.0 |\n"
     "| LBR-COOLANT-BYPASS-001 | Coolant bypass valve replacement | 1.4 |\n"
     "| LBR-PCV-SEPARATOR-001 | PCV separator replacement | 0.9 |\n"),

    # DTC-specific warranty policy documents (one per covered DTC)
    ("warranty-policy-p0420",
     "Warranty Policy: DTC P0420 — Catalyst System Efficiency Below Threshold",
     "# Warranty Policy: DTC P0420\n\n"
     "**DTC:** P0420 — Catalyst System Efficiency Below Threshold (Bank 1)\n"
     "**DTC Severity:** P2 (Medium)\n"
     "**Coverage:** Emissions — Federal 8 years / 80,000 mi; "
     "CARB 15 years / 150,000 mi\n\n"
     "## Submission Requirements\n\n"
     "1. Verify DTC P0420 is stored or pending with freeze frame data\n"
     "2. Confirm no mechanical damage to exhaust system (physical "
     "inspection required)\n"
     "3. Check O2 sensor upstream and downstream response — "
     "if O2 sensor failed, replace O2 sensor first and retest "
     "before claiming catalytic converter\n"
     "4. Document exhaust backpressure reading and catalytic "
     "converter temperature differential\n"
     "5. Replace catalytic converter only if O2 sensors pass "
     "and converter fails efficiency test\n\n"
     "## Parts\n\n"
     "- Catalytic converter assembly: DMS-PT-00421\n"
     "- Upstream O2 sensor (if failed): DMS-PT-00422\n"
     "- Downstream O2 sensor (if failed): DMS-PT-00423\n\n"
     "## Labor Operation\n\n"
     "LBR-CAT-REPLACE-001 (MAT 1.8 hr)\n\n"
     "## Notes\n\n"
     "P0420 warranty claims require completion of the two-trip "
     "drive cycle verification per Federal emissions warranty "
     "procedures. Retain O2 sensor data logs with claim submission.\n"),
    ("warranty-policy-p0300",
     "Warranty Policy: DTC P0300 — Random/Multiple Cylinder Misfire",
     "# Warranty Policy: DTC P0300\n\n"
     "**DTC:** P0300 — Random/Multiple Cylinder Misfire Detected\n"
     "**DTC Severity:** P1 (High)\n"
     "**Coverage:** Powertrain — 5 years / 60,000 mi\n\n"
     "## Diagnostic Steps Before Claim Submission\n\n"
     "1. Record freeze frame data and misfire event counter per cylinder\n"
     "2. Perform relative compression test — document all cylinder values\n"
     "3. Check spark plug condition on all affected cylinders\n"
     "4. Check ignition coil primary resistance on all affected coils\n"
     "5. Fuel injector balance test — document delta flow for all injectors\n\n"
     "## Covered Repairs\n\n"
     "- Ignition coil replacement (DMS-PT-00301) — covered under "
     "powertrain warranty when misfire follows coil resistance pattern\n"
     "- Spark plug replacement (DMS-PT-00302) — NOT covered under "
     "warranty (wear item), except when premature failure < 30,000 km\n"
     "- Fuel injector replacement (DMS-PT-00303) — covered under "
     "powertrain warranty when injector delta flow > 15%\n\n"
     "## Labor Operation\n\n"
     "LBR-MISFIRE-DIAG-001 for diagnostic; "
     "LBR-COIL-REPLACE-001 per coil (MAT 0.4 hr each).\n\n"
     "## Notes\n\n"
     "P0300 with a flashing MIL qualifies for emergency service "
     "reimbursement at 1.5× MAT.\n"),
    ("warranty-policy-c0035",
     "Warranty Policy: DTC C0035 — Left Front Wheel Speed Sensor Circuit",
     "# Warranty Policy: DTC C0035\n\n"
     "**DTC:** C0035 — Left Front Wheel Speed Sensor Circuit\n"
     "**DTC Severity:** P1 (High)\n"
     "**Coverage:** Chassis — Bumper-to-Bumper 3 years / 36,000 mi\n\n"
     "## Submission Requirements\n\n"
     "1. Confirm DTC C0035 is stored with ABS/stability control "
     "disabled telltale illuminated\n"
     "2. Visually inspect wheel speed sensor wiring harness for "
     "chafe or connector damage before claiming sensor\n"
     "3. Measure sensor resistance and AC signal frequency at wheel "
     "speed — document readings\n"
     "4. If wiring harness damage is present: document source of "
     "damage (warranty covers manufacturing defects, not "
     "customer-induced road damage)\n\n"
     "## Parts\n\n"
     "- Wheel speed sensor LF (DMS-PT-00351): covered under "
     "B-t-B when resistance out of spec\n"
     "- Wiring harness repair kit (DMS-PT-00352): covered if "
     "chafe location is at factory routing point\n\n"
     "## Labor Operation\n\n"
     "LBR-WSS-REPLACE-001 (MAT 0.6 hr)\n\n"
     "## Notes\n\n"
     "Brake fluid contamination (see DB-2024-BR-001) may "
     "co-present with C0035 on vehicles with brake caliper corrosion. "
     "If both conditions are present, submit separate claim lines.\n"),
    ("warranty-policy-u0100",
     "Warranty Policy: DTC U0100 — Lost Communication with ECM/PCM",
     "# Warranty Policy: DTC U0100\n\n"
     "**DTC:** U0100 — Lost Communication with ECM/PCM\n"
     "**DTC Severity:** P1 (High)\n"
     "**Coverage:** Powertrain — 5 years / 60,000 mi\n\n"
     "## Diagnostic Protocol\n\n"
     "1. Check battery voltage — U0100 false-trips below 10.5V "
     "during cranking; if battery < 70% CCA, replace battery "
     "first (not warranty)\n"
     "2. Inspect CAN bus wiring connectors at PCM and junction boxes "
     "for corrosion\n"
     "3. Measure CAN high/low bus voltage differential — "
     "should be 2.5V nominal at idle\n"
     "4. Check PCM ground circuit resistance\n"
     "5. If no external fault found, PCM programming verification "
     "required before requesting PCM replacement\n\n"
     "## Parts\n\n"
     "- PCM programming only: LBR-PCM-PROGRAM-001 (no parts)\n"
     "- PCM replacement (DMS-PT-00401) — only after programming "
     "fails to resolve; requires technical assistance authorization\n"
     "- CAN harness repair kit (DMS-PT-00402)\n\n"
     "## Labor Operation\n\n"
     "LBR-CAN-DIAG-001 (MAT 1.2 hr); LBR-PCM-REPLACE-001 (MAT 1.8 hr)\n\n"
     "## Technical Assistance\n\n"
     "PCM replacement requires prior authorization from technical "
     "assistance. Document all wiring and programming checks "
     "before calling.\n"),
    ("warranty-policy-p0171",
     "Warranty Policy: DTC P0171 — System Too Lean (Bank 1)",
     "# Warranty Policy: DTC P0171\n\n"
     "**DTC:** P0171 — System Too Lean (Bank 1)\n"
     "**DTC Severity:** P2 (Medium)\n"
     "**Coverage:** Emissions — Federal 8 years / 80,000 mi\n\n"
     "## Diagnostic Sequence\n\n"
     "1. Check for vacuum leaks — smoke test at intake manifold "
     "and all hose connections\n"
     "2. Inspect MAF sensor for contamination — if contaminated, "
     "clean first and retest before replacing\n"
     "3. Check fuel pressure at idle and WOT — must be within "
     "±5% of specification\n"
     "4. Check fuel injector pulse width long-term fuel trim (LTFT) "
     "— LTFT > +15% indicates lean condition confirmed\n\n"
     "## Covered Repairs\n\n"
     "- MAF sensor replacement (DMS-PT-00171): covered under "
     "emissions warranty when signal out of range after cleaning\n"
     "- Intake manifold gasket (DMS-PT-00172): covered if vacuum "
     "leak at gasket — document smoke test result\n"
     "- Fuel injector replacement (DMS-PT-00303): covered if "
     "flow test shows injector restricted\n\n"
     "## Labor Operation\n\n"
     "LBR-LEAN-DIAG-001 (MAT 0.8 hr); LBR-MAF-REPLACE-001 (MAT 0.4 hr)\n\n"
     "## Notes\n\n"
     "P0171 paired with P0420 on the same vehicle requires emissions "
     "warranty claim for both; address lean condition first to "
     "prevent catalytic converter damage.\n"),
    ("warranty-policy-b0001",
     "Warranty Policy: DTC B0001 — Driver Frontal Stage 1 Airbag Deployment Control",
     "# Warranty Policy: DTC B0001\n\n"
     "**DTC:** B0001 — Driver Frontal Stage 1 Deployment Control\n"
     "**DTC Severity:** P0 (Critical — Safety)\n"
     "**Coverage:** Safety System — Bumper-to-Bumper 3 years / 36,000 mi\n\n"
     "## Important Safety Notice\n\n"
     "**Any vehicle presenting DTC B0001 must NOT be returned "
     "to the customer until the fault is confirmed resolved.** "
     "A non-functional driver airbag is a safety-critical condition.\n\n"
     "## Diagnostic Steps\n\n"
     "1. Document all restraint DTCs present — B0001 may co-occur "
     "with clock spring faults or airbag module connector faults\n"
     "2. Inspect clock spring for wear or intermittent connection "
     "with steering wheel full-lock rotation test\n"
     "3. Inspect airbag module connector for corrosion or bent pins\n"
     "4. Resistance check of airbag initiator circuit — "
     "use ONLY approved resistance tester; never apply test current "
     "directly to airbag circuit\n\n"
     "## Parts\n\n"
     "- Clock spring replacement (DMS-PT-00801B): most common fix "
     "for B0001 on vehicles > 3 years\n"
     "- Airbag module connector repair kit (DMS-PT-00802B)\n"
     "- Airbag module replacement (DMS-PT-00803B): only with "
     "technical assistance authorization\n\n"
     "## Labor Operation\n\n"
     "LBR-AIRBAG-DIAG-001 (MAT 0.8 hr); "
     "LBR-CLOCKSPRING-REPLACE-001 (MAT 0.6 hr)\n\n"
     "## Documentation\n\n"
     "All B-series DTC warranty claims require before/after "
     "resistance readings and photographs of connector condition. "
     "Retain original parts for minimum 90 days post-claim.\n"),

    # Supplementary policy documents
    ("warranty-fleet-extended-coverage",
     "Fleet Extended Coverage Options and Claim Procedures",
     "# Fleet Extended Coverage\n\n"
     "## Available Fleet Plans\n\n"
     "| Plan | Term | Deductible | Covered Components |\n"
     "|---|---|---|---|\n"
     "| Fleet Basic | 5y / 100,000 mi | $100 | Powertrain + A/C + "
     "electrical |\n"
     "| Fleet Plus | 6y / 125,000 mi | $50 | Basic + suspension + "
     "steering + brakes |\n"
     "| Fleet Premium | 7y / 150,000 mi | $0 | Comprehensive "
     "(excludes wear items) |\n\n"
     "## Claim Process for Extended Coverage\n\n"
     "1. Verify active coverage in fleet portal (Coverage Lookup)\n"
     "2. Submit claim with repair order and DTC documentation "
     "within 30 days of repair\n"
     "3. Deductible collected from fleet operator at billing\n"
     "4. Reimbursement processed within 10 business days\n\n"
     "## Exclusions\n\n"
     "All plans exclude: maintenance items (oil, filters, pads), "
     "glass, paint, upholstery, and damage from collision or misuse.\n"),
    ("warranty-goodwill-adjustment-policy",
     "Goodwill Adjustment Policy for Out-of-Warranty Repairs",
     "# Goodwill Adjustment Policy\n\n"
     "## When Goodwill Applies\n\n"
     "Goodwill adjustments are available for components that fail "
     "shortly outside warranty coverage when:\n"
     "1. The vehicle is within 6 months or 10,000 km of warranty expiry\n"
     "2. The failure pattern matches a known defect category\n"
     "3. The customer has a documented service history with the dealer\n\n"
     "## Approval Process\n\n"
     "Submit a goodwill request through the dealer portal with:\n"
     "- Documented service history (all prior visits)\n"
     "- Description of why the failure is consistent with a "
     "manufacturing defect vs normal wear\n"
     "- Repair cost estimate\n\n"
     "## Common Goodwill Categories\n\n"
     "- Powertrain failures < 6 months post-warranty\n"
     "- Premature catalytic converter failure (P0420) on low-mileage "
     "vehicles\n"
     "- EV battery SoH < 75% within 6 months of warranty expiry\n"),
    ("warranty-parts-core-return-procedures",
     "Parts Core Return Procedures for Warranty Claims",
     "# Parts Core Return Procedures\n\n"
     "## Core-Tracked Parts\n\n"
     "The following part categories require core return within "
     "10 business days of claim approval:\n\n"
     "- Engine assemblies and long blocks\n"
     "- Transmission assemblies\n"
     "- Catalytic converters (P0420 claims)\n"
     "- ECM/PCM modules (U0100 claims)\n"
     "- EV battery modules\n"
     "- Electric motor assemblies\n\n"
     "## Core Return Process\n\n"
     "1. Place removed core in supplied return container "
     "(include claim number on the core tag)\n"
     "2. Ship prepaid label within 10 business days\n"
     "3. Core credit issued within 15 days of receipt and "
     "inspection\n\n"
     "## Non-Core Items\n\n"
     "Sensors, seat belts, airbag modules, and electrical "
     "components (see DB-2024-INFO-221) are retained by the "
     "warranty technical team on request only.\n"),
    ("warranty-repeat-repair-escalation",
     "Repeat Repair and Escalation Policy",
     "# Repeat Repair and Escalation Policy\n\n"
     "## Definition\n\n"
     "A repeat repair is defined as a second repair for the same "
     "DTC or symptom within 12 months of the original repair.\n\n"
     "## Escalation Triggers\n\n"
     "- Same DTC stored within 30 days of original repair\n"
     "- Customer reports same symptom within 90 days\n"
     "- Three or more claims on the same system within 12 months\n\n"
     "## Process\n\n"
     "1. Open a technical assistance case before performing the "
     "second repair — do not proceed without authorization\n"
     "2. Document all prior repair orders and DTC freeze frame data\n"
     "3. Technical team may request vehicle retention for "
     "engineering inspection\n\n"
     "## Parts Covered\n\n"
     "All parts on an escalated claim are covered at no charge "
     "to the dealer, regardless of warranty status, for the "
     "repeat event.\n"),
    ("warranty-ev-battery-capacity-testing",
     "EV Battery Capacity Test Procedures for Warranty Claims",
     "# EV Battery Capacity Testing\n\n"
     "## When Testing Is Required\n\n"
     "A battery capacity test is required before any warranty "
     "claim involving EV/hybrid battery performance, including:\n"
     "- Customer complaint of reduced range (> 20% below EPA estimate)\n"
     "- Battery SoH < 80% reported by BMS health scan\n"
     "- Pre-claim documentation for EV battery warranty claims\n\n"
     "## Test Procedure\n\n"
     "1. Charge battery to 100% on Level 2 charger\n"
     "2. Drive standardized cycle at 75 kph constant speed "
     "until battery reaches 5% SoC\n"
     "3. Record total kWh discharged and compare to rated capacity\n"
     "4. Capacity < 70% of rated qualifies for battery warranty "
     "replacement\n\n"
     "## Labor Operation\n\n"
     "LBR-EV-BAT-TEST-001 (MAT 2.0 hr, non-reimbursable if claim "
     "is denied)\n\n"
     "## Parts\n\n"
     "Battery module replacement: DMS-PT-00901E (requires "
     "technical assistance pre-authorization).\n"),
    ("warranty-sublet-repair-authorization",
     "Sublet Repair Authorization for Specialty Warranty Work",
     "# Sublet Repair Authorization\n\n"
     "## When Sublet Is Permitted\n\n"
     "Warranty repairs requiring specialized equipment or facilities "
     "not available at the servicing dealer may be sublet with "
     "prior authorization:\n\n"
     "- Collision-caused warranty damage (requires body shop)\n"
     "- EV high-voltage battery replacement (requires HV-certified "
     "facility)\n"
     "- ADAS camera dynamic calibration (requires road test facility)\n\n"
     "## Authorization Process\n\n"
     "1. Contact dealer warranty coordinator before subletting\n"
     "2. Get written pre-authorization with maximum allowable cost\n"
     "3. Sublet facility must provide itemized invoice referencing "
     "the warranty claim number\n\n"
     "## Reimbursement\n\n"
     "Sublet reimbursed at cost + 10% handling, up to the "
     "pre-authorized amount. Costs above the authorized amount "
     "require supplemental authorization.\n"),
    ("warranty-emission-recall-procedures",
     "Emissions Recall and Warranty Claim Overlap Procedures",
     "# Emissions Recall and Warranty Claim Overlap\n\n"
     "## Overview\n\n"
     "When a DTC-triggered warranty repair overlaps with an open "
     "emissions recall, specific procedures apply to ensure the "
     "repair is attributed correctly.\n\n"
     "## Determination Rules\n\n"
     "1. If the component requiring replacement is covered by an "
     "open recall, the repair must be documented as a recall "
     "campaign repair — not a warranty claim\n"
     "2. If the component is NOT covered by the recall but the "
     "DTC is identical, proceed with warranty claim and note "
     "the recall number on the claim as a cross-reference\n"
     "3. If both a recall remedy and a warranty repair are needed "
     "in the same visit: complete the recall first, then submit "
     "separate warranty claim for the unrelated component\n\n"
     "## Relevant DTCs\n\n"
     "- P0420 (emissions): check for active catalyst recall before "
     "submitting warranty claim\n"
     "- P0171 (emissions): check for active intake/fuel system "
     "recall before proceeding\n"
     "- B0001 (safety): always check for active airbag recalls "
     "before proceeding with warranty repair\n"),
    ("warranty-dealer-advance-program",
     "Dealer Advance Program for High-Value Warranty Repairs",
     "# Dealer Advance Program\n\n"
     "## Purpose\n\n"
     "The dealer advance program provides interim parts funding "
     "for warranty repairs where the parts cost exceeds $2,000 "
     "and the full claim has not yet been processed.\n\n"
     "## Eligibility\n\n"
     "- Parts cost > $2,000 retail on a single claim\n"
     "- Vehicle is within active warranty coverage period\n"
     "- Dealer has < 3 outstanding advance repayment items\n\n"
     "## Process\n\n"
     "1. Submit claim with complete documentation\n"
     "2. Request advance via dealer portal (Claims > Advance Request)\n"
     "3. Advance issued within 2 business days\n"
     "4. Reconciled against final claim approval\n\n"
     "## High-Value Claim Examples\n\n"
     "- EV battery module replacement: typically $4,000–$8,000\n"
     "- Engine long block: typically $3,500–$6,000\n"
     "- Transmission assembly: typically $2,500–$5,000\n"),
    ("warranty-regional-emissions-addendum-carb",
     "Regional Addendum: CARB-State Extended Emissions Warranty",
     "# CARB-State Extended Emissions Warranty Addendum\n\n"
     "## Applicability\n\n"
     "This addendum applies to vehicles registered in states that "
     "have adopted California Air Resources Board (CARB) emissions "
     "standards: California, Colorado, Connecticut, Maine, Maryland, "
     "Massachusetts, New Jersey, New Mexico, New York, Oregon, "
     "Pennsylvania, Rhode Island, Vermont, Virginia, Washington.\n\n"
     "## Extended Coverage\n\n"
     "CARB states require 15 years / 150,000 miles emissions warranty "
     "on the following components (vs Federal 8 years / 80,000 mi):\n"
     "- Catalytic converter (relevant DTC: P0420)\n"
     "- Oxygen sensors (upstream + downstream)\n"
     "- EGR valve and related emissions hardware\n"
     "- ECM/PCM (relevant DTC: U0100 on emissions-related PCM failures)\n"
     "- EVAP canister and purge valve\n\n"
     "## Claim Handling\n\n"
     "When a warranty claim for P0420 or U0100 is submitted on "
     "a vehicle registered in a CARB state with mileage between "
     "80,000 and 150,000 mi, apply the CARB extended coverage "
     "indicator in the claim system.\n"),
    ("warranty-documentation-retention-policy",
     "Warranty Documentation Retention Policy",
     "# Warranty Documentation Retention Policy\n\n"
     "## Retention Requirements\n\n"
     "Dealers must retain the following for a minimum of 5 years "
     "after claim approval:\n\n"
     "| Document Type | Retention Period |\n"
     "|---|---|\n"
     "| Signed repair orders | 5 years |\n"
     "| DTC scan tool data printouts | 5 years |\n"
     "| Customer signatures | 5 years |\n"
     "| Airbag / safety-system photos (B0001 etc.) | 7 years |\n"
     "| Core return receipts | 3 years |\n"
     "| Sublet authorization letters | 5 years |\n\n"
     "## Storage\n\n"
     "Electronic retention via the DMS dealer portal document "
     "management module satisfies all requirements. Physical "
     "copies may be discarded once uploaded and confirmed stored.\n\n"
     "## Audit\n\n"
     "Random documentation audits occur quarterly. Missing "
     "documentation results in claim charge-back. Appeal period: "
     "30 days from charge-back notice.\n"),
    # Additional supplementary warranty policy documents
    ("warranty-technician-certification-requirements",
     "Technician Certification Requirements for Warranty Repairs",
     "# Technician Certification Requirements\n\n"
     "## Purpose\n\n"
     "Certain warranty repairs require technician certification "
     "at a specific level. Claims submitted by uncertified "
     "technicians are subject to charge-back.\n\n"
     "## Certification Requirements by Repair Type\n\n"
     "| Repair Type | Minimum Certification |\n"
     "|---|---|\n"
     "| EV high-voltage system | Level 2 EV Certified |\n"
     "| Airbag and restraint system | Safety Systems Certified |\n"
     "| ADAS camera calibration | ADAS Calibration Certified |\n"
     "| Engine/transmission assembly | Master Technician |\n"
     "| Software/module reprogramming | Module Certification Course |\n"
     "| General warranty repairs | Journeyman or higher |\n\n"
     "## Verification\n\n"
     "Certification status is verified automatically in the claim "
     "submission system against the dealership technician registry. "
     "Update technician records in the dealer portal before "
     "submitting certification-gated claims.\n"),
    ("warranty-technical-assistance-hotline",
     "Technical Assistance Hotline Usage Guidelines",
     "# Technical Assistance Hotline\n\n"
     "## When to Call\n\n"
     "Technical assistance is required (not optional) before "
     "proceeding with the following repairs:\n\n"
     "- PCM replacement (DTC U0100 after wiring checks pass)\n"
     "- Airbag module replacement (DTC B0001)\n"
     "- Third or subsequent repair for the same DTC\n"
     "- Any repair estimated above $3,000 labor + parts\n"
     "- EV battery module replacement\n\n"
     "## Information to Have Ready\n\n"
     "1. VIN and mileage\n"
     "2. All stored and pending DTCs with freeze frame data\n"
     "3. All prior repair orders for this vehicle\n"
     "4. Scan tool data from current session\n"
     "5. Technician certification level\n\n"
     "## Process\n\n"
     "Technical assistance case number must appear on the claim "
     "as a cross-reference. Claims without case numbers on "
     "authorization-required repairs will be pended for review.\n"),
    ("warranty-remote-diagnostic-data-submission",
     "Remote Diagnostic Data Submission for Warranty Pre-Authorization",
     "# Remote Diagnostic Data Submission\n\n"
     "## Overview\n\n"
     "The remote diagnostic data portal allows dealers to submit "
     "vehicle scan data for warranty pre-authorization review "
     "without calling the technical assistance hotline.\n\n"
     "## Supported Data Formats\n\n"
     "- OBD-II scan tool export (J2534 format)\n"
     "- Dealer diagnostic tool XML export (all supported tool brands)\n"
     "- Freeze frame screenshot with DTC codes visible\n\n"
     "## When to Use\n\n"
     "Use remote diagnostic submission for:\n"
     "- PCM and module replacement pre-authorization\n"
     "- Emissions warranty claims requiring engineering review\n"
     "- Repeat repair authorization\n\n"
     "## SLA\n\n"
     "Pre-authorization decision within 4 business hours "
     "during standard dealer hours (08:00–18:00 local time).\n"),
    ("warranty-mileage-verification-procedure",
     "Mileage Verification Procedure for Warranty Claim Accuracy",
     "# Mileage Verification Procedure\n\n"
     "## Requirement\n\n"
     "Mileage must be verified at the time of write-up "
     "from the vehicle odometer, not from a prior service record "
     "or customer statement.\n\n"
     "## Process\n\n"
     "1. Read odometer from instrument cluster at vehicle check-in\n"
     "2. Record on repair order — digital photograph recommended\n"
     "3. Compare to any prior recent service records — "
     "discrepancies > 5% from expected accumulation require note\n\n"
     "## Discrepancy Handling\n\n"
     "If odometer discrepancy is detected (replacement instrument "
     "cluster, non-reporting telematics, customer dispute), "
     "document the discrepancy and proceed with the claim. "
     "Do NOT refuse to service or claim on discrepancy alone — "
     "submit with explanation for manual review.\n\n"
     "## Odometer Fraud\n\n"
     "If rollback is confirmed via telematics history, retain all "
     "records and escalate to warranty fraud investigation team.\n"),
    ("warranty-pre-owned-vehicle-coverage",
     "Pre-Owned Vehicle Warranty Coverage and Transfer Policy",
     "# Pre-Owned Vehicle Warranty Coverage\n\n"
     "## Coverage Transfer\n\n"
     "Factory warranty coverage (Bumper-to-Bumper, Powertrain, "
     "Emissions) transfers to subsequent owners for the "
     "unexpired portion of the original coverage term.\n\n"
     "## Documentation Required\n\n"
     "For warranty claims on pre-owned vehicles, the claim system "
     "automatically verifies coverage using the VIN. Dealers do "
     "not need to provide title or purchase documentation.\n\n"
     "## Emissions Coverage Transfer\n\n"
     "Federal and CARB emissions warranty transfers fully "
     "regardless of number of owners.\n\n"
     "## Extended Coverage Plans\n\n"
     "Fleet extended coverage plans (Basic, Plus, Premium) are "
     "VIN-linked and transfer with the vehicle. Contact the "
     "fleet warranty coordinator to update the plan holder name "
     "after a vehicle is sold out of fleet.\n\n"
     "## Deductibles on Pre-Owned\n\n"
     "Factory warranty carries no deductible. Extended fleet plans "
     "retain their original deductible on transfer.\n"),
    ("warranty-diagnostic-fee-policy",
     "Diagnostic Fee Policy for Warranty and Non-Warranty Repairs",
     "# Diagnostic Fee Policy\n\n"
     "## Warranty Diagnostic Fees\n\n"
     "When a diagnostic procedure leads to a warranty repair:\n"
     "- Diagnostic labor is reimbursed as part of the warranty claim\n"
     "- Use the appropriate diagnostic labor op code "
     "(LBR-*-DIAG-001 series)\n"
     "- Maximum diagnostic time: 2.0 hr without technical assistance pre-approval\n\n"
     "## Non-Warranty Outcome After Diagnosis\n\n"
     "When diagnosis reveals the fault is not covered under warranty "
     "(wear item, customer-caused damage, out-of-warranty component):\n"
     "- A diagnostic fee may be charged to the customer "
     "per the dealer's published diagnostic rate\n"
     "- Written estimate must be provided before proceeding with repair\n"
     "- Customer must approve the repair estimate in writing\n\n"
     "## Declined Repairs\n\n"
     "If customer declines the recommended repair after diagnosis:\n"
     "- Document declined repair on repair order\n"
     "- Collect diagnostic fee\n"
     "- Do not submit a warranty claim for a declined repair\n"),
    ("warranty-claim-correction-and-supplement",
     "Warranty Claim Correction and Supplement Procedures",
     "# Claim Correction and Supplement Procedures\n\n"
     "## Correction Period\n\n"
     "Claims may be corrected within 30 days of submission "
     "for the following errors without charge-back risk:\n"
     "- Wrong labor op code\n"
     "- Missing DTC code\n"
     "- Incorrect part number\n"
     "- Mileage transcription error\n\n"
     "## Supplement Process\n\n"
     "A supplement is required when additional work is discovered "
     "during an approved warranty repair:\n"
     "1. Contact warranty coordinator before proceeding with "
     "supplemental work\n"
     "2. Document the additional findings on the original RO\n"
     "3. Submit supplement claim referencing the original claim number\n"
     "4. Supplement must be submitted within 10 days of original "
     "claim approval\n\n"
     "## Denial and Appeal\n\n"
     "Denied claims may be appealed within 60 days. Submit appeal "
     "with additional documentation explaining why the repair "
     "should be covered. One appeal per claim is permitted.\n"),
    ("warranty-rental-car-reimbursement",
     "Rental Car Reimbursement Policy for Warranty Repairs",
     "# Rental Car Reimbursement Policy\n\n"
     "## Eligibility\n\n"
     "Rental car reimbursement is available when a warranty repair:\n"
     "- Is expected to take more than 1 business day\n"
     "- Is covered under an active warranty\n"
     "- Results from a safety-critical condition that prevents "
     "vehicle use\n\n"
     "## Rates\n\n"
     "| Vehicle Class | Daily Max Rate |\n"
     "|---|---|\n"
     "| Compact | $45/day |\n"
     "| Mid-size | $55/day |\n"
     "| Full-size / SUV | $65/day |\n"
     "| EV equivalent | $70/day |\n\n"
     "## Process\n\n"
     "1. Advise customer of rental eligibility at write-up\n"
     "2. Use approved rental agency (listed in dealer portal)\n"
     "3. Include rental receipt with warranty claim\n"
     "4. Maximum 7 rental days per repair event; extended "
     "cases require prior authorization\n\n"
     "## Safety-Critical Expedited Rental\n\n"
     "For safety-critical conditions (B0001, C0035 with ABS "
     "disabled, brake system failure): rental reimbursement "
     "begins day 1 with no waiting period.\n"),
    ("warranty-fleet-reporting-monthly",
     "Monthly Fleet Warranty Activity Reporting Requirements",
     "# Monthly Fleet Warranty Activity Reporting\n\n"
     "## Purpose\n\n"
     "Fleet operators with 10+ vehicles receive monthly warranty "
     "activity reports via the DMS fleet portal, summarizing:\n\n"
     "- Open and closed warranty claims by VIN\n"
     "- Repeat repair rate by DTC code\n"
     "- Parts usage summary with DMS-PT part numbers\n"
     "- Estimated warranty value remaining per vehicle\n"
     "- Vehicles approaching end of coverage period\n\n"
     "## Report Access\n\n"
     "Fleet operators access reports at Fleet Portal > Reports > "
     "Warranty Activity. Available in PDF or CSV format.\n\n"
     "## Data Retention\n\n"
     "Reports are retained for 36 months in the portal. "
     "Fleet operators should archive annual summary reports "
     "per their own internal document retention policy.\n\n"
     "## DTC Trend Monitoring\n\n"
     "The fleet warranty report highlights DTC codes appearing "
     "on 3 or more vehicles in the fleet within a 90-day window "
     "as a fleet-level trend indicator for proactive maintenance.\n"),
    ("warranty-new-vehicle-preparation-claims",
     "New Vehicle Preparation (NVP) Warranty Claim Guidelines",
     "# New Vehicle Preparation Warranty Claims\n\n"
     "## Overview\n\n"
     "Pre-delivery inspection (PDI) defects discovered during "
     "new vehicle preparation are claimable under New Vehicle "
     "Preparation warranty, separate from customer warranty coverage.\n\n"
     "## Claimable Conditions\n\n"
     "- Paint defects (scratches, chips) present before delivery\n"
     "- Software requiring update at PDI per current bulletin\n"
     "- DTC stored at PDI with no customer use (< 50 km)\n"
     "- Missing or incorrect parts found during PDI checklist\n\n"
     "## Non-Claimable Under NVP\n\n"
     "- Transit damage (submit to carrier claims process)\n"
     "- Customer-requested accessories not pre-approved\n"
     "- Normal PDI preparation time (not warranty work)\n\n"
     "## Submission Timing\n\n"
     "NVP claims must be submitted within 30 days of vehicle "
     "arrival at dealership. Claims submitted after first customer "
     "delivery default to standard warranty coverage.\n"),
    ("warranty-wear-item-exception-protocol",
     "Wear Item Exception Protocol — Premature Failure Claims",
     "# Wear Item Exception Protocol\n\n"
     "## Overview\n\n"
     "Standard warranty excludes wear items (brake pads, tires, "
     "filters, wiper blades). However, premature failure of a "
     "normally excluded wear item may be claimable when:\n\n"
     "1. The wear item fails at less than 40% of its expected "
     "minimum service life as published in service literature\n"
     "2. The premature failure is attributable to a covered "
     "component defect (e.g., premature brake pad wear caused "
     "by a sticking caliper under warranty)\n"
     "3. The wear item is from a batch that is the subject of "
     "an active bulletin or recall\n\n"
     "## Claim Process\n\n"
     "1. Document the wear condition with measurements — "
     "brake pad thickness, tire tread depth, etc.\n"
     "2. Identify and document the covered root cause, if any\n"
     "3. Submit both the wear item replacement AND the root cause "
     "repair as separate line items on the claim\n"
     "4. Include justification for why the wear rate exceeds "
     "expected minimum life\n\n"
     "## Examples\n\n"
     "- Brake pads worn to 1 mm at 15,000 km → inspect and claim "
     "brake caliper if seized (covered) → claim pads as "
     "consequential wear (covered when caliper is root cause)\n"
     "- Tires worn unevenly at 20,000 km → inspect wheel alignment "
     "for suspension defect → if alignment within spec, not claimable\n"),
]


def generate_warranty_policy() -> list[tuple[str, str, str, str, str]]:
    """Emit warranty policy documents — claim requirements, labor ops, coverage.

    Returns ``(relpath, source_doc_id, title, category, text)`` rows.
    source_category is exactly ``"warranty_policy"`` on every row, matching
    the enum value added to schema.yaml in G4.T1.

    References the six existing DTC codes (P0420, P0300, C0035, U0100, P0171,
    B0001) by ID only — does not re-seed the underlying DTC guides.
    Parts are referenced by DMS-prefixed synthetic IDs only (DMS-PT-*).
    """
    rows = []
    for slug, title, body in _WARRANTY_POLICY_DOCS:
        rows.append((
            f"sources/warranty-policy/{slug}.md",
            f"WP-{slug.upper()}",
            title,
            "warranty_policy",
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
    ("dealer_bulletins", generate_dealer_bulletins),
    ("warranty_policy", generate_warranty_policy),
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

    # FG3.T1 (spec 2026-08-26-adp-dealer-domain Fix Group 3): reconcile the
    # parts-catalog prefix so that superseded docs from the retired naming scheme
    # (<category>.md) cannot survive a regeneration that emits sku-<part>.md.
    #
    # Approach: snapshot the existing .md and .md.metadata.json files in
    # sources/parts-catalog/ BEFORE generating, track every file written during
    # this run, then remove any pre-existing file that was NOT written.
    #
    # Scope is strictly sources/parts-catalog/ — other category prefixes are
    # NOT touched.  A bare shutil.rmtree on sources/ would destroy the other
    # 8 category prefixes and is explicitly prohibited by spec Constraints.
    _PARTS_CATALOG_S3_PREFIX = "sources/parts-catalog/"
    _parts_catalog_dir = output_root / "sources" / "parts-catalog"
    _parts_catalog_pre_existing: set[Path] = set()
    if _parts_catalog_dir.exists():
        for _p in _parts_catalog_dir.iterdir():
            if _p.is_file() and (
                _p.suffix == ".md" or _p.name.endswith(".md.metadata.json")
            ):
                _parts_catalog_pre_existing.add(_p)
    _parts_catalog_written: set[Path] = set()

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
            # Track files written to the parts-catalog prefix for reconciliation.
            if relpath.startswith(_PARTS_CATALOG_S3_PREFIX):
                _parts_catalog_written.add(local_path)
                _parts_catalog_written.add(sidecar_path)
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

    # FG3.T1 reconciliation: remove pre-existing parts-catalog files that were
    # NOT written in this run.  Handles two cases:
    #   1. Retired naming scheme (brakes.md, engine.md, …) superseded by
    #      sku-<part>.md — no new file collides with the old name, so without
    #      this step both lineups survive.
    #   2. A SKU removed from the fixture — its stale doc would stay
    #      retrievable in the KB after removal.
    #
    # Scope: strictly sources/parts-catalog/.  The set difference
    # (_parts_catalog_pre_existing - _parts_catalog_written) is the exact set
    # of generator-owned files that no longer belong in the prefix.
    _stale = _parts_catalog_pre_existing - _parts_catalog_written
    for _stale_path in sorted(_stale):
        if _stale_path.exists():
            _stale_path.unlink()

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
