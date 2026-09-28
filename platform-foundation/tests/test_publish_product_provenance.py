"""Test skeletons: publish_product enforcement matrix (T1.4).

These tests are RED in Group 1 and go GREEN as G3 lands:
  - T3.1: provenance-aware branching (single-vintage vs cumulative-snapshot vs managed)
  - T3.2: --allow-purge flag with narrowed --delete sync
  - T3.3: multi-vintage summary print for cumulative-snapshot
  - T3.4: manifest.json + .vintage-meta.json excluded from sync argv

The 5 test cases map directly to spec.md § D3's behaviour matrix:

  | # | Case | Expected behaviour |
  |---|------|--------------------|
  | a | single-vintage + 1 partition | additive sync (no --delete) |
  | b | single-vintage + >1 partition (no --allow-purge) | refuse, exit nonzero, print vintages |
  | c | single-vintage + >1 partition + --allow-purge | --delete sync via _purge_sync() |
  | d | cumulative-snapshot + N partitions | additive sync + multi-vintage summary line |
  | e | managed | skip with "handled by Bedrock ingestion" note |

No real AWS calls are made. All tests monkeypatch subprocess.run so that
assertion is on the argv that *would* be passed, not on real S3 operations.
stdout/stderr are captured via capsys.

Design: tests call `publish_product.publish_product()` through its public
Python API (same pattern as test_publish_product.py's TestProdGuard) rather
than invoking via subprocess.run, so we get proper Python-level mocking.

Fixture structure
-----------------
Each test builds a minimal synthetic curated tree under tmp_path using
pathlib.mkdir + pathlib.touch for parquet files (content doesn't matter —
the publisher reads the directory structure, not the file contents, for
provenance decisions).

Schema injection
----------------
The new provenance-aware publish_product path reads provenance from
schema_loader. Rather than mutating the real schema.yaml files (forbidden),
tests monkeypatch `publish_product._load_table_provenance` (or equivalent
internal helper that the implementation will expose).

At G1 time the exact internal helper name is unknown (implementation lands
in G3). The tests use `patch.object(..., create=True)` so the patch
context manager doesn't raise AttributeError during G1 when the helper
doesn't exist yet. The tests will be RED because publish_product itself
will raise AttributeError or won't branch on provenance — not because
the patch setup fails. This is the correct RED-for-right-reason pattern.

When T3.1 lands and `_load_table_provenance` exists, remove `create=True`
from all `patch.object` calls that target it, and record the change in
decisions.md.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_PF_ROOT = Path(__file__).resolve().parents[1]
_LIB = _PF_ROOT / "source" / "lib"
_SCRIPTS = _PF_ROOT / "source" / "scripts"

for _p in (_LIB, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import publish_product as pp  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_single_partition_tree(root: Path, product: str, table: str) -> Path:
    """Create a synthetic curated/<product>/<table>/ with ONE partition subdir."""
    partition_dir = root / product / table / "snapshot_date=2026-08-30"
    partition_dir.mkdir(parents=True)
    (partition_dir / "part-0.parquet").touch()
    return root / product


def _make_multi_partition_tree(
    root: Path,
    product: str,
    table: str,
    dates: list[str] | None = None,
) -> Path:
    """Create a synthetic curated/<product>/<table>/ with MULTIPLE partition subdirs."""
    if dates is None:
        dates = ["2026-05-31", "2026-06-30", "2026-07-31"]
    for date in dates:
        d = root / product / table / f"snapshot_date={date}"
        d.mkdir(parents=True)
        (d / "part-0.parquet").touch()
    return root / product


# ---------------------------------------------------------------------------
# Shared mock builders
# ---------------------------------------------------------------------------

def _mock_subprocess_run():
    """Return a MagicMock for subprocess.run that records calls."""
    mock = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    return mock


# ---------------------------------------------------------------------------
# T1.4(a): single-vintage + 1 partition → additive sync path chosen (no --delete)
# ---------------------------------------------------------------------------


def test_single_vintage_one_partition_additive(tmp_path: Path, capsys):
    """single-vintage table with exactly 1 partition on disk → additive sync.

    Spec § D3 row 1: single-vintage + 1 partition → sync additively.
    Asserts:
      1. subprocess.run is called with an 'aws s3 sync' command.
      2. '--delete' does NOT appear in the argv of any sync call.
      3. The function does not sys.exit() (no refusal).

    Goes GREEN when T3.1 + T3.2 land.
    """
    product_dir = _make_single_partition_tree(tmp_path, "service_records", "service_records")

    sync_calls: list[list[str]] = []

    def _capture_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and "s3" in cmd and "sync" in cmd:
            sync_calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(pp, "_local_product_dir", return_value=product_dir), \
         patch.object(pp, "_resolve_account_id", return_value="123456789012"), \
         patch.object(pp, "_load_table_provenance", return_value="single-vintage", create=True), \
         patch("subprocess.run", side_effect=_capture_subprocess_run):
        # Must not raise SystemExit
        try:
            pp.publish_product(
                "service_records",
                "staging",
                apply=False,
                allow_prod=False,
            )
        except SystemExit as e:
            pytest.fail(
                f"single-vintage + 1 partition should not exit non-zero, got exit({e.code})"
            )

    # At least one sync call must have been built
    assert sync_calls, "Expected at least one aws s3 sync call for single-vintage + 1 partition"

    # None of the sync calls may include --delete
    for argv in sync_calls:
        assert "--delete" not in argv, (
            f"single-vintage + 1 partition must use additive sync (no --delete). "
            f"Got argv: {argv}"
        )


# ---------------------------------------------------------------------------
# T1.4(b): single-vintage + >1 partition → refuse, exit nonzero, print vintages
# ---------------------------------------------------------------------------


def test_single_vintage_multi_refuses(tmp_path: Path, capsys):
    """single-vintage table with >1 partition on disk → publisher refuses.

    Spec § D3 row 2: single-vintage + >1 partition (no --allow-purge) →
    refuse with non-zero exit and print the offending vintages.

    Asserts:
      1. sys.exit() is called with a non-zero code.
      2. The offending partition names appear in stdout or stderr.
      3. No 'aws s3 sync' subprocess call is made (no partial sync before refusal).

    Goes GREEN when T3.2 lands.
    """
    product_dir = _make_multi_partition_tree(
        tmp_path, "service_records", "service_records",
        dates=["2026-06-30", "2026-07-31", "2026-08-30"],
    )

    sync_calls: list[list[str]] = []

    def _capture_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and "s3" in cmd and "sync" in cmd:
            sync_calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(pp, "_local_product_dir", return_value=product_dir), \
         patch.object(pp, "_resolve_account_id", return_value="123456789012"), \
         patch.object(pp, "_load_table_provenance", return_value="single-vintage", create=True), \
         patch("subprocess.run", side_effect=_capture_subprocess_run):
        with pytest.raises(SystemExit) as exc_info:
            pp.publish_product(
                "service_records",
                "staging",
                apply=False,
                allow_prod=False,
            )

    assert exc_info.value.code != 0, (
        "single-vintage + >1 partition must exit with a non-zero code (refusal)"
    )

    # No sync must have been initiated before the refusal
    assert sync_calls == [], (
        f"Publisher must refuse before syncing. Got sync calls: {sync_calls}"
    )

    # Offending vintage names must appear in the output
    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    # At least one of the offending partition paths should be mentioned
    assert "snapshot_date=" in combined_output or "2026-" in combined_output, (
        "Refusal message must mention the offending vintages. "
        f"Output was:\n{combined_output}"
    )


# ---------------------------------------------------------------------------
# T1.4(c): single-vintage + >1 partition + --allow-purge → --delete sync path
# ---------------------------------------------------------------------------


def test_single_vintage_multi_with_purge_deletes(tmp_path: Path, capsys):
    """single-vintage + >1 partition + --allow-purge → --delete sync via _purge_sync().

    Spec § D3 row 3: the ONLY code path where --delete is ever passed.
    Asserts:
      1. subprocess.run is called with 'aws s3 sync' that includes '--delete'.
      2. The call goes through _purge_sync() (verifiable by asserting the
         helper exists on the module — it is the single --delete call site
         per spec § D3 / T3.2 constraints).
      3. No non-zero sys.exit().

    Goes GREEN when T3.2 lands.
    """
    product_dir = _make_multi_partition_tree(
        tmp_path, "service_records", "service_records",
        dates=["2026-06-30", "2026-07-31", "2026-08-30"],
    )

    sync_calls_with_delete: list[list[str]] = []

    def _capture_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and "s3" in cmd and "sync" in cmd and "--delete" in cmd:
            sync_calls_with_delete.append(list(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(pp, "_local_product_dir", return_value=product_dir), \
         patch.object(pp, "_resolve_account_id", return_value="123456789012"), \
         patch.object(pp, "_load_table_provenance", return_value="single-vintage", create=True), \
         patch("subprocess.run", side_effect=_capture_subprocess_run):
        try:
            # G3 adds allow_purge kwarg to publish_product. Until then the call
            # raises TypeError — that is acceptable RED; the assertions below
            # are the real failure signal once G3 ships.
            pp.publish_product(
                "service_records",
                "staging",
                apply=False,
                allow_prod=False,
                allow_purge=True,
            )
        except TypeError:
            # G1: allow_purge kwarg not yet accepted — expected RED state.
            # The assertions below will still fail for the right reasons once
            # the kwarg is accepted and the purge logic is implemented.
            pass
        except SystemExit as e:
            pytest.fail(
                f"single-vintage + --allow-purge should not refuse. Got exit({e.code})"
            )

    assert sync_calls_with_delete, (
        "single-vintage + >1 partition + --allow-purge must issue an "
        "aws s3 sync --delete call"
    )

    # The _purge_sync helper must exist (spec § D3 / T3.2: single --delete call site)
    assert hasattr(pp, "_purge_sync"), (
        "publish_product must expose a _purge_sync() helper as the single --delete "
        "call site (spec § D3 / T3.2)"
    )


# ---------------------------------------------------------------------------
# T1.4(d): cumulative-snapshot + N partitions → additive sync + summary line printed
# ---------------------------------------------------------------------------


def test_cumulative_snapshot_summary_printed(tmp_path: Path, capsys):
    """cumulative-snapshot → additive sync AND multi-vintage summary line printed.

    Spec § D3 row 4: cumulative-snapshot + any partition count →
    sync additively + print "publishing N vintages (N-1 pre-existing, 1 new)".

    Asserts:
      1. No --delete in any sync call.
      2. stdout contains a line mentioning the vintage count and the
         "pre-existing" / "new" framing from spec § D3.
      3. No non-zero sys.exit().

    Goes GREEN when T3.1 + T3.3 land.
    """
    product_dir = _make_multi_partition_tree(
        tmp_path, "customer_360", "customer_360",
        dates=["2026-05-31", "2026-06-30", "2026-07-31", "2026-08-30"],
    )

    sync_calls: list[list[str]] = []

    def _capture_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and "s3" in cmd and "sync" in cmd:
            sync_calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(pp, "_local_product_dir", return_value=product_dir), \
         patch.object(pp, "_resolve_account_id", return_value="123456789012"), \
         patch.object(pp, "_load_table_provenance", return_value="cumulative-snapshot", create=True), \
         patch("subprocess.run", side_effect=_capture_subprocess_run):
        try:
            pp.publish_product(
                "customer_360",
                "staging",
                apply=False,
                allow_prod=False,
            )
        except SystemExit as e:
            pytest.fail(
                f"cumulative-snapshot must not refuse. Got exit({e.code})"
            )

    # Additive sync: no --delete
    for argv in sync_calls:
        assert "--delete" not in argv, (
            f"cumulative-snapshot must use additive sync (no --delete). Got: {argv}"
        )

    # Summary line must mention vintage count
    captured = capsys.readouterr()
    stdout = captured.out
    assert "vintage" in stdout.lower(), (
        "cumulative-snapshot must print a multi-vintage summary line mentioning 'vintage(s)'. "
        f"stdout was:\n{stdout}"
    )
    # Should mention the count (4 partitions → "4 vintages" or "publishing 4")
    assert any(str(n) in stdout for n in range(2, 10)), (
        "cumulative-snapshot summary line must include the vintage count. "
        f"stdout was:\n{stdout}"
    )


# ---------------------------------------------------------------------------
# T1.4(e): managed → publisher skips with a "handled by Bedrock ingestion" note
# ---------------------------------------------------------------------------


def test_managed_skipped(tmp_path: Path, capsys):
    """managed provenance → publisher skips; prints a note about Bedrock ingestion.

    Spec § D3 row 5: managed → publisher skips (ingestion is Bedrock-owned).

    Asserts:
      1. No aws s3 sync subprocess call is made.
      2. stdout or stderr contains a message mentioning Bedrock or ingestion.
      3. No non-zero sys.exit() (clean exit with skip message).

    Goes GREEN when T3.1 lands.
    """
    product_dir = tmp_path / "vehicle_knowledge_base"
    product_dir.mkdir(parents=True)
    # Create a table subdir to simulate presence of data
    table_dir = product_dir / "vehicle_knowledge_base"
    table_dir.mkdir(parents=True)

    sync_calls: list[list[str]] = []

    def _capture_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and "s3" in cmd and "sync" in cmd:
            sync_calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(pp, "_local_product_dir", return_value=product_dir), \
         patch.object(pp, "_resolve_account_id", return_value="123456789012"), \
         patch.object(pp, "_load_table_provenance", return_value="managed", create=True), \
         patch("subprocess.run", side_effect=_capture_subprocess_run):
        try:
            pp.publish_product(
                "vehicle_knowledge_base",
                "staging",
                apply=False,
                allow_prod=False,
            )
        except SystemExit as e:
            pytest.fail(
                f"managed provenance must not exit non-zero. Got exit({e.code})"
            )

    # No sync calls for managed products
    assert sync_calls == [], (
        f"managed product must skip S3 sync. Got sync calls: {sync_calls}"
    )

    # Output must mention Bedrock ingestion
    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert "bedrock" in combined_output.lower() or "ingestion" in combined_output.lower(), (
        "managed product skip message must mention Bedrock or ingestion. "
        f"Output was:\n{combined_output}"
    )


# ---------------------------------------------------------------------------
# T1.4 bonus: manifest.json is excluded from sync argv
#
# This maps to T3.4's Verify: unit test asserts against captured argv.
# Included here per the spec's T1.4 "5 red test cases" scope — this is the
# 5-case requirement from tasks.md, and the manifest exclude is one of the
# cases the publish_product tests must cover (it exercises T3.4's contract).
# ---------------------------------------------------------------------------


def test_manifest_excluded_from_sync(tmp_path: Path, capsys):
    """aws s3 sync argv must include --exclude 'manifest.json' excludes.

    Spec § D4: manifest.json must NOT be synced to the Glue LOCATION.
    T3.4 adds the --exclude flags to every sync invocation.

    Asserts that every aws s3 sync call includes:
      --exclude manifest.json
      --exclude */manifest.json

    Goes GREEN when T3.4 lands.
    """
    product_dir = _make_single_partition_tree(tmp_path, "service_records", "service_records")

    sync_calls: list[list[str]] = []

    def _capture_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and "s3" in cmd and "sync" in cmd:
            sync_calls.append(list(cmd))
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(pp, "_local_product_dir", return_value=product_dir), \
         patch.object(pp, "_resolve_account_id", return_value="123456789012"), \
         patch.object(pp, "_load_table_provenance", return_value="single-vintage", create=True), \
         patch("subprocess.run", side_effect=_capture_subprocess_run):
        try:
            pp.publish_product(
                "service_records",
                "staging",
                apply=False,
                allow_prod=False,
            )
        except SystemExit as e:
            pytest.fail(f"Unexpected exit: {e.code}")

    assert sync_calls, "Expected at least one sync call"

    for argv in sync_calls:
        # Find all --exclude values in the argv
        exclude_values = [
            argv[i + 1] for i, arg in enumerate(argv)
            if arg == "--exclude" and i + 1 < len(argv)
        ]
        assert "manifest.json" in exclude_values, (
            f"sync argv must include --exclude manifest.json. "
            f"Got --exclude values: {exclude_values}\n"
            f"Full argv: {argv}"
        )
        assert "*/manifest.json" in exclude_values, (
            f"sync argv must include --exclude */manifest.json. "
            f"Got --exclude values: {exclude_values}\n"
            f"Full argv: {argv}"
        )
        assert "*/.vintage-meta.json" in exclude_values, (
            f"sync argv must include --exclude */.vintage-meta.json (sidecar). "
            f"aws s3 sync does NOT skip dotfiles by default — "
            f"see spec security-review Cycle 2 Suggestion 3 + T3.4. "
            f"Got --exclude values: {exclude_values}\n"
            f"Full argv: {argv}"
        )
