"""Test skeletons: schema_loader provenance validation (T1.2).

These tests are RED in Group 1. They go GREEN when T2.1 lands:
  - `Table` dataclass gains a required `provenance: str` field
  - `load_schema_from_path()` raises `SchemaValidationError` when
    `provenance` is missing or carries a value outside the allowed set
  - A new `ALLOWED_PROVENANCE` constant is colocated with
    `ALLOWED_STORAGE_FORMATS` / `ALLOWED_COLUMN_TYPES`.

Convention: tests use `tmp_path` with inline YAML strings so they
never depend on the real `source/data-products/*/schema.yaml` files.
That constraint is deliberately encoded here to protect the real
schemas from G1 accidents.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Add schema_loader to path (mirrors conftest.py's approach)
# ---------------------------------------------------------------------------

_PF_ROOT = Path(__file__).resolve().parents[1]
_LIB = _PF_ROOT / "source" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import schema_loader as sl  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal valid schema template — each test adds / omits provenance as needed.
# Deliberately mirrors the invalid_type_raises test from test_schema_loader.py
# (same pattern: write a YAML file to tmp_path, then call load_schema_from_path).
# ---------------------------------------------------------------------------

_VALID_SCHEMA_TEMPLATE = """\
name: test_product
kind: product
domain: automotive
display_name: 'Test Product'
tables:
  - name: test_table
    storage_format: iceberg
    provenance: {provenance}
    columns:
      - {{name: vin, type: string}}
"""

_SCHEMA_MISSING_PROVENANCE = """\
name: test_product
kind: product
domain: automotive
display_name: 'Test Product'
tables:
  - name: test_table
    storage_format: iceberg
    columns:
      - {name: vin, type: string}
"""


# ---------------------------------------------------------------------------
# T1.2(a): valid schema with provenance: single-vintage loads successfully
# ---------------------------------------------------------------------------


def test_single_vintage_provenance_loads(tmp_path: Path):
    """A table declaring provenance: single-vintage must load without error.

    This test is RED until T2.1 adds the `provenance` field to the Table
    dataclass. Once T2.1 lands, `load_schema_from_path` must accept this
    value and the loaded Table must expose `.provenance == 'single-vintage'`.
    """
    schema_yaml = _VALID_SCHEMA_TEMPLATE.format(provenance="single-vintage")
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(schema_yaml)

    schema = sl.load_schema_from_path(schema_file)

    assert schema is not None
    assert len(schema.tables) == 1
    table = schema.tables[0]
    assert table.provenance == "single-vintage"


# ---------------------------------------------------------------------------
# T1.2(b): valid schema with provenance: cumulative-snapshot loads successfully
# ---------------------------------------------------------------------------


def test_cumulative_snapshot_provenance_loads(tmp_path: Path):
    """A table declaring provenance: cumulative-snapshot must load without error.

    Goes GREEN when T2.1 lands. The loaded Table must expose
    `.provenance == 'cumulative-snapshot'`.
    """
    schema_yaml = _VALID_SCHEMA_TEMPLATE.format(provenance="cumulative-snapshot")
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(schema_yaml)

    schema = sl.load_schema_from_path(schema_file)

    assert schema is not None
    table = schema.tables[0]
    assert table.provenance == "cumulative-snapshot"


# ---------------------------------------------------------------------------
# T1.2(c): valid schema with provenance: managed loads successfully
# ---------------------------------------------------------------------------


def test_managed_provenance_loads(tmp_path: Path):
    """A table declaring provenance: managed must load without error.

    Goes GREEN when T2.1 lands. The loaded Table must expose
    `.provenance == 'managed'`.
    """
    schema_yaml = _VALID_SCHEMA_TEMPLATE.format(provenance="managed")
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(schema_yaml)

    schema = sl.load_schema_from_path(schema_file)

    assert schema is not None
    table = schema.tables[0]
    assert table.provenance == "managed"


# ---------------------------------------------------------------------------
# T1.2(d): schema missing provenance raises SchemaValidationError
# ---------------------------------------------------------------------------


def test_missing_provenance_raises_validation_error(tmp_path: Path):
    """A table entry that omits `provenance:` must raise SchemaValidationError.

    Goes GREEN when T2.1 lands. The error message should mention 'provenance'
    so an operator can quickly identify what is missing.
    """
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text(_SCHEMA_MISSING_PROVENANCE)

    with pytest.raises(sl.SchemaValidationError, match="provenance"):
        sl.load_schema_from_path(schema_file)
