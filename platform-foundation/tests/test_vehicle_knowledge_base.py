"""Per-product tests for `vehicle_knowledge_base` (documents-format, not Iceberg)."""

from __future__ import annotations

import pytest

import schema_loader as sl  # noqa: E402


def test_schema_loads():
    s = sl.load_schema("vehicle_knowledge_base", kind="product")
    assert s.first_table().name == "vehicle_knowledge_base"


def test_documents_storage_format():
    s = sl.load_schema("vehicle_knowledge_base", kind="product")
    assert s.first_table().storage_format == "documents"


def test_no_iceberg_ddl_for_documents():
    s = sl.load_schema("vehicle_knowledge_base", kind="product")
    tbl = s.first_table()
    with pytest.raises(ValueError):
        tbl.iceberg_ddl(database="adp_vehicle_knowledge_base", location="s3://x/")


def test_chunk_metadata_fields_present():
    s = sl.load_schema("vehicle_knowledge_base", kind="product")
    tbl = s.first_table()
    for col in ("chunk_id", "source_doc_id", "chunk_size_tokens", "chunk_overlap_tokens", "embedding_model"):
        assert tbl.column_by_name(col) is not None, f"Missing KB column: {col}"


def test_source_category_enum_includes_charging_and_ota():
    s = sl.load_schema("vehicle_knowledge_base", kind="product")
    col = s.first_table().column_by_name("source_category")
    assert col is not None
    assert "charging_narrative" in col.enum_values
    assert "ota_rollout_summary" in col.enum_values


@pytest.mark.needs_curated
def test_kb_chunks_present(curated_root):
    """Validate the Group 3 generator's manifest if curated data exists.

    The ``needs_curated`` marker auto-skips when the curated tree is
    empty (per ``conftest.py``). When present, this test reads
    ``manifest.json`` and asserts the chunk schema contract holds.
    """
    manifest_path = curated_root / "vehicle_knowledge_base" / "manifest.json"
    if not manifest_path.exists():
        pytest.skip(f"manifest not found at {manifest_path}")
    import json

    manifest = json.loads(manifest_path.read_text())
    assert manifest["product"] == "vehicle_knowledge_base"
    assert manifest["storage_format"] == "documents"
    assert manifest["chunk_count"] > 0, "no chunks emitted"
    # Every chunk row must carry the schema-declared columns.
    required = {
        "chunk_id", "source_doc_id", "source_category", "title",
        "chunk_index", "chunk_text", "chunk_size_tokens",
        "chunk_overlap_tokens", "embedding_model", "s3_uri",
        "language", "indexed_at",
    }
    for c in manifest["chunks"][:5]:  # spot-check first 5
        missing = required - c.keys()
        assert not missing, f"chunk missing columns: {missing}"
    # The two EV-specific categories must be present per schema enum.
    cats = manifest["chunks_by_category"]
    assert cats.get("charging_narrative", 0) > 0
    assert cats.get("ota_rollout_summary", 0) > 0
