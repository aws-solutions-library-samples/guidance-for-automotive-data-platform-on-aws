# Migration from v0.1.0

This guide is for users of the **v0.1.0** release of
`automotive-data-platform-on-aws` who want to move to the v0.2
foundation. It is the long-form companion to the
[Migration from v0.1.0](../README.md#migration-from-v010) section
in the top-level README.

If you are starting fresh and have never deployed v0.1.0, you do not
need this guide — go straight to [`docs/DEPLOYMENT.md`](DEPLOYMENT.md).

## Why v0.2 reframes the project

v0.1.0 shipped as **five independently-deployable guidances** plus a
`datasource/` synthetic data generator, with an implicit "automotive
manufacturing convergence" framing. Each guidance was a standalone
CDK stack family with its own deploy, its own data, and its own
Bedrock-Agent / QuickSight / Aurora / Step Functions wiring.

That shape did not match how a customer (an EV startup) actually
wants to consume an analytical platform. To demonstrate one EV
scenario, a customer had to deploy three guidances independently and
re-solve data integration between them; cross-product joins (e.g.
"why is this customer's charging cost high?") were not possible
without writing the join layer themselves.

**v0.2 reframes the project as the foundational data platform an EV
startup would set up on day one.** It collapses the five guidances
into one foundation deploy under `platform-foundation/` that
publishes 9 DataZone-cataloged data products sharing dimension keys
(VIN, customer_id, dealer_id, supplier_id, part_number, station_id)
so any consumer can join across automotive, EV operations, customer,
service, and knowledge domains without re-solving data integration.

Three EV-Operations data products are net-new in v0.2:
`charging_sessions`, `energy_usage`, `ota_campaigns`. Manufacturing
products from earlier internal designs (`production_quality`,
`supplier_traceability`) are **not** in v0.2 and are not on the v0.2
roadmap — they were a manufacturing-convergence framing, not an
EV-startup one.

This is a **deliberate scope re-frame**, not a refactor. The
foundation does not promise feature parity with v0.1.0 — see
[What was dropped](#what-was-dropped) below.

## Disposition of v0.1.0 subdirectories

The five `guidance-for-*/` subdirs and the two `datasource/`
subdirs are all demoted in v0.2. None of them are independently
deployable any more. They remain on disk for historical reference
under their original paths.

| v0.1.0 location | v0.2 disposition | Where the logic lives now |
|---|---|---|
| `guidance-for-agentic-customer-360/` | **Demoted — source of generation logic.** Synthetic-data generators ported into the foundation. Operational shape (QuickSight + Aurora pgvector + custom Bedrock-Agent) is dropped — see [What was dropped](#what-was-dropped). | `platform-foundation/source/data-products/customer_360/`, `…/customer_interactions/`, `…/service_records/` |
| `guidance-for-vehicle-knowledge-base/` | **Demoted — source of generation logic.** Document generators (DTC guides, TSB/recalls, owner manuals, parts catalog, service network, service policy) ported. Bedrock KB infra is now part of the foundation, not a per-guidance stack. The `generate-vehicle-identity.py` logic seeds product #2 in v0.2. | `platform-foundation/source/data-products/vehicle_knowledge_base/`, `…/vehicle_identity/` |
| `guidance-for-telemetry-normalization/` | **Demoted implementation, retained use case.** v0.1.0 ran a Flink pipeline to normalize raw 1Hz signals. The v0.2 foundation does not re-implement that pipeline — `vehicle_telemetry_aggregated` publishes per-VIN-per-time-window analytical rollups, not raw 1Hz signals. Telemetry normalization remains a documented ADP architecture pattern; see `telemetry-normalization.adoc` in the Implementation Guide. CMS (`connected-mobility-guidance-on-aws`) is cited there as a reference implementation of the pattern, not the sole owner of the use case. | `platform-foundation/source/data-products/vehicle_telemetry_aggregated/` |
| `guidance-for-data-governance/` | **Demoted — replaced by a foundation-wide cross-cutting governance layer.** v0.1.0 shipped this as a separate stack family with EU/global region split and EU Data Act portal. v0.2 ships Lake Formation tag-based access control + Macie classification + CloudTrail data-event logging in the foundation `governance` stack. Multi-region / EU Data Act features are out of v0.2 scope. | `platform-foundation/stacks/governance_stack.py`; the per-stage Macie job is created post-deploy by `scripts/macie-create-job.sh` |
| `guidance-for-predictive-maintenance/` | **Demoted — operational shape not provisioned by the foundation deploy.** v0.1.0 shipped a custom CDK stack with Step Functions, a Random Cut Forest tire-anomaly endpoint, and a private API. The CDK stack, Lambda functions, and Step Functions still exist in `guidance-for-predictive-maintenance/` but are not part of the default `platform-foundation/` deploy path. v0.2 ships an Isolation-Forest example notebook in SageMaker Studio as an additive reference consumer. | `platform-foundation/source/reference-consumers/predictive-maintenance/notebook.ipynb` |
| `datasource/cx-analytics/` | **Demoted — superseded by per-product generators.** v0.1.0's free-standing CX analytics generator is replaced by the foundation's unified pipeline (dimensions first, then 9 per-product generators with deterministic seeds and 1–3% calibrated edge-case injection). | `platform-foundation/source/dimensions/`, `platform-foundation/source/data-products/<product>/generator.py` |
| `datasource/crm/` | **Demoted — superseded by per-product generators.** v0.1.0's free-standing CRM-style customer/dealer generator is replaced by the foundation's `customers` / `dealers` dimension catalog and the `customer_360` / `customer_interactions` product generators. | `platform-foundation/source/dimensions/customers/`, `…/dealers/`, `platform-foundation/source/data-products/customer_360/`, `…/customer_interactions/` |

The five `guidance-for-*` subdirs are the "5 deprecated guidance
subdirs" referenced in the spec; the two `datasource/` subdirs are
demoted alongside them and follow the same redirect-README pattern
documented below.

## Per-subdir redirect README pattern

Every demoted subdir's `README.md` carries a `DEPRECATED — see
foundation` notice **at the top**, followed by the original v0.1.0
content **preserved below the notice**. The original READMEs are
not deleted — they remain as historical reference for anyone
navigating from v0.1.0 docs, blog posts, or links.

The notice block follows this shape:

```markdown
> ## DEPRECATED in v0.2 — see `platform-foundation/`
>
> This subdirectory is no longer independently deployable. Its
> logic has been demoted into the foundation deploy under
> `platform-foundation/`. See:
>
> - [`README.md`](../README.md) — top-level repository overview
> - [`docs/MIGRATION-FROM-V0.1.0.md`](../docs/MIGRATION-FROM-V0.1.0.md) — this guide
> - [`platform-foundation/source/data-products/<product>/`](…) — where the generation logic lives now
>
> The original v0.1.0 README content for this subdir follows below
> for historical reference.

---

# Original v0.1.0 README content begins here

…
```

The seven affected files are:

- `guidance-for-agentic-customer-360/README.md`
- `guidance-for-vehicle-knowledge-base/README.md`
- `guidance-for-telemetry-normalization/README.md`
- `guidance-for-data-governance/README.md`
- `guidance-for-predictive-maintenance/README.md`
- `datasource/cx-analytics/README.md`
- `datasource/crm/README.md`

## What was added in v0.2

These items did not exist in v0.1.0 and have no v0.1.0 equivalent.

- **3 net-new EV-Operations data products**: `charging_sessions`,
  `energy_usage`, `ota_campaigns`. Schemas are documented in the
  spec at
  `.kiro/specs/2026-05-28-adp-ev-startup-foundation/spec.md`
  ("Schemas for the three new EV-Operations products").
- **1 net-new dimension**: `charging_stations` (~50K stations across
  Tesla Supercharger, Electrify America, EVgo, ChargePoint, plus
  synthetic home/destination L2). FK target for `charging_sessions`.
- **A unified `make seed STAGE=...` pipeline** that emits dimensions
  first (with deterministic seeds → byte-identical regeneration),
  then runs 9 product generators, then runs referential-integrity
  tests against the materialized tree.
- **Calibrated edge-case injection** at 1–3% per product across six
  taxonomy codes (`missing_required`, `late_arrival`, `schema_drift`,
  `bad_pii`, `outlier_value`, `orphan_fk` — the last is a 0%
  counter-example used to verify the integrity assertion).
- **DataZone V2 domain + 10 projects (9 product + 1 smoke-test
  consumer)** with auto-grant within-domain subscriptions.
- **Two-stage rollout** (`staging`, `prod`) with stack-name prefixes
  (`adp-staging-foundation-*`, `adp-prod-foundation-*`) and a
  fail-closed Makefile gate (`make deploy STAGE=...` rejects any
  value other than `staging` or `prod`).
- **`docs/data-contracts.md`** — VSS signal vocabulary subset,
  identifier regex per type, time/date conventions, Iceberg
  partition conventions, and explicit non-dependencies between
  ADP and CMS.
- **`docs/cvx-integration-contract.md`** — 17 sample SQL blocks
  documenting the CVX subscription flow, IAM contract, per-product
  Athena queries, and 4 cross-product joins (customer × charging ×
  energy, VIN × OTA × energy, customer × service × charging,
  full-VIN-360).
- **Optional CMS → ADP ingest module** (`docs/cms-ingest-optional-module.md`)
  — opt-in DynamoDB Streams → Firehose → S3 → Glue Iceberg MERGE
  pipeline. Off by default; deploys synthesize zero ingest
  resources unless `-c enable_cms_ingest=true` is passed.
- **Per-stage data-quality CloudWatch dashboard**
  (`adp-{stage}-foundation-data-quality`) showing per-table row
  counts, edge-case rates per code, drift-check pass/fail counts,
  and last-seed-run timestamp.

## What was dropped

These v0.1.0 features are **not** in v0.2 and are **not** on the
v0.2 roadmap. v0.2 does not promise feature parity with v0.1.0 —
the scope was deliberately narrowed to "foundational data platform
for an EV startup" and operational / dashboarding / agent layers
were removed in favor of letting consumers (CVX, customer code,
SageMaker notebooks) own those concerns.

### QuickSight dashboards

v0.1.0's `guidance-for-agentic-customer-360` shipped 8 QuickSight
datasets and accompanying dashboards. **v0.2 ships zero QuickSight
assets.** The foundation publishes data products via DataZone +
Glue + Athena; rendering them in a BI tool is the consumer's
responsibility. Customers who want QuickSight against the
foundation can subscribe a QuickSight consumer project to the
DataZone domain — no foundation change is required, but no
QuickSight datasets are pre-built.

### Custom Bedrock-Agent CDK

v0.1.0's `guidance-for-agentic-customer-360` shipped a custom
Bedrock-Agent CDK stack with action groups, Aurora pgvector
knowledge base, and a Lambda-backed action layer. **v0.2 ships zero
Bedrock-Agent infra.** Conversational agents live with **CVX**
(`guidance-for-connected-vehicle-experience-on-aws`), which
subscribes to ADP data products via DataZone and grounds its agents
on top. The foundation publishes the data; agents are downstream.

### Aurora pgvector knowledge base

v0.1.0 used Aurora pgvector as the vector store for the agentic
customer-360 KB. **v0.2 replaces this with Bedrock Knowledge Base +
OpenSearch Serverless** for the `vehicle_knowledge_base` product
(KB infra deferred to a future task per the spec; the artifact +
manifest emission lands in v0.2).

### Manufacturing data products

Earlier internal design iterations included `production_quality`
(SPC, defect rates, yield) and `supplier_traceability` (parts
provenance, tier-N supplier graphs). **v0.2 does not ship these
products and does not plan to.** The EV-startup framing does not
include manufacturing — see [Why v0.2 reframes the project](#why-v02-reframes-the-project)
above. The `suppliers` dimension is retained because the `parts`
dimension still references it, but no fact table publishes
manufacturing data.

### Tire-anomaly Random Cut Forest API

v0.1.0's `guidance-for-predictive-maintenance` shipped a private
SageMaker endpoint for tire-anomaly detection using Random Cut
Forest, plus a Step Functions workflow that orchestrated inference.
**The CDK stack, Lambda functions, and Step Functions still exist in
`guidance-for-predictive-maintenance/` — they are not part of the
`platform-foundation/` deploy path and are not provisioned by the
foundation deploy.** v0.2 ships an additive Isolation-Forest SageMaker
Studio notebook (`predictive-maintenance/notebook.ipynb`) as the
reference consumer over `vehicle_telemetry_aggregated +
service_records + charging_sessions + energy_usage`. The API surface
and production endpoint are out of v0.2 scope.

### Multi-region EU/global split and EU Data Act portal

v0.1.0's `guidance-for-data-governance` shipped a multi-region
deploy mode with an EU Data Act-style data-access portal. **v0.2
ships single-region (us-east-1) only.** EU Data Act / GDPR
cross-region split and the access-request portal are out of v0.2
scope.

### Flink-based real-time normalization

v0.1.0's `guidance-for-telemetry-normalization` ran a Flink pipeline
to normalize raw 1Hz signals. **v0.2 does not re-implement that
pipeline.** The foundation's `vehicle_telemetry_aggregated` product
publishes per-VIN-per-time-window analytical rollups, not raw 1Hz
signals. The demoted subdir is replaced, for the foundation's scope,
by that aggregated data product. Telemetry normalization as an
architectural pattern — multi-source ingestion, schema normalization,
windowing, stateful processing, anomaly detection — remains an ADP
use case; the pattern documentation lives on in the Implementation
Guide chapter `telemetry-normalization.adoc`.

### `datasource/`-style standalone synthetic generators

v0.1.0 published `datasource/cx-analytics/` and `datasource/crm/`
as separate generator paths with their own configuration. **v0.2
unifies generation under `platform-foundation/source/`** (dimensions
+ 9 product generators + a master `make seed` target). Operators
who scripted against the v0.1.0 layout will need to re-point at
the v0.2 paths — the v0.1.0 generators are not maintained.

## What v0.1.0 users need to do

1. **Tear down v0.1.0 deploys.** Each `guidance-for-*` subdir was a
   standalone CDK stack family with its own outputs and its own
   synthetic data. There is no auto-migration tool. Use the per-
   guidance tear-down procedure each subdir documented in v0.1.0
   (typically `cdk destroy --all`).
2. **Empty and delete v0.1.0 S3 buckets** if they used
   `RemovalPolicy.RETAIN`. v0.2 buckets are stage-prefixed
   (`adp-staging-foundation-lake-…`, `adp-prod-foundation-lake-…`)
   and will not collide on bucket names with v0.1.0 buckets, but
   leaving v0.1.0 buckets behind continues to incur S3 cost.
3. **Pull `main` and follow [`docs/DEPLOYMENT.md`](DEPLOYMENT.md)**
   to deploy the foundation. The flow is:
   - `make bootstrap` (one-time, account-level — enables Macie)
   - `make deploy STAGE=staging`
   - `make seed STAGE=staging` (re-creates synthetic data from a
     deterministic seed)
   - `make smoke-test STAGE=staging`
4. **Re-create downstream consumers against the new DataZone
   catalog.** v0.1.0 did not have DataZone projects per product;
   v0.2 has 9 product projects + 1 smoke-test consumer project.
   Consumer code that read directly from S3 paths or hard-coded
   Glue database names in v0.1.0 must be re-pointed at the v0.2
   `adp_{stage}_<product>` Glue databases via DataZone subscription.
5. **Re-build any QuickSight dashboards from scratch.** v0.2 does
   not ship QuickSight assets. The 9 data products carry sufficient
   column-level intent to reconstruct equivalent v0.1.0 Customer 360
   visuals, but no datasets, analyses, or dashboards are pre-built.
6. **Rewrite Bedrock-Agent integrations against CVX or your own
   agent stack.** v0.1.0's custom Bedrock-Agent CDK is not in v0.2.
   If you need conversational agents, subscribe a CVX deployment
   to the foundation per [`docs/cvx-integration-contract.md`](cvx-integration-contract.md),
   or build your own agent stack on top of the foundation's
   DataZone subscriptions and Bedrock Knowledge Base.

### Synthetic data is not migrated

v0.1.0 synthetic data was scoped to each guidance and did not share
identifiers across guidances (each guidance generated its own VIN
pool, customer pool, etc.). **v0.2 generates a fresh, unified
synthetic catalog** (5M VINs, 5M customers, 200 dealers, 500
suppliers, 50K parts, 50K charging stations, 10y of `time_calendar`)
with deterministic seeds. There is no ETL from v0.1.0's per-
guidance datasets into v0.2's unified catalog, and there is no
plan to write one — v0.1.0 data was synthetic, and re-generating
from a deterministic seed in v0.2 is byte-reproducible.

If you have **real production data** that you previously loaded
through v0.1.0 generators, that is out of scope for both v0.1.0
and v0.2. Both releases ship synthetic-only — see [`spec.md`
Constraints #4](../.kiro/specs/2026-05-28-adp-ev-startup-foundation/spec.md).

## Caveats and what NOT to expect

These are explicit non-promises. If you depended on any of them in
v0.1.0, v0.2 does not deliver them and is not planning to.

- **No feature parity.** v0.2 is a deliberate scope re-frame, not a
  refactor. Operational layers (dashboards, agents, APIs) that
  v0.1.0 shipped are intentionally not in v0.2.
- **No backwards-compatible identifiers.** v0.2's VIN/customer_id/
  dealer_id formats follow [`docs/data-contracts.md`](data-contracts.md).
  v0.1.0 generators may have used different formats; FK joins
  across v0.1.0 and v0.2 datasets will not work.
- **No upgrade-in-place path.** Tear-down and redeploy is the only
  supported migration. CDK stack names changed (v0.1.0 used
  per-guidance prefixes; v0.2 uses `adp-{stage}-foundation-*`).
- **No multi-region.** v0.2 is single-region (us-east-1) for both
  staging and prod.
- **No public mirror update.** v0.2 ships internally; the public
  mirror at `aws-solutions-library-samples/guidance-for-automotive-data-platform-on-aws`
  remains frozen at v0.1.x. Do not consume v0.2 from the public
  mirror — pull from the internal repo.
- **No real-time / streaming integration.** Iceberg-on-S3 batch is
  the table format. The optional CMS → ADP ingest module is
  micro-batch (Firehose 60s buffer), not true streaming.
- **No manufacturing roadmap.** `production_quality`,
  `supplier_traceability`, MES integration, SPC, OEE — none are
  planned. The EV-startup framing does not include them.

## Where to go next

- [`README.md`](../README.md) — top-level repository overview and
  Quick start.
- [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) — per-stage deploy runbook,
  prereqs, smoke tests, tear-down, troubleshooting.
- [`docs/data-contracts.md`](data-contracts.md) — VSS signal subset,
  identifier formats, partition conventions, explicit non-
  dependencies between ADP and CMS.
- [`docs/cvx-integration-contract.md`](cvx-integration-contract.md)
  — how CVX subscribes to the foundation. Useful as a model for any
  consumer (your own agent stack, BI tool, ML notebook).
- [`docs/cms-ingest-optional-module.md`](cms-ingest-optional-module.md)
  — opt-in CMS → ADP ingest, when CMS and ADP are deployed in the
  same account.
- Per-product READMEs under
  `platform-foundation/source/data-products/<product>/README.md`
  — schema, partitions, sample queries, lineage, data-quality
  summary per product.
- [`.kiro/specs/2026-05-28-adp-ev-startup-foundation/spec.md`](../.kiro/specs/2026-05-28-adp-ev-startup-foundation/spec.md)
  — full design rationale, including the alternatives-considered
  table that explains why v0.2 reframed the project.
