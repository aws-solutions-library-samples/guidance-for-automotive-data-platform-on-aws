# Platform Foundation — Automotive Data Platform

## Overview

The Platform Foundation is the single deployable unit of the Automotive Data Platform (ADP).
A single invocation of `make deploy STAGE=staging` provisions the complete infrastructure
required to publish **10 governed data products** via **Amazon DataZone V2**, backed by an
Apache Iceberg lake on Amazon S3 and a cross-cutting governance layer (AWS Lake Formation
tag-based access control, Amazon Macie, AWS CloudTrail, IAM Identity Center).

ADP v0.2 is **not** a collection of independently-deployable guidances. It is one
foundation deploy. The legacy guidance subdirectories are demoted to source-of-logic;
the primary catalog surface is **Amazon DataZone V2** — not SageMaker Unified Studio,
which appears only as a reference-consumer notebook host.

---

## Architecture

The `platform-foundation/` CDK app deploys ten stacks: one account-singular bootstrap
plus nine per-stage stacks.

```
┌──────────────────────────────────────────────────────────────────┐
│  adp-shared-bootstrap  (account-level, deploy once)              │
│  └── Amazon Macie session                                        │
└──────────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────┼───────────────────────────────────┐
│  Per stage (staging | prod) — adp-{stage}-foundation-*           │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  network    │  │     lake     │  │       datazone         │  │
│  │  VPC +      │→ │  S3 Iceberg  │→ │  DataZone V2 domain    │  │
│  │  endpoints  │  │  KMS  Glue   │  │  adp-{stage}-          │  │
│  └─────────────┘  └──────────────┘  │  foundation-domain     │  │
│                         │           └────────────────────────┘  │
│                         │                       │               │
│               ┌─────────┴────────┐  ┌───────────┴────────────┐  │
│               │ datazone-projects│  │      governance        │  │
│               │  9 producer +    │  │  Lake Formation TBAC   │  │
│               │  1 consumer proj │  │  CloudTrail trail      │  │
│               └──────────────────┘  │  IAM Identity Center   │  │
│                                     └────────────────────────┘  │
│  ┌──────────────────────┐  ┌──────────────────────────────┐     │
│  │   data-products      │  │   vehicle-knowledge-base     │     │
│  │  PySpark/Glue ETL    │  │  Bedrock KB + Amazon S3      │     │
│  │  IAM role            │  │  Vectors (VKB, <$10/mo)      │     │
│  └──────────────────────┘  └──────────────────────────────┘     │
│  ┌──────────────────────┐  ┌──────────────────────────────┐     │
│  │   parts-domain       │  │      dealer-domain           │     │
│  │  adp_{stage}_parts_  │  │  adp_{stage}_dealer_domain   │     │
│  │  domain Glue DB +    │  │  Glue DB + DataZone project  │     │
│  │  DataZone project    │  │  + Glue-job IAM role         │     │
│  │  (DMS accelerator)   │  │  (DMS accelerator)           │     │
│  └──────────────────────┘  └──────────────────────────────┘     │
│                                                                  │
│  (Optional) adp-{stage}-foundation-cms-ingest  — off by default  │
└──────────────────────────────────────────────────────────────────┘
```

### Stack inventory

| Deploy order | Stack name | Purpose |
|---|---|---|
| Bootstrap (once) | `adp-shared-bootstrap` | Enables Amazon Macie session at account level. Deployed once; not stage-bound; safe to re-run (idempotent). |
| 1 | `adp-{stage}-foundation-network` | VPC + VPC endpoints for S3, Glue, and Athena. |
| 2 | `adp-{stage}-foundation-lake` | S3 lake bucket (Iceberg, KMS-encrypted, versioned) + 11 Glue databases: 10 per-product (`adp_{stage}_<product>`) + 1 shared dimensions (`adp_{stage}_dimensions`). Two additional Glue databases (`adp_{stage}_dealer_domain`, `adp_{stage}_parts_domain`) are created by their own stacks (see rows 7a, 7b), bringing the per-stage total to 13. |
| 3 | `adp-{stage}-foundation-datazone` | Amazon DataZone V2 domain (`adp-{stage}-foundation-domain`) + associated IAM roles. |
| 4 | `adp-{stage}-foundation-datazone-projects` | 10 DataZone projects: 9 producer projects (one per governed data product except `tire_health`) + 1 smoke-test consumer with auto-grant subscriptions. Two additional producer projects (`adp_dealer_domain`, `adp_parts_domain`) are created inside the same domain by their own stacks (see rows 7a, 7b), bringing the per-stage total to 12. |
| 5 | `adp-{stage}-foundation-governance` | Lake Formation tag-based access control, CloudTrail data-event trail, 3 IAM Identity Center groups per stage. |
| 6 | `adp-{stage}-foundation-data-products` | Persistent IAM execution role for the PySpark/Glue 5.1 ETL jobs that build the analytical data products (`vehicle_telemetry_aggregated`, `energy_usage`). |
| 7 | `adp-{stage}-foundation-vehicle-knowledge-base` | Amazon Bedrock Knowledge Base + Amazon S3 Vectors index backing the `vehicle_knowledge_base` product. Single-digit dollars per month (usage-priced, no OCU floor) — see Components below. |
| 7a | `adp-{stage}-foundation-parts-domain` | DMS accelerator: `adp_{stage}_parts_domain` Glue database + DataZone producer project + region-suffixed Glue-job IAM role. Ships unconditionally at stage-deploy. Contents seeded via `make seed-parts`. Spec: `.kiro/specs/2026-08-26-adp-dealer-domain/`. |
| 7b | `adp-{stage}-foundation-dealer-domain` | DMS accelerator: `adp_{stage}_dealer_domain` Glue database + DataZone producer project + region-suffixed Glue-job IAM role. Ships unconditionally at stage-deploy. Contents populated by DMS-side ETL. Spec: `.kiro/specs/2026-08-26-adp-dealer-domain/`. |

Both `staging` and `prod` stages coexist in the same AWS account in `us-east-1`, isolated
by resource-name prefix.

---

## 10 Governed Data Products

The foundation publishes 10 governed data products via Amazon DataZone V2. Nine are
Iceberg-backed; one (`vehicle_knowledge_base`) is a Bedrock Knowledge Base over S3
artifacts (see [Vehicle Knowledge Base](#vehicle-knowledge-base) below).

| # | Technical name | Domain |
|---|---|---|
| 1 | `vehicle_telemetry_aggregated` | Automotive |
| 2 | `vehicle_identity` | Automotive |
| 3 | `tire_health` | Automotive |
| 4 | `charging_sessions` | EV Operations |
| 5 | `energy_usage` | EV Operations |
| 6 | `ota_campaigns` | EV Operations |
| 7 | `customer_360` | Customer |
| 8 | `customer_interactions` | Customer |
| 9 | `service_records` | Service |
| 10 | `vehicle_knowledge_base` | Knowledge |

For the authoritative catalog — per-product schemas, partitions, sample queries, and
lineage — see the
[root `README.md` § The 10 data products](../README.md#the-10-data-products) and the
shipped Implementation Guide chapter `data-products.adoc`.

---

## Quick Start

All commands run from `platform-foundation/`. The Makefile is the **only** sanctioned
entry point — do NOT run `cdk deploy` directly (see [Stage Gate](#stage-gate)).

```bash
# 1. Set up Python venv and install dependencies
make install

# 2. One-time account-level bootstrap (Macie session)
make bootstrap

# 3. Deploy all 9 per-stage foundation stacks (~15–25 min)
make deploy STAGE=staging

# 4. Seed the data lake (dimensions + 10 product generators)
make seed STAGE=staging

# 5. Post-deploy smoke test (DataZone subscription end-to-end)
make smoke-test STAGE=staging
```

Replace `staging` with `prod` for the production stage.

`STAGE` is required and fail-closed: `make deploy` (without `STAGE=`) exits 1.
See [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) for the full runbook including
prerequisites, post-deploy CloudWatch validation, optional CMS-ingest enablement,
and tear-down.

---

## Components

### 1. Account Bootstrap (`adp-shared-bootstrap`)

Deployed once per account via `make bootstrap`. Creates an Amazon Macie session at
account level. The Macie session persists across stage deploys and has a 30-day
cool-down after disabling — the bootstrap stack retains the session on deletion.

### 2. Network (`adp-{stage}-foundation-network`)

VPC with private subnets across Availability Zones, NAT Gateway, and VPC endpoints for
S3, Glue, Athena, and Bedrock. Provides isolated networking for all per-stage resources.

### 3. Data Lake (`adp-{stage}-foundation-lake`)

- S3 lake bucket: `adp-{stage}-foundation-lake-<account>-us-east-1` — Iceberg-formatted,
  KMS-encrypted (`alias/adp-{stage}-foundation-lake`), versioned, with CloudTrail
  data-event logging wired in the governance stack.
- 11 Glue databases: 10 per-product (`adp_{stage}_<product>`) + 1 shared dimensions
  (`adp_{stage}_dimensions`). Two additional Glue databases (`adp_{stage}_dealer_domain`,
  `adp_{stage}_parts_domain`) are created by their own stacks — see Components §§ 7a, 7b.

### 4. Amazon DataZone V2 Domain (`adp-{stage}-foundation-datazone`)

Amazon DataZone V2 is the primary catalog surface for ADP v0.2. The domain
(`adp-{stage}-foundation-domain`) hosts all 9 governed data products, manages
producer/consumer project subscriptions, and enforces access governance across
the full catalog.

### 5. DataZone Projects (`adp-{stage}-foundation-datazone-projects`)

10 projects: 9 producer projects (one per governed data product) and 1 smoke-test
consumer project (`data_consumer_test`) with auto-granted subscriptions. DataZone
project technical names (e.g., `vehicle_telemetry_aggregated`) are stage-agnostic;
only display names carry a `[Staging]` suffix on the staging stage.

### 6. Governance (`adp-{stage}-foundation-governance`)

Cross-cutting controls applied to all 9 governed data products:

- **Lake Formation tag-based access control (LF-TBAC)**: 3 IAM Identity Center groups
  per stage (`adp-{stage}-data-owners`, `adp-{stage}-data-consumers`,
  `adp-{stage}-platform-admins`) with column-level permissions on PII-bearing tables.
- **AWS CloudTrail**: data-event trail (`adp-{stage}-foundation-lake-trail`) on the
  lake bucket. Every `GetObject`, `PutObject`, and `DeleteObject` API call is recorded.
- **IAM Identity Center groups**: regional (us-east-1 only — the primary reason ADP is
  single-region in v0.2; see `docs/DEPLOYMENT.md` § _Why single-region_).

### 7. Data Products (`adp-{stage}-foundation-data-products`)

Provisions the persistent IAM execution role used by the PySpark/Glue 5.1 ETL jobs that
build the analytical data products from the raw lake data. In v0.2 the
`vehicle_telemetry_aggregated` and `energy_usage` products are produced by Glue PySpark
jobs (per the Glue 5.1 data-product pipeline); the remaining products are produced by
pandas-based generators. The stack holds the long-lived role so the ETL jobs have a stable
identity across `make seed` runs; the seed pipeline assumes this role rather than creating
per-run roles.

### 7a. Parts Domain (`adp-{stage}-foundation-parts-domain`)

DMS-accelerator producer stack. Creates the `adp_{stage}_parts_domain` Glue database
and a DataZone producer project, plus a region-suffixed IAM execution role for the
PySpark/Glue ETL that populates the three parts products (`parts_catalog`,
`parts_fitment`, `parts_interchange`). Contents are seeded on the ADP side via
`make seed-parts`; the DMS-side consumer reads via the LF cross-account share (see
[DMS cross-account share](#optional-cross-account-share-to-dms) below).

The `parts_catalog` product also underlies the Bedrock KB corpus with
`source_category: "parts_catalog"` — see [`../docs/parts-surface-boundary.md`](../docs/parts-surface-boundary.md)
for the authoritative-store vs. derived-read-surface contract. Spec:
`.kiro/specs/2026-08-26-adp-dealer-domain/`.

### 7b. Dealer Domain (`adp-{stage}-foundation-dealer-domain`)

DMS-accelerator producer stack. Creates the `adp_{stage}_dealer_domain` Glue database
and a DataZone producer project, plus a region-suffixed IAM execution role for the
Glue ETL that lands dealer-side operational data. Populated by DMS-side ETL — the
Iceberg tables are provisioned by ADP; the row content is written by the DMS-side
accelerator. Consumed via the LF cross-account share (see
[DMS cross-account share](#optional-cross-account-share-to-dms) below). Spec:
`.kiro/specs/2026-08-26-adp-dealer-domain/`.

### 8. Vehicle Knowledge Base (`adp-{stage}-foundation-vehicle-knowledge-base`)

> **Cost update (2026-08-30)**: The VKB stack cost dropped from ~$345/month per stage
> (AOSS 2-OCU floor) to single-digit dollars/month (Amazon S3 Vectors usage-priced). 
> Cost verification pending one full billing cycle post-cutover; see spec 
> `2026-08-03-adp-vkb-s3-vectors` for the migration details.

The `vehicle_knowledge_base` product is stored as Markdown artifacts (DTC guides, TSBs,
recall notices, owner manuals, charging narratives, OTA rollout summaries) and backed by
an Amazon Bedrock Knowledge Base with Amazon S3 Vectors as the vector store. Provisioned 
by the `adp-{stage}-foundation-vehicle-knowledge-base` stack:

- Amazon S3 Vectors `VectorBucket` + `Index` (`adp-{stage}-vehicle-knowledge-vectors-{region}`)
- Bedrock `CfnKnowledgeBase` (Titan Embeddings v2) wired to the S3 Vectors index
- `CfnDataSource` reading chunked Markdown from
  `s3://adp-{stage}-foundation-lake-<account>-us-east-1/knowledge/vehicle_knowledge_base/sources/`
- Optional `CfnResourcePolicy` granting cross-account CVX retrieval access (gated on
  `ADP_KB_CVX_PRINCIPAL_ARNS` or `-c cvxKbPrincipals=...` — see
  [Cross-Account Share to CVX](#optional-cross-account-share-to-cvx) below)

See [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) § _Vehicle Knowledge Base (Bedrock KB +
S3 Vectors) deploy_ for the full operator runbook including the cutover migration steps from 
the retired AOSS collection.

---

## Stage Gate

The Makefile is the only sanctioned entry point. All per-stage targets require
`STAGE=staging|prod` (lower-case, case-sensitive).

| Invocation | Behavior |
|---|---|
| `make deploy` | ❌ exits 1 — `STAGE is required` |
| `make deploy STAGE=foo` | ❌ exits 1 — must be `staging` or `prod` |
| `make deploy STAGE=Staging` | ❌ exits 1 — case-sensitive |
| `make deploy STAGE=staging` | ✅ deploys staging stacks |
| `make bootstrap` | ✅ no STAGE required — account-level only |

> ⚠️ **DO NOT run `cdk deploy` directly.** The Makefile sets required CDK context
> flags and environment variables. Direct invocation bypasses the `STAGE` validation
> guard and may produce stacks with unprefixed names that collide with existing deploys.

---

## Prerequisites

| Tool | Minimum version |
|---|---|
| Python | 3.12+ |
| Node.js | 22.x LTS |
| AWS CDK CLI | 2.255+ |
| AWS CLI v2 | 2.15+ |
| Docker | 24+ |
| jq | any |

AWS account requirements: default credentials configured, CDK bootstrapped in `us-east-1`,
IAM Identity Center enabled in `us-east-1`, Macie not in conflicting state.

See [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) § _Prereqs_ for the full prerequisite
checklist with verify commands.

---

## Optional: Cross-Account Share to CVX

The CVX agent platform consumes ADP data products via DataZone subscriptions and the
Vehicle Knowledge Base via Bedrock KB retrieval. Two optional cross-account mechanisms
are available:

### Lake Formation cross-account share (LF)

To enable Lake Formation cross-account `SELECT`/`DESCRIBE` on the six in-scope curated
databases (`vehicle_identity`, `service_records`, `charging_sessions`, `customer_360`,
`customer_interactions`, `ota_campaigns`) for a CVX consumer account, supply the CVX
account ID via the `ADP_KB_CVX_ACCOUNT_ID` environment variable before running `make deploy`:

```bash
export ADP_KB_CVX_ACCOUNT_ID=<cvx-account>
make deploy STAGE=staging
```

Or pass it as a CDK context flag via the env var (the Makefile's `deploy` target uses
`-c stage=STAGE` only, so env var is the recommended path for the LF share):

```bash
ADP_KB_CVX_ACCOUNT_ID=<cvx-account> make deploy STAGE=staging
```

**Manual prerequisite**: before deploying, set Lake Formation v4 cross-account settings:

```bash
aws lakeformation put-data-lake-settings --region us-east-1 \
  --data-lake-settings '{"AllowExternalDataFiltering":true,"CrossAccountVersion":4}'
```

See [`docs/cvx-integration-contract.md`](../docs/cvx-integration-contract.md)
§ "Cross-account grants for CVX" for the full IAM contract.

When `ADP_KB_CVX_ACCOUNT_ID` is absent (default), no Lake Formation cross-account
resources are synthesized — single-account mode is the safe default.

### Bedrock KB cross-account retrieval principal

To grant a CVX-side IAM role retrieval access to the Vehicle Knowledge Base, supply the
CVX KB principal ARN(s):

```bash
export ADP_KB_CVX_PRINCIPAL_ARNS=arn:aws:iam::<cvx-account>:role/cvx-staging-kb-retrieval-role
make deploy STAGE=staging
```

See [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) § _Bedrock KB cross-account
integration_ for the IAM contract and notes on why LF-vended credentials do NOT cover
Bedrock KB reads.

---

## Optional: Cross-Account Share to DMS

The DMS accelerator platform (spec `2026-08-26-adp-dealer-domain`) consumes ADP data
via a parallel set of opt-in flags. Both consumers (CVX + DMS) can be enabled
simultaneously; when neither is set, no cross-account resources synthesize.

### Lake Formation cross-account share (DMS)

To grant a DMS-accelerator consumer account `SELECT`/`DESCRIBE` on the two
DMS-facing databases (`dealer_domain`, `parts_domain`), supply the DMS account ID:

```bash
export ADP_KB_DMS_ACCOUNT_ID=<dms-account>
make deploy STAGE=staging
```

The `deploy` target passes `-c stage=STAGE` only via `CDK_CTX`; DMS flags flow
through `os.environ`, which `app.py` resolvers read. Absence of the env var
disables the DMS-side LF resources — the default single-account posture.

**Manual prerequisite**: the same Lake Formation v4 setting as the CVX section
above (`AllowExternalDataFiltering=true`, `CrossAccountVersion=4`). If already set
for CVX, no re-application is required — this is an account-region-level singleton.

### Bedrock KB cross-account retrieval principal (DMS)

To grant DMS-side IAM role(s) retrieval access to the Vehicle Knowledge Base:

```bash
export ADP_KB_DMS_PRINCIPAL_ARNS=arn:aws:iam::<dms-account>:role/dms-staging-supervisor-role
make deploy STAGE=staging
```

DMS consumers filter retrievals by `source_category` at query time — the
supervisor-side agents use `dealer_bulletin`, `warranty_policy`, and `parts_catalog`
(the two new categories shipped by Group 4 plus the R2d-superseded corpus shipped
by Group 5 of spec `2026-08-26-adp-dealer-domain`).

See [`../docs/cvx-integration-contract.md`](../docs/cvx-integration-contract.md)
§ "Cross-account grants for DMS" for the full IAM contract, single-combined-Statement
resource-policy semantics, and audit posture.

---

## Automotive Use Cases

The foundation enables data-driven automotive and EV use cases via governed DataZone
subscriptions. Consumers (CVX agents, notebook users, BI tools) subscribe to specific
data products via DataZone and query with Athena.

**1. Predictive Maintenance**
Subscribe to `vehicle_telemetry_aggregated` + `service_records`. Join in Athena to train
at-risk-VIN models. The reference SageMaker Studio notebook at
`source/reference-consumers/predictive-maintenance/notebook.ipynb` demonstrates an
end-to-end Isolation-Forest workflow over these two products.

**2. Connected Vehicle Analytics**
Subscribe to `vehicle_telemetry_aggregated` + `energy_usage` + `ota_campaigns`. Analyze
battery degradation, OTA campaign outcomes, and range efficiency by season.

**3. Customer 360**
Subscribe to `customer_360` + `customer_interactions` + `service_records` +
`charging_sessions`. Calculate customer health scores and churn signals across the full
customer journey.

**4. Knowledge Base Grounding (CVX)**
The CVX agent platform retrieves from `vehicle_knowledge_base` via Bedrock KB for RAG
over DTC guides, TSBs, and recall notices. See
[`docs/cvx-integration-contract.md`](../docs/cvx-integration-contract.md) for the
17-query cross-product join contract.

---

## Configuration

All per-stage configuration is supplied at deploy time via Makefile `STAGE=` and
environment variables. There is no static config file to edit.

Key environment variables:

| Variable | Purpose |
|---|---|
| `STAGE` | Required. `staging` or `prod` (lower-case). |
| `AWS_REGION` | Defaults to `us-east-1` (single-region by design). |
| `ADP_KB_CVX_ACCOUNT_ID` | Optional. CVX account ID for Lake Formation cross-account share. |
| `ADP_KB_CVX_PRINCIPAL_ARNS` | Optional. Comma-separated CVX IAM role ARNs for KB retrieval. |

See [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) for the full environment-variable
reference and CDK context alternatives.

---

## Teardown

The `teardown` target defaults to **dry-run** (prints what would be deleted without
destroying anything). Pass `YES=1` to execute:

```bash
# Dry-run — safe, shows what would be deleted
make teardown STAGE=staging

# Actually destroy per-stage stacks
make teardown STAGE=staging YES=1
```

Teardown removes only the per-stage stacks (`adp-staging-foundation-*`). It does NOT
touch `adp-shared-bootstrap`, the other stage's stacks, or the lake KMS CMK
(`RemovalPolicy.RETAIN`). Synthetic data is regenerable via `make seed STAGE=staging`.

See [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) § _Stage-side teardown_ for the
six-step teardown sequence and post-teardown verification commands.

---

## Cost Estimate

The foundation lake is the dominant cost driver. Amazon S3 Vectors (Vehicle Knowledge
Base) is now usage-priced with no floor commitment (cost improved 2026-08-30).

| Component | Approx monthly cost (us-east-1) |
|---|---|
| S3 lake bucket (synthetic data, ~2–3 TiB at full Spark scale) | $50–80 |
| Glue catalog (13 databases) | <$5 |
| Athena queries (development workload) | $5–25 |
| DataZone V2 domain | $0 (consumption-based; minimal at v1) |
| Macie classification | $30–80 (PII-bearing prefixes only) |
| CloudTrail data events | $5–15 |
| Bedrock Knowledge Base + Amazon S3 Vectors | <$10 |
| CloudWatch quality dashboard | $3 (flat, first 3 dashboards/account/region free) |
| Optional CMS-ingest module (one CMS table) | +$256 (Firehose + Glue MERGE) |
| **Foundation only** | **~$100–200** |
| **+ Optional CMS-ingest** | **~$350–460** |

Costs scale with synthetic-data refresh frequency, query volume, and KB ingestion
cadence. See the root [`README.md`](../README.md#cost-estimates) for the authoritative
breakdown, and AWS pricing pages for current rates.

---

## Monitoring

Post-deploy validation uses the foundation's built-in verification toolset:

```bash
# Post-deploy smoke test (DataZone subscription + live Athena query)
make smoke-test STAGE=staging

# Synth-time check: no CMS ARNs in the foundation templates
make verify-standalone STAGE=staging

# Run all pytest tests (schema, FK, edge-case, distribution)
make verify STAGE=staging
```

See [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) § _Post-deploy CloudWatch monitoring_
for the CloudFormation event scan + CloudTrail / KMS key health checks to run after
smoke-test passes.

The optional CloudWatch data-quality dashboard (`scripts/deploy-quality-dashboard.sh
staging`) provides per-product row counts, edge-case rates, and drift-check pass/fail.

---

## Troubleshooting

Full troubleshooting guidance — including common deploy failures (stage guard, Macie
conflict, VPC quota, DataZone domain hang, cdk-nag errors, Lake Formation grant failures,
and CMS-ingest module errors) — is in
[`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) § _Troubleshooting_.

Quick reference for the most common issues:

| Symptom | Resolution |
|---|---|
| `cdk synth` fails with "stage is required" | Run via `make synth STAGE=staging`, not `cdk synth` directly |
| Bootstrap fails: "Macie is already enabled" | Import existing session via `cdk import` OR `aws macie2 disable-macie` (30d cool-down) |
| `make deploy` fails at governance: IDC group creation error | Verify IAM Identity Center is in `us-east-1` and `--identity-store-id` matches your instance |
| Subscription smoke test fails: "asset not found" | Expected before `make seed STAGE=...` lands data; re-run smoke-test after seed completes |

---

## Next Steps

1. **Deploy the foundation** — follow [Quick Start](#quick-start) above
2. **Seed the data lake** — `make seed STAGE=staging` generates all 9 products
3. **Smoke-test** — `make smoke-test STAGE=staging` validates end-to-end
4. **Subscribe consumers** — CVX agents and SageMaker Studio notebooks subscribe via DataZone
5. **Wire the Vehicle Knowledge Base** — see [`docs/cvx-integration-contract.md`](../docs/cvx-integration-contract.md)
6. **Enable optional CMS ingest** (if CMS is in same account) — see [`docs/cms-ingest-optional-module.md`](../docs/cms-ingest-optional-module.md)

---

## References

- [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) — per-stage deploy runbook (authoritative)
- [`docs/data-contracts.md`](../docs/data-contracts.md) — VSS signal subset, schemas, partitions
- [`docs/cvx-integration-contract.md`](../docs/cvx-integration-contract.md) — CVX consumer contract (17 Athena queries, Bedrock KB, cross-account grants)
- [`docs/cms-ingest-optional-module.md`](../docs/cms-ingest-optional-module.md) — opt-in CMS→ADP ingest
- [Amazon DataZone V2 documentation](https://docs.aws.amazon.com/datazone/latest/userguide/)
- [Amazon S3 Vectors documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors.html)
- [AWS Lake Formation documentation](https://docs.aws.amazon.com/lake-formation/latest/dg/)
