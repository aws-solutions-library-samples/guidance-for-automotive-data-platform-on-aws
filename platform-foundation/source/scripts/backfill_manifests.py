"""backfill_manifests.py — one-shot v2 manifest backfill for existing curated/ trees.

Usage (from platform-foundation/):
    python source/scripts/backfill_manifests.py            # dry-run (default)
    python source/scripts/backfill_manifests.py --apply    # execute writes

What it does
------------
For every product in ``curated/`` (except ``vehicle_knowledge_base``, whose
provenance is ``managed`` and whose publisher is Bedrock ingestion), walks
the on-disk partition tree and reconstructs a v2 manifest.json using
``product_generator.write_manifest()`` helpers.

Idempotency
-----------
If a v2 manifest already exists (has ``vintages`` and ``total_row_count``
keys), the script preserves the existing ``last_run`` sub-object so that
re-running against a v2-manifest tree produces byte-identical output.
It only rewrites the manifest if vintages or row counts have changed.

Dry-run default
---------------
Without ``--apply``, the script prints what would be written without
touching disk.  ``--apply`` gates all writes.

Skipped products
----------------
``vehicle_knowledge_base`` — provenance is ``managed``; its KB is governed
by Bedrock ingestion, not this publisher.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup — work from platform-foundation/source/lib/
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_PF_ROOT = _SCRIPT_DIR.parent.parent  # platform-foundation/
_LIB = _PF_ROOT / "source" / "lib"

if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import product_generator as pg  # noqa: E402

# Products whose provenance is "managed" — skip entirely.
_SKIP_PRODUCTS = {"vehicle_knowledge_base"}


# ---------------------------------------------------------------------------
# Public API (used by tests via pytest.importorskip)
# ---------------------------------------------------------------------------


def backfill_product(
    *,
    curated_root: Path,
    product: str,
    apply: bool = False,
) -> dict[str, Any]:
    """Backfill v2 manifests for every table under ``<curated_root>/<product>/``.

    Returns a summary dict keyed by table name with ``"status"`` of
    ``"written"``, ``"skipped"`` (already v2), or ``"dry-run"``.

    ``apply=True`` writes to disk.  Default is dry-run.

    Idempotency contract: if the manifest already has ``vintages`` and
    ``total_row_count`` (v2 shape), the function preserves the existing
    ``last_run`` block on all subsequent runs so that the JSON output is
    byte-identical.  It only rewrites when vintages change.
    """
    product_dir = curated_root / product
    if not product_dir.exists():
        return {}

    results: dict[str, Any] = {}

    # Each subdirectory of <product>/ is a table directory.
    for table_dir in sorted(product_dir.iterdir()):
        if not table_dir.is_dir():
            continue
        table = table_dir.name
        manifest_path = table_dir / "manifest.json"

        # --- Read existing manifest (if any) ---
        existing: dict[str, Any] | None = None
        if manifest_path.exists():
            try:
                existing = json.loads(manifest_path.read_text())
            except (json.JSONDecodeError, OSError):
                existing = None

        # --- Build vintages from disk (deterministic) ---
        vintages: list[dict] = []
        for partition_name, partition_dir in pg._enumerate_partitions(table_dir):
            sidecar = pg._read_partition_sidecar(partition_dir)
            if sidecar is not None:
                vintage_entry: dict = {
                    "partition": sidecar.get("partition", partition_name),
                    "row_count": sidecar.get("row_count", 0),
                    "generated_at_utc": sidecar.get("generated_at_utc", "unknown"),
                    "files": sidecar.get("files", []),
                }
            else:
                vintage_entry = pg._infer_partition_vintage(partition_dir, partition_name)
            vintages.append(vintage_entry)

        total_row_count = sum(v["row_count"] for v in vintages)

        # --- Determine last_run ---
        # Preserve existing last_run for idempotency: if a v2 manifest
        # already exists, its last_run is stable (it was set at generation
        # time or on the first backfill).  Reusing it makes run2 identical.
        if (
            existing is not None
            and "last_run" in existing
            and isinstance(existing["last_run"], dict)
        ):
            last_run = existing["last_run"]
        elif existing is not None and "seed" in existing:
            # v1 manifest — migrate its flat keys into last_run.
            last_run = {
                "seed": existing.get("seed"),
                "generated_at_utc": existing.get("generated_at_utc", "unknown"),
                "elapsed_seconds": existing.get("elapsed_seconds", 0.0),
                "edge_case_summary": existing.get("edge_case_summary", {}),
                "edge_case_aggregate_rate": existing.get("edge_case_aggregate_rate", 0.0),
            }
        else:
            # No existing manifest — derive from newest vintage timestamp.
            latest_ts = "unknown"
            for v in vintages:
                ts = v.get("generated_at_utc", "unknown")
                if ts > latest_ts:
                    latest_ts = ts
            last_run = {
                "seed": None,
                "generated_at_utc": latest_ts,
                "elapsed_seconds": 0.0,
                "edge_case_summary": {},
                "edge_case_aggregate_rate": 0.0,
            }

        # --- Build v2 manifest ---
        new_manifest: dict = {
            "product": product,
            "table": table,
            "provenance": (
                existing.get("provenance")
                if existing is not None
                else None
            ),
            "total_row_count": total_row_count,
            "row_count": total_row_count,  # backward-compat alias
            "vintages": vintages,
            "last_run": last_run,
        }
        new_content = json.dumps(new_manifest, indent=2, default=str)

        # --- Check if write is needed ---
        if existing is not None:
            # Compare vintages + total_row_count; if identical, skip write
            # to preserve idempotency on run2.
            existing_v2 = (
                "vintages" in existing
                and "total_row_count" in existing
            )
            if existing_v2:
                # Re-serialise the new manifest and compare.
                existing_content = json.dumps(
                    json.loads(manifest_path.read_text()),
                    indent=2,
                    default=str,
                )
                if new_content == existing_content:
                    results[table] = {
                        "status": "skipped",
                        "reason": "already-v2-identical",
                        "total_row_count": total_row_count,
                        "num_vintages": len(vintages),
                    }
                    continue

        if not apply:
            print(
                f"[dry-run] {product}/{table}: "
                f"total_row_count={total_row_count}, {len(vintages)} vintages"
            )
            results[table] = {
                "status": "dry-run",
                "total_row_count": total_row_count,
                "num_vintages": len(vintages),
            }
            continue

        # --- Write ---
        # Atomic write via temp + rename for safety.
        import os
        import tempfile

        table_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=table_dir, prefix=".manifest.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(new_content)
            os.replace(tmp_path, manifest_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        print(
            f"[written] {product}/{table}: "
            f"total_row_count={total_row_count}, {len(vintages)} vintages"
        )
        results[table] = {
            "status": "written",
            "total_row_count": total_row_count,
            "num_vintages": len(vintages),
        }

    return results


def backfill_all(
    *,
    curated_root: Path,
    apply: bool = False,
    skip_products: set[str] | None = None,
) -> dict[str, Any]:
    """Backfill v2 manifests for all products under ``curated_root``.

    Skips products in ``skip_products`` (defaults to ``_SKIP_PRODUCTS``).
    """
    if skip_products is None:
        skip_products = _SKIP_PRODUCTS

    summary: dict[str, Any] = {}
    for product_dir in sorted(curated_root.iterdir()):
        if not product_dir.is_dir():
            continue
        product = product_dir.name
        if product in skip_products:
            print(f"[skip] {product} (provenance=managed)")
            continue
        result = backfill_product(
            curated_root=curated_root,
            product=product,
            apply=apply,
        )
        summary[product] = result
    return summary


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill v2 manifest.json for all products under platform-foundation/curated/. "
            "Dry-run by default; use --apply to write."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write manifests to disk (default: dry-run only)",
    )
    parser.add_argument(
        "--curated-root",
        type=Path,
        default=_PF_ROOT / "curated",
        help="Path to curated/ directory (default: platform-foundation/curated/)",
    )
    parser.add_argument(
        "--product",
        type=str,
        default=None,
        help="Backfill a single product only (default: all products)",
    )
    args = parser.parse_args()

    curated_root: Path = args.curated_root
    if not curated_root.exists():
        print(f"[error] curated root does not exist: {curated_root}", file=sys.stderr)
        sys.exit(1)

    if args.product:
        result = backfill_product(
            curated_root=curated_root,
            product=args.product,
            apply=args.apply,
        )
        print(f"\nResult for {args.product}: {result}")
    else:
        summary = backfill_all(curated_root=curated_root, apply=args.apply)
        written = sum(
            1
            for prod in summary.values()
            for tbl in prod.values()
            if isinstance(tbl, dict) and tbl.get("status") == "written"
        )
        dry_run = sum(
            1
            for prod in summary.values()
            for tbl in prod.values()
            if isinstance(tbl, dict) and tbl.get("status") == "dry-run"
        )
        skipped = sum(
            1
            for prod in summary.values()
            for tbl in prod.values()
            if isinstance(tbl, dict) and tbl.get("status") == "skipped"
        )
        if args.apply:
            print(f"\nDone: {written} written, {skipped} skipped (already v2).")
        else:
            print(
                f"\n[dry-run complete] {dry_run} would be written. "
                "Re-run with --apply to execute."
            )


if __name__ == "__main__":
    _cli()
