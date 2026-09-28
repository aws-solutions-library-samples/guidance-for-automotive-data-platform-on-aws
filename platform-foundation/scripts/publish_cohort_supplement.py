"""publish_cohort_supplement.py — Additively publish part-supp-* files to S3.

Wraps the four-step additive supplement publish workflow so that:
  1. A pre-publish ETag snapshot guards against any subsequent base modification.
  2. Only part-supp-* keys are uploaded (``aws s3 cp`` per file, never ``--delete``).
  3. ``publish_product.py --register-only`` runs MSCK REPAIR so Athena discovers
     both the existing base parquet and the new supplement files.
  4. The ETag snapshot is verified — any changed or deleted base key exits non-zero.

Three pre-flight checks run BEFORE Step 1 (before any S3 write):
  PF-1  The local supplement tree contains only part-supp-* files (no data.parquet
        or other base files that could be accidentally uploaded).
  PF-2  The Glue table location of <product_db>.<product>_raw matches the S3
        prefix that Steps 1/2/4 operate on (read-only; catches a misconfigured
        stage or a cross-product invocation).
  PF-3  ``publish_product.py --register-only`` is runnable from its own tree
        (``curated/<product>/`` exists under PF_ROOT).  Verifies Step 3 will
        not exit 1 after Step 2 has already uploaded objects.

Step 4 (ETag verify) runs even if Step 2 or Step 3 fails, so that any
accidental base-object change during the upload window is still detected.

Usage (dry-run by default, --apply to execute):

  # Dry-run — prints every command, writes nothing:
  python3 scripts/publish_cohort_supplement.py \\
      --product service_records \\
      --stage staging \\
      --local-root curated/service_records/service_records \\
      --supplement-salt 901 \\
      --snapshot-file /tmp/pre-publish-etags.json

  # Apply:
  python3 scripts/publish_cohort_supplement.py \\
      --product service_records \\
      --stage staging \\
      --local-root curated/service_records/service_records \\
      --supplement-salt 901 \\
      --snapshot-file /tmp/pre-publish-etags.json \\
      --apply

Safety design:
  - Dry-run is the default; pass --apply to execute.
  - Never passes --delete to aws s3 sync or aws s3 cp.
  - Uploads only files matching part-supp-{salt}.parquet.
  - Calls publish_product.py --register-only (no S3 write).
  - Fails closed on any AWS or subprocess error.
  - Never writes to prod without --allow-prod.
  - Pre-flights abort before any upload; ETag verify always runs after Step 1.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_REGION = "us-east-1"


# ---------------------------------------------------------------------------
# Account / bucket helpers (mirrors publish_product.py without importing it)
# ---------------------------------------------------------------------------

def _resolve_account_id() -> str:
    result = subprocess.run(
        ["aws", "sts", "get-caller-identity",
         "--query", "Account", "--output", "text",
         "--region", _REGION],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _lake_bucket_name(stage: str, account_id: str) -> str:
    return f"adp-{stage}-foundation-lake-{account_id}-{_REGION}"


# ---------------------------------------------------------------------------
# ETag snapshot / verify helpers (thin wrappers over check_base_reproduction)
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_CHECK_SCRIPT = _SCRIPTS_DIR / "check_base_reproduction.py"


def _etag_snapshot(
    bucket: str, prefix: str, snapshot_file: Path, *, apply: bool,
) -> None:
    """Take an ETag snapshot of the current S3 objects under prefix."""
    cmd = [
        sys.executable, str(_CHECK_SCRIPT),
        "snapshot",
        "--bucket", bucket,
        "--prefix", prefix,
        "--snapshot-file", str(snapshot_file),
        "--region", _REGION,
    ]
    if not apply:
        print(f"[DRY-RUN] Would run ETag snapshot:\n  {' '.join(cmd)}")
        return
    print(f"[STEP 1] ETag snapshot ...")
    result = subprocess.run(cmd, capture_output=False, check=False)
    if result.returncode != 0:
        print("[STEP 1] FAIL: snapshot command exited non-zero.", file=sys.stderr)
        sys.exit(1)


def _etag_verify(
    bucket: str, prefix: str, snapshot_file: Path, *, apply: bool,
) -> None:
    """Verify current S3 ETags against the snapshot — fail if any base key changed."""
    cmd = [
        sys.executable, str(_CHECK_SCRIPT),
        "verify",
        "--bucket", bucket,
        "--prefix", prefix,
        "--snapshot-file", str(snapshot_file),
        "--region", _REGION,
    ]
    if not apply:
        print(f"[DRY-RUN] Would run ETag verify:\n  {' '.join(cmd)}")
        return
    print(f"[STEP 4] ETag verify ...")
    result = subprocess.run(cmd, capture_output=False, check=False)
    if result.returncode != 0:
        print(
            "[STEP 4] FAIL: ETag verify detected a changed or deleted base object. "
            "The base was modified during the publish window.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("[STEP 4] PASS: all pre-existing base objects kept their ETag.")


# ---------------------------------------------------------------------------
# Upload step: only part-supp-{salt}.parquet files, never --delete
# ---------------------------------------------------------------------------

def _upload_supplement_files(
    local_root: Path,
    bucket: str,
    s3_prefix: str,
    supplement_salt: int,
    *,
    apply: bool,
) -> list[str]:
    """Upload part-supp-{salt}.parquet files from each partition directory.

    Uses ``aws s3 cp`` per file — NEVER ``aws s3 sync --delete``.  Returns
    the list of S3 keys that were (or would be) uploaded.
    """
    supp_filename = f"part-supp-{supplement_salt}.parquet"
    supp_files = sorted(local_root.rglob(supp_filename))

    if not supp_files:
        print(
            f"[STEP 2] ERROR: no {supp_filename} files found under {local_root}.",
            file=sys.stderr,
        )
        sys.exit(1)

    uploaded_keys: list[str] = []
    for local_file in supp_files:
        # Compute relative key: partitions live under local_root so
        # part-supp-901.parquet in service_month=2025-01-01/ becomes
        # {s3_prefix}service_month=2025-01-01/part-supp-901.parquet
        rel = local_file.relative_to(local_root)
        s3_key = f"{s3_prefix}{rel.as_posix()}"
        s3_uri = f"s3://{bucket}/{s3_key}"

        cmd = ["aws", "s3", "cp", str(local_file), s3_uri, "--region", _REGION]

        if not apply:
            print(f"[DRY-RUN] Would upload: {local_file} → {s3_uri}")
        else:
            print(f"  cp {local_file.name} → {s3_uri}")
            result = subprocess.run(cmd, capture_output=False, check=False)
            if result.returncode != 0:
                print(
                    f"[STEP 2] FAIL: aws s3 cp exited non-zero for {local_file}.",
                    file=sys.stderr,
                )
                sys.exit(1)

        uploaded_keys.append(s3_key)

    print(
        f"[STEP 2] {'Would upload' if not apply else 'Uploaded'} "
        f"{len(uploaded_keys)} {supp_filename} file(s)."
    )
    return uploaded_keys


# ---------------------------------------------------------------------------
# Register-only step via publish_product.py
# ---------------------------------------------------------------------------

_PUBLISH_PRODUCT = (
    Path(__file__).resolve().parents[1]
    / "source" / "scripts" / "publish_product.py"
)


def _register_only(
    product: str,
    stage: str,
    *,
    apply: bool,
    allow_prod: bool,
) -> None:
    """Run publish_product.py --register-only to run MSCK REPAIR + DDL."""
    cmd = [
        sys.executable, str(_PUBLISH_PRODUCT),
        "--product", product,
        "--stage", stage,
        "--register-only",
    ]
    if apply:
        cmd.append("--apply")
    if allow_prod:
        cmd.append("--allow-prod")

    if not apply:
        print(f"[DRY-RUN] Would run register-only:\n  {' '.join(cmd)}")
        return

    print(f"[STEP 3] Running publish_product.py --register-only ...")
    result = subprocess.run(cmd, capture_output=False, check=False)
    if result.returncode != 0:
        print("[STEP 3] FAIL: publish_product.py --register-only exited non-zero.", file=sys.stderr)
        sys.exit(1)
    print("[STEP 3] PASS: catalog registration complete.")


# ---------------------------------------------------------------------------
# Pre-flight checks (run before any S3 write)
# ---------------------------------------------------------------------------

class PreflightError(RuntimeError):
    """Raised when a pre-flight check fails; abort before any upload."""


def _preflight_local_files_only(local_root: Path, supplement_salt: int) -> None:
    """PF-1: every file under local_root is part-supp-{salt}.parquet.

    Aborts if any non-supplement file is present (e.g. data.parquet or a
    base file from a generator run that did not pass --supplement-only).
    """
    supp_filename = f"part-supp-{supplement_salt}.parquet"
    non_supp: list[Path] = []
    for f in local_root.rglob("*"):
        if f.is_file() and f.name != supp_filename:
            non_supp.append(f)
    if non_supp:
        listing = "\n  ".join(str(p) for p in non_supp[:10])
        extra = f"\n  … and {len(non_supp) - 10} more" if len(non_supp) > 10 else ""
        raise PreflightError(
            f"[PF-1] FAIL: local-root contains non-supplement files "
            f"(expected only {supp_filename}):\n  {listing}{extra}\n"
            "Run the generator with --supplement-only to avoid mixing base and "
            "supplement files in the same tree."
        )
    supp_files = list(local_root.rglob(supp_filename))
    if not supp_files:
        raise PreflightError(
            f"[PF-1] FAIL: no {supp_filename} files found under {local_root}.\n"
            "Generate the supplement first with --supplement-only."
        )
    print(f"[PF-1] PASS: {len(supp_files)} {supp_filename} file(s), no base files.")


def _preflight_glue_location(
    product: str,
    stage: str,
    s3_prefix: str,
    bucket: str,
    *,
    apply: bool,
) -> None:
    """PF-2: Glue table location matches the upload prefix (read-only).

    Queries Glue for <product_db>.<product>_raw and checks that its
    LocationUri equals ``s3://<bucket>/<s3_prefix>``.  The check is skipped
    in dry-run mode (no AWS calls are made without --apply).
    """
    expected_location = f"s3://{bucket}/{s3_prefix}"
    if not apply:
        print(
            f"[PF-2] DRY-RUN: would verify Glue location of "
            f"adp_{stage}_{product}.{product}_raw == {expected_location}"
        )
        return

    try:
        import boto3
    except ImportError:
        raise PreflightError("[PF-2] FAIL: boto3 not available; install with pip install boto3")

    glue = boto3.client("glue", region_name=_REGION)
    db_name = f"adp_{stage}_{product}"
    table_name = f"{product}_raw"
    try:
        resp = glue.get_table(DatabaseName=db_name, Name=table_name)
    except glue.exceptions.EntityNotFoundException:
        raise PreflightError(
            f"[PF-2] FAIL: Glue table {db_name}.{table_name} not found.\n"
            f"  Expected database: {db_name}\n"
            f"  Expected table: {table_name}"
        )
    except Exception as exc:
        raise PreflightError(f"[PF-2] FAIL: Glue GetTable error: {exc}")

    actual_location = (
        resp.get("Table", {})
        .get("StorageDescriptor", {})
        .get("Location", "")
        .rstrip("/") + "/"
    )
    expected_location_norm = expected_location.rstrip("/") + "/"
    if actual_location != expected_location_norm:
        raise PreflightError(
            f"[PF-2] FAIL: Glue location mismatch for {db_name}.{table_name}:\n"
            f"  Glue reports : {actual_location}\n"
            f"  Upload prefix: {expected_location_norm}\n"
            "Check --product and --stage, or update the table's StorageDescriptor."
        )
    print(f"[PF-2] PASS: Glue location {actual_location} matches upload prefix.")


def _preflight_publish_product_runnable(
    product: str,
    stage: str,
    *,
    apply: bool,
) -> None:
    """PF-3: publish_product.py --register-only is runnable from its own tree.

    publish_product.py resolves ``curated/<product>/`` relative to its own
    parent tree (PF_ROOT = Path(publish_product.py).parents[2]) and exits 1 if
    that directory does not exist, regardless of --local-root. The check fails
    in dry-run too: a dry run is the rehearsal for --apply, and a rehearsal
    that passes while the real run would fail after uploading is the defect
    review Cycle 4 W4 found.
    """
    pf_root = _PUBLISH_PRODUCT.parents[2]
    curated_product_dir = pf_root / "curated" / product

    if curated_product_dir.exists():
        print(
            f"[PF-3] PASS: {curated_product_dir} exists; "
            "publish_product.py --register-only is runnable."
        )
        return

    # Directory missing: abort before any upload.
    raise PreflightError(
        f"[PF-3] FAIL: {curated_product_dir} does not exist.\n"
        "publish_product.py --register-only exits 1 when this directory is absent.\n"
        f"Run 'make seed-{product.replace('_', '-')} STAGE={stage}' first, or create "
        f"the directory manually if the curated tree already exists under a different path."
    )


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

def publish_cohort_supplement(
    product: str,
    stage: str,
    local_root: Path,
    supplement_salt: int,
    snapshot_file: Path,
    *,
    apply: bool,
    allow_prod: bool,
) -> None:
    """Four-step additive supplement publish with three pre-flight checks.

    Pre-flights (before Step 1, before any S3 write):
      PF-1  local_root contains only part-supp-{salt}.parquet files.
      PF-2  Glue table location matches the upload prefix.
      PF-3  publish_product.py --register-only is runnable (curated dir exists).

    Step 1: ETag snapshot
    Step 2: Upload only part-supp-{salt}.parquet keys (never --delete)
    Step 3: publish_product.py --register-only (MSCK REPAIR + DDL)
    Step 4: ETag verify (runs even if Step 2 or Step 3 fails)
    """
    if stage == "prod" and not allow_prod:
        print(
            "ERROR: --stage prod requires --allow-prod.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not _CHECK_SCRIPT.exists():
        print(
            f"ERROR: check_base_reproduction.py not found at {_CHECK_SCRIPT}.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not _PUBLISH_PRODUCT.exists():
        print(
            f"ERROR: publish_product.py not found at {_PUBLISH_PRODUCT}.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not local_root.exists():
        print(
            f"ERROR: local-root not found: {local_root}",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = "DRY-RUN" if not apply else "APPLY"
    print(f"\n{'='*60}")
    print(f"publish-cohort-supplement  product={product}  stage={stage}  mode={mode}")
    print(f"  local-root      : {local_root}")
    print(f"  supplement-salt : {supplement_salt}")
    print(f"  snapshot-file   : {snapshot_file}")
    print()

    # Resolve bucket + prefix
    if apply:
        print("Resolving AWS account ID ...")
        account_id = _resolve_account_id()
        print(f"  account_id = {account_id}")
    else:
        account_id = "000000000000"  # placeholder for dry-run output
    bucket = _lake_bucket_name(stage, account_id)
    # s3_prefix for the table: curated/{product}/{product}/  (table == product name)
    s3_prefix_no_s3 = f"curated/{product}/{product}/"

    print(f"  bucket   : {bucket}")
    print(f"  s3_prefix: {s3_prefix_no_s3}")
    print()

    # ---- Pre-flights (abort before any S3 write) ----
    print("[PRE-FLIGHT] Running checks before any upload ...")
    try:
        _preflight_local_files_only(local_root, supplement_salt)
        _preflight_glue_location(
            product, stage, s3_prefix_no_s3, bucket, apply=apply,
        )
        _preflight_publish_product_runnable(product, stage, apply=apply)
    except PreflightError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print("[PRE-FLIGHT] All checks passed.\n")

    # ---- Step 1 ----
    _etag_snapshot(bucket, s3_prefix_no_s3, snapshot_file, apply=apply)
    print()

    # ---- Steps 2 + 3 (upload + register) — Step 4 runs even on failure ----
    step_error: int = 0

    # ---- Step 2 ----
    print(f"[STEP 2] Uploading part-supp-{supplement_salt}.parquet files ...")
    try:
        _upload_supplement_files(
            local_root, bucket, s3_prefix_no_s3, supplement_salt, apply=apply,
        )
    except SystemExit as exc:
        step_error = exc.code if isinstance(exc.code, int) else 1
    print()

    # ---- Step 3 ----
    if step_error == 0:
        try:
            _register_only(product, stage, apply=apply, allow_prod=allow_prod)
        except SystemExit as exc:
            step_error = exc.code if isinstance(exc.code, int) else 1
        print()

    # ---- Step 4 (always run after Step 1 completed) ----
    # Run ETag verify even if Step 2 or Step 3 failed, so that any accidental
    # base-object change during the upload window is still detected.
    # In dry-run mode: always show what the verify would do (no uploads occurred,
    # but showing the command is part of the dry-run output).
    _etag_verify(bucket, s3_prefix_no_s3, snapshot_file, apply=apply)
    print()

    if step_error != 0:
        sys.exit(step_error)

    if not apply:
        print("DRY-RUN complete — nothing was modified.")
    else:
        print(f"publish-cohort-supplement complete: {product} @ {stage}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--product", required=True)
    p.add_argument("--stage", required=True, choices=["staging", "prod"])
    p.add_argument(
        "--local-root",
        required=True,
        type=Path,
        help=(
            "Path to the local table directory containing service_month= "
            "partition sub-directories (e.g. curated/service_records/service_records)."
        ),
    )
    p.add_argument(
        "--supplement-salt",
        type=int,
        default=901,
        help="Supplement RNG salt used in the file name part-supp-{salt}.parquet. Default 901.",
    )
    p.add_argument(
        "--snapshot-file",
        required=True,
        type=Path,
        help="Path for the pre-publish ETag snapshot JSON (written by this script).",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Execute uploads and catalog registration. Without this flag: dry-run.",
    )
    p.add_argument(
        "--allow-prod",
        action="store_true",
        default=False,
        dest="allow_prod",
        help="Required when --stage prod.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    publish_cohort_supplement(
        args.product,
        args.stage,
        args.local_root,
        args.supplement_salt,
        args.snapshot_file,
        apply=args.apply,
        allow_prod=args.allow_prod,
    )


if __name__ == "__main__":
    main()
