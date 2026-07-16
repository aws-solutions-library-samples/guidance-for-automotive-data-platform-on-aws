# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v0.2.3 — 2026-07-15

### Security — dependency modernization (`guidance-for-predictive-maintenance`)

Resolves 25 Dependabot security alerts (1 Critical + 24 High) in the
`guidance-for-predictive-maintenance` subproject by regenerating all three
`poetry.lock` files and bumping direct + transitive dependencies to
current-secure versions.

**Critical fix:**
- `jupyter-server` 2.17.0 → **2.20.0** (CVE-2025-29241 — XSS via malformed
  notebook filenames; CVSS 9.6 Critical)

**High fixes (selected):**
- `jupyterlab` 4.5.3 → **4.6.1** (CVE-2025-30370 — XSS in workspace title)
- `notebook` 7.5.3 → **7.6.0** (inherits jupyter-server + jupyterlab fixes)
- `tornado` 6.5.4 → **6.5.7** (CVE-2025-47287 — log injection; CVE-2025-47288 — CRLF injection)
- `mistune` 3.2.0 → **3.3.3** (CVE-2025-46403 — XSS in renderer)
- `soupsieve` 2.8.3 → **2.8.4** (CVE-2025-47472 — ReDoS)
- `urllib3` already at 2.6.3 → **2.7.0** (runtime dep — refreshed to latest)
- `pillow` → **12.3.0** (latest; CVE-2025-48432 + related)
- `black` 24.10.0 → **26.5.1** (CVE-2026-32274 — arbitrary file write via `--python-cell-magics`; constraint was pinned `^24` and had to be bumped to `^26.3.1`)

**Direct dep bumps (all three lock files):**
- `aws-cdk-lib` 2.237.1 → **2.261.0**
- `aws-lambda-powertools` 3.24.0 → **3.31.1**
- `boto3` / `botocore` 1.42.41 → **1.43.48**

**Files changed:**
- `guidance-for-predictive-maintenance/poetry.lock` (top-level)
- `guidance-for-predictive-maintenance/source/infrastructure/pyproject.toml`
  (constraint bumps: `aws-cdk-lib ^2.170.0→^2.204.0`, `boto3/botocore ^1.35.0→^1.39.3`,
  `notebook ^7.4.0→^7.5.6`, `black ^24.0.0→^26.3.1`)
- `guidance-for-predictive-maintenance/source/infrastructure/poetry.lock`
- `guidance-for-predictive-maintenance/source/lambda/layers/common_dependencies/poetry.lock`
- `guidance-for-predictive-maintenance/source/lambda/layers/common_dependencies/pyproject.toml`
  (fixed an invalid PyPI trove classifier `License :: Apache-2.0` →
  `License :: OSI Approved :: Apache Software License`, which was blocking `poetry build`
  during Lambda-layer bundling)

## v0.2.2 — 2026-07-15

### Documentation / hygiene

- **Removed EV OEM names from the README "Why ADP" section.** The
  market-positioning copy named specific EV manufacturers; reworded to a
  generic "Modern EV startups build on AWS from day one." so the public
  reference guidance carries no company references.
- **Scanner guard added.** `.publish-secrets-scan.yml` now flags the EV OEM
  names via a word-boundary `forbidden_patterns` entry (word-boundary rather
  than substring to avoid false positives such as `union`/`elucidate`), so
  reintroduction is caught pre-publish.

## v0.2.1 — 2026-07-14

### Documentation

- **`platform-foundation/README.md` restructured for the v0.2 model.** The
  foundation-level developer guide still described the v0.1 SageMaker Unified
  Studio / DataZone-domain-only setup. Rewritten so Amazon DataZone V2 is the
  primary catalog surface (SageMaker Studio reframed as a reference-consumer
  notebook host); the v0.1 component list (which referenced CloudFormation
  templates and shell scripts that no longer exist) is replaced with the real
  8-stack topology (`adp-shared-bootstrap` + 7 per-stage stacks: network, lake,
  datazone, datazone-projects, governance, data-products, vehicle-knowledge-base);
  adds the 9 governed data products, `make teardown`, and the sanctioned
  cross-account CVX flow (`ADP_KB_CVX_ACCOUNT_ID` + `make deploy`). Completes the
  documentation re-frame started in v0.2.0.

## v0.2.0 — 2026-07-14

### Breaking changes

- **Platform re-framing: from 5 independently-deployable guidances to 1
  foundation deploy.** ADP is no longer a collection of separate guidance
  stacks (Agentic Customer 360, Predictive Maintenance, Data Governance,
  Telemetry Normalization, Vehicle Knowledge Base). It is now a single
  foundation deploy under `platform-foundation/` that publishes **9
  governed data products** to one Amazon DataZone V2 domain: Vehicle
  Telemetry (Aggregated), Vehicle Identity Graph, Charging Sessions,
  Energy Usage, OTA Campaigns, Customer 360, Customer Interactions,
  Service Records, and Vehicle Knowledge Base. The 5 legacy
  `guidance-for-*/` subdirs are demoted to source-of-logic reference
  material for the foundation's generators — their content is preserved
  in place with deprecation banners, not deleted. See
  [`docs/MIGRATION-FROM-V0.1.0.md`](docs/MIGRATION-FROM-V0.1.0.md) for
  the full before/after disposition table and migration steps.
- **`guidance-for-vehicle-knowledge-base/` deleted.** Its generators and
  Bedrock Knowledge Base construct were ported into
  `platform-foundation/source/data-products/vehicle_knowledge_base/` and
  `platform-foundation/stacks/vehicle_knowledge_base_stack.py`.

### Added

- **Platform Foundation** (`platform-foundation/`) — 5 per-stage CDK
  stacks (network, lake, datazone, datazone-projects, governance) plus 1
  account-singular bootstrap stack (Macie session). Deploys to a single
  AWS account in `us-east-1` across `staging`/`prod` stages via
  `make bootstrap` → `make deploy STAGE=` → `make seed STAGE=` →
  `make smoke-test STAGE=`.
- **9 governed data products** — 8 Iceberg-backed (via S3 + Glue +
  DataZone) plus 1 Bedrock Knowledge Base (`vehicle_knowledge_base`).
  3 net-new EV-Operations products vs. v0.1: `charging_sessions`,
  `energy_usage`, `ota_campaigns`.
- **Vehicle Knowledge Base Bedrock KB + AOSS construct** — OpenSearch
  Serverless `VECTORSEARCH` collection, FAISS knn_vector index (1024
  dims), Titan Embeddings v2, optional cross-account `Retrieve` grant for
  CVX consumers gated on `-c cvxKbPrincipals=...`.
- **Cross-account DataZone/Lake Formation grants for CVX** — tag-based
  access control, per-database wildcard share, CloudTrail data events on
  `AWS::Bedrock::KnowledgeBase`. See
  [`docs/cvx-integration-contract.md`](docs/cvx-integration-contract.md).
- **Vehicle Knowledge Base content-fill**: +6 DTC guides
  (P0420/P0300/C0035/U0100/P0171/B0001), `source_category` metadata
  sidecars on all 57 corpus documents.
- **Cross-cutting governance**: Lake Formation tag-based access control,
  Macie PII classification on PII-bearing prefixes, CloudTrail data-event
  logging, IAM Identity Center groups
  (`adp-{stage}-data-owners`/`-data-consumers`/`-platform-admins`).
- **Reference consumer**: SageMaker Studio predictive-maintenance
  notebook (Isolation-Forest at-risk-VIN model, no custom CDK/Step
  Functions).
- **End-to-end verification tooling**:
  `scripts/smoke-test-subscription.sh`, `scripts/verify-standalone.sh`,
  `scripts/verify-contract-queries.sh`, `scripts/profile-data.py`, and a
  CloudWatch data-quality dashboard.

### Fixed

- **`charging_sessions` FK drift orphans** — schema-drift injection was
  bleeding into FK columns; `str(None)` coercion in `station_id`. Fixed
  at the generator + covered by regression tests.
- **Public-mirror scanner case-sensitivity default** — ported the CMS
  fix (`890ad58`) so brand-canary scanning is case-insensitive by
  default, closing the `ADP scanner issues-dir` blocker (5,077
  test-fixture canary findings previously blocking public-mirror
  publish — resolved via `scan_exclude` scoping to `issues/**/{review,
  security-review}.md`, matching the CMS convention).
- **Hardcoded AWS account ID + IAM Identity Center store ID** —
  sanitized as a preventative pre-publish fix.

### Documentation

- **Implementation Guide re-framed for the v0.2 platform-foundation
  model.** All published chapters updated: `guidance-overview.adoc` +
  `architecture-overview.adoc` rewritten for the 1-foundation-deploy /
  9-data-products model (was: "three integrated solutions" / 5
  independently-deployable guidances); new `platform-foundation.adoc` +
  `data-products.adoc` chapters; `automotive-data-mesh.adoc` terminology
  synced; deprecation banners (redirect, not delete) added to the 4
  legacy-guidance chapters; operational surfaces refreshed
  (troubleshooting, developer-guide, update-guide, uninstall, reference,
  revisions). Root README + `datasource/README.md` deprecation banner +
  `platform-foundation/README.md` Quick Start also refreshed.
- **`platform-foundation/README.md` cost table corrected** — was
  describing v0.1 SageMaker-Studio per-user pricing ($50-250/mo,
  2-6x understated); now mirrors the root README's authoritative
  9-line-item breakdown (~$300-600/mo foundation-only) including the
  ~$345/mo Bedrock KB + AOSS line item that was previously omitted
  entirely. Remaining drift (component-list file references,
  architecture-diagram framing) tracked as a follow-on.
- **`MIGRATION-FROM-V0.1.0.md` corrections** — fixed a false claim that
  predictive-maintenance "has no API, no Step Functions, no custom CDK"
  (a `TirePredictiveMaintenanceStack` CDK app is demonstrably still
  present); corrected an over-broad "telemetry normalization belongs to
  CMS now" framing back to "documented ADP architecture pattern, CMS is
  a reference implementation, not the sole home."

## v0.1.1 — 2026-05-27

### Fixed

- **CodeQL Default Setup error on public mirror**. After v0.1.0
  published, the org-level CodeQL Default Setup at the
  `aws-solutions-library-samples` org failed to scan the public repo
  with the error "CodeQL detected code written in GitHub Actions but
  could not process any of it." Root cause: the v0.1.0 publish
  excluded `.github/workflows/pr-validation.yml` (it contains an
  internal AWS account ID in a grep-exclusion list), leaving the
  public mirror with zero workflow files. CodeQL Default Setup's
  Actions language analyzer requires at least one workflow file in
  the repo to scan.
- **Fix**: shipped a minimal `.github/workflows/lint.yml` to the
  public mirror — runs yamllint on workflow files and shellcheck on
  shell scripts. Provides Default Setup with workflow content to
  analyze. Same fix that resolved this on the CMS public mirror at
  CMS v0.1.3.

## v0.1.0 — 2026-05-27

Initial public release on
[aws-solutions-library-samples/guidance-for-automotive-data-platform-on-aws](https://github.com/aws-solutions-library-samples/guidance-for-automotive-data-platform-on-aws).

### Included guidance

- **Platform Foundation** (`platform-foundation/`) — base infrastructure
  for automotive data platforms using Amazon SageMaker Unified Studio,
  IAM Identity Center, and DataZone.
- **Agentic Customer 360** (`guidance-for-agentic-customer-360/`) —
  agent-based customer-data unification across vehicle, ownership,
  service, and product engineering domains.
- **Data Governance** (`guidance-for-data-governance/`) — DataZone
  domain configuration, blueprints, and access controls.
- **Predictive Maintenance** (`guidance-for-predictive-maintenance/`) —
  tire predictive maintenance for commercial fleets, with ETL pipeline,
  ML training/inference, alerts, and Redshift integration.
- **Telemetry Normalization** (`guidance-for-telemetry-normalization/`) —
  schema normalization for heterogeneous vehicle telemetry feeds.
- **Vehicle Knowledge Base** (`guidance-for-vehicle-knowledge-base/`) —
  Bedrock-backed knowledge base over technical references, TSBs/recalls,
  owner manuals, and service policy.

### Public-mirror infrastructure

- `scripts/publish-to-github.sh` — staging-tree publish driver: applies
  `.publish-exclude`, runs the secret scanner, squashes the release to
  a single commit, force-pushes to the public GitHub mirror.
- `scripts/lib/secret-scan.py` + `test_secret_scan.py` — secret scanner
  with forbidden-strings + forbidden-patterns rules; 8 unit tests.
- `.publish-exclude` — staging-tree exclusion list.
- `.publish-secrets-scan.yml` — scanner configuration (forbidden
  patterns, allowlists, scan_exclude globs).
- `.gitlab-ci.yml` `publish_to_github` job — manual, semver-tag-gated,
  HTTPS+token-authenticated GitLab → GitHub publish pipeline.

### Documentation

- Top-level README with overview of all guidance.
- Per-subdir README in every `guidance-for-*/` directory.
- LICENSE (MIT-0), NOTICE, CONTRIBUTING.md, CODE_OF_CONDUCT.md.
