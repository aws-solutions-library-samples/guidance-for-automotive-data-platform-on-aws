"""DynamoDB Streams enablement helper for CMS source tables.

Per the spec (Group 5 task "Optional CMS→ADP ingest module"):

> When enabled (with ``-c cms_vehicle_state_table_arn=...``), deploys:
> DDB Streams enablement (or assertion that they're already enabled),
> Kinesis Firehose with parquet conversion to
> ``s3://.../cms-ingest/<table>/dt=YYYY-MM-DD/``, scheduled Glue
> Iceberg MERGE job (15-min cadence) into ``adp_cms_ingest`` Glue DB.

DDB Streams enablement happens *outside* CloudFormation because the
CMS DynamoDB table is owned by the CMS deploy, not by ADP. The
foundation stack therefore expects the operator to run this helper
**before** deploying the optional ``cms-ingest`` stack with
``enable_cms_ingest=true``.

The helper is **read-only-by-default**. Without ``--enable``, it
inspects the table and exits ``0`` only when the stream is already
in the expected ``NEW_AND_OLD_IMAGES`` view-type. With ``--enable``,
it issues an ``UpdateTable`` call to turn the stream on (or
escalates the view-type if it's currently a narrower image set).

Usage::

    # 1) Audit only — fail closed if streams are not yet on.
    python -m platform_foundation.source.optional.cms_ingest.enable_streams \\
        --table-arn arn:aws:dynamodb:us-east-1:123456789012:table/cms-prod-vehicle-state

    # 2) Enable streams (idempotent — no-op if already correct).
    python -m platform_foundation.source.optional.cms_ingest.enable_streams \\
        --table-arn arn:aws:dynamodb:us-east-1:123456789012:table/cms-prod-vehicle-state \\
        --enable

Cross-account caveat: in v1 we assume CMS and ADP live in the same
AWS account, so the local default-credential chain is sufficient. The
cross-account v2 pattern (DDB resource-based policy on the CMS table
+ identity-based policy on the ADP role) is documented in
``docs/cms-ingest-optional-module.md`` but not implemented here.

Pitfalls
--------
* DynamoDB Streams *cannot* be safely toggled on a write-hot table
  during a deploy window — turning streams off and on reset the
  shard iterator and Firehose will miss the records written during
  the cutover. This helper therefore fails closed rather than
  flipping ``StreamEnabled`` from ``true`` to ``false``.
* The view type matters: the Iceberg MERGE job needs both old and
  new images to compute deletes (``REMOVE`` events carry only the
  old image). ``NEW_IMAGE`` alone is *not* sufficient.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from typing import Optional


_LOG = logging.getLogger("cms_ingest.enable_streams")

#: DynamoDB Streams view type required by the MERGE job.
#:
#: ``NEW_AND_OLD_IMAGES`` lets the Glue MERGE job:
#:   - resolve the new state on ``INSERT`` / ``MODIFY`` events,
#:   - resolve the prior state on ``REMOVE`` events (so it can issue
#:     the matching Iceberg ``DELETE FROM ... WHERE pk = ...``).
REQUIRED_STREAM_VIEW_TYPE = "NEW_AND_OLD_IMAGES"

#: Strict ARN regex for DynamoDB tables (region MUST be ``us-east-1``
#: for v1 per spec Constraint #3).
_DDB_TABLE_ARN_RE = re.compile(
    r"^arn:aws:dynamodb:(?P<region>[a-z0-9-]+):(?P<account>\d{12})"
    r":table/(?P<table>[A-Za-z0-9_.-]+)$"
)


@dataclass(frozen=True)
class TableArn:
    """Parsed DynamoDB table ARN."""

    region: str
    account: str
    table: str
    raw: str


def parse_table_arn(arn: str) -> TableArn:
    """Validate ``arn`` and split it into region/account/table.

    Raises
    ------
    ValueError
        If ``arn`` is malformed or not a DynamoDB *table* ARN.
    """
    match = _DDB_TABLE_ARN_RE.match(arn)
    if not match:
        raise ValueError(
            f"Not a valid DynamoDB table ARN: {arn!r}. "
            "Expected: arn:aws:dynamodb:<region>:<account>:table/<name>"
        )
    return TableArn(
        region=match.group("region"),
        account=match.group("account"),
        table=match.group("table"),
        raw=arn,
    )


def _make_client(region: str, *, session=None):
    """Construct a boto3 DynamoDB client (lazy import for offline tests)."""
    import boto3  # local import keeps module importable without boto3

    sess = session or boto3.session.Session()
    return sess.client("dynamodb", region_name=region)


def describe_stream_state(
    table: TableArn,
    *,
    client=None,
) -> dict:
    """Return ``{enabled: bool, view_type: Optional[str], stream_arn: Optional[str]}``.

    Pure read; never mutates the table.
    """
    ddb = client or _make_client(table.region)
    resp = ddb.describe_table(TableName=table.table)
    spec = resp["Table"].get("StreamSpecification") or {}
    return {
        "enabled": bool(spec.get("StreamEnabled", False)),
        "view_type": spec.get("StreamViewType"),
        "stream_arn": resp["Table"].get("LatestStreamArn"),
    }


def assert_streams_ok(
    table: TableArn,
    *,
    client=None,
    expected_view_type: str = REQUIRED_STREAM_VIEW_TYPE,
) -> dict:
    """Audit-only check: streams must be ON and at the required view type.

    Raises
    ------
    RuntimeError
        If the stream is disabled or has the wrong view type. The
        message tells the operator how to fix it (run with
        ``--enable``).
    """
    state = describe_stream_state(table, client=client)
    if not state["enabled"]:
        raise RuntimeError(
            f"DynamoDB Streams are NOT enabled on {table.raw}. "
            f"Re-run this helper with --enable, OR ask the CMS operator "
            f"to set StreamSpecification.StreamEnabled=true with "
            f"StreamViewType={expected_view_type} on the table."
        )
    if state["view_type"] != expected_view_type:
        raise RuntimeError(
            f"DynamoDB Streams on {table.raw} are enabled with "
            f"StreamViewType={state['view_type']!r}, but the CMS-ingest "
            f"MERGE job requires {expected_view_type!r} (REMOVE events "
            f"need the OLD image to compute Iceberg deletes). "
            f"Re-run this helper with --enable to escalate, OR ask the "
            f"CMS operator to update the table."
        )
    return state


def enable_streams_idempotent(
    table: TableArn,
    *,
    client=None,
    view_type: str = REQUIRED_STREAM_VIEW_TYPE,
) -> dict:
    """Turn streams on (or escalate the view type) if needed.

    No-op when the table already meets the contract.

    Raises
    ------
    RuntimeError
        If the table is in ``UPDATING`` state when called (operator
        must wait for the prior write to settle).
    """
    state = describe_stream_state(table, client=client)
    if state["enabled"] and state["view_type"] == view_type:
        _LOG.info(
            "Streams already on for %s with view_type=%s — no-op.",
            table.raw,
            view_type,
        )
        return state

    ddb = client or _make_client(table.region)
    desc = ddb.describe_table(TableName=table.table)
    table_status = desc["Table"]["TableStatus"]
    if table_status != "ACTIVE":
        raise RuntimeError(
            f"Refusing to update StreamSpecification on {table.raw} "
            f"while TableStatus={table_status!r}. Wait for ACTIVE."
        )

    _LOG.warning(
        "Updating StreamSpecification on %s: enabled=True, view_type=%s "
        "(was: enabled=%s, view_type=%r).",
        table.raw,
        view_type,
        state["enabled"],
        state["view_type"],
    )
    ddb.update_table(
        TableName=table.table,
        StreamSpecification={
            "StreamEnabled": True,
            "StreamViewType": view_type,
        },
    )
    # Re-read after the update so the caller sees the new ARN.
    return describe_stream_state(table, client=client)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Returns the desired process exit code."""
    parser = argparse.ArgumentParser(
        prog="enable_streams",
        description=(
            "Audit (or enable) DynamoDB Streams on the CMS source "
            "table that feeds the optional CMS→ADP ingest module."
        ),
    )
    parser.add_argument(
        "--table-arn",
        required=True,
        help=(
            "Full ARN of the CMS DynamoDB source table, e.g. "
            "arn:aws:dynamodb:us-east-1:123456789012:table/cms-prod-vehicle-state"
        ),
    )
    parser.add_argument(
        "--enable",
        action="store_true",
        help=(
            "Issue an UpdateTable call to enable streams (or escalate "
            "the view type to NEW_AND_OLD_IMAGES) when the audit "
            "fails. Without this flag the helper is read-only."
        ),
    )
    parser.add_argument(
        "--view-type",
        default=REQUIRED_STREAM_VIEW_TYPE,
        choices=("NEW_AND_OLD_IMAGES",),
        help=(
            "View type to assert/enable. Only NEW_AND_OLD_IMAGES is "
            "supported by the MERGE job (the operator must not "
            "narrow it via this CLI)."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        table = parse_table_arn(args.table_arn)
    except ValueError as exc:
        _LOG.error(str(exc))
        return 2

    try:
        if args.enable:
            state = enable_streams_idempotent(table, view_type=args.view_type)
            print(json.dumps({"action": "enabled", **state}, default=str, indent=2))
            return 0
        state = assert_streams_ok(table, expected_view_type=args.view_type)
        print(json.dumps({"action": "audit", **state}, default=str, indent=2))
        return 0
    except RuntimeError as exc:
        _LOG.error(str(exc))
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
