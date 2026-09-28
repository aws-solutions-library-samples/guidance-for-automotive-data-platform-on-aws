"""tests/test_parts_seed.py — Verify T3.6 seed scripts.

Tests cover:
  1. Fixture counts (catalog >=500, fitment >=1200, interchange >=200)
  2. All IDs in DMS-prefixed namespace
  3. Zero 'independent' rows (access_channel='franchise' only)
  4. Supersession chain proof (3-deep)
  5. Fanout proof (1-primary-to-N)
  6. DTC family coverage (OE cross + aftermarket per P0420/P0300/C0035/U0100/P0171/B0001)
  7. All three relationship_type values present
  8. Schema validation against pies_8_0_shape.json / aces_5_0_shape.json
  9. IDEMPOTENCY — a real second run produces zero net writes (not stubbed)

T3.7's lint tests live in test_lint_no_licensed_autocare_ids.py.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Resolve script paths relative to this test file
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
SCHEMAS_DIR = Path(__file__).parent.parent / "source" / "schemas"

sys.path.insert(0, str(SCRIPTS_DIR))

import seed_parts_catalog as catalog_mod
import seed_parts_fitment as fitment_mod
import seed_parts_interchange as interchange_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _all_catalog(fixture_dir: Path) -> list[dict[str, Any]]:
    return catalog_mod.generate_catalog()


def _all_fitment() -> list[dict[str, Any]]:
    return fitment_mod.generate_fitment()


def _all_interchange() -> list[dict[str, Any]]:
    records = interchange_mod._generate_interchange()
    # De-duplicate exactly as the seed function does
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for r in records:
        pk = (r["primary_part_number"], r["replacement_part_number"])
        if pk not in seen:
            seen[pk] = r
            deduped.append(r)
    return deduped


# ---------------------------------------------------------------------------
# 1. Fixture counts
# ---------------------------------------------------------------------------
class TestFixtureCounts:
    def test_catalog_at_least_500(self) -> None:
        records = _all_catalog(Path())
        assert len(records) >= 500, (
            f"Expected >=500 catalog records, got {len(records)}"
        )

    def test_catalog_spans_at_least_80_terminology_categories(self) -> None:
        records = _all_catalog(Path())
        categories = {r["part_terminology_id"] for r in records}
        assert len(categories) >= 80, (
            f"Expected >=80 terminology categories, got {len(categories)}"
        )

    def test_fitment_at_least_1200(self) -> None:
        records = _all_fitment()
        assert len(records) >= 1200, (
            f"Expected >=1200 fitment records, got {len(records)}"
        )

    def test_fitment_spans_all_12_vehicle_configs(self) -> None:
        records = _all_fitment()
        configs = {r["vehicle_config_id"] for r in records}
        assert len(configs) == 12, (
            f"Expected 12 vehicle configs, got {len(configs)}"
        )

    def test_interchange_at_least_200(self) -> None:
        records = _all_interchange()
        assert len(records) >= 200, (
            f"Expected >=200 interchange records, got {len(records)}"
        )


# ---------------------------------------------------------------------------
# 2. DMS-namespace invariant
# ---------------------------------------------------------------------------
class TestDmsNamespace:
    def test_catalog_brand_ids_are_dms_prefixed(self) -> None:
        records = _all_catalog(Path())
        violations = [
            r["brand_aaia_id"]
            for r in records
            if not r["brand_aaia_id"].startswith("DMS-BR-")
        ]
        assert not violations, f"Non-DMS brand_aaia_id found: {violations[:5]}"

    def test_catalog_terminology_ids_are_dms_prefixed(self) -> None:
        records = _all_catalog(Path())
        violations = [
            r["part_terminology_id"]
            for r in records
            if not r["part_terminology_id"].startswith("DMS-PT-")
        ]
        assert not violations, f"Non-DMS part_terminology_id: {violations[:5]}"

    def test_catalog_attribute_ids_are_dms_prefixed(self) -> None:
        records = _all_catalog(Path())
        for rec in records:
            attrs = rec.get("extended_attributes") or []
            for a in attrs:
                assert a["attribute_id"].startswith("DMS-PA-"), (
                    f"Non-DMS attribute_id: {a['attribute_id']} on part {rec['part_number']}"
                )

    def test_fitment_vehicle_config_ids_are_dms_prefixed(self) -> None:
        records = _all_fitment()
        violations = [
            r["vehicle_config_id"]
            for r in records
            if not r["vehicle_config_id"].startswith("DMS-VCFG-")
        ]
        assert not violations, f"Non-DMS vehicle_config_id found: {violations[:5]}"

    def test_fitment_qualifier_ids_are_dms_prefixed_when_present(self) -> None:
        records = _all_fitment()
        for rec in records:
            quals = rec.get("qualifiers") or []
            for q in quals:
                qid = q.get("qualifier_id")
                if qid is not None:
                    assert qid.startswith("DMS-QT-"), (
                        f"Non-DMS qualifier_id: {qid}"
                    )

    def test_interchange_part_numbers_are_dms_prefixed(self) -> None:
        records = _all_interchange()
        for rec in records:
            for field in ("primary_part_number", "replacement_part_number"):
                assert rec[field].startswith("DMS-"), (
                    f"Non-DMS part number in interchange {field}: {rec[field]}"
                )


# ---------------------------------------------------------------------------
# 3. access_channel='franchise' — zero 'independent' rows
# ---------------------------------------------------------------------------
class TestAccessChannelFranchiseOnly:
    def test_catalog_no_independent_rows(self) -> None:
        records = _all_catalog(Path())
        violations = [r for r in records if r.get("access_channel") != "franchise"]
        assert not violations, (
            f"Found {len(violations)} non-franchise rows in catalog. "
            "Decision 3: v1 seeds franchise only."
        )

    def test_fitment_no_independent_rows(self) -> None:
        records = _all_fitment()
        violations = [r for r in records if r.get("access_channel") != "franchise"]
        assert not violations, (
            f"Found {len(violations)} non-franchise rows in fitment. "
            "Decision 3: v1 seeds franchise only."
        )

    def test_interchange_no_independent_rows(self) -> None:
        records = _all_interchange()
        violations = [r for r in records if r.get("access_channel") != "franchise"]
        assert not violations, (
            f"Found {len(violations)} non-franchise rows in interchange. "
            "Decision 3: v1 seeds franchise only."
        )


# ---------------------------------------------------------------------------
# 4. Supersession chain proof — at least 3-deep
# ---------------------------------------------------------------------------
class TestSupersessionChain:
    def test_3_deep_chain_exists(self) -> None:
        """A 3-deep chain: A → B → C means:
        record (A, B, supersession) AND record (B, C, supersession) both exist.
        """
        records = _all_interchange()
        # Build adjacency: primary → set of replacements for supersession only
        superseded_by: dict[str, set[str]] = {}
        for rec in records:
            if rec["relationship_type"] == interchange_mod.SUPERSESSION:
                superseded_by.setdefault(rec["primary_part_number"], set()).add(
                    rec["replacement_part_number"]
                )

        # Find a 3-deep chain: exists A, B, C where A→B and B→C (supersession)
        found_3_deep = False
        chain_example = None
        for a, b_set in superseded_by.items():
            for b in b_set:
                if b in superseded_by:
                    # A → B → C
                    for c in superseded_by[b]:
                        if c != a:  # No cycles back to start
                            found_3_deep = True
                            chain_example = (a, b, c)
                            break
                if found_3_deep:
                    break
            if found_3_deep:
                break

        assert found_3_deep, (
            "No 3-deep supersession chain found. "
            "Required: at least one A→B→C chain where both links are 'supersession'."
        )
        # Log the discovered chain for audit
        a, b, c = chain_example  # type: ignore[misc]
        assert a.startswith("DMS-"), f"Chain node A is not DMS-prefixed: {a}"
        assert b.startswith("DMS-"), f"Chain node B is not DMS-prefixed: {b}"
        assert c.startswith("DMS-"), f"Chain node C is not DMS-prefixed: {c}"


# ---------------------------------------------------------------------------
# 5. Fanout proof — 1-primary-to-N replacements
# ---------------------------------------------------------------------------
class TestFanout:
    def test_one_primary_to_multiple_replacements(self) -> None:
        """At least one primary_part_number maps to >= 3 distinct replacement_part_numbers."""
        records = _all_interchange()
        by_primary: dict[str, list[str]] = {}
        for rec in records:
            primary = rec["primary_part_number"]
            by_primary.setdefault(primary, []).append(rec["replacement_part_number"])

        max_fanout = max(len(v) for v in by_primary.values())
        fanout_examples = {k: v for k, v in by_primary.items() if len(v) >= 3}
        assert max_fanout >= 3, (
            f"Expected at least one 1→N fanout with N>=3, max found was {max_fanout}. "
            "Required: same primary_part_number with 3+ replacement entries."
        )
        assert len(fanout_examples) >= 1, "No 1→N fanout example found"


# ---------------------------------------------------------------------------
# 6. DTC family coverage
# ---------------------------------------------------------------------------
DTC_FAMILIES = ["P0420", "P0300", "C0035", "U0100", "P0171", "B0001"]


class TestDtcFamilyCoverage:
    def _get_interchange_records(self) -> list[dict[str, Any]]:
        return _all_interchange()

    @pytest.mark.parametrize("dtc", DTC_FAMILIES)
    def test_dtc_has_oe_cross_reference(self, dtc: str) -> None:
        """Each DTC family must have at least one OE cross-reference record."""
        records = self._get_interchange_records()
        oe_records = [
            r for r in records
            if r["relationship_type"] == interchange_mod.OE_CROSS
            and dtc in (r.get("notes") or "")
        ]
        assert oe_records, (
            f"DTC {dtc}: no OE cross-reference record found in interchange. "
            "Required per T3.6: at least one oe_cross per warranty-relevant DTC family."
        )

    @pytest.mark.parametrize("dtc", DTC_FAMILIES)
    def test_dtc_has_aftermarket_equivalent(self, dtc: str) -> None:
        """Each DTC family must have at least one aftermarket equivalent record."""
        records = self._get_interchange_records()
        am_records = [
            r for r in records
            if r["relationship_type"] == interchange_mod.AFTERMARKET
            and dtc in (r.get("notes") or "")
        ]
        assert am_records, (
            f"DTC {dtc}: no aftermarket_equivalent record found in interchange. "
            "Required per T3.6: at least one aftermarket_equivalent per DTC family."
        )


# ---------------------------------------------------------------------------
# 7. All three relationship_type values present
# ---------------------------------------------------------------------------
class TestRelationshipTypes:
    def test_all_three_types_present(self) -> None:
        records = _all_interchange()
        types_present = {r["relationship_type"] for r in records}
        required = {
            interchange_mod.SUPERSESSION,
            interchange_mod.OE_CROSS,
            interchange_mod.AFTERMARKET,
        }
        missing = required - types_present
        assert not missing, f"Missing relationship types: {missing}"


# ---------------------------------------------------------------------------
# 8. Schema validation (sampled records)
# ---------------------------------------------------------------------------
class TestSchemaValidation:
    @pytest.fixture(scope="class")
    def pies_schema(self) -> dict[str, Any]:
        schema_path = SCHEMAS_DIR / "pies_8_0_shape.json"
        return json.loads(schema_path.read_text())

    @pytest.fixture(scope="class")
    def aces_schema(self) -> dict[str, Any]:
        schema_path = SCHEMAS_DIR / "aces_5_0_shape.json"
        return json.loads(schema_path.read_text())

    def test_catalog_sample_validates_against_pies_schema(
        self, pies_schema: dict[str, Any]
    ) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        records = _all_catalog(Path())
        # Validate first, middle, and last records
        samples = [records[0], records[len(records) // 2], records[-1]]
        validator = jsonschema.Draft7Validator(pies_schema)
        for rec in samples:
            errors = list(validator.iter_errors(rec))
            assert not errors, (
                f"Catalog record {rec['part_number']} failed PIES schema validation: "
                + "; ".join(str(e.message) for e in errors[:3])
            )

    def test_fitment_sample_validates_against_aces_schema(
        self, aces_schema: dict[str, Any]
    ) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        records = _all_fitment()
        samples = [records[0], records[len(records) // 2], records[-1]]
        validator = jsonschema.Draft7Validator(aces_schema)
        for rec in samples:
            errors = list(validator.iter_errors(rec))
            assert not errors, (
                f"Fitment record {rec['part_number']}/{rec['vehicle_config_id']} "
                "failed ACES schema validation: "
                + "; ".join(str(e.message) for e in errors[:3])
            )


# ---------------------------------------------------------------------------
# 9. IDEMPOTENCY — real second run must produce zero net writes
#
# Portfolio lesson from agentic-tiers.md:
#   "A stub cannot fail the way a service fails."
#   We exercise each seed() function twice against a real temp directory.
#   The first run writes N records; the second run must write 0.
# ---------------------------------------------------------------------------
class TestIdempotency:
    def _run_twice(self, seed_fn, name: str) -> None:
        """Run seed_fn twice; assert second run writes 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_dir = Path(tmpdir)

            first_run_writes = seed_fn(
                dry_run=False,
                fixture_dir=fixture_dir,
                verbose=False,
            )
            assert first_run_writes > 0, (
                f"{name}: first run wrote 0 records — "
                "fixture generation may be broken."
            )

            second_run_writes = seed_fn(
                dry_run=False,
                fixture_dir=fixture_dir,
                verbose=False,
            )
            assert second_run_writes == 0, (
                f"{name}: second run wrote {second_run_writes} records — "
                "idempotency contract violated. "
                "The seed must produce zero net writes on re-run."
            )

    def test_catalog_idempotency(self) -> None:
        self._run_twice(catalog_mod.seed, "seed_parts_catalog")

    def test_fitment_idempotency(self) -> None:
        self._run_twice(fitment_mod.seed, "seed_parts_fitment")

    def test_interchange_idempotency(self) -> None:
        self._run_twice(interchange_mod.seed, "seed_parts_interchange")

    def test_all_three_seeds_idempotent_in_shared_dir(self) -> None:
        """All three seeds share the same fixture_dir; none should corrupt the others."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_dir = Path(tmpdir)

            # First pass — all three
            c1 = catalog_mod.seed(dry_run=False, fixture_dir=fixture_dir)
            f1 = fitment_mod.seed(dry_run=False, fixture_dir=fixture_dir)
            i1 = interchange_mod.seed(dry_run=False, fixture_dir=fixture_dir)

            assert c1 > 0, "Catalog first-run wrote 0"
            assert f1 > 0, "Fitment first-run wrote 0"
            assert i1 > 0, "Interchange first-run wrote 0"

            # Second pass — all three must be 0
            c2 = catalog_mod.seed(dry_run=False, fixture_dir=fixture_dir)
            f2 = fitment_mod.seed(dry_run=False, fixture_dir=fixture_dir)
            i2 = interchange_mod.seed(dry_run=False, fixture_dir=fixture_dir)

            assert c2 == 0, f"Catalog second-run wrote {c2} (expected 0)"
            assert f2 == 0, f"Fitment second-run wrote {f2} (expected 0)"
            assert i2 == 0, f"Interchange second-run wrote {i2} (expected 0)"
