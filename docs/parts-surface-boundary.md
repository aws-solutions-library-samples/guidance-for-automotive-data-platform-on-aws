# Parts surface boundary — authoritative store vs. derived read surface

**Status:** Current direction, effective 2026-08-27. Records Decision 4
of spec `2026-08-26-adp-dealer-domain` (R2d supersession).

This file is the go-to reference for how the two "parts" surfaces
relate. It is not a history log — for the pre-supersession
"complementary, not competing" position, see the spec's own
`spec.md` § Decision 4 § Provenance.

## The two surfaces

ADP ships two catalog surfaces that carry parts data:

| Surface | Kind | Location | Cardinality (v1) |
|---|---|---|---|
| `adp_{stage}_parts_domain.parts_catalog` | Iceberg table (structured) | Glue database `adp_{stage}_parts_domain`, backed by the S3 lake | ~500 SKU rows |
| Bedrock KB corpus with `source_category: "parts_catalog"` | Markdown docs (unstructured) | `s3://adp-{stage}-foundation-lake-<account>-us-east-1/knowledge/vehicle_knowledge_base/sources/` under the `parts-catalog/` prefix | ~500 per-SKU markdown documents |

Both surfaces exist because agents and analytics need different
access shapes. The point of this doc is what happens when they
diverge: which one wins.

## The direction

`adp_parts_domain.parts_catalog` is **authoritative**. It is the
structured, governed, single source of truth for parts.

The Bedrock KB corpus with `source_category: "parts_catalog"` is a
**derived read surface regenerated from `adp_parts_domain.parts_catalog`**.
The corpus is produced by the seed pipeline's per-SKU markdown
generator (`source/data-products/vehicle_knowledge_base/generator.py`
§ `generate_parts_catalog()`), reading the seeded parts-catalog
fixtures at generation time. A single-source-of-truth model applies:
every fact expressed in a KB parts-catalog document is derivable
from the corresponding SKU row in the authoritative table.

The sidecar value `source_category: "parts_catalog"` is preserved
**byte-for-byte** as the compatibility contract with three live
CVX consumer sites (all in the sibling repo
`guidance-for-connected-vehicle-experience-on-aws`):

- `agents/supervisor/tools/parts_lookup.py:83` — runtime KB Retrieve
  filter (literal `{"equals": {"key": "source_category", "value":
  "parts_catalog"}}`).
- `agents/supervisor/persona_definitions.py:133,435` — the Technician
  persona's KB category list carries `"parts_catalog"` verbatim.
- `agents/supervisor/tests/test_kb_tools.py:228` — CVX CI asserts
  `flt == {"equals": {"key": "source_category", "value": "parts_catalog"}}`.

Any change to the sidecar value (adding a hyphenated variant,
renaming, dropping the sidecar) breaks all three consumers silently
— they get zero hits and produce unhelpful "no results" responses.
The regeneration test suite (`platform-foundation/tests/test_r2d_cvx_compat.py`)
guards this contract by loading a fixture of the live consumers'
retrieve calls and asserting non-empty results against the regenerated
corpus.

## Do not do

The regeneration test suite (G5.T2) and the licensing lint (G3.T2)
enforce these prohibitions, but write them down so they are visible
to a human reader before the tests catch them at review time:

- **Do not rebuild the corpus from a stale KB copy.** Always
  regenerate from `adp_parts_domain.parts_catalog` in the same run
  that reads the authoritative table. Reading the old KB corpus
  and re-emitting it perpetuates any drift that has crept in since
  the last regeneration. See `parts_lookup.py` § "why we read the
  KB and not the table" — it explains what the corpus does that
  the table cannot (unstructured text for embedding), not that the
  KB is the source of truth.
- **Do not add a `parts-catalog` (hyphenated) sidecar variant.**
  The three consumers listed above filter on the exact string
  `"parts_catalog"` (underscore, singular, lowercase). A hyphenated
  variant introduces a second lineup that consumers cannot see, and
  Decision 4 exists to prevent exactly that state.
- **Do not retire the corpus without re-ingesting the regeneration
  first.** The regenerated docs replace the pre-supersession
  category-narrative corpus by prefix reconciliation (see spec
  Fix Group 3): the S3 prefix reconciliation runs before ingestion
  so no superseded document survives. Retiring in the wrong order —
  wiping the old corpus, ingesting the new later — leaves the
  three consumers with zero hits for however long the gap lasts.
- **Do not let sidecar drift into the authoritative table.** The
  `source_category` sidecar is a KB-corpus concept, not a table
  column. The Iceberg schema for `parts_catalog` (see
  `source/data-products/parts_catalog/schema.yaml`) does not declare
  a `source_category` column, and the seed generator does not write
  one. Keeping the concept in one place (the KB corpus) is what
  keeps this surface derived rather than a second source of truth.

## Concurrent-spec sequencing

DMS spec `2026-08-26-dms-accelerator-v1` T3.3 (KB source-category
extensions) and its DMS-side follow-on `2026-09-01-dms-customer-master-adp`
both read from the KB via the same `source_category == "parts_catalog"`
filter. When either DMS spec's tests need a live parts corpus, run
the ADP-side regeneration (`python3 scripts/generate.py --product
vehicle_knowledge_base --category parts_catalog`) plus the manual
ingestion trigger (`python3 scripts/trigger-kb-ingest.py --stage
<stage>`) before the DMS tests run. G4.T3 in the ADP spec captures
the manual ingestion runbook.

## References

- Spec: `.kiro/specs/2026-08-26-adp-dealer-domain/spec.md` § Decision 4
- Regeneration generator: `source/data-products/vehicle_knowledge_base/generator.py` § `generate_parts_catalog()`
- Prefix reconciliation (Fix Group 3): same generator, plus the
  guarded `_reconcile_parts_catalog_prefix()` helper
- Consumer contract test: `platform-foundation/tests/test_r2d_cvx_compat.py`
- Licensing lint: `platform-foundation/scripts/lint_no_licensed_autocare_ids.py`
- CVX consumer sites (three): `guidance-for-connected-vehicle-experience-on-aws/agents/supervisor/tools/parts_lookup.py`, `.../agents/supervisor/persona_definitions.py`, `.../agents/supervisor/tests/test_kb_tools.py`
