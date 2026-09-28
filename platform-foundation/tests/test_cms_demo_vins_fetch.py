"""Red-phase tests for `lib/cms_demo_vins.py` — the CMS demo VIN fetcher.

Spec: `.kiro/specs/2026-09-10-adp-meridian-ev-oem-reseed/spec.md`
      D2 (CMS demo VINs at ordinal 0-20), R4 (fail-closed on CMS DDB errors).

The rebrand generator reads `cms-staging-storage-vehicles` at seed time
and inserts those 21 Meridian VINs verbatim at the head of the pool.
The fetcher module (`platform-foundation/source/lib/cms_demo_vins.py`)
is the ONLY place that touches CMS DDB from the ADP repo.

Fail-closed discipline (R4): if the DDB scan returns zero rows or errors,
the fetcher raises rather than silently returning [] and letting the
generator publish 4,999,979 Meridian VINs without any CMS demo VIN. Silent
success is the failure mode this contract exists to prevent.

These tests FAIL until T2.1 ships `lib/cms_demo_vins.py`. Failure is the
red phase.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure platform-foundation/source is importable at test time.
_PF_SOURCE = Path(__file__).resolve().parent.parent / "source"
if str(_PF_SOURCE) not in sys.path:
    sys.path.insert(0, str(_PF_SOURCE))


def _fresh_module():
    """Force a fresh import so env-var patches take effect per-test.

    The fetcher reads `CMS_STAGING_VEHICLES_TABLE` at call time (not import
    time), so module-level env-var patching should not be required — but a
    fresh import prevents cross-test caching of any lazy-init state.
    """
    if "lib.cms_demo_vins" in sys.modules:
        del sys.modules["lib.cms_demo_vins"]
    from lib import cms_demo_vins  # type: ignore[import-not-found]

    return cms_demo_vins


# ---------------------------------------------------------------------------
# Happy path — stubbed DDB with mixed Meridian + Ford rows
# ---------------------------------------------------------------------------


def _stub_ddb_response(items: list[dict]) -> dict:
    """Build a boto3-shape DynamoDB scan response body."""
    return {"Items": items, "Count": len(items)}


def _meridian_item(vin: str, model: str, year: int) -> dict:
    """Build a DDB item shape for a Meridian vehicle.

    DDB attributes are wrapped in type descriptors, e.g. `{"S": "..."}` for
    string, `{"N": "2025"}` for numbers. The fetcher must unwrap them.
    """
    return {
        "vehicleId": {"S": f"VEH-MRDN-{vin[-4:]}"},
        "vin": {"S": vin},
        "make": {"S": "Meridian"},
        "model": {"S": model},
        "year": {"N": str(year)},
    }


def _ford_item(vin: str) -> dict:
    return {
        "vehicleId": {"S": vin},
        "vin": {"S": vin},
        "make": {"S": "Ford"},
        "model": {"S": "F-150"},
        "year": {"N": "2024"},
    }


def test_fetch_returns_21_meridian_vins_from_ddb_stub(monkeypatch):
    """Happy path: DDB returns 21 Meridian + 48 Ford; fetcher returns 21 Meridian."""
    import botocore.session
    from botocore.stub import Stubber

    session = botocore.session.Session()
    ddb = session.create_client("dynamodb", region_name="us-west-2")
    stubber = Stubber(ddb)

    meridian_vins = [
        ("MRDN0000000000001", "Trailwind", 2024),
        ("MRDN0000000000002", "Azimuth", 2025),
        ("MRDN0000000000003", "Windrose", 2023),
        ("MRDN0000000000004", "Trailwind", 2023),
        ("MRDN0000000000005", "Trailwind", 2025),
        ("MRDN0000000000006", "Crestwind", 2025),
        ("MRDN0000000000007", "Crestwind", 2026),
        ("MRDN0000000000008", "Azimuth", 2022),
        ("MRDN0000000000009", "Zephyr", 2024),
        ("MRDN0000000000010", "Sirocco", 2024),
        ("MRDN0000000000011", "Windrose", 2024),
        ("MRDN0000000000012", "Azimuth", 2025),
        ("MRDN0000000000013", "Mistral", 2025),
        ("MRDN0000000000014", "Windrose", 2022),
        ("MRDN0000000000015", "Windrose", 2026),
        ("MRDN0000000000016", "Zephyr", 2025),
        ("DEMO0000000000001", "Azimuth", 2025),
        ("DEMO0000000000002", "Azimuth", 2026),
        ("DEMO0000000000003", "Crestwind", 2022),
        ("DEMO0000000000004", "Trailwind", 2023),
        ("DEMO0000000000005", "Azimuth", 2025),
    ]
    items = [_meridian_item(v, m, y) for v, m, y in meridian_vins]
    items += [_ford_item(f"1FTBR3X8XLKA{i:05d}") for i in range(48)]

    stubber.add_response(
        "scan",
        _stub_ddb_response(items),
        expected_params={
            "TableName": "cms-staging-storage-vehicles",
            "FilterExpression": "#m = :m",
            "ExpressionAttributeNames": {"#m": "make"},
            "ExpressionAttributeValues": {":m": {"S": "Meridian"}},
        },
    )
    stubber.activate()

    m = _fresh_module()
    result = m.fetch_meridian_demo_vins(ddb_client=ddb)

    assert len(result) == 21, f"Expected 21 Meridian VINs, got {len(result)}"
    assert all(r["vin"].startswith(("MRDN", "DEMO")) for r in result), (
        "All returned VINs must have MRDN or DEMO prefix"
    )
    assert {r["model"] for r in result} <= {
        "Trailwind", "Azimuth", "Windrose", "Crestwind",
        "Zephyr", "Sirocco", "Mistral",
    }
    stubber.assert_no_pending_responses()


# ---------------------------------------------------------------------------
# Fail-closed paths — R4 discipline
# ---------------------------------------------------------------------------


def test_fetch_fails_closed_on_empty_ddb():
    """Empty DDB scan (0 Meridian rows) MUST raise, not return []."""
    import botocore.session
    from botocore.stub import Stubber

    session = botocore.session.Session()
    ddb = session.create_client("dynamodb", region_name="us-west-2")
    stubber = Stubber(ddb)
    stubber.add_response("scan", _stub_ddb_response([]))
    stubber.activate()

    m = _fresh_module()
    with pytest.raises((ValueError, RuntimeError)) as excinfo:
        m.fetch_meridian_demo_vins(ddb_client=ddb)
    msg = str(excinfo.value).lower()
    assert "meridian" in msg or "empty" in msg or "no rows" in msg, (
        f"Error message must mention Meridian/empty/no rows; got: {excinfo.value}"
    )


def test_fetch_fails_closed_on_ddb_client_error():
    """DDB ClientError (throttling, permission denied, table missing) MUST propagate."""
    import botocore.session
    from botocore.exceptions import ClientError
    from botocore.stub import Stubber

    session = botocore.session.Session()
    ddb = session.create_client("dynamodb", region_name="us-west-2")
    stubber = Stubber(ddb)
    stubber.add_client_error(
        "scan",
        service_error_code="ResourceNotFoundException",
        service_message="Requested resource not found",
    )
    stubber.activate()

    m = _fresh_module()
    # Fetcher may re-raise ClientError directly OR wrap in a domain error.
    with pytest.raises((ClientError, RuntimeError, ValueError)):
        m.fetch_meridian_demo_vins(ddb_client=ddb)


def test_fetch_excludes_invalid_vins():
    """Rows with vin=None, vin='', or vin length != 17 MUST be excluded."""
    import botocore.session
    from botocore.stub import Stubber

    session = botocore.session.Session()
    ddb = session.create_client("dynamodb", region_name="us-west-2")
    stubber = Stubber(ddb)

    # Mix of valid + invalid entries. Valid Meridian VINs (5) + invalid (3).
    valid_items = [
        _meridian_item(f"MRDN000000000000{i}", "Trailwind", 2024) for i in range(1, 6)
    ]
    invalid_items = [
        # vin absent
        {
            "vehicleId": {"S": "VEH-MRDN-BAD1"},
            "make": {"S": "Meridian"},
            "model": {"S": "Trailwind"},
            "year": {"N": "2024"},
        },
        # vin empty string
        {
            "vehicleId": {"S": "VEH-MRDN-BAD2"},
            "vin": {"S": ""},
            "make": {"S": "Meridian"},
            "model": {"S": "Trailwind"},
            "year": {"N": "2024"},
        },
        # vin wrong length (not 17)
        {
            "vehicleId": {"S": "VEH-MRDN-BAD3"},
            "vin": {"S": "MRDNSHORT"},
            "make": {"S": "Meridian"},
            "model": {"S": "Trailwind"},
            "year": {"N": "2024"},
        },
    ]
    stubber.add_response("scan", _stub_ddb_response(valid_items + invalid_items))
    stubber.activate()

    m = _fresh_module()
    # Since valid count is 5 (below the 21-minimum expected in the happy-path
    # test), the fetcher MAY still succeed with 5 valid rows OR MAY fail-closed
    # on a low-count check. Both behaviours are acceptable — the assertion is
    # that invalid rows are excluded and the count reflects only valid ones.
    try:
        result = m.fetch_meridian_demo_vins(ddb_client=ddb)
    except (ValueError, RuntimeError):
        return  # fail-closed on low valid count is acceptable
    assert len(result) == 5, (
        f"Expected 5 valid Meridian VINs after filtering invalids; got {len(result)}"
    )
    for r in result:
        assert r["vin"] and len(r["vin"]) == 17, (
            f"Invalid VIN slipped through: {r['vin']!r}"
        )


# ---------------------------------------------------------------------------
# Interface tests — module surface
# ---------------------------------------------------------------------------


def test_module_exports_fetch_function():
    """T2.1 must export `fetch_meridian_demo_vins` from the module."""
    m = _fresh_module()
    assert hasattr(m, "fetch_meridian_demo_vins"), (
        "T2.1 must export fetch_meridian_demo_vins"
    )
    import inspect

    sig = inspect.signature(m.fetch_meridian_demo_vins)
    # Signature: fetch_meridian_demo_vins(*, ddb_client=None) or similar. At
    # minimum the ddb_client kwarg must exist (test-injection seam).
    assert "ddb_client" in sig.parameters, (
        "fetch_meridian_demo_vins must accept `ddb_client` kwarg for test injection"
    )
