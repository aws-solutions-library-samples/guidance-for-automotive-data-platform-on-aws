#!/usr/bin/env python3
"""S3 ETag before/after check for service_records additive supplement publish.

Verifies that an additive supplement publish (writing only part-supp-* files)
has not altered any pre-existing S3 object.  Replaces the previous Athena
row-count / TABLESAMPLE hash approach, which was non-deterministic (see
review.md Cycle 2 Critical 3 and decisions.md "Step back on the ADP cohort").

The check is structured as a two-step workflow:

  Step A — snapshot (run BEFORE the publish):
    python3 scripts/check_base_reproduction.py snapshot \\
        --bucket adp-staging-foundation-lake-... \\
        --prefix curated/service_records/service_records/ \\
        --snapshot-file /tmp/pre-publish-etags.json \\
        --region us-east-1

  Step B — verify (run AFTER the publish):
    python3 scripts/check_base_reproduction.py verify \\
        --bucket adp-staging-foundation-lake-... \\
        --prefix curated/service_records/service_records/ \\
        --snapshot-file /tmp/pre-publish-etags.json \\
        --region us-east-1

Verify exit codes:
  0 — all pre-existing keys kept their ETag; only part-supp-* keys are new
  1 — at least one pre-existing key changed ETag (base was modified)
  2 — usage error (missing arguments)

Safety design:
  - Non-destructive: only s3:ListObjectsV2 is required.
  - Fail-closed on any AWS error.
  - The snapshot is a plain JSON file (s3_key → ETag); trivially auditable.
  - Part-supp-* keys are expected NEW keys; other new keys are flagged as
    warnings (not failures) since Athena's MSCK REPAIR may add hidden files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _list_s3_objects(
    bucket: str, prefix: str, *, region: str,
) -> dict[str, str]:
    """Return {key: etag} for every object under prefix (paged)."""
    try:
        import boto3
    except ImportError:
        print("[etag-check] boto3 not available — install with pip install boto3", file=sys.stderr)
        sys.exit(2)

    s3 = boto3.client("s3", region_name=region)
    result: dict[str, str] = {}
    paginator = s3.get_paginator("list_objects_v2")
    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                result[obj["Key"]] = obj["ETag"].strip('"')
    except Exception as exc:
        print(f"[etag-check] FAIL: s3:ListObjectsV2 error: {exc}", file=sys.stderr)
        sys.exit(1)
    return result


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

def _cmd_snapshot(
    bucket: str, prefix: str, snapshot_file: Path, *, region: str,
) -> int:
    """List S3 objects and write {key: etag} to snapshot_file."""
    objects = _list_s3_objects(bucket, prefix, region=region)
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    snapshot_file.write_text(json.dumps(objects, indent=2, sort_keys=True))
    print(
        f"[etag-check] snapshot: {len(objects):,} objects under "
        f"s3://{bucket}/{prefix} written to {snapshot_file}"
    )
    return 0


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def _cmd_verify(
    bucket: str, prefix: str, snapshot_file: Path, *, region: str,
) -> int:
    """Compare current S3 ETag map to the snapshot.

    Pass: every pre-existing key still has the same ETag; only
    part-supp-* keys (and Athena/Iceberg hidden files) are new.
    Fail: at least one pre-existing key has a different ETag.
    """
    if not snapshot_file.exists():
        print(f"[etag-check] FAIL: snapshot file not found: {snapshot_file}", file=sys.stderr)
        return 1

    pre: dict[str, str] = json.loads(snapshot_file.read_text())
    post: dict[str, str] = _list_s3_objects(bucket, prefix, region=region)

    changed: list[str] = []
    deleted: list[str] = []
    new_base: list[str] = []    # new keys that are NOT part-supp-*
    new_supp: list[str] = []    # new part-supp-* keys

    for key, etag in pre.items():
        if key not in post:
            deleted.append(key)
        elif post[key] != etag:
            changed.append(key)

    for key in post:
        if key not in pre:
            filename = key.rsplit("/", 1)[-1]
            if filename.startswith("part-supp-"):
                new_supp.append(key)
            else:
                new_base.append(key)

    # Report
    print(f"[etag-check] pre-existing objects: {len(pre):,}")
    print(f"[etag-check] post-publish objects: {len(post):,}")
    print(f"[etag-check] changed: {len(changed)}, deleted: {len(deleted)}, "
          f"new part-supp-*: {len(new_supp)}, other new: {len(new_base)}")

    failed = False

    if changed:
        print(
            f"[etag-check] FAIL: {len(changed)} pre-existing object(s) changed ETag:",
            file=sys.stderr,
        )
        for k in changed[:20]:
            print(f"  {k}", file=sys.stderr)
        if len(changed) > 20:
            print(f"  ... and {len(changed) - 20} more", file=sys.stderr)
        failed = True

    if deleted:
        print(
            f"[etag-check] FAIL: {len(deleted)} pre-existing object(s) were deleted:",
            file=sys.stderr,
        )
        for k in deleted[:20]:
            print(f"  {k}", file=sys.stderr)
        failed = True

    if new_base:
        # New non-supplement files are unexpected but not a failure (Athena/Iceberg
        # may add metadata files).  Warn so the operator can inspect.
        print(
            f"[etag-check] WARN: {len(new_base)} new non-supplement object(s) "
            f"(Athena metadata files or unexpected writes):",
        )
        for k in new_base[:10]:
            print(f"  {k}")
        if len(new_base) > 10:
            print(f"  ... and {len(new_base) - 10} more")

    if new_supp:
        print(f"[etag-check] OK: {len(new_supp)} new part-supp-* file(s) as expected.")

    if not failed:
        print("[etag-check] PASS: all pre-existing objects kept their ETag.")
        return 0
    return 1


# ---------------------------------------------------------------------------
# Self-test: verify the check fails when a pre-existing object is changed
# ---------------------------------------------------------------------------

def _cmd_selftest() -> int:
    """Demonstrate that _cmd_verify returns 1 when a base object's ETag changes.

    Does not require AWS credentials — uses a fake in-memory objects dict.
    """
    import hashlib
    import tempfile

    def _fake_etag(content: bytes) -> str:
        return hashlib.md5(content).hexdigest()

    # Pre state: 3 base objects + no supplement objects.
    pre_objects = {
        "curated/service_records/service_records/service_month=2025-01-01/data.parquet": _fake_etag(b"base-jan"),
        "curated/service_records/service_records/service_month=2025-02-01/data.parquet": _fake_etag(b"base-feb"),
        "curated/service_records/service_records/service_month=2025-03-01/data.parquet": _fake_etag(b"base-mar"),
    }

    # Post state (supplement publish): base objects unchanged + new part-supp-* files.
    post_objects_ok = dict(pre_objects)
    post_objects_ok["curated/service_records/service_records/service_month=2025-01-01/part-supp-901.parquet"] = _fake_etag(b"supp-jan")
    post_objects_ok["curated/service_records/service_records/service_month=2025-02-01/part-supp-901.parquet"] = _fake_etag(b"supp-feb")

    # Bad post state: one base object changed ETag.
    post_objects_bad = dict(post_objects_ok)
    post_objects_bad["curated/service_records/service_records/service_month=2025-02-01/data.parquet"] = _fake_etag(b"base-feb-CHANGED")

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(pre_objects, f)
        snap_path = Path(f.name)

    # --- Case 1: expect PASS ---
    # Temporarily monkey-patch _list_s3_objects.
    import unittest.mock as _mock

    with _mock.patch(f"{__name__}._list_s3_objects", return_value=post_objects_ok):
        rc_pass = _cmd_verify("fake-bucket", "curated/", snap_path, region="us-east-1")
    if rc_pass != 0:
        print("[selftest] FAIL: expected PASS (0) on unchanged base, got non-zero.", file=sys.stderr)
        snap_path.unlink(missing_ok=True)
        return 1
    print("[selftest] PASS case OK (rc=0).")

    # --- Case 2: expect FAIL ---
    with _mock.patch(f"{__name__}._list_s3_objects", return_value=post_objects_bad):
        rc_fail = _cmd_verify("fake-bucket", "curated/", snap_path, region="us-east-1")
    if rc_fail != 1:
        print("[selftest] FAIL: expected FAIL (1) on changed ETag, got non-1.", file=sys.stderr)
        snap_path.unlink(missing_ok=True)
        return 1
    print("[selftest] FAIL case OK (rc=1 as expected when a base object changes).")

    snap_path.unlink(missing_ok=True)
    print("[selftest] PASS: ETag check correctly detects a changed base object.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command")

    snap = sub.add_parser("snapshot", help="Snapshot current S3 ETag map.")
    snap.add_argument("--bucket", required=True)
    snap.add_argument("--prefix", required=True)
    snap.add_argument("--snapshot-file", required=True, type=Path)
    snap.add_argument("--region", default="us-east-1")

    ver = sub.add_parser("verify", help="Compare current S3 state to snapshot.")
    ver.add_argument("--bucket", required=True)
    ver.add_argument("--prefix", required=True)
    ver.add_argument("--snapshot-file", required=True, type=Path)
    ver.add_argument("--region", default="us-east-1")

    sub.add_parser("selftest", help="Run the self-test (no AWS required).")

    return p.parse_args()


def main() -> int:
    args = _parse()
    if args.command == "snapshot":
        return _cmd_snapshot(
            args.bucket, args.prefix, args.snapshot_file, region=args.region,
        )
    if args.command == "verify":
        return _cmd_verify(
            args.bucket, args.prefix, args.snapshot_file, region=args.region,
        )
    if args.command == "selftest":
        return _cmd_selftest()
    # No command given.
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
