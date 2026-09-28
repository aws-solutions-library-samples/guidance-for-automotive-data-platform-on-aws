"""Test skeletons: manifest v2 shape + backfill idempotency (T1.3).

These tests are RED in Group 1 and go GREEN when G2/G3 land:
  - T2.3 refactors `write_manifest()` to emit the v2 shape (vintages array,
    total_row_count, last_run sub-object, top-level row_count alias).
  - T2.4 makes generators emit the per-partition sidecar `.vintage-meta.json`.
  - T2.5 authors `backfill_manifests.py`.

Design notes
------------
Synthetic parquet trees use pyarrow to write minimal 1-row parquet files.
Real curated/ data is NOT required — these tests synthesise their own fixture
trees under `tmp_path`.

The backfill idempotency test (test_backfill_idempotent) must import
`backfill_manifests`. That module does not exist until T2.5 lands. We use
`pytest.importorskip` at **function** scope rather than module scope so
collection of the other tests in this file is not blocked. Each backfill
test skips cleanly with a legible reason while the module is absent, then
auto-unblocks when T2.5 ships.

Choice rationale: module-level `pytest.importorskip` would skip the entire
file, which would hide the v2-shape tests from CI during the G1 → G2 window.
Per-function skip is more surgical.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

# ---------------------------------------------------------------------------
# Path setup — match conftest.py's pattern
# ---------------------------------------------------------------------------

_PF_ROOT = Path(__file__).resolve().parents[1]
_LIB = _PF_ROOT / "source" / "lib"
_SCRIPTS = _PF_ROOT / "source" / "scripts"

for _p in (_LIB, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import product_generator as pg  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — synthetic parquet writers
# ---------------------------------------------------------------------------

def _write_minimal_parquet(path: Path, row_count: int = 1) -> None:
    """Write a minimal 1-column parquet file with `row_count` rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table({"vin": pa.array(["TEST_VIN_0001"] * row_count, type=pa.string())})
    pq.write_table(table, path)


def _make_single_partition_tree(root: Path, product: str, table: str, row_count: int = 5) -> Path:
    """Create a synthetic curated tree with ONE partition.

    Structure:
        <root>/<product>/<table>/snapshot_date=2026-08-30/part-0.parquet
    """
    partition_dir = root / product / table / "snapshot_date=2026-08-30"
    parquet_file = partition_dir / "part-0.parquet"
    _write_minimal_parquet(parquet_file, row_count=row_count)
    return partition_dir


def _make_multi_partition_tree(
    root: Path,
    product: str,
    table: str,
    partition_dates: list[str],
    rows_per_partition: int = 5,
) -> list[Path]:
    """Create a synthetic curated tree with multiple partitions.

    Returns list of partition directories created.
    """
    dirs = []
    for date in partition_dates:
        partition_dir = root / product / table / f"snapshot_date={date}"
        parquet_file = partition_dir / "part-0.parquet"
        _write_minimal_parquet(parquet_file, row_count=rows_per_partition)
        dirs.append(partition_dir)
    return dirs


# ---------------------------------------------------------------------------
# T1.3(a): write_manifest() emits v2 shape for a single-vintage tree
# ---------------------------------------------------------------------------


def test_v2_shape_emitted(tmp_path: Path):
    """write_manifest() must produce a manifest.json with the v2 shape.

    Required top-level keys (spec.md § D2):
      - product
      - table
      - provenance
      - total_row_count (integer)
      - vintages (list, may be empty or single-element)
      - last_run (dict with seed, generated_at_utc, elapsed_seconds)
      - row_count (alias for total_row_count — backward compat for notebook reader)

    This test is RED until T2.3 refactors write_manifest() to emit the v2 shape.
    """
    product = "test_product"
    table = "test_table"
    partition_dir = _make_single_partition_tree(tmp_path, product, table, row_count=10)
    parquet_file = partition_dir / "part-0.parquet"

    manifest_path = pg.write_manifest(
        output_dir=tmp_path / product / table,
        product=product,
        table=table,
        seed=42,
        row_count=10,
        edge_case_summary={"null_vin": 0},
        elapsed_seconds=1.23,
        files=[parquet_file],
    )

    assert manifest_path.exists(), "write_manifest() must write manifest.json"

    manifest = json.loads(manifest_path.read_text())

    # --- Structural v2 assertions ---
    assert "vintages" in manifest, "v2 manifest must have a 'vintages' array"
    assert isinstance(manifest["vintages"], list), "'vintages' must be a list"

    assert "total_row_count" in manifest, "v2 manifest must have 'total_row_count'"
    assert isinstance(manifest["total_row_count"], int)

    assert "last_run" in manifest, "v2 manifest must have a 'last_run' sub-object"
    assert isinstance(manifest["last_run"], dict)

    # Backward compat alias — the notebook reads row_count at top level
    assert "row_count" in manifest, "v2 manifest must retain top-level 'row_count' alias"
    assert manifest["row_count"] == manifest["total_row_count"], (
        "row_count must equal total_row_count (backward compat alias)"
    )

    # --- Identity fields ---
    assert manifest.get("product") == product
    assert manifest.get("table") == table


# ---------------------------------------------------------------------------
# T1.3(b): total_row_count == sum of vintages[].row_count for multi-vintage tree
# ---------------------------------------------------------------------------


def test_total_row_count_sum(tmp_path: Path):
    """For a tree with 4 partitions, total_row_count must equal the sum of
    all vintage row_counts.

    Tree: 3 pre-existing partitions + 1 new one (spec.md § D2 example).
    This test is RED until T2.3 and T2.4 land.

    Each partition has 5 rows → total_row_count == 20.
    """
    product = "test_product"
    table = "test_table"
    rows_per_partition = 5
    dates = [
        "2026-05-31",
        "2026-06-30",
        "2026-07-31",
        "2026-08-30",
    ]
    partition_dirs = _make_multi_partition_tree(
        tmp_path, product, table,
        partition_dates=dates,
        rows_per_partition=rows_per_partition,
    )

    all_parquets = [d / "part-0.parquet" for d in partition_dirs]
    total_expected = rows_per_partition * len(dates)  # 20

    manifest_path = pg.write_manifest(
        output_dir=tmp_path / product / table,
        product=product,
        table=table,
        seed=42,
        row_count=rows_per_partition,  # current run's contribution
        edge_case_summary={},
        elapsed_seconds=2.5,
        files=[all_parquets[-1]],  # newest partition files
    )

    manifest = json.loads(manifest_path.read_text())

    assert "vintages" in manifest
    assert len(manifest["vintages"]) == len(dates), (
        f"Expected {len(dates)} vintages, got {len(manifest['vintages'])}"
    )

    # Sum of per-vintage row counts must equal total_row_count
    vintage_sum = sum(v["row_count"] for v in manifest["vintages"])
    assert vintage_sum == total_expected, (
        f"Sum of vintage row_counts ({vintage_sum}) != total_expected ({total_expected})"
    )
    assert manifest["total_row_count"] == total_expected
    assert manifest["row_count"] == total_expected  # backward compat alias


# ---------------------------------------------------------------------------
# T1.3(c): backfill script is idempotent — running twice produces byte-identical output
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T2.4: .vintage-meta.json sidecar emitted by write_partitioned_parquet
# ---------------------------------------------------------------------------


def test_sidecar_present_on_new_partition(tmp_path: Path):
    """write_partitioned_parquet() must emit .vintage-meta.json alongside
    each partition's parquet file.

    Shape (spec.md T2.4):
        {partition, row_count, generated_at_utc, seed, files: [{relpath, size_bytes, sha256}]}

    This test goes GREEN with T2.4.
    """
    # Write a minimal parquet using pyarrow directly, then emit the sidecar
    # via the internal helper exposed on product_generator.
    partition_dir = tmp_path / "my_product" / "my_table" / "snapshot_date=2026-08-31"
    partition_dir.mkdir(parents=True, exist_ok=True)
    pf = partition_dir / "part-0.parquet"
    tbl = pa.table({"vin": pa.array(["V001", "V002", "V003"], type=pa.string())})
    pq.write_table(tbl, pf)

    # Emit the sidecar using the internal helper
    pg._write_partition_sidecar(
        partition_dir,
        partition="snapshot_date=2026-08-31",
        row_count=3,
        seed=42,
        files=[pf],
    )

    sidecar_path = partition_dir / ".vintage-meta.json"
    assert sidecar_path.exists(), ".vintage-meta.json sidecar must be written"

    sidecar = json.loads(sidecar_path.read_text())

    # Shape assertions
    assert sidecar.get("partition") == "snapshot_date=2026-08-31"
    assert sidecar.get("row_count") == 3
    assert "generated_at_utc" in sidecar
    assert sidecar.get("seed") == 42
    assert isinstance(sidecar.get("files"), list)
    assert len(sidecar["files"]) == 1

    f0 = sidecar["files"][0]
    assert "relpath" in f0
    assert "size_bytes" in f0
    assert "sha256" in f0
    assert isinstance(f0["size_bytes"], int) and f0["size_bytes"] > 0
    assert len(f0["sha256"]) == 64  # hex SHA-256

    # Idempotent overwrite: calling again must not raise
    pg._write_partition_sidecar(
        partition_dir,
        partition="snapshot_date=2026-08-31",
        row_count=3,
        seed=42,
        files=[pf],
    )
    sidecar2 = json.loads(sidecar_path.read_text())
    assert sidecar2["row_count"] == sidecar["row_count"]


# ---------------------------------------------------------------------------
# T1.3(c): backfill script is idempotent — running twice produces byte-identical output
# ---------------------------------------------------------------------------


def test_backfill_idempotent(tmp_path: Path):
    """backfill_manifests.py is idempotent: running twice against a v2-manifest
    tree produces byte-identical output on run 2.

    This test is SKIPPED until T2.5 ships backfill_manifests.py.
    The test body is fully authored so it goes GREEN immediately when the
    module becomes importable.

    Choice of skip mechanism: per-function `pytest.importorskip` rather than
    module-level, so the v2-shape tests above (which do not require
    backfill_manifests) still run and surface failures during the G1 → G2
    window.
    """
    bm = pytest.importorskip("backfill_manifests", reason="awaits T2.5")

    product = "test_product"
    table = "test_table"
    dates = ["2026-05-31", "2026-06-30", "2026-07-31"]
    partition_dirs = _make_multi_partition_tree(
        tmp_path, product, table,
        partition_dates=dates,
        rows_per_partition=5,
    )

    # ---- First run: backfill produces the v2 manifest ----
    bm.backfill_product(
        curated_root=tmp_path,
        product=product,
        apply=True,
    )

    manifest_path = tmp_path / product / table / "manifest.json"
    assert manifest_path.exists(), "backfill must write manifest.json on first run"
    content_run1 = manifest_path.read_text()
    manifest_run1 = json.loads(content_run1)
    assert "vintages" in manifest_run1, "backfill must produce v2-shape manifest"

    # ---- Second run: byte-identical output (idempotent) ----
    bm.backfill_product(
        curated_root=tmp_path,
        product=product,
        apply=True,
    )
    content_run2 = manifest_path.read_text()

    assert content_run1 == content_run2, (
        "backfill_manifests is not idempotent: manifest.json changed on the second run.\n"
        f"Run 1 (first 200 chars): {content_run1[:200]}\n"
        f"Run 2 (first 200 chars): {content_run2[:200]}"
    )
