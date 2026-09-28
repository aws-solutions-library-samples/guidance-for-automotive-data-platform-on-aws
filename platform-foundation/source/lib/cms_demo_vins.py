"""Fetch CMS demo Meridian VINs from DynamoDB.

The Meridian EV-OEM rebrand generator reads ``cms-staging-storage-vehicles``
at seed time and inserts the 21 Meridian rows verbatim at the head of the
VIN pool (ordinals 0-20). This module is the only place in the ADP repo
that touches CMS DDB.

Spec: ``.kiro/specs/2026-09-10-adp-meridian-ev-oem-reseed/spec.md``
      D2 (CMS demo VINs at ordinal 0-20),
      R4 (fail-closed on CMS DDB errors),
      R5 (accept modest DDB drift — caller adjusts procedural tail).

Fail-closed discipline (R4): if the scan returns zero valid rows or the
DDB call errors, this module RAISES. It does NOT silently return ``[]``
and let the seed publish 4,734,883 Meridian VINs without any CMS demo
block. Silent success is the failure mode this contract exists to prevent.

The caller (``dimensions/generate_all.py::gen_vins``) sizes the procedural
tail based on the returned row count so the total pool stays at
``TOTAL_POOL_SIZE`` per D1 — this module does not care how many valid
rows come back beyond ``> 0``.

Interface signature:

    fetch_meridian_demo_vins(
        *, ddb_client=None, table_name=None,
    ) -> list[dict]

Returned dict shape per row (fields present when DDB provides them):

    {"vin": "MRDN0000000000005", "model": "Trailwind", "year": 2025,
     "make": "Meridian", "vehicleId": "VEH-MRDN-0005"}

Only rows with a valid 17-character ``vin`` string are included; rows
with ``vin=None``, ``vin=""``, or ``len(vin) != 17`` are filtered out
silently. This mirrors the CMS-side data quality (the ``vehicleId``
column can carry non-VIN identifiers that would otherwise pollute the
ADP pool).

The ``ddb_client`` kwarg is the test-injection seam. Tests pass a
``botocore.stub.Stubber``-wrapped low-level client so no live DDB call
happens. In production, callers omit the kwarg and a default low-level
``boto3.client('dynamodb')`` is constructed.

The low-level client is required (not the resource API) because the DDB
filter expression uses ``ExpressionAttributeValues`` in wire format
(``{":m": {"S": "Meridian"}}``); the resource API auto-unwraps values
and would send ``{":m": "Meridian"}``, which mismatches what the caller
stubs against.
"""

from __future__ import annotations

import os
from typing import Any, Optional

# Default table; overridable via env var so a staging seed can point at a
# different DDB table (e.g. a snapshot copy) without a code change.
_DEFAULT_TABLE = "cms-staging-storage-vehicles"

# ISO 3779 VIN length. CMS demo VINs (MRDN/DEMO prefixes) are all 17 chars
# per F4 of the spec; rows shorter/longer than 17 are treated as invalid
# and filtered out.
_VIN_LENGTH = 17


def _unwrap_attr(av: Any) -> Any:
    """Unwrap a single DDB attribute value into a native Python value.

    Supports the subset of DDB types this module reads from
    ``cms-staging-storage-vehicles``: ``S`` (string), ``N`` (number),
    ``BOOL`` (boolean), ``NULL``. Unknown wrapper keys return ``None``.

    If ``av`` is already a plain value (not a dict wrapper), it is
    returned unchanged. This keeps the function safe against callers
    that pre-unwrap.
    """
    if not isinstance(av, dict):
        return av
    if "S" in av:
        return av["S"]
    if "N" in av:
        n = av["N"]
        # DDB numbers are strings on the wire; coerce to int if integral,
        # else float. ADP rebrand only reads ``year`` as a number here.
        try:
            return int(n)
        except ValueError:
            return float(n)
    if "BOOL" in av:
        return av["BOOL"]
    if "NULL" in av:
        return None
    return None


def _row_from_ddb_item(item: dict) -> Optional[dict]:
    """Convert one DDB item into a plain dict, or None if the row is invalid.

    Two filters apply, both defense-in-depth behind the server-side
    ``FilterExpression``:

      1. ``make`` MUST equal ``"Meridian"``. The server-side filter
         should already have enforced this, but a mismatch (table drift,
         stubbed test data, adjacent-brand rows) is a fail-safe drop.
      2. ``vin`` MUST be present, be a string, and be exactly 17 chars
         (ISO 3779). Non-VIN identifiers in ``vehicleId``-only rows are
         dropped.

    Any row failing either filter returns ``None`` and is dropped by the
    caller. Non-``vin`` attributes are optional; whatever DDB returns is
    passed through unchanged.
    """
    make = _unwrap_attr(item.get("make"))
    if make != "Meridian":
        return None

    vin = _unwrap_attr(item.get("vin"))
    if not isinstance(vin, str) or len(vin) != _VIN_LENGTH:
        return None

    row: dict[str, Any] = {"vin": vin, "make": make}
    # Pass through the subset the ADP generator actually reads. Additional
    # DDB attributes on the CMS row are ignored here — the generator uses
    # `model` + `year` for D12.b/D12.a lookups and `vehicleId` for audit.
    for key in ("model", "vehicleId", "year"):
        av = item.get(key)
        if av is not None:
            row[key] = _unwrap_attr(av)
    return row


def fetch_meridian_demo_vins(
    *,
    ddb_client: Optional[Any] = None,
    table_name: Optional[str] = None,
) -> list[dict]:
    """Scan CMS DDB for Meridian vehicles and return valid rows.

    Args:
        ddb_client: Optional low-level DynamoDB client (from
            ``boto3.client('dynamodb')`` or ``botocore.session.Session().
            create_client('dynamodb', ...)``). Test-injection seam. If
            ``None``, a default ``boto3.client('dynamodb')`` is created —
            requires AWS credentials at runtime.
        table_name: Optional DDB table name. Defaults to the value of
            ``CMS_STAGING_VEHICLES_TABLE`` env var, falling back to
            ``cms-staging-storage-vehicles``.

    Returns:
        A list of dicts, one per valid Meridian row. Each dict has at
        least a ``vin`` key (17-char string) plus ``model``, ``make``,
        ``vehicleId``, ``year`` where DDB provides them.

    Raises:
        ValueError: If the scan completes but returns zero valid Meridian
            rows. This is the R4 fail-closed guarantee: the ADP seed will
            NOT publish a Meridian pool without a CMS demo block.
        botocore.exceptions.ClientError: If DDB itself errors (throttling,
            table missing, permission denied). Propagated as-is; the ADP
            seed then fails, no silent fallback.

    Side effects:
        Reads DDB. No writes. No local caching.
    """
    if ddb_client is None:
        # Lazy import so callers running tests with a stubbed client don't
        # need boto3 at import time. In production, boto3 is a required
        # dep of the platform-foundation package.
        import boto3

        ddb_client = boto3.client("dynamodb")

    table = table_name or os.environ.get(
        "CMS_STAGING_VEHICLES_TABLE", _DEFAULT_TABLE
    )

    # DDB Scan with a filter on the reserved keyword ``make`` — aliased via
    # ExpressionAttributeNames for safety. Wire-format
    # ExpressionAttributeValues (``{"S": "Meridian"}``) because we're on the
    # low-level client.
    scan_kwargs: dict[str, Any] = {
        "TableName": table,
        "FilterExpression": "#m = :m",
        "ExpressionAttributeNames": {"#m": "make"},
        "ExpressionAttributeValues": {":m": {"S": "Meridian"}},
    }

    items: list[dict] = []
    while True:
        response = ddb_client.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        last = response.get("LastEvaluatedKey")
        if not last:
            break
        # Pagination: today the CMS demo fleet is small enough (~21 rows in
        # a ~100-row table) that a single scan returns everything, but if
        # the demo fleet grows past DDB's 1MB scan page limit this loop
        # handles it. The stubber in tests only supplies one page, so this
        # loop exits after the first iteration under test.
        scan_kwargs["ExclusiveStartKey"] = last

    # Filter to valid Meridian rows (17-char VIN string). Silent drop on
    # invalid rows — the DDB table may legitimately have rows with a
    # non-VIN ``vehicleId`` where the ``vin`` attribute wasn't populated;
    # those aren't ADP-relevant.
    valid: list[dict] = []
    for it in items:
        row = _row_from_ddb_item(it)
        if row is not None:
            valid.append(row)

    if not valid:
        # R4: zero valid rows is a fail-closed condition. The ADP seed must
        # not publish a Meridian pool without the CMS demo block, so raise
        # loudly and let the caller propagate.
        raise ValueError(
            f"CMS DDB scan of {table!r} returned no valid Meridian rows — "
            "refusing to seed an empty CMS demo block. Verify the table "
            "has make='Meridian' entries with valid 17-char VIN strings."
        )

    return valid
