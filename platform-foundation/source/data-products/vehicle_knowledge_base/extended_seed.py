"""Extended Bedrock-KB seeding for ``vehicle_knowledge_base``.

Per Group 5 task ``Bedrock KB seeding extensions``, this module
*extends* the base
:mod:`platform-foundation/source/data-products/vehicle_knowledge_base/generator.py`
output with **data-derived** narrative summaries:

1. **Service-records insights** — top failure patterns and customer-
   complaint themes derived from
   ``curated/service_records/.../*.parquet``. Emitted under existing
   schema enum categories ``tsb_recall`` (failure patterns map cleanly
   to TSB-style summaries) and ``service_policy`` (complaint themes
   inform service-network playbooks). Source-doc IDs use the
   ``SVC-FAILURE-…`` / ``SVC-COMPLAINT-…`` prefixes so consumers can
   filter by ``source_doc_id LIKE 'SVC-%'`` when they want only the
   data-derived summaries (vs the base generator's static documents).

2. **Charging-pattern narratives** — distributional summaries of
   ``curated/charging_sessions/.../*.parquet`` (network / station-type
   mix, interrupt-reason mix, energy-per-session quantiles) under
   category ``charging_narrative``.

3. **OTA rollout summaries** — adoption + failure-mode summaries of
   ``curated/ota_campaigns/.../*.parquet`` (header + events tables)
   under category ``ota_rollout_summary``. One per-campaign summary
   doc plus a fleet-wide aggregate.

The chunk schema, embedding model defaults, S3 URI resolution, and
manifest shape match the base generator's contract, so the same
Bedrock KB ingestion job consumes both sets of artifacts without
schema drift.

Per the Group 5 task **Constraint** ("KB index size limits — sample,
don't full-load"), every parquet read is sampled
(``--max-rows-per-product``, default 5,000). Fleet-wide aggregates are
computed against the sample, NOT the full table. The narratives
explicitly note "sampled at N rows" so a CVX consumer reading them
understands they're directional, not exact.

The module is **importable without boto3** — the upload path lazy-
imports ``boto3`` only when ``--upload`` is set, mirroring the base
generator's pattern. ``pandas`` + ``pyarrow`` are required at import
time (already pinned in ``requirements.txt``).

When the curated tree is missing or empty (typical pre-Group-3 state),
the runner falls back to a deterministic in-memory synthetic sample
(via :func:`_synthesize_sample_frames`) so the module always runs and
emits a non-empty manifest. The fallback is clearly tagged in the
manifest's ``data_source`` field so downstream consumers can detect
it.

Run::

    # Local smoke (uses synthetic fallback when curated is missing)
    python source/data-products/vehicle_knowledge_base/extended_seed.py \\
        --output-root /tmp/adp-vkb-extended

    # Read from a real curated tree
    python source/data-products/vehicle_knowledge_base/extended_seed.py \\
        --curated-root curated \\
        --output-root /tmp/adp-vkb-extended

    # Upload to staging S3 alongside the base manifest
    python source/data-products/vehicle_knowledge_base/extended_seed.py \\
        --curated-root curated \\
        --output-root /tmp/adp-vkb-extended \\
        --upload \\
        --s3-root s3://adp-staging-foundation-lake-<account>-<region>/knowledge/vehicle_knowledge_base
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
import pyarrow.parquet as pq

# Reuse the base generator's chunking + manifest helpers so both paths
# emit byte-identical chunk shapes. The extended_seed lives in the
# same package directory so importing the sibling module is a direct
# `import generator`.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import generator as base  # noqa: E402  (sibling module — vehicle_knowledge_base.generator)

# Make ``schema_loader`` importable when run directly from the source tree.
_LIB = Path(__file__).resolve().parents[3] / "source" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
import schema_loader as sl  # noqa: E402

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MAX_ROWS_PER_PRODUCT = 5_000
"""Per-product sampling cap — keeps the KB index small (Constraint #5)."""

DEFAULT_TOP_N = 10
"""How many top failure patterns / complaint themes to surface."""

DEFAULT_CAMPAIGN_SUMMARY_LIMIT = 10
"""Max number of per-campaign rollout summaries to emit (sampled)."""

DEFAULT_SAMPLE_SEED = 42
"""Deterministic seed for parquet sampling. Same seed → same chunks."""


# ---------------------------------------------------------------------------
# Parquet sampling helpers
# ---------------------------------------------------------------------------


def _list_parquet_files(curated_root: Path, product: str) -> list[Path]:
    """Return parquet files under ``curated_root/<product>/**/*.parquet``.

    Tolerates Hive-style partition trees and single-file layouts. Returns
    an empty list when the product directory is missing.
    """
    product_dir = curated_root / product
    if not product_dir.exists():
        return []
    return sorted(p for p in product_dir.rglob("*.parquet") if p.is_file())


def _read_sample_frame(
    files: list[Path],
    *,
    columns: list[str] | None,
    max_rows: int,
    seed: int = DEFAULT_SAMPLE_SEED,
) -> pd.DataFrame:
    """Read a bounded sample DataFrame from a list of parquet files.

    Reads files one-by-one (avoiding the Hive-partition schema-merge
    issue documented in Group 3 follow-ups) and concatenates after
    column projection. Returns a deterministic random sample of at
    most ``max_rows`` rows. When ``files`` is empty, returns an empty
    DataFrame with the requested columns.
    """
    if not files:
        return pd.DataFrame(columns=columns or [])
    frames: list[pd.DataFrame] = []
    rows_so_far = 0
    # Read up to ~3x max_rows worth of input then sample down — keeps
    # memory bounded but representative across multiple partitions.
    cap = max(max_rows * 3, 1000)
    for parq in files:
        try:
            schema = pq.read_schema(str(parq))
            present = {f.name for f in schema}
            project = (
                [c for c in columns if c in present]
                if columns is not None
                else None
            )
            tbl = pq.read_table(str(parq), columns=project)
        except Exception:  # noqa: BLE001 — best-effort sampling
            continue
        df = tbl.to_pandas()
        if df.empty:
            continue
        frames.append(df)
        rows_so_far += len(df)
        if rows_so_far >= cap:
            break
    if not frames:
        return pd.DataFrame(columns=columns or [])
    out = pd.concat(frames, ignore_index=True, sort=False)
    if len(out) > max_rows:
        out = out.sample(n=max_rows, random_state=seed).reset_index(drop=True)
    return out


def _synthesize_sample_frames(seed: int = DEFAULT_SAMPLE_SEED) -> dict[str, pd.DataFrame]:
    """Deterministic synthetic frames used when the curated tree is empty.

    Returns ``{"service_records": df, "charging_sessions": df,
    "ota_campaigns": df, "ota_campaign_events": df}`` with just enough
    rows + columns to exercise every summarizer. Mirrors the
    distributions documented in the per-product schema YAMLs so the
    narratives emitted in fallback mode read like a real Group 3 run
    (except smaller).
    """
    import numpy as np  # local import — numpy is a transitive pin already

    rng = np.random.default_rng(seed)

    # ----- service_records -----
    svc_n = 200
    svc_types = [
        "scheduled_maintenance", "warranty_repair", "safety_recall",
        "software_recall", "body_repair", "tire_service",
        "charging_system", "battery_replacement", "hv_battery_diagnostic",
        "software_update",
    ]
    svc_weights = [0.30, 0.15, 0.05, 0.10, 0.05, 0.10, 0.05, 0.02, 0.08, 0.10]
    complaint_pool = [
        "Range loss after recent OTA update; battery cycles fewer miles than expected.",
        "Charging port latch fails to engage on first attempt; sometimes works on second try.",
        "Regen braking inconsistent at low speeds; pedal feel changes between drives.",
        "Thermal warning on hot days during DC fast charging.",
        "OTA install reported failure but vehicle behavior unchanged afterward.",
        "Drive unit grinding noise above 45 mph; intermittent.",
        "Touchscreen freezes during navigation; soft reboot resolves temporarily.",
        "Battery state-of-health drop noticed; previously 95%, now 89%.",
        "Public DC fast charge slower than expected; only reaches 50 kW peak.",
        "Phone-as-key fails to wake the vehicle on cold mornings.",
    ]
    dtc_pool = [
        ["P0AA6"], ["P1A0F"], ["P0A7F", "P1AF0"], ["U0100"],
        ["B1318"], ["C0561"], [], ["P0BBD"], ["P0AC4"], None,
    ]
    svc = pd.DataFrame({
        "service_id": [f"SR-{i:08d}" for i in range(svc_n)],
        "service_type": rng.choice(svc_types, size=svc_n, p=svc_weights),
        "complaint_text": rng.choice(complaint_pool + [None] * 3, size=svc_n),
        "dtc_codes": [dtc_pool[int(i % len(dtc_pool))] for i in rng.integers(0, len(dtc_pool), size=svc_n)],
        "outcome": rng.choice(
            ["resolved", "parts_pending", "follow_up_required", "lemon_law_buyback"],
            size=svc_n, p=[0.78, 0.12, 0.09, 0.01],
        ),
        "csat_score": rng.choice([1, 2, 3, 4, 5, None], size=svc_n,
                                 p=[0.02, 0.04, 0.10, 0.34, 0.30, 0.20]),
        "labor_hours": rng.gamma(2.0, 1.5, size=svc_n).round(2),
        "warranty_covered": rng.random(size=svc_n) > 0.55,
    })

    # ----- charging_sessions -----
    chg_n = 200
    station_types = ["home_l1", "home_l2", "public_dc_fast", "destination_l2"]
    station_w = [0.14, 0.56, 0.25, 0.05]
    networks = ["Tesla Supercharger", "Electrify America", "EVgo",
                "ChargePoint", "Home", "Destination"]
    network_w = [0.20, 0.20, 0.10, 0.10, 0.30, 0.10]
    chg = pd.DataFrame({
        "session_id": [f"CHG-{i:08d}" for i in range(chg_n)],
        "station_type": rng.choice(station_types, size=chg_n, p=station_w),
        "network_provider": rng.choice(networks, size=chg_n, p=network_w),
        "kwh_delivered": rng.gamma(2.0, 15.0, size=chg_n).clip(0, 200).round(3),
        "duration_seconds": rng.integers(900, 28800, size=chg_n),
        "interrupted": rng.random(size=chg_n) < 0.04,
        "interrupt_reason": rng.choice(
            ["user_unplug", "station_fault", "vehicle_fault", "network_drop", None],
            size=chg_n, p=[0.022, 0.008, 0.006, 0.004, 0.96],
        ),
        "start_soc_pct": rng.uniform(10, 50, size=chg_n).round(2),
        "end_soc_pct": rng.uniform(50, 100, size=chg_n).round(2),
        "connector_type": rng.choice(["J1772", "CCS1", "NACS", "CHAdeMO"],
                                     size=chg_n, p=[0.30, 0.30, 0.35, 0.05]),
    })

    # ----- ota_campaigns header + events -----
    camp_n = 8
    categories = ["safety_recall", "feature_add", "bug_fix",
                  "security_patch", "performance"]
    cats = list(rng.choice(categories, size=camp_n,
                           p=[0.10, 0.30, 0.30, 0.20, 0.10]))
    campaigns = pd.DataFrame({
        "campaign_id": [f"CAMP-{i:04d}" for i in range(1, camp_n + 1)],
        "campaign_name": [f"OTA Sample Campaign {i}" for i in range(1, camp_n + 1)],
        "release_version": [f"3.{i}.0" for i in range(1, camp_n + 1)],
        "category": cats,
        "severity": list(rng.choice(["critical", "high", "medium", "low"],
                                    size=camp_n, p=[0.10, 0.20, 0.40, 0.30])),
        "package_size_mb": rng.integers(50, 4000, size=camp_n),
        "status": ["active"] * camp_n,
    })

    statuses = ["installed", "downloading", "dispatched", "download_failed",
                "install_failed", "rolled_back", "declined_by_user"]
    status_w = [0.845, 0.005, 0.05, 0.04, 0.03, 0.005, 0.025]
    failure_reasons = [
        "Cellular signal lost during download window.",
        "Battery below 25% SoC at install attempt.",
        "Vehicle in motion during install attempt.",
        "Post-install regression detected — auto-rollback triggered.",
        "Customer postponed via in-vehicle prompt.",
    ]
    ev_n = 600
    events = pd.DataFrame({
        "campaign_id": rng.choice(campaigns["campaign_id"].tolist(), size=ev_n),
        "vin": [f"1FA00000000000{i:03d}" for i in range(ev_n)],
        "final_status": rng.choice(statuses, size=ev_n, p=status_w),
        "failure_reason": rng.choice(failure_reasons + [None] * 8, size=ev_n),
    })

    return {
        "service_records": svc,
        "charging_sessions": chg,
        "ota_campaigns": campaigns,
        "ota_campaign_events": events,
    }


# ---------------------------------------------------------------------------
# Service-records summarizers
# ---------------------------------------------------------------------------


_FAILURE_SERVICE_TYPES = {
    "warranty_repair", "safety_recall", "software_recall",
    "charging_system", "battery_replacement", "hv_battery_diagnostic",
}
"""Service types that represent vehicle issues (vs scheduled maintenance)."""


def _explode_dtc_codes(values: Iterable) -> Counter:
    """Flatten a column of nullable ``array<string>`` DTC codes into a counter."""
    c: Counter = Counter()
    for v in values:
        if v is None:
            continue
        if isinstance(v, (list, tuple)):
            for code in v:
                if isinstance(code, str) and code:
                    c[code] += 1
        elif isinstance(v, str) and v:
            c[v] += 1
    return c


def _summarize_failure_patterns(svc: pd.DataFrame) -> str:
    """Top-N failure patterns derived from ``service_records`` sample.

    Returns a markdown body suitable for KB ingestion. Empty input
    yields a "no data sampled" stub so the runner never emits an
    empty document.
    """
    n = len(svc)
    if n == 0:
        return ("# Top Failure Patterns (Sampled Service Records)\n\n"
                "No service-records sample available at index time. "
                "Re-run after Group 3 service_records generator emits "
                "curated parquet.\n")
    failure_only = svc[svc["service_type"].isin(_FAILURE_SERVICE_TYPES)]
    type_counts = (
        failure_only["service_type"].value_counts(dropna=False).head(DEFAULT_TOP_N)
    )
    dtc_counts = _explode_dtc_codes(svc.get("dtc_codes", [])).most_common(DEFAULT_TOP_N)
    outcome_counts = svc["outcome"].value_counts(normalize=True).round(3)
    csat_avg = svc.get("csat_score")
    if csat_avg is not None and csat_avg.notna().any():
        csat_text = f"Average CSAT (when reported): **{csat_avg.dropna().mean():.2f} / 5**."
    else:
        csat_text = "CSAT scores not present in sample."

    failure_share = len(failure_only) / n if n else 0.0
    lines = [
        "# Top Failure Patterns (Sampled Service Records)",
        "",
        f"_Source: ``service_records`` sampled at **{n} rows**. "
        f"{len(failure_only)} rows ({failure_share:.1%}) classify as failure-class "
        "service types (warranty / safety_recall / software_recall / "
        "charging_system / battery_replacement / hv_battery_diagnostic)._",
        "",
        "## Top failure-class service types",
        "",
    ]
    if type_counts.empty:
        lines.append("No failure-class rows in this sample.")
    else:
        for st, count in type_counts.items():
            lines.append(f"- **{st}**: {int(count)} rows")
    lines += ["", "## Top DTC codes captured at intake", ""]
    if not dtc_counts:
        lines.append("No DTC codes present in sample.")
    else:
        for code, count in dtc_counts:
            lines.append(f"- `{code}`: {int(count)} occurrences")
    lines += ["", "## Outcome distribution", ""]
    for outcome, share in outcome_counts.items():
        lines.append(f"- **{outcome}**: {float(share):.1%} of sampled rows")
    lines += ["", "## CSAT signal", "", csat_text, ""]
    lines.append(
        "_Use this summary as a directional signal for service-quality "
        "trends. Exact counts require querying the full Iceberg "
        "table (Athena `adp_<stage>_service_records.service_records`)._"
    )
    return "\n".join(lines) + "\n"


_COMPLAINT_THEMES: list[tuple[str, list[str]]] = [
    # Theme name → keyword list (lower-case substring match against complaint_text).
    ("range_loss_post_ota", ["range loss", "fewer miles", "less range", "range drop"]),
    ("charging_port_engagement", ["charge port", "charging port", "latch", "won't engage"]),
    ("regen_braking_inconsistent", ["regen", "braking", "pedal feel"]),
    ("thermal_warning_dcfc", ["thermal", "overheat", "hot"]),
    ("ota_install_failure", ["ota", "update fail", "install fail"]),
    ("drivetrain_noise", ["grinding", "noise", "whining", "drive unit"]),
    ("infotainment_freeze", ["touchscreen", "infotainment", "freeze", "reboot"]),
    ("soh_decline", ["state of health", "soh", "battery health", "capacity loss"]),
    ("public_dcfc_slow", ["dc fast", "public charge", "kw peak", "slow charge"]),
    ("phone_key_failure", ["phone key", "phone-as-key", "phone as key", "can't unlock"]),
]


def _summarize_complaint_themes(svc: pd.DataFrame) -> str:
    """Group complaint_text by keyword themes and emit a markdown summary."""
    n = len(svc)
    if n == 0 or "complaint_text" not in svc.columns:
        return ("# Customer Complaint Themes (Sampled Service Records)\n\n"
                "No complaint text available at index time.\n")
    texts = (
        svc["complaint_text"]
        .dropna()
        .astype(str)
        .str.lower()
        .tolist()
    )
    total_with_text = len(texts)
    theme_hits: list[tuple[str, int, list[str]]] = []
    for theme, kws in _COMPLAINT_THEMES:
        matched: list[str] = []
        for t in texts:
            if any(kw in t for kw in kws):
                matched.append(t)
        if matched:
            theme_hits.append((theme, len(matched), matched[:3]))
    theme_hits.sort(key=lambda r: r[1], reverse=True)

    lines = [
        "# Customer Complaint Themes (Sampled Service Records)",
        "",
        f"_Source: ``service_records.complaint_text`` sampled at **{n} rows**, "
        f"of which **{total_with_text}** carry free-text complaints. "
        "Themes are keyword-derived from the sampled text — directional, not exhaustive._",
        "",
    ]
    if not theme_hits:
        lines.append("No themes matched the keyword catalog. "
                     "Review raw complaint_text for emergent issues.")
    else:
        for theme, count, exemplars in theme_hits[:DEFAULT_TOP_N]:
            share = count / total_with_text if total_with_text else 0
            lines += [
                f"## Theme: {theme}",
                "",
                f"- Hits: **{count}** ({share:.1%} of sampled complaints)",
                "- Sample complaints:",
            ]
            for ex in exemplars:
                # Truncate each exemplar to a single line for KB readability.
                excerpt = ex.replace("\n", " ").strip()
                if len(excerpt) > 240:
                    excerpt = excerpt[:237] + "..."
                lines.append(f"  - \"{excerpt}\"")
            lines.append("")
    lines.append(
        "_Themes are heuristic. The triage agent should still read the "
        "raw `complaint_text` column for case-specific context — these "
        "summaries are for KB-level grounding, not per-case dispatch._"
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Charging-pattern summarizer
# ---------------------------------------------------------------------------


def _summarize_charging_patterns(chg: pd.DataFrame) -> str:
    """Distributional summary of ``charging_sessions`` for KB grounding."""
    n = len(chg)
    if n == 0:
        return ("# Charging Patterns (Sampled Charging Sessions)\n\n"
                "No charging-session sample available at index time.\n")
    type_share = chg["station_type"].value_counts(normalize=True).round(3)
    network_share = (
        chg["network_provider"].value_counts(normalize=True, dropna=True).round(3)
        if "network_provider" in chg.columns else pd.Series(dtype=float)
    )
    interrupt_rate = float(chg["interrupted"].mean()) if "interrupted" in chg.columns else 0.0
    interrupt_reasons = (
        chg.loc[chg["interrupted"] == True, "interrupt_reason"]  # noqa: E712
        .value_counts(normalize=True, dropna=True)
        .round(3)
        if "interrupt_reason" in chg.columns else pd.Series(dtype=float)
    )
    kwh_q = chg["kwh_delivered"].quantile([0.10, 0.50, 0.90]).round(2) \
        if "kwh_delivered" in chg.columns else None
    duration_q = chg["duration_seconds"].quantile([0.10, 0.50, 0.90]) \
        if "duration_seconds" in chg.columns else None
    connector_share = (
        chg["connector_type"].value_counts(normalize=True).round(3)
        if "connector_type" in chg.columns else pd.Series(dtype=float)
    )
    # Per-station-type kWh median (a meaningful operator signal).
    kwh_by_type = (
        chg.groupby("station_type")["kwh_delivered"].median().round(2)
        if "kwh_delivered" in chg.columns else pd.Series(dtype=float)
    )

    lines = [
        "# Charging Patterns (Sampled Charging Sessions)",
        "",
        f"_Source: ``charging_sessions`` sampled at **{n} rows**. "
        "Distribution is directional; the canonical full-table query "
        "is Athena `adp_<stage>_charging_sessions.charging_sessions`._",
        "",
        "## Station-type mix",
        "",
    ]
    for k, v in type_share.items():
        lines.append(f"- **{k}**: {float(v):.1%}")
    lines += ["", "## Network-provider mix", ""]
    if network_share.empty:
        lines.append("No network_provider values in sample.")
    else:
        for k, v in network_share.head(8).items():
            lines.append(f"- **{k}**: {float(v):.1%}")
    lines += ["", "## Connector-type mix", ""]
    if connector_share.empty:
        lines.append("No connector_type values in sample.")
    else:
        for k, v in connector_share.items():
            lines.append(f"- **{k}**: {float(v):.1%}")
    lines += ["", "## Energy delivered (kWh per session)", ""]
    if kwh_q is not None and not kwh_q.empty:
        lines.append(f"- p10: {float(kwh_q.loc[0.10]):.2f} kWh")
        lines.append(f"- median: {float(kwh_q.loc[0.50]):.2f} kWh")
        lines.append(f"- p90: {float(kwh_q.loc[0.90]):.2f} kWh")
    else:
        lines.append("No kwh_delivered values in sample.")
    if not kwh_by_type.empty:
        lines += ["", "## Median kWh by station type", ""]
        for k, v in kwh_by_type.items():
            lines.append(f"- **{k}**: {float(v):.2f} kWh")
    lines += ["", "## Session duration (seconds)", ""]
    if duration_q is not None and not duration_q.empty:
        lines.append(f"- p10: {int(duration_q.loc[0.10])} s")
        lines.append(f"- median: {int(duration_q.loc[0.50])} s")
        lines.append(f"- p90: {int(duration_q.loc[0.90])} s")
    else:
        lines.append("No duration_seconds values in sample.")
    lines += [
        "",
        "## Interrupted sessions",
        "",
        f"- Overall interrupt rate: **{interrupt_rate:.2%}** of sampled rows.",
    ]
    if not interrupt_reasons.empty:
        lines.append("- Interrupt-reason mix among interrupted sessions:")
        for k, v in interrupt_reasons.items():
            lines.append(f"  - **{k}**: {float(v):.1%}")
    else:
        lines.append("- No interrupted sessions in sample.")
    lines += [
        "",
        "_For per-station-id rollups (e.g., 'why is this station "
        "interrupting more than peers?'), join `charging_sessions` "
        "to the `charging_stations` dimension via `station_id`._",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# OTA rollout summarizer
# ---------------------------------------------------------------------------


def _summarize_ota_fleet(events: pd.DataFrame, header: pd.DataFrame) -> str:
    """Fleet-wide OTA rollout summary across all sampled campaigns."""
    n_events = len(events)
    n_campaigns = len(header)
    if n_events == 0:
        return ("# Fleet-wide OTA Rollout Summary\n\n"
                "No OTA event sample available at index time.\n")
    status_share = events["final_status"].value_counts(normalize=True).round(4)
    failure_statuses = {"download_failed", "install_failed", "rolled_back"}
    failure_count = int(events["final_status"].isin(failure_statuses).sum())
    failure_rate = failure_count / n_events
    declined_rate = float((events["final_status"] == "declined_by_user").mean())
    install_rate = float((events["final_status"] == "installed").mean())
    cat_share = (
        header["category"].value_counts(normalize=True).round(3)
        if "category" in header.columns else pd.Series(dtype=float)
    )
    sev_share = (
        header["severity"].value_counts(normalize=True).round(3)
        if "severity" in header.columns else pd.Series(dtype=float)
    )
    failure_reasons = (
        events.loc[events["final_status"].isin(failure_statuses), "failure_reason"]
        .dropna()
        .value_counts()
        .head(DEFAULT_TOP_N)
        if "failure_reason" in events.columns else pd.Series(dtype=int)
    )

    lines = [
        "# Fleet-wide OTA Rollout Summary",
        "",
        f"_Source: ``ota_campaigns`` ({n_campaigns} sampled campaigns) + "
        f"``ota_campaign_events`` ({n_events} sampled dispatch rows). "
        "Distribution is directional; full table lives in Athena "
        "`adp_<stage>_ota_campaigns.{ota_campaigns,ota_campaign_events}`._",
        "",
        "## Final-status mix (all sampled events)",
        "",
    ]
    for k, v in status_share.items():
        lines.append(f"- **{k}**: {float(v):.2%}")
    lines += [
        "",
        "## Headline rates",
        "",
        f"- **Install rate** (final_status = `installed`): {install_rate:.2%}",
        f"- **Failure rate** (download_failed + install_failed + rolled_back): {failure_rate:.2%}",
        f"- **Decline rate** (declined_by_user): {declined_rate:.2%}",
        "",
    ]
    if not cat_share.empty:
        lines += ["## Category mix (campaigns)", ""]
        for k, v in cat_share.items():
            lines.append(f"- **{k}**: {float(v):.1%}")
        lines.append("")
    if not sev_share.empty:
        lines += ["## Severity mix (campaigns)", ""]
        for k, v in sev_share.items():
            lines.append(f"- **{k}**: {float(v):.1%}")
        lines.append("")
    if not failure_reasons.empty:
        lines += ["## Top failure reasons (free-text)", ""]
        for reason, count in failure_reasons.items():
            excerpt = str(reason).replace("\n", " ").strip()
            if len(excerpt) > 200:
                excerpt = excerpt[:197] + "..."
            lines.append(f"- **{count} occurrences**: \"{excerpt}\"")
        lines.append("")
    lines.append(
        "_For per-VIN rollout history use the §4.2 join in "
        "`docs/cvx-integration-contract.md` — this fleet aggregate is "
        "for KB-level grounding only._"
    )
    return "\n".join(lines) + "\n"


def _summarize_ota_per_campaign(
    events: pd.DataFrame,
    header: pd.DataFrame,
    *,
    limit: int = DEFAULT_CAMPAIGN_SUMMARY_LIMIT,
) -> list[tuple[str, str, str]]:
    """Per-campaign rollout summaries — returns ``[(slug, title, body), ...]``.

    Limited to the ``limit`` most-dispatched campaigns from the sample
    so the KB index size stays bounded.
    """
    if events.empty or header.empty:
        return []
    by_campaign = events.groupby("campaign_id").size().sort_values(ascending=False).head(limit)
    out: list[tuple[str, str, str]] = []
    header_indexed = header.set_index("campaign_id") if "campaign_id" in header.columns else None
    failure_statuses = {"download_failed", "install_failed", "rolled_back"}
    for campaign_id, dispatch_count in by_campaign.items():
        sub = events[events["campaign_id"] == campaign_id]
        installed = int((sub["final_status"] == "installed").sum())
        failed = int(sub["final_status"].isin(failure_statuses).sum())
        declined = int((sub["final_status"] == "declined_by_user").sum())
        meta = {}
        if header_indexed is not None and campaign_id in header_indexed.index:
            row = header_indexed.loc[campaign_id]
            for col in ("campaign_name", "release_version", "category",
                        "severity", "package_size_mb", "status"):
                if col in header_indexed.columns:
                    meta[col] = row[col]
        slug = str(campaign_id).lower().replace("_", "-")
        title = (
            f"OTA Rollout — {meta.get('campaign_name', campaign_id)} "
            f"({meta.get('release_version', 'unknown release')})"
        )
        lines = [
            f"# {title}",
            "",
            f"- campaign_id: `{campaign_id}`",
        ]
        for k, v in meta.items():
            lines.append(f"- {k}: `{v}`")
        lines += [
            "",
            f"## Dispatch outcomes ({dispatch_count} sampled rows)",
            "",
            f"- Installed: **{installed}** ({installed / dispatch_count:.1%})",
            f"- Failed (download/install/rolled_back): **{failed}** ({failed / dispatch_count:.1%})",
            f"- Declined by user: **{declined}** ({declined / dispatch_count:.1%})",
            "",
            "_Sample-derived numbers; full per-campaign rollout history "
            "lives in `ota_campaign_events`._",
        ]
        out.append((slug, title, "\n".join(lines) + "\n"))
    return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _build_extended_artifacts(
    *,
    service_records: pd.DataFrame,
    charging_sessions: pd.DataFrame,
    ota_campaigns: pd.DataFrame,
    ota_campaign_events: pd.DataFrame,
    campaign_summary_limit: int,
) -> list[tuple[str, str, str, str, str]]:
    """Build the (relpath, source_doc_id, title, category, body) tuples."""
    rows: list[tuple[str, str, str, str, str]] = []

    # Service-records — failure patterns (tsb_recall) + complaint themes
    # (service_policy). source_doc_id prefixed `SVC-` so consumers can
    # filter SVC-* to scope to data-derived summaries only.
    rows.append((
        "sources/extended/service_failure_patterns.md",
        "SVC-FAILURE-TOP-N",
        "Top Failure Patterns (Sampled Service Records)",
        "tsb_recall",
        _summarize_failure_patterns(service_records),
    ))
    rows.append((
        "sources/extended/service_complaint_themes.md",
        "SVC-COMPLAINT-THEMES",
        "Customer Complaint Themes (Sampled Service Records)",
        "service_policy",
        _summarize_complaint_themes(service_records),
    ))

    # Charging-pattern narrative — supplements the base generator's
    # static charging_narrative docs with data-derived distributions.
    rows.append((
        "sources/extended/charging_patterns_sampled.md",
        "CHARGE-PATTERNS-SAMPLED",
        "Charging Patterns (Sampled Charging Sessions)",
        "charging_narrative",
        _summarize_charging_patterns(charging_sessions),
    ))

    # OTA rollout — fleet-wide aggregate.
    rows.append((
        "sources/extended/ota_rollout_fleet_summary.md",
        "OTA-FLEET-SUMMARY",
        "Fleet-wide OTA Rollout Summary",
        "ota_rollout_summary",
        _summarize_ota_fleet(ota_campaign_events, ota_campaigns),
    ))

    # OTA rollout — per-campaign (sampled, capped).
    for slug, title, body in _summarize_ota_per_campaign(
        ota_campaign_events, ota_campaigns, limit=campaign_summary_limit
    ):
        rows.append((
            f"sources/extended/ota_rollout_{slug}.md",
            f"OTA-CAMPAIGN-{slug.upper()}",
            title,
            "ota_rollout_summary",
            body,
        ))

    return rows


def run(
    *,
    output_root: Path | str,
    curated_root: Path | str | None = None,
    s3_root: str | None = None,
    region: str = "us-east-1",
    max_rows_per_product: int = DEFAULT_MAX_ROWS_PER_PRODUCT,
    campaign_summary_limit: int = DEFAULT_CAMPAIGN_SUMMARY_LIMIT,
    chunk_size_tokens: int = base.DEFAULT_CHUNK_SIZE_TOKENS,
    chunk_overlap_tokens: int = base.DEFAULT_CHUNK_OVERLAP_TOKENS,
    embedding_model: str = base.DEFAULT_EMBEDDING_MODEL,
    upload: bool = False,
) -> dict:
    """Run the extended seed.

    Parameters
    ----------
    output_root
        Local directory under which ``sources/extended/`` and
        ``manifest_extended.json`` are written. Created if missing.
    curated_root
        Optional path to a Group-3 curated tree. When provided and
        non-empty, samples are read from
        ``<curated_root>/{service_records,charging_sessions,ota_campaigns}``.
        When ``None`` or empty, falls back to the deterministic
        synthetic sample (via :func:`_synthesize_sample_frames`).
    s3_root
        ``s3://bucket/prefix`` populated into each chunk's ``s3_uri``.
        Defaults to the staging path declared in the base generator.
    upload
        When True, lazy-imports ``boto3`` and uploads the local tree
        under ``output_root`` to ``s3_root``.

    Returns
    -------
    dict
        Summary written alongside ``manifest_extended.json``.
    """
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if s3_root is None:
        s3_root = base.DEFAULT_STAGING_S3_ROOT

    # Sanity-check the schema column contract before doing any work.
    schema = sl.load_schema("vehicle_knowledge_base", kind="product")
    table = schema.first_table()
    if table.storage_format != "documents":
        raise RuntimeError(
            f"vehicle_knowledge_base.storage_format must be 'documents', "
            f"got {table.storage_format!r}"
        )
    enum_values = set(table.column_by_name("source_category").enum_values or ())
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
            f"schema.yaml is missing required columns: {sorted(missing)}"
        )

    # Resolve sample frames. Use curated parquet when available,
    # synthetic fallback otherwise.
    data_source: str
    if curated_root is not None:
        curated_root_p = Path(curated_root)
        svc_files = _list_parquet_files(curated_root_p, "service_records")
        chg_files = _list_parquet_files(curated_root_p, "charging_sessions")
        ota_header_files = _list_parquet_files(curated_root_p, "ota_campaigns")
        # ota_campaigns may store header + events in the same product
        # tree (multi-table). Best-effort: read all and split by
        # presence of `vin` column (events) vs absence (header).
        if any([svc_files, chg_files, ota_header_files]):
            data_source = f"curated:{curated_root_p}"
            svc = _read_sample_frame(
                svc_files,
                columns=["service_type", "complaint_text", "dtc_codes",
                         "outcome", "csat_score", "labor_hours",
                         "warranty_covered"],
                max_rows=max_rows_per_product,
            )
            chg = _read_sample_frame(
                chg_files,
                columns=["station_type", "network_provider", "kwh_delivered",
                         "duration_seconds", "interrupted", "interrupt_reason",
                         "start_soc_pct", "end_soc_pct", "connector_type"],
                max_rows=max_rows_per_product,
            )
            # Read ota header + events together by reading raw and
            # splitting on the presence of `vin` (events have it, header
            # doesn't).
            all_ota = _read_sample_frame(
                ota_header_files,
                columns=None,  # need to inspect schema, take what's there
                max_rows=max_rows_per_product * 2,
            )
            if "vin" in all_ota.columns:
                events = all_ota[all_ota["vin"].notna()]
                header = all_ota[all_ota["vin"].isna()]
                # Drop the empty `vin` column from header for cleanliness.
                if "vin" in header.columns:
                    header = header.drop(columns=["vin"])
            else:
                # Either pure-header tree or curated split is unusual;
                # treat the whole thing as header and synthesize empty events.
                header = all_ota
                events = pd.DataFrame(columns=["campaign_id", "vin", "final_status",
                                               "failure_reason"])
        else:
            data_source = f"synthetic_fallback:{curated_root_p} (empty)"
            frames = _synthesize_sample_frames()
            svc = frames["service_records"]
            chg = frames["charging_sessions"]
            header = frames["ota_campaigns"]
            events = frames["ota_campaign_events"]
    else:
        data_source = "synthetic_fallback:no curated_root"
        frames = _synthesize_sample_frames()
        svc = frames["service_records"]
        chg = frames["charging_sessions"]
        header = frames["ota_campaigns"]
        events = frames["ota_campaign_events"]

    started = time.time()
    artifacts = _build_extended_artifacts(
        service_records=svc,
        charging_sessions=chg,
        ota_campaigns=header,
        ota_campaign_events=events,
        campaign_summary_limit=campaign_summary_limit,
    )

    chunks: list[dict] = []
    artifact_records: list[dict] = []
    indexed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    for relpath, source_doc_id, title, category, body in artifacts:
        if category not in enum_values:
            raise RuntimeError(
                f"extended_seed produced unsupported source_category "
                f"{category!r}; allowed: {sorted(enum_values)}"
            )
        local_path = output_root / relpath
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(body, encoding="utf-8")
        artifact_records.append({
            "relpath": relpath,
            "source_doc_id": source_doc_id,
            "title": title,
            "category": category,
            "size_bytes": local_path.stat().st_size,
            "sha256": base._sha256_path(local_path),
        })
        s3_uri = base._resolve_s3_uri(s3_root, relpath)
        for idx, chunk_text in enumerate(base._split_into_chunks(
            body,
            chunk_size_tokens=chunk_size_tokens,
            chunk_overlap_tokens=chunk_overlap_tokens,
        )):
            chunks.append({
                "chunk_id": base._chunk_id(source_doc_id, idx),
                "source_doc_id": source_doc_id,
                "source_category": category,
                "title": title,
                "chunk_index": idx,
                "chunk_text": chunk_text,
                "chunk_size_tokens": base._approx_token_count(chunk_text),
                "chunk_overlap_tokens": chunk_overlap_tokens,
                "embedding_model": embedding_model,
                "s3_uri": s3_uri,
                "language": base.DEFAULT_LANGUAGE,
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
        "manifest_kind": "extended_seed",
        "data_source": data_source,
        "generated_at_utc": indexed_at,
        "elapsed_seconds": elapsed,
        "embedding_model": embedding_model,
        "chunk_size_tokens": chunk_size_tokens,
        "chunk_overlap_tokens": chunk_overlap_tokens,
        "max_rows_per_product": max_rows_per_product,
        "campaign_summary_limit": campaign_summary_limit,
        "s3_root": s3_root,
        "artifact_count": len(artifact_records),
        "chunk_count": len(chunks),
        "chunks_by_category": by_category,
        "sample_row_counts": {
            "service_records": int(len(svc)),
            "charging_sessions": int(len(chg)),
            "ota_campaigns_header": int(len(header)),
            "ota_campaign_events": int(len(events)),
        },
        "artifacts": artifact_records,
        "chunks": chunks,
        "bedrock_kb_status": "DEFERRED_TO_GROUP_5_INFRA",
    }
    manifest_path = output_root / "manifest_extended.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    summary = {
        "product": "vehicle_knowledge_base",
        "manifest_kind": "extended_seed",
        "data_source": data_source,
        "output_root": str(output_root),
        "s3_root": s3_root,
        "artifact_count": len(artifact_records),
        "chunk_count": len(chunks),
        "chunks_by_category": by_category,
        "sample_row_counts": manifest["sample_row_counts"],
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
        description="Generate the extended Bedrock-KB seed for "
                    "vehicle_knowledge_base — narrative summaries derived "
                    "from sampled service_records, charging_sessions, "
                    "and ota_campaigns parquet output."
    )
    p.add_argument(
        "--output-root", default="curated/vehicle_knowledge_base",
        help="Local directory for extended artifacts + manifest "
             "(default: curated/vehicle_knowledge_base — sits alongside "
             "the base generator's output).",
    )
    p.add_argument(
        "--curated-root", default=None,
        help="Optional path to a Group-3 curated tree (containing "
             "service_records/, charging_sessions/, ota_campaigns/ "
             "subdirectories). Falls back to a deterministic synthetic "
             "sample when missing or empty.",
    )
    p.add_argument(
        "--s3-root", default=None,
        help="s3://bucket/prefix used in each chunk's s3_uri. "
             f"Defaults to {base.DEFAULT_STAGING_S3_ROOT}.",
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
        "--max-rows-per-product", type=int,
        default=DEFAULT_MAX_ROWS_PER_PRODUCT,
        help=f"Max rows sampled per source product "
             f"(default: {DEFAULT_MAX_ROWS_PER_PRODUCT}). KB index size "
             f"limit per Group 5 Constraint.",
    )
    p.add_argument(
        "--campaign-summary-limit", type=int,
        default=DEFAULT_CAMPAIGN_SUMMARY_LIMIT,
        help=f"Max number of per-campaign rollout summaries "
             f"(default: {DEFAULT_CAMPAIGN_SUMMARY_LIMIT}).",
    )
    p.add_argument(
        "--chunk-size-tokens", type=int,
        default=base.DEFAULT_CHUNK_SIZE_TOKENS,
        help=f"Approx tokens per chunk "
             f"(default: {base.DEFAULT_CHUNK_SIZE_TOKENS}).",
    )
    p.add_argument(
        "--chunk-overlap-tokens", type=int,
        default=base.DEFAULT_CHUNK_OVERLAP_TOKENS,
        help=f"Approx token overlap between adjacent chunks "
             f"(default: {base.DEFAULT_CHUNK_OVERLAP_TOKENS}).",
    )
    p.add_argument(
        "--embedding-model", default=base.DEFAULT_EMBEDDING_MODEL,
        help=f"Bedrock embedding model id "
             f"(default: {base.DEFAULT_EMBEDDING_MODEL}).",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv else None)
    summary = run(
        output_root=args.output_root,
        curated_root=args.curated_root,
        s3_root=args.s3_root,
        region=args.region,
        max_rows_per_product=args.max_rows_per_product,
        campaign_summary_limit=args.campaign_summary_limit,
        chunk_size_tokens=args.chunk_size_tokens,
        chunk_overlap_tokens=args.chunk_overlap_tokens,
        embedding_model=args.embedding_model,
        upload=args.upload,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
