"""test_r2d_cvx_compat.py — R2d compatibility smoke tests.

Two enforcement layers per spec § R2d (2026-08-26-adp-dealer-domain Group 5):

1. **Sidecar snapshot** — generate the parts-catalog corpus into a tmpdir and
   assert every sidecar carries ``source_category: "parts_catalog"``
   byte-identical.  This is the authoritative local proof that the G5.T1
   rewrite preserved the byte-identity contract.

2. **Cross-repo consumer smoke** — run the CVX-side filter-assertion test as a
   subprocess.  This confirms that three live CVX consumers (parts_lookup.py,
   persona_definitions.py, test_kb_tools.py) still see exactly the filter value
   they expect.  Requires the CVX checkout at
   ``~/guidance-for-connected-vehicle-experience-on-aws`` (or the path
   overridden via ``CVX_REPO_PATH`` env var).  The test ``pytest.skip``s with a
   named reason when the checkout is genuinely absent — a skip that fires when
   the checkout IS present is a self-defeating test and is prevented by the
   existence check below.

Constraints:
  - Do NOT hardcode absolute paths — resolve CVX repo via expanduser / env var.
  - The cross-repo smoke is *the* executable expression of the R2d contract; do
    NOT weaken it into a documentary assertion.
  - pytest.skip is acceptable only when CVX_REPO_PATH / the default path does
    not exist.  If the path exists, the test MUST run.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLATFORM_FOUNDATION = Path(__file__).resolve().parents[1]
_GENERATOR_PATH = (
    _PLATFORM_FOUNDATION
    / "source"
    / "data-products"
    / "vehicle_knowledge_base"
    / "generator.py"
)


def _load_generator():
    """Load generator module from file (avoids requiring it to be on sys.path)."""
    spec = importlib.util.spec_from_file_location("gen", _GENERATOR_PATH)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen


def _cvx_repo_path() -> Path:
    """Resolve the CVX checkout path from env var or default."""
    override = os.environ.get("CVX_REPO_PATH")
    if override:
        return Path(override)
    return Path("~/guidance-for-connected-vehicle-experience-on-aws").expanduser()


# ---------------------------------------------------------------------------
# Layer 1: Sidecar snapshot — regenerate corpus into tmpdir, verify all sidecars
# ---------------------------------------------------------------------------


class TestSidecarSnapshot:
    """Prove that every regenerated parts-catalog sidecar carries 'parts_catalog'."""

    def test_all_sidecars_carry_parts_catalog_value(self, tmp_path):
        """After run(), every *.md.metadata.json in parts-catalog has correct value."""
        gen = _load_generator()
        gen.run(output_root=tmp_path)

        pc_dir = tmp_path / "sources" / "parts-catalog"
        sidecars = sorted(pc_dir.glob("*.md.metadata.json"))
        assert sidecars, "No sidecars found in sources/parts-catalog/ — did the generator run?"

        drift = []
        for sc in sidecars:
            data = json.loads(sc.read_text(encoding="utf-8"))
            got = data.get("metadataAttributes", {}).get("source_category")
            if got != "parts_catalog":
                drift.append((str(sc.name), got))

        assert not drift, (
            f"Sidecar value drift on {len(drift)} file(s) — "
            f"must remain 'parts_catalog' (underscore, not hyphen) verbatim "
            f"per R2d compatibility contract with three live CVX consumers.\n"
            f"First drifted files: {drift[:5]}"
        )

    def test_doc_count_meets_requirement(self, tmp_path):
        """Regenerated corpus must emit >= 400 parts-catalog documents."""
        gen = _load_generator()
        gen.run(output_root=tmp_path)

        pc_dir = tmp_path / "sources" / "parts-catalog"
        docs = sorted(pc_dir.glob("*.md"))
        assert len(docs) >= 400, (
            f"Expected >= 400 parts-catalog docs post-regeneration, got {len(docs)}.  "
            "G5.T1 requires one document per SKU derived from generate_catalog()."
        )

    def test_sidecar_json_structure_is_exact(self, tmp_path):
        """Sidecar JSON structure must be exactly the Bedrock metadata format."""
        gen = _load_generator()
        gen.run(output_root=tmp_path)

        pc_dir = tmp_path / "sources" / "parts-catalog"
        sidecars = sorted(pc_dir.glob("*.md.metadata.json"))
        assert sidecars, "No sidecars found"

        # Check a sample of 10 (or all if fewer) for exact structure
        sample = sidecars[:10]
        for sc in sample:
            data = json.loads(sc.read_text(encoding="utf-8"))
            assert "metadataAttributes" in data, (
                f"{sc.name}: missing 'metadataAttributes' key — "
                "Bedrock KB metadata format requires this wrapper."
            )
            assert data["metadataAttributes"] == {"source_category": "parts_catalog"}, (
                f"{sc.name}: sidecar content mismatch.\n"
                f"  Expected: {{'metadataAttributes': {{'source_category': 'parts_catalog'}}}}\n"
                f"  Got:      {data}"
            )

    def test_filenames_are_deterministic_sku_based(self, tmp_path):
        """Filenames must be sku-<part_number>.md, not category-level names."""
        gen = _load_generator()
        gen.run(output_root=tmp_path)

        pc_dir = tmp_path / "sources" / "parts-catalog"
        docs = sorted(pc_dir.glob("*.md"))
        assert docs, "No docs found"

        # All filenames must start with 'sku-' — the category-narrative names
        # (brakes.md, engine.md, electrical.md, suspension.md, hvac.md)
        # must NOT appear after G5.T1 replacement.
        category_names = {"brakes.md", "engine.md", "electrical.md", "suspension.md", "hvac.md"}
        for doc in docs:
            assert doc.name not in category_names, (
                f"Old category-narrative document '{doc.name}' found after G5.T1 "
                "replacement.  Expected only per-SKU 'sku-*.md' documents."
            )
            assert doc.name.startswith("sku-"), (
                f"Document '{doc.name}' does not follow the expected 'sku-<part_number>.md' "
                "naming convention introduced by G5.T1."
            )

    def test_sidecar_value_uses_underscore_not_hyphen(self, tmp_path):
        """Explicitly confirm underscore ('parts_catalog') not hyphen ('parts-catalog')."""
        gen = _load_generator()
        gen.run(output_root=tmp_path)

        pc_dir = tmp_path / "sources" / "parts-catalog"
        sidecars = sorted(pc_dir.glob("*.md.metadata.json"))
        assert sidecars, "No sidecars found"

        # Sample check — the full check is in test_all_sidecars_carry_parts_catalog_value
        sc = sidecars[0]
        data = json.loads(sc.read_text(encoding="utf-8"))
        val = data.get("metadataAttributes", {}).get("source_category", "")
        assert val == "parts_catalog", (
            f"Sidecar value is {val!r}, expected 'parts_catalog' (underscore).\n"
            "The S3 prefix uses a hyphen ('sources/parts-catalog/') but the sidecar "
            "value uses an underscore — these are INDEPENDENT by design (§ Conventions).  "
            "CVX consumers filter on 'parts_catalog' (underscore)."
        )

    def test_curated_sidecars_if_present(self):
        """If the curated directory exists, all its sidecars must also carry parts_catalog."""
        curated_pc = (
            _PLATFORM_FOUNDATION
            / "curated"
            / "vehicle_knowledge_base"
            / "sources"
            / "parts-catalog"
        )
        if not curated_pc.exists():
            pytest.skip("Curated parts-catalog directory not present — skipping curated check")

        sidecars = sorted(curated_pc.glob("*.md.metadata.json"))
        if not sidecars:
            pytest.skip("No sidecars in curated directory — skipping curated check")

        for sc in sidecars:
            data = json.loads(sc.read_text(encoding="utf-8"))
            got = data.get("metadataAttributes", {}).get("source_category")
            assert got == "parts_catalog", (
                f"Curated sidecar {sc.name}: has source_category={got!r}, "
                "expected 'parts_catalog'.  Run the generator and re-ingest to update."
            )


# ---------------------------------------------------------------------------
# Layer 2: Cross-repo consumer smoke — CVX parts_lookup filter assertion
# ---------------------------------------------------------------------------


class TestCvxCrossRepoSmoke:
    """Run CVX-side filter test to confirm the R2d contract is live end-to-end."""

    def test_cvx_parts_lookup_happy_path(self):
        """CVX test_parts_lookup_happy_path must pass with the current sidecar value.

        This test is the executable expression of the R2d compatibility contract.
        It confirms that three live CVX consumers key off source_category='parts_catalog'
        (underscore) and that the filter value matches:

            {'equals': {'key': 'source_category', 'value': 'parts_catalog'}}

        Reference: ~/guidance-for-connected-vehicle-experience-on-aws/
                   agents/supervisor/tests/test_kb_tools.py::test_parts_lookup_happy_path
                   (asserts the filter at line ~232)
        """
        cvx_repo = _cvx_repo_path()
        if not cvx_repo.exists():
            pytest.skip(
                f"CVX checkout not found at {cvx_repo} "
                "(set CVX_REPO_PATH env var to override). "
                "This skip is acceptable ONLY when the checkout is genuinely absent."
            )

        # CVX checkout IS present — the test MUST run, not skip.
        cvx_python = cvx_repo / ".venv" / "bin" / "python"
        if not cvx_python.exists():
            # Fall back to the system python from the CVX venv
            cvx_python = cvx_repo / ".venv" / "bin" / "python3"
        if not cvx_python.exists():
            pytest.fail(
                f"CVX checkout is present at {cvx_repo} but no .venv/bin/python found.  "
                "Cannot run cross-repo smoke — install CVX dependencies first."
            )

        result = subprocess.run(
            [
                str(cvx_python),
                "-m",
                "pytest",
                "agents/supervisor/tests/test_kb_tools.py::test_parts_lookup_happy_path",
                "-v",
                "--tb=short",
            ],
            cwd=str(cvx_repo),
            env={**os.environ, "VSA_KB_SOURCE_CATEGORY_FILTER": "true"},
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            pytest.fail(
                f"CVX cross-repo smoke FAILED (exit {result.returncode}).\n\n"
                f"stdout:\n{result.stdout}\n\n"
                f"stderr:\n{result.stderr}\n\n"
                "This indicates the sidecar value 'parts_catalog' no longer matches "
                "what the CVX parts_lookup tool expects.  "
                "Check agents/supervisor/tools/parts_lookup.py:83 in the CVX repo."
            )



# ---------------------------------------------------------------------------
# Layer 3: Reconciliation regression — regeneration over a stale corpus
#          This test MUST FAIL against the pre-fix generator and PASS after.
#          Added by Fix Group 3 (FG3.T1) to pin the exact-set contract that
#          the prior >= 400 floor assertions left unguarded.
# ---------------------------------------------------------------------------


_SUPERSEDED_NAMES = ("brakes", "electrical", "engine", "hvac", "suspension")


class TestPartsReconciliation:
    """Prove that regenerating over a stale corpus removes superseded docs.

    This is the regression test for the defect reported in
    ``issues/2026-09-09-parts-catalog-regen-leaves-superseded-narrative-docs/``.

    The defect: ``run()`` writes docs by deterministic filename and never
    reconciles the output directory.  The old naming scheme (``<category>.md``)
    does not collide with the new scheme (``sku-<part_number>.md``), so stale
    docs survive regeneration.  Both lineups carry
    ``source_category: "parts_catalog"`` and would be ingested together.

    The fix: before writing parts-catalog docs, snapshot the existing ``*.md``
    and ``*.md.metadata.json`` files in ``sources/parts-catalog/``; after
    writing the new set, delete any files not written this run.  The
    reconciliation MUST be scoped to ``sources/parts-catalog/`` only.
    """

    def test_regeneration_removes_superseded_narrative_docs(self, tmp_path):
        """Regenerating over a pre-seeded stale corpus MUST leave zero survivors.

        Pre-condition: seed the 5 superseded category-narrative docs into
        ``sources/parts-catalog/`` *before* calling run().  A correct generator
        removes them; a broken generator leaves them alongside the new sku-*.md
        docs.
        """
        gen = _load_generator()

        # --- seed the superseded docs ----------------------------------------
        pc_dir = tmp_path / "sources" / "parts-catalog"
        pc_dir.mkdir(parents=True)
        for name in _SUPERSEDED_NAMES:
            body_path = pc_dir / f"{name}.md"
            body_path.write_text(f"stale narrative for {name}\n", encoding="utf-8")
            sidecar_path = pc_dir / f"{name}.md.metadata.json"
            sidecar_path.write_text(
                '{"metadataAttributes": {"source_category": "parts_catalog"}}',
                encoding="utf-8",
            )

        stale_before = sorted(p.name for p in pc_dir.glob("*.md"))
        assert len(stale_before) == 5, f"setup error: expected 5 stale docs, got {stale_before}"

        # --- regenerate -------------------------------------------------------
        gen.run(output_root=tmp_path)

        # --- assert: superseded docs are gone ---------------------------------
        all_md = {p.name for p in pc_dir.glob("*.md")}
        stale_survivors = {f"{n}.md" for n in _SUPERSEDED_NAMES} & all_md
        assert not stale_survivors, (
            f"Superseded narrative docs survived regeneration: {sorted(stale_survivors)}\n"
            "The generator must reconcile the parts-catalog prefix so that files not "
            "written in the current run are removed.  Both the stale docs and the new "
            "sku-*.md docs carry source_category='parts_catalog', so a mixed corpus "
            "defeats spec Decision 4 (R2d supersession).\n"
            f"Total docs in prefix after regen: {len(all_md)} "
            f"(expected ~586 sku-*.md only, no category-narrative names)"
        )

    def test_regeneration_removes_orphaned_sidecars(self, tmp_path):
        """A stale doc's paired sidecar must also be removed on regeneration.

        An orphaned sidecar (body deleted, .metadata.json surviving) is itself
        a KB-ingest artifact — Bedrock treats it as standalone metadata and
        could associate it with a freshly-ingested document by chance.
        """
        gen = _load_generator()

        pc_dir = tmp_path / "sources" / "parts-catalog"
        pc_dir.mkdir(parents=True)
        for name in _SUPERSEDED_NAMES:
            (pc_dir / f"{name}.md").write_text(f"stale {name}\n", encoding="utf-8")
            (pc_dir / f"{name}.md.metadata.json").write_text(
                '{"metadataAttributes": {"source_category": "parts_catalog"}}',
                encoding="utf-8",
            )

        gen.run(output_root=tmp_path)

        # After reconciliation, every remaining sidecar must have a paired body.
        orphaned = [
            s.name
            for s in pc_dir.glob("*.md.metadata.json")
            if not (pc_dir / s.name.replace(".metadata.json", "")).exists()
        ]
        assert not orphaned, (
            f"Orphaned sidecars (body deleted, sidecar surviving): {orphaned}\n"
            "Each stale .md and its .md.metadata.json must be removed together."
        )

    def test_reconciliation_does_not_delete_outside_parts_catalog(self, tmp_path):
        """Reconciliation MUST NOT remove files from other KB category prefixes.

        This is the blast-radius guard.  TWO canaries are required, at
        different depths, because the reconciliation snapshot uses a
        non-recursive ``iterdir()``:

        - ``sources/dtc-guides/`` (sibling subdirectory) catches a widening
          of the scope to a recursive walk.
        - ``sources/`` (directly, one level up) catches a widening of
          ``_parts_catalog_dir`` from ``sources/parts-catalog`` to ``sources``.
          The subdirectory canary alone passes VACUOUSLY under that mutation,
          since a non-recursive ``iterdir()`` of ``sources/`` never descends
          into ``dtc-guides/``.  Found by review cycle 4; do not remove either
          canary on the assumption the other covers it.
        """
        gen = _load_generator()

        # Canary 1 — sibling subdirectory (guards against a recursive walk).
        dtc_dir = tmp_path / "sources" / "dtc-guides"
        dtc_dir.mkdir(parents=True)
        nested_canary = dtc_dir / "ZZ-architect-canary.md"
        nested_canary.write_text(
            "must survive parts-catalog regeneration\n", encoding="utf-8")

        # Canary 2 — directly in sources/ (guards against widening the
        # reconciliation directory itself by one level).
        top_canary = tmp_path / "sources" / "ZZ-architect-toplevel-canary.md"
        top_canary.write_text(
            "must survive parts-catalog regeneration\n", encoding="utf-8")
        top_sidecar = tmp_path / "sources" / "ZZ-architect-toplevel-canary.md.metadata.json"
        top_sidecar.write_text('{"metadataAttributes":{}}', encoding="utf-8")

        gen.run(output_root=tmp_path)

        assert nested_canary.exists(), (
            "Reconciliation deleted a file in a sibling category prefix "
            "('sources/dtc-guides/') — blast radius widened to a recursive "
            "walk.  Only 'sources/parts-catalog/' is generator-owned here."
        )
        assert top_canary.exists(), (
            "Reconciliation deleted a .md file directly in 'sources/' — the "
            "reconciliation directory has been widened from "
            "'sources/parts-catalog' to 'sources'."
        )
        assert top_sidecar.exists(), (
            "Reconciliation deleted a sidecar directly in 'sources/' — the "
            "reconciliation directory has been widened from "
            "'sources/parts-catalog' to 'sources'."
        )

    def test_removed_sku_leaves_no_stale_doc(self, tmp_path):
        """A SKU removed from the fixture must not leave a stale doc after regen.

        This pins the secondary defect: a discontinued SKU stays retrievable
        after removal unless the generator reconciles.
        """
        gen = _load_generator()

        # First run: generate normally.
        gen.run(output_root=tmp_path)
        pc_dir = tmp_path / "sources" / "parts-catalog"
        docs_run1 = {p.name for p in pc_dir.glob("*.md")}
        assert docs_run1, "First run produced no docs — fixture issue"

        # Plant a fake SKU doc as if it were a removed-SKU leftover.
        ghost_name = "sku-ZZDISCONTINUED99999.md"
        ghost = pc_dir / ghost_name
        ghost.write_text("discontinued SKU, must be removed on next run\n", encoding="utf-8")
        ghost_sidecar = pc_dir / f"{ghost_name}.metadata.json"
        ghost_sidecar.write_text(
            '{"metadataAttributes": {"source_category": "parts_catalog"}}',
            encoding="utf-8",
        )

        # Second run: regenerate.
        gen.run(output_root=tmp_path)
        docs_run2 = {p.name for p in pc_dir.glob("*.md")}

        assert ghost_name not in docs_run2, (
            f"Stale doc for discontinued SKU '{ghost_name}' survived regeneration.\n"
            "The generator must reconcile the parts-catalog prefix on every run so "
            "that SKUs no longer in the fixture do not remain retrievable."
        )
        assert not ghost_sidecar.exists(), (
            f"Orphaned sidecar for discontinued SKU '{ghost_name}' survived.\n"
            "Both the body and the sidecar must be removed together."
        )
