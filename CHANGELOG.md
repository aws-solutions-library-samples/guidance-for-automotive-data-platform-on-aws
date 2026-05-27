# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
