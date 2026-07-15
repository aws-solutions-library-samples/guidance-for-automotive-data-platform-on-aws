# Vehicle Knowledge Base (`vehicle_knowledge_base`)

> **Domain**: Knowledge &nbsp;·&nbsp; **Storage**: documents
> (NOT Iceberg) &nbsp;·&nbsp; **Display name**: `Vehicle Knowledge Base`

Document-oriented knowledge product — pre-chunked text artifacts
(DTC guides, TSBs, owner manuals, parts catalog, service network,
service policy, plus EV-specific charging narratives and OTA rollout
summaries) materialized to S3 with a manifest describing every chunk.
Designed to be ingested by a Bedrock Knowledge Base; retrievable by
a CVX agent or any Bedrock-grounded consumer. Producer is
[`generator.py`](generator.py) plus the data-derived
[`extended_seed.py`](extended_seed.py); column formats follow
[`docs/data-contracts.md`](../../../../docs/data-contracts.md).

## Schema

| Column | Type | Nullable | Description |
|---|---|---|---|
| `chunk_id` | string | no | Stable chunk identifier (UUIDv5 from `source_doc_id + chunk_index`; PK) |
| `source_doc_id` | string | no | Source document identifier (DTC guide ID, TSB number, etc.) |
| `source_category` | string | no | enum: `dtc_guide` / `tsb_recall` / `owner_manual` / `parts_catalog` / `service_network` / `service_policy` / `charging_narrative` / `ota_rollout_summary` |
| `title` | string | no | Human-readable document title |
| `chunk_index` | int | no | 0-based index within the source document (0–100000) |
| `chunk_text` | string | no | Plain-text body of the chunk |
| `chunk_size_tokens` | int | no | Heuristic token count (~1.3 tokens/word; Bedrock recomputes exact at ingest) |
| `chunk_overlap_tokens` | int | no | Token overlap with adjacent chunk (0–512) |
| `embedding_model` | string | no | Bedrock embedding model identifier (default `amazon.titan-embed-text-v2:0`) |
| `s3_uri` | string | no | S3 URI of the source artifact |
| `language` | string | no | ISO 639-1 language code (default `en`) |
| `indexed_at` | timestamp | no | When the Bedrock KB ingested this chunk |

## Partition keys

- **No Iceberg partition** — `storage_format: documents`. The
  manifest is a single JSON file; chunks are stored as Markdown
  artifacts under category-named S3 prefixes.
- **Source-of-truth layout**:
  ```
  s3://adp-{stage}-foundation-lake-<account>-us-east-1/knowledge/vehicle_knowledge_base/
  ├── manifest.json                       # base generator chunks
  ├── manifest_extended.json              # data-derived narrative summaries
  └── sources/
      ├── dtc-guides/<doc>.md             (+ <doc>.md.metadata.json)
      ├── tsb-recalls/<doc>.md            (+ <doc>.md.metadata.json)
      ├── owner-manuals/<doc>.md          (+ <doc>.md.metadata.json)
      ├── parts-catalog/<doc>.md          (+ <doc>.md.metadata.json)
      ├── service-network/<doc>.md        (+ <doc>.md.metadata.json)
      ├── service-policy/<doc>.md         (+ <doc>.md.metadata.json)
      ├── charging-narratives/<doc>.md    (+ <doc>.md.metadata.json)
      ├── ota-rollout-summaries/<doc>.md  (+ <doc>.md.metadata.json)
      └── extended/<doc>.md               # data-derived (extended_seed.py)
  ```
  Each source artifact carries a Bedrock KB metadata sidecar
  `<doc>.md.metadata.json` = `{"metadataAttributes": {"source_category":
  "<category>"}}` (the underscored schema-enum value, e.g. `dtc_guide`),
  emitted by the generator alongside the markdown. Bedrock treats these as
  metadata (not standalone documents) and exposes `source_category` as a
  filterable attribute — consumers (e.g. CVX `PERSONA_KB_FILTERS`) can
  scope retrievals with a `{equals|in: {key: source_category, ...}}` filter.
- **Retrieval**: consumers either (a) read `manifest.json` and embed
  themselves, or (b) point a Bedrock KB at the
  `knowledge/vehicle_knowledge_base/sources/` prefix as an S3 data
  source. See
  [`docs/cvx-integration-contract.md` § 5](../../../../docs/cvx-integration-contract.md).

## Sample queries

This product is consumed primarily through Bedrock Knowledge Base
retrieval, not Athena. The optional manifest-introspection table —
registered by the Group 5 Bedrock-KB-seeding-extensions task — is:

```sql
-- Optional: surface the chunk manifest for inspection (not required for retrieval).
SELECT source_category,
       COUNT(*)                                      AS chunks,
       APPROX_PERCENTILE(chunk_size_tokens, 0.50)    AS p50_tokens,
       MAX(indexed_at)                               AS most_recent_indexed_at
FROM   adp_staging_vehicle_knowledge_base.vehicle_knowledge_base_manifest
GROUP BY source_category
ORDER BY chunks DESC;
```

Bedrock KB retrieval (boto3, the canonical consumer pattern):

```python
import boto3
bra = boto3.client("bedrock-agent-runtime", region_name="us-east-1")

resp = bra.retrieve(
    knowledgeBaseId=cvx_kb_id,
    retrievalQuery={"text": "common charging-port engagement issues"},
    retrievalConfiguration={
        "vectorSearchConfiguration": {
            "numberOfResults": 5,
            "filter": {"equals": {"key": "source_category",
                                  "value": "dtc_guide"}},
        }
    },
)
for r in resp["retrievalResults"]:
    print(r["location"]["s3Location"]["uri"], r["score"])
```

The full Bedrock KB seeding pattern (`create_data_source`,
`start_ingestion_job`, `Retrieve` with `source_category` filter) is
in
[`docs/cvx-integration-contract.md` § 5](../../../../docs/cvx-integration-contract.md).

## Lineage

- **Inputs (base generator)**:
  - Hand-curated content from the legacy generators under
    `guidance-for-vehicle-knowledge-base/scripts/generate-*.py`
    (DTC guides, TSB / recalls, owner manuals, parts catalog,
    service network, service policy).
  - EV-specific narratives required by the schema enum
    (`charging_narrative`, `ota_rollout_summary`).
- **Inputs (extended seed)**:
  - [`service_records`](../service_records/README.md) curated parquet
    — sampled 5K rows for failure-pattern + complaint-theme
    summaries.
  - [`charging_sessions`](../charging_sessions/README.md) curated
    parquet — sampled for charging-pattern narratives (network mix,
    kWh quantiles, interrupt rates).
  - [`ota_campaigns`](../ota_campaigns/README.md) curated parquet —
    sampled for fleet-wide and per-campaign rollout summaries.
- **Producer**: [`generator.py`](generator.py) emits the base 57
  artifacts / 57 chunks across all 8 schema categories (plus a
  `<doc>.md.metadata.json` sidecar per artifact);
  [`extended_seed.py`](extended_seed.py) emits the data-derived
  ~12 artifacts to `extended/` with a separate manifest. Both share
  the same chunk shape so a single Bedrock KB ingestion job consumes
  both.
- **Consumers**:
  - CVX agent runtime — retrieves chunks via Bedrock KB
    `Retrieve` API for grounded responses.
  - Predictive-maintenance reference notebook (read-only context).
  - Any downstream consumer subscribing to the `vehicle_knowledge_base`
    DataZone listing — gets `s3:GetObject` on the
    `knowledge/vehicle_knowledge_base/` prefix.
- **Lineage trace**: not Iceberg, so no `$snapshots`. Tracking is via
  `manifest.json::indexed_at` per chunk + S3 object metadata; the
  optional Athena manifest table (section above) surfaces
  `MAX(indexed_at)` per category.

## Data-quality summary

- **Chunk count**: 57 base + ~12 extended at default settings;
  scales with `--max-rows-per-product` (default 5K) and
  `--campaign-summary-limit` (default 10) on the extended generator.
- **Category coverage**: all 8 schema-enum values populated by the
  base generator (`dtc_guide` 23, `tsb_recall` 9, `owner_manual` 6,
  `parts_catalog` 5, `service_network` 5, `service_policy` 4,
  `charging_narrative` 3, `ota_rollout_summary` 2). The extended
  generator additionally emits `tsb_recall` + `service_policy` +
  `charging_narrative` + `ota_rollout_summary` data-derived
  documents.
- **Chunking contract**: ~512-token windows with 50-token overlap;
  paragraph-boundary splitter with sentence-boundary fallback for
  over-large paragraphs. Same chunk shape across base + extended
  manifests, so a single Bedrock KB ingestion job consumes both.
- **Manifest validation**: the runner sanity-checks `schema.yaml`
  at startup — fails fast if any of the 12 columns is missing or
  `storage_format != documents`. `source_category` is constrained
  to the schema enum at runtime with a fail-fast error on drift.
- **Edge-case injection**: NOT applicable — this product carries
  hand-curated content; the six-code taxonomy in
  [`docs/tech.md`](../../../../docs/tech.md) targets Iceberg
  fact-tables only.
- **PII**: zero. The generator emits no customer-identifying material;
  any PII-looking strings in source documents are synthetic
  illustrative examples (e.g. `customer@example.com`) — the schema
  declares zero PII columns.
- **FK / orphan concerns**: NOT applicable — this product has no
  FK columns. Cross-product joins are mediated through Bedrock KB
  retrieval, not Iceberg join.
- **Profiling**: `quality-reports/vehicle_knowledge_base/profile.{json,md}`
  — the profiler reads `manifest.json` / `manifest_extended.json`
  and reports chunk count + per-category distribution; FK and
  partition sections are intentionally empty per the schema's
  document-storage shape.

## See also

- Schema-of-record: [`schema.yaml`](schema.yaml) (`storage_format: documents`)
- Producer (base): [`generator.py`](generator.py)
- Producer (data-derived): [`extended_seed.py`](extended_seed.py)
- Bedrock KB seeding pattern:
  [`docs/cvx-integration-contract.md` § 5](../../../../docs/cvx-integration-contract.md)
- Column formats: [`docs/data-contracts.md`](../../../../docs/data-contracts.md)
