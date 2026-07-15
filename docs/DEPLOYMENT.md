# ADP Foundation — Deployment Runbook

**Status**: Final form (Group 7). Documents the foundation as
actually shipped — every command verified, every prereq tested,
every smoke test runnable. Follows the structure mandated by
`~/.kiro/steering/deploy-validation.md` for projects with
deployable runtimes.

The foundation is a **two-stage** (`staging`, `prod`) AWS data
platform pinned to **us-east-1** and **single-account** (one
12-digit AWS account ID for both stages — the only account ADP
currently targets per deploy). Stages
differ only by **resource-name prefix** — not by region, account,
or AWS Identity Center instance. Each stage deploys 5 stacks
(network, lake, datazone, datazone-projects, governance) plus an
account-singular bootstrap (`adp-shared-bootstrap`, deployed once)
plus an optional 6th per-stage stack (`cms-ingest`, off by default).

> **The `Makefile` is the only sanctioned entry point.** Direct
> `cdk deploy` without `-c stage=...` triggers `app.py`'s
> fail-closed guard. Every per-stage target requires
> `STAGE=staging|prod` (lower-case, case-sensitive). See
> [Stage gate](#stage-gate) below.

> **Placeholder notation in commands and ARNs below**: any
> `<account>` token is a **user-substitution** — replace it with
> your 12-digit AWS account ID before running the command (e.g.
> `aws sts get-caller-identity --query Account --output text`).
> Likewise `<idc-store-id>` denotes your IAM Identity Center
> IdentityStore ID (e.g. `d-XXXXXXXXXX`) — resolve it via
> `aws sso-admin list-instances --region us-east-1
> --query 'Instances[0].IdentityStoreId' --output text` and
> supply it at deploy time via `-c identity_store_id=...`.
> Region is pinned to `us-east-1` as a literal throughout (single-
> region by design — see [Why single-region](#why-single-region));
> there is no `<region>` placeholder.

---

## Table of contents

1. [Why single-region](#why-single-region)
2. [Stage gate](#stage-gate)
3. [Naming summary](#naming-summary)
4. [Prereqs](#prereqs)
5. [One-time bootstrap (account-level)](#one-time-bootstrap-account-level)
6. [Stage deploy (`make deploy STAGE=...`)](#stage-deploy-make-deploy-stage)
7. [Expected outcome](#expected-outcome)
8. [Smoke test](#smoke-test)
9. [Post-deploy CloudWatch monitoring](#post-deploy-cloudwatch-monitoring)
10. [Optional: CMS→ADP ingest module](#optional-cmsadp-ingest-module)
11. [Optional: Group 5 add-ons](#optional-group-5-add-ons)
12. [Group 6 verification toolset](#group-6-verification-toolset)
13. [Stage-side teardown](#stage-side-teardown)
14. [Troubleshooting](#troubleshooting)
15. [CI integration](#ci-integration)
16. [Appendix A: Migration history](#appendix-a-migration-history)

---

## Why single-region

The user's IAM Identity Center (IDC) instance `<idc-store-id>` is
**regional and lives only in us-east-1**. The governance stack
creates IDC groups against that store, so any other region fails
at governance creation. This forecloses the CMS-style "region as
stage" pattern for ADP — `staging` and `prod` are
prefix-distinguished within the single us-east-1 account.

---

## Stage gate

Stage is supplied via the CDK context flag `-c stage=staging|prod`,
propagated from the Makefile via `STAGE=...`. The Makefile is the
only sanctioned entry point. Direct `cdk deploy` without
`-c stage=...` will fail in `app.py` with a clear error.

| Invocation | Behavior |
|---|---|
| `make deploy` | ❌ exits 1 — `STAGE is required` |
| `make deploy STAGE=` | ❌ exits 1 — `STAGE is required` |
| `make deploy STAGE=foo` | ❌ exits 1 — must be `staging` or `prod` |
| `make deploy STAGE=Staging` | ❌ exits 1 — case-sensitive (lower-case only) |
| `make deploy STAGE=staging` | ✅ deploys staging stacks |
| `make deploy STAGE=prod` | ✅ deploys prod stacks |
| `make bootstrap` | ✅ no STAGE — account-level only |
| `make help` / `make venv` | ✅ no STAGE required |

> ⚠️ **DO NOT run `cdk deploy` directly.** The Makefile is the
> sanctioned entry point. Direct invocation sidesteps the
> `STAGE` validation guard and may produce stacks with
> unprefixed names that collide with existing deploys.

### Sanctioned commands

All run from `platform-foundation/`.

| Command | Purpose |
|---|---|
| `make bootstrap` | Deploy the account-level `adp-shared-bootstrap` stack (Macie session). One-time per account. |
| `make deploy STAGE=staging\|prod` | Deploy the 5 per-stage foundation stacks. |
| `make deploy-cms-ingest STAGE=... CMS_TABLE_ARN=...` | Deploy with optional CMS→ADP ingest enabled. |
| `make seed-dimensions STAGE=staging\|prod` | Generate the dimension catalog into the stage's lake bucket. |
| `make seed STAGE=staging\|prod` | Master seed: dimensions + 9 product generators + integrity tests (Group 3+). |
| `make smoke-test STAGE=staging\|prod` | Post-deploy DataZone subscription smoke test. |
| `make verify-standalone STAGE=staging\|prod` | Synth-time check that no CMS ARNs leak into the stage's templates. |
| `make teardown STAGE=staging\|prod [YES=1]` | Tear down per-stage stacks (default dry-run; pass `YES=1` to destroy). |

---

## Naming summary

For the full naming inventory, see
`.kiro/specs/2026-05-28-adp-ev-startup-foundation/staging-prod-design.md`
§2. Quick reference:

| Resource class | Staging | Prod |
|---|---|---|
| Bootstrap stack | `adp-shared-bootstrap` (account-singular — same name across stages) | same |
| Stage stack names | `adp-staging-foundation-{network,lake,datazone,datazone-projects,governance}` | `adp-prod-foundation-{network,lake,datazone,datazone-projects,governance}` |
| Optional stack | `adp-staging-foundation-cms-ingest` | `adp-prod-foundation-cms-ingest` |
| Lake bucket | `adp-staging-foundation-lake-<account>-us-east-1` | `adp-prod-foundation-lake-<account>-us-east-1` |
| KMS aliases | `alias/adp-staging-foundation-{lake,trail}` | `alias/adp-prod-foundation-{lake,trail}` |
| DataZone domain | `adp-staging-foundation-domain` | `adp-prod-foundation-domain` |
| Glue databases | `adp_staging_<product>` (10 dbs) | `adp_prod_<product>` (10 dbs) |
| IDC groups | `adp-staging-{data-owners,data-consumers,platform-admins}` | `adp-prod-{data-owners,data-consumers,platform-admins}` |
| CloudTrail trail | `adp-staging-foundation-lake-trail` | `adp-prod-foundation-lake-trail` |
| CFN exports | `adp-staging-foundation-*` | `adp-prod-foundation-*` |

DataZone **project technical names stay unprefixed** across stages
(e.g., `vehicle_telemetry_aggregated`); only the **display name**
gets a `[Staging]` suffix. Prod display names carry no suffix
(asymmetric on purpose — prod is the canonical, staging is the
variant).

---

## Prereqs

### Tools

| Tool | Version | Verify command |
|---|---|---|
| Python | 3.12+ (3.14 supported) | `python3 --version` |
| Node.js | 22.x LTS | `node --version` |
| AWS CDK CLI | 2.255+ | `cdk --version` |
| AWS CLI v2 | 2.15+ | `aws --version` |
| Docker | 24+ | `docker info >/dev/null && echo OK` |
| jq | any | `jq --version` |

If any check fails, install the missing tool and re-run before
proceeding. Docker is required for `cdk bootstrap` asset publishing
and for the optional cms-ingest Glue job's PySpark Docker image.

### AWS account state

| Requirement | Verify command |
|---|---|
| Default credentials configured | `aws sts get-caller-identity` |
| Region us-east-1 reachable | `aws ec2 describe-availability-zones --region us-east-1` |
| CDK bootstrapped in us-east-1 | `aws cloudformation describe-stacks --stack-name CDKToolkit --region us-east-1 >/dev/null && echo OK` |
| IAM Identity Center enabled in us-east-1 | `aws sso-admin list-instances --region us-east-1 --query 'Instances[0].IdentityStoreId' --output text` (record the value as `<idc-store-id>` — supplied to deploys via `-c identity_store_id=<idc-store-id>`) |
| Macie not in conflicting state | `aws macie2 get-macie-session --region us-east-1 2>&1 \| grep -E 'ENABLED\|ResourceNotFoundException'` |
| VPC quota headroom | `aws service-quotas get-service-quota --service-code vpc --quota-code L-F678F1CE --region us-east-1 --query 'Quota.Value' --output text` minus `aws ec2 describe-vpcs --region us-east-1 --query 'length(Vpcs)' --output text` returns ≥1 per stage you intend to deploy |

If `Macie` is already enabled by an unrelated stack and you cannot
import it, escalate before continuing — the bootstrap stack will
fail with "Macie is already enabled" otherwise. Resolution path:
delete the existing session via
`aws macie2 disable-macie --region us-east-1` (lossy — 30-day
cool-down before re-enable) OR import via `cdk import`.

### Project venv

```bash
cd platform-foundation
python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -r requirements.txt
```

Equivalent one-shot: `make venv`.

Verify:

```bash
.venv/bin/python -c "import aws_cdk, constructs, cdk_nag, pyspark; print('OK')"
```

### Environment variables

```bash
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export CDK_DEFAULT_REGION=us-east-1
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
```

The Makefile sets these internally for every `aws` / `cdk`
invocation; the export is only required if you need the values in
your shell for ad-hoc commands.

### Cost-allocation tag (one-time, ~24h propagation)

`common_tags` in `app.py` includes `adp:stage = <stage>` on every
per-stage stack. Per-stage cost reporting in Cost Explorer /
Budgets requires a one-time activation:

```bash
# One-time, account-level. Takes ~24h to populate Cost Explorer.
aws ce update-cost-allocation-tags-status --region us-east-1 \
    --cost-allocation-tags-status TagKey=adp:stage,Status=Active
```

If the CLI is unavailable, do this in the **Billing console →
Cost Allocation Tags → User-defined tags → activate `adp:stage`**.
Until activated, Cost Explorer will report aggregate ADP spend
without per-stage breakdown.

---

## One-time bootstrap (account-level)

Run **once per account**, before the first stage deploy. Re-running
is idempotent and safe (CloudFormation no-op when the stack is
already up).

### Bootstrap command

```bash
cd platform-foundation
make bootstrap
```

Equivalent CDK invocation (do not run directly — Makefile supplies
the synth-time `-c stage=staging` placeholder required by
`app.py`'s upfront stage validation):

```bash
.venv/bin/cdk deploy adp-shared-bootstrap \
    -c stage=staging \
    --require-approval never
```

Approximate time: ~30 seconds (single `AWS::Macie::Session`
resource).

### Bootstrap expected outcome

| Check | Verify command |
|---|---|
| Bootstrap stack `CREATE_COMPLETE` | `aws cloudformation describe-stacks --stack-name adp-shared-bootstrap --region us-east-1 --query 'Stacks[0].StackStatus' --output text` returns `CREATE_COMPLETE` |
| Macie session enabled | `aws macie2 get-macie-session --region us-east-1 --query status --output text` returns `ENABLED` |
| Macie publishing frequency | `aws macie2 get-macie-session --region us-east-1 --query findingPublishingFrequency --output text` returns `FIFTEEN_MINUTES` |
| CFN export present | `aws cloudformation list-exports --region us-east-1 --query "Exports[?Name=='adp-shared-bootstrap-macie-session-status'].Value" --output text` returns `ENABLED` |

### Bootstrap notes

- **Macie session deletion has a 30-day cool-down** per AWS docs.
  The bootstrap stack therefore sets `RemovalPolicy.RETAIN` on the
  session resource. Tearing down the bootstrap stack does NOT
  disable Macie; the session persists and is re-used on the next
  bootstrap.
- The bootstrap stack carries a subset of `common_tags` (project,
  spec, owner) but does **not** carry an `adp:stage` tag — by
  design (the bootstrap is account-singular, not stage-bound).
- Per-stage stacks do **not** declare a synth-time
  `Fn::ImportValue` against the bootstrap. The relationship is
  "deployed once, assumed live"; no synth-time coupling.

---

## Stage deploy (`make deploy STAGE=...`)

Run for each stage you want live. Both stages can coexist in the
same account+region.

### Stage deploy prereqs

- `make bootstrap` has run successfully and Macie session is
  `ENABLED` (per the section above).
- VPC quota margin: each stage consumes 1 VPC slot in us-east-1.
  Confirm headroom **before** deploying:

  ```bash
  QUOTA=$(aws service-quotas get-service-quota \
      --service-code vpc --quota-code L-F678F1CE \
      --region us-east-1 --query 'Quota.Value' --output text)
  CURRENT=$(aws ec2 describe-vpcs --region us-east-1 \
      --query 'length(Vpcs)' --output text)
  echo "Quota=$QUOTA  Current=$CURRENT  Headroom=$((${QUOTA%.*} - CURRENT))"
  ```

  If `headroom < 1`, halt and request a quota raise via Service
  Quotas (`L-F678F1CE`, recommended target: 20). Adding staging at
  quota=10 with 9 VPCs already in use will fail at network stack
  creation — the same trap that caused deploy-attempt-1 to roll
  back per `decisions.md`.

- Project venv exists at `platform-foundation/.venv/`. If not,
  rebuild with `make venv`.

### Stage deploy command

```bash
cd platform-foundation

# Staging
make deploy STAGE=staging

# Prod (gated on VPC quota raise per decisions.md)
make deploy STAGE=prod
```

The Makefile invokes (for each stage):

```
.venv/bin/cdk deploy -c stage=<stage> --require-approval never \
    --exclusively \
    adp-<stage>-foundation-network \
    adp-<stage>-foundation-lake \
    adp-<stage>-foundation-datazone \
    adp-<stage>-foundation-datazone-projects \
    adp-<stage>-foundation-governance
```

Stacks deploy in dependency order:

1. `adp-{stage}-foundation-network` — VPC + endpoints
2. `adp-{stage}-foundation-lake` — S3 lake + KMS + 10 Glue databases
3. `adp-{stage}-foundation-datazone` — DataZone V2 domain + roles
4. `adp-{stage}-foundation-datazone-projects` — 10 projects (9 product + 1 smoke-test consumer)
5. `adp-{stage}-foundation-governance` — Lake Formation tags + per-stage CloudTrail trail + 3 IDC groups (Macie *session* lives in `adp-shared-bootstrap`; per-stage Macie *job* is created post-deploy via `scripts/macie-create-job.sh`)

Approximate time: ~15-25 minutes per stage. The DataZone domain
creation is the slow step.

### Post-deploy: dimension catalog

```bash
make seed-dimensions STAGE=staging
# Generates 7 dimensions (~10.1M rows total, deterministic seed=42)
# to local filesystem under platform-foundation/dimensions/
```

To upload to the stage's lake bucket:

```bash
aws s3 sync dimensions/ \
    s3://adp-staging-foundation-lake-${CDK_DEFAULT_ACCOUNT}-us-east-1/dimensions/ \
    --region us-east-1
```

Re-running `make seed-dimensions STAGE=...` with the same seed
produces byte-identical parquet (deterministic UUIDv5 generation).

### Post-deploy: Macie classification job

The per-stage Macie classification job is bucket-scoped and is
created out-of-band (CloudFormation does not support
`AWS::Macie::ClassificationJob`):

```bash
./scripts/macie-create-job.sh staging
# OR: ./scripts/macie-create-job.sh prod
```

The script picks up the stage's lake bucket name and the same
excluded-prefix list (`dimensions/`,
`curated/vehicle_telemetry_aggregated/`, `curated/energy_usage/`,
`knowledge/`).

---

## Expected outcome

After `make deploy STAGE=staging` completes:

| Check | Verify command |
|---|---|
| 5 stage stacks `CREATE_COMPLETE` | `aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --region us-east-1 --query 'StackSummaries[?starts_with(StackName, ` + "`adp-staging-foundation-`" + `)].StackName' --output text \| tr '\t' '\n' \| wc -l` returns 5 |
| Lake bucket exists | `aws s3 ls s3://adp-staging-foundation-lake-${CDK_DEFAULT_ACCOUNT}-us-east-1/` |
| 10 stage Glue DBs | `aws glue get-databases --region us-east-1 --query 'DatabaseList[?starts_with(Name, ` + "`adp_staging_`" + `)].Name' --output text \| tr '\t' '\n' \| wc -l` returns 10 |
| 10 DataZone projects | `aws datazone list-projects --domain-identifier $DOMAIN_ID --region us-east-1 --query 'items[].name' --output text \| wc -w` returns 10 |
| 3 stage IDC groups | `aws identitystore list-groups --identity-store-id <idc-store-id> --region us-east-1 --query 'Groups[?starts_with(DisplayName, ` + "`adp-staging-`" + `)].DisplayName' --output text \| tr '\t' '\n' \| wc -l` returns 3 |
| Stage CloudTrail logging | `aws cloudtrail get-trail-status --name adp-staging-foundation-lake-trail --region us-east-1 --query IsLogging --output text` returns `True` |
| Macie session still enabled | `aws macie2 get-macie-session --region us-east-1 --query status --output text` returns `ENABLED` |

Substitute `prod` for `staging` to verify the prod stage.

To resolve `$DOMAIN_ID` for the DataZone check:

```bash
DOMAIN_ID=$(aws cloudformation list-exports --region us-east-1 \
    --query "Exports[?Name=='adp-staging-foundation-datazone-domain-id'].Value" \
    --output text)
```

---

## Smoke test

Per `~/.kiro/steering/deploy-validation.md`, **the deploy script
MUST exit non-zero on smoke test failure**. The Makefile's
`smoke-test` target satisfies this contract — it shells out to
`./scripts/smoke-test-subscription.sh $(STAGE)` which exits 1 on
any check failure.

```bash
make smoke-test STAGE=staging
echo "Exit code: $?"   # Must be 0
```

The smoke test:

1. Resolves DataZone domain ID, consumer project ID, producer
   project ID from CFN exports.
2. Validates the stage's Glue catalog is reachable.
3. Validates the DataZone domain is `AVAILABLE`.
4. Validates project exports resolve to live DataZone project IDs.
5. (Post-Group-3 only) Subscribes `data_consumer_test` to the
   `vehicle_telemetry_aggregated` published asset, waits for grant
   propagation (up to 60s), executes
   `SELECT COUNT(*) FROM adp_staging_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated`,
   asserts rows > 0.

**Pre-Group-3 deploy gate**: query succeeds + table exists. Row
count > 0 is required only after Group 3 generators have run and
published the asset.

> ⚠️ **A deploy is not complete until smoke-test passes.** Per
> `~/.kiro/steering/deploy-validation.md`, treat any non-zero
> exit as a deploy failure. Do not run subsequent operator tasks
> (seed, subscriptions, queries) until smoke-test exits 0.

---

## Post-deploy CloudWatch monitoring

The smoke test gates "did the deploy succeed structurally" — but
runtime errors can still surface in the first hour after deploy.
Per `~/.kiro/steering/deploy-validation.md`'s post-deploy
health-check pattern, scan CloudWatch for `ERROR`/`Traceback`
events on the foundation's runtime services:

### Foundation post-deploy CloudWatch scan

Run after `make smoke-test STAGE=...` exits 0. The 60-second wait
gives CloudFormation drift detection and DataZone domain
post-create initialization time to settle.

```bash
STAGE=staging
REGION=us-east-1
START_MS=$(python3 -c "import time; print(int((time.time()-300)*1000))")

# 1. CloudFormation events for any stack failure during the last 5 minutes.
for stack in adp-${STAGE}-foundation-network \
             adp-${STAGE}-foundation-lake \
             adp-${STAGE}-foundation-datazone \
             adp-${STAGE}-foundation-datazone-projects \
             adp-${STAGE}-foundation-governance; do
    aws cloudformation describe-stack-events \
        --stack-name "$stack" --region "$REGION" --no-cli-pager \
        --query 'StackEvents[?ResourceStatus==`CREATE_FAILED` || ResourceStatus==`UPDATE_FAILED` || ResourceStatus==`ROLLBACK_IN_PROGRESS`].[Timestamp,ResourceStatus,LogicalResourceId,ResourceStatusReason]' \
        --output text
done

# 2. CloudTrail data events on the lake bucket — sanity-check the trail is logging.
aws cloudtrail get-trail-status \
    --name adp-${STAGE}-foundation-lake-trail \
    --region "$REGION" --no-cli-pager \
    --query 'LatestDeliveryTime' --output text

# 3. Lake-bucket KMS key — confirm the alias resolves and the key is enabled.
aws kms describe-key --key-id "alias/adp-${STAGE}-foundation-lake" \
    --region "$REGION" --no-cli-pager \
    --query 'KeyMetadata.[KeyState,Enabled]' --output text
# Expected: ENABLED  True
```

Any CloudFormation event matching `*_FAILED` or `ROLLBACK_*` is a
deploy failure. Investigate via
`aws cloudformation describe-stack-events --stack-name <stack> --region us-east-1`.

### CMS-ingest post-enable CloudWatch scan (only when enabled)

If you have enabled the optional cms-ingest module
(see [Optional: CMS→ADP ingest module](#optional-cmsadp-ingest-module)),
add the Glue MERGE job and Firehose to the post-deploy scan. The
60-second wait is critical here — the Glue MERGE job runs every 15
minutes via EventBridge, so look back farther.

```bash
STAGE=staging
REGION=us-east-1
sleep 60

# 4. Glue MERGE job — last run state.
aws glue get-job-runs \
    --job-name "adp-${STAGE}-foundation-cms-ingest-merge" \
    --max-results 5 --region "$REGION" --no-cli-pager \
    --query 'JobRuns[].[StartedOn,JobRunState,ErrorMessage]' \
    --output text 2>&1 || echo "Job not yet executed (EventBridge schedule has not fired)"

# 5. Glue MERGE job CloudWatch logs — scan the last 15 minutes for ERROR/Traceback.
ERRORS=$(aws logs filter-log-events \
    --log-group-name "/aws-glue/jobs/output" \
    --log-stream-name-prefix "adp-${STAGE}-foundation-cms-ingest-merge" \
    --start-time "$(python3 -c 'import time; print(int((time.time()-900)*1000))')" \
    --filter-pattern "?ERROR ?Traceback ?Exception" \
    --limit 5 --region "$REGION" --no-cli-pager \
    --query 'events[].message' --output text 2>/dev/null)
if [ -n "$ERRORS" ]; then
    echo "Runtime errors detected in Glue MERGE job:"
    echo "$ERRORS"
    exit 1
fi

# 6. Firehose stream metrics — confirm records are flowing.
aws firehose describe-delivery-stream \
    --delivery-stream-name "adp-${STAGE}-foundation-cms-vehicle-state" \
    --region "$REGION" --no-cli-pager \
    --query 'DeliveryStreamDescription.[DeliveryStreamStatus,DeliveryStreamARN]' \
    --output text
# Expected: ACTIVE  arn:aws:firehose:us-east-1:<account>:deliverystream/adp-staging-foundation-cms-vehicle-state
```

If `ERRORS` is non-empty, do **not** consider the cms-ingest
enable complete — investigate the Glue job logs before declaring
the module live. Common causes:
* Lake bucket KMS encryption-context mismatch (per
  [Troubleshooting](#troubleshooting) — the bucket-key path).
* DDB Streams `view_type != NEW_AND_OLD_IMAGES` (re-run the
  enable-streams helper from `docs/cms-ingest-optional-module.md` § 2.2).
* Operator-supplied Lambda transformer not yet wired (records not
  arriving at Firehose — `IncomingRecords` metric is 0).

### Add to your operator runbook

The pattern above scales to any new runtime service the foundation
adds. The contract is:
1. Wait 60 seconds after the deploy/enable command exits.
2. `aws logs filter-log-events` with `?ERROR ?Traceback`
   pattern over a 5–15-minute window.
3. Exit non-zero if any error matched.
4. Surface the matched lines so the operator can investigate.

A deploy script that satisfies this contract has the right
post-deploy validation shape per the steering doc.

---

## Post-deploy seed validation

After `make deploy STAGE=staging` completes and smoke-test passes, optionally run the
2026-06-01-adp-foundation-within-quota-seed data-only seeding flow to populate the lake with
6 pandas data products, 7 dimensions, and Bedrock Knowledge Base artifacts. This is the path
to landing queryable data for CVX downstream consumers; the foundation infrastructure alone
is inert without seeded data.

### Flow: Four-phase data-only seed execution

The seeding flow is fully reversible and idempotent at each phase boundary.

#### Phase 1: Local seed generation (Option B scope — 6 pandas + 7 dimensions + KB)

```bash
cd platform-foundation

# Generate dimensions locally
make seed-dimensions STAGE=staging
# → writes 7 dimension catalogs (~10.1M rows total) to platform-foundation/dimensions/

# Generate 6 pandas products + vehicle_knowledge_base artifacts locally
# (PySpark products vehicle_telemetry_aggregated and energy_usage deferred to closed-spec
# Group 6 production Glue follow-up — local venv has Python 3.14 + PySpark 3.5.6
# incompatibility that blocks their generation here)
python source/data-products/vehicle_identity/generator.py
python source/data-products/customer_360/generator.py
python source/data-products/charging_sessions/generator.py
python source/data-products/ota_campaigns/generator.py
python source/data-products/customer_interactions/generator.py
python source/data-products/service_records/generator.py
python source/data-products/vehicle_knowledge_base/generator.py
# → writes parquet files to platform-foundation/curated/<product>/
# → writes KB manifest + markdown to platform-foundation/curated/vehicle_knowledge_base/

# Run referential-integrity + contract tests against local data
pytest tests/test_referential_integrity.py tests/test_data_contracts.py -v
# Expected: 0 failures on FK closure for 6 pandas products (PySpark-product tests skip gracefully)
```

#### Phase 2: S3 sync (raw parquet upload to lake bucket)

```bash
STAGE=staging
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="adp-staging-foundation-lake-${ACCOUNT}-us-east-1"

# Upload dimensions
aws s3 sync dimensions/ \
    s3://${BUCKET}/dimensions/ \
    --region us-east-1

# Upload 6 pandas products + KB
aws s3 sync curated/ \
    s3://${BUCKET}/curated/ \
    --region us-east-1
```

Result: lake bucket non-empty for 6 pandas products + 7 dimensions + KB.

#### Phase 3: Hive EXTERNAL TABLE registration

Staging shipment uses Hive EXTERNAL TABLE registration (not Iceberg-formatted metadata;
production Glue jobs will generate true Iceberg tables). The KB is registered as a
two-part Hive table for manifest + raw-file reference.

```bash
# Register 7 Hive EXTERNAL TABLEs across 6 Glue databases
python lib/group4-hive-register.py --stage staging --region us-east-1

# Expected output:
#   ✓ vehicle_identity        stage=COMPLETE   count=5,000,000
#   ✓ customer_360            stage=COMPLETE   count=10,000,000
#   ✓ service_records         stage=COMPLETE   count=10,000,000
#   ✓ ota_campaigns           stage=COMPLETE   count=100
#   ✓ ota_campaign_events     stage=COMPLETE   count=29,804,114
#   ✓ charging_sessions       stage=COMPLETE   count=20,000,033
#   ✓ customer_interactions   stage=COMPLETE   count=50,000,038
#   VERDICT: PASS — 7 Hive EXTERNAL TABLEs, 124,804,285 queryable rows
```

#### Phase 4: Live verification (smoke-test + contract queries + profile-data)

```bash
STAGE=staging

# Smoke-test the stage's DataZone subscription (prerequisite: Group 3 asset publish)
make smoke-test STAGE=${STAGE}

# Run contract queries against live Athena
./scripts/verify-contract-queries.sh ${STAGE}
# Expected: 15/20 pass (5 PySpark-product-dependent, 3 Iceberg-metadata-syntax,
# 1 KB-as-non-parquet, 2 permanent expected-fails on data-window closed-spec mismatch)
# See decisions.md for full failure catalog and per-cause explanation.

# Profile per-product distributions and publish to CloudWatch dashboard + S3
python scripts/profile-data.py --stage ${STAGE}
# → generates 6 pandas product + 2 KB profile reports (.json + .md)
# → uploads to s3://${BUCKET}/quality-reports/
```

### Resulting state

| Check | Post-seed state |
|---|---|
| Lake bucket (`adp-staging-foundation-lake-<account>-us-east-1`) | Non-empty: 6 pandas curated/ + 7 dimensions/ + KB knowledge/ prefixes |
| Glue databases (6 pandas product dbs + 1 dimensions) | 7 databases live |
| Hive EXTERNAL TABLEs | 7 tables registered (1 per pandas product, 1 for KB manifest) across 6 pandas + 1 dimensions db |
| Athena queryable rows | 124,804,285 total rows across 6 pandas products (verified via `COUNT(*)` post-MSCK REPAIR) |
| Contract queries | 15/20 pass (5 deferred, 3 syntax, 1 format, 2 permanent mismatch — see decisions.md) |
| Profile reports | 8 reports (.json + .md) per product, published to S3 + CloudWatch dashboard metrics |
| Pre-seed state | Lake empty, 0 Glue tables, 0 queryable rows |

### Known issues and deferred scope

**Two generator bugs** (FK drift, str(None) coercion) surfaced during this seeding run and
were inline-fixed per spec scope extension (see
[issues/2026-06-02-adp-charging-sessions-fk-drift-orphans/report.md](../../issues/2026-06-02-adp-charging-sessions-fk-drift-orphans/report.md) for root-cause analysis and prevention tracking).

**PySpark products** (`vehicle_telemetry_aggregated`, `energy_usage`) deferred to
**closed-spec Group 6 production Glue follow-up** — local venv incompatibility (Python 3.14 +
PySpark 3.5.6) is not out-of-scope for the data-only seed (Glue-managed compute uses
AWS-pinned runtimes and bypasses the venv entirely). Filed as
[issues/2026-06-01-pyspark-py314-pickle-incompat/report.md](../../issues/2026-06-01-pyspark-py314-pickle-incompat/report.md).

**KB generator** invoked directly (not via `make seed-vehicle-knowledge-base` — that Makefile target
re-attempts the deferred PySpark step). Produces 51 markdown artifacts + manifest for Bedrock KB
ingestion. The KB is registered as `adp_staging_vehicle_knowledge_base.vehicle_knowledge_base_manifest`
(Hive table pointing at KB manifest; actual ingestion into Bedrock KB is a consumer-side task per
`docs/cvx-integration-contract.md`).

### Reversibility

All four phases are reversible:

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="adp-staging-foundation-lake-${ACCOUNT}-us-east-1"

# Phase 1 + 2: remove local + S3 artifacts
rm -rf curated/ dimensions/ quality-reports/
aws s3 rm --recursive s3://${BUCKET}/curated/
aws s3 rm --recursive s3://${BUCKET}/dimensions/
aws s3 rm --recursive s3://${BUCKET}/knowledge/
aws s3 rm --recursive s3://${BUCKET}/quality-reports/

# Phase 3: drop Glue tables
aws glue delete-table --database-name adp_staging_vehicle_identity \
    --name vehicle_identity --region us-east-1
# … repeat for each table / database

# Phase 4: no persistent changes beyond Glue tables
```

---

## Optional: CMS→ADP ingest module

> ⚠️ **Off by default. Opt-in only.** Vanilla
> `make deploy STAGE=staging|prod` creates **zero** CMS-ingest
> resources. Skip this section unless you are running both CMS
> and ADP in the same AWS account and want a read-only replica
> of CMS DDB tables in the ADP analytical lake.

The full operator-facing runbook for this module lives in
[`docs/cms-ingest-optional-module.md`](./cms-ingest-optional-module.md).
This section is the deploy-runbook entry point.

### When to enable

Enable only if **all** of the following are true:

1. CMS and ADP are deployed in the **same AWS account**.
   Cross-account is deferred to v2 per
   [`docs/cms-ingest-optional-module.md`](./cms-ingest-optional-module.md) § 8.
2. The CMS DDB table you want to replicate is in **us-east-1**
   (matches the ADP foundation's pinned region).
3. The CMS table has **DynamoDB Streams enabled** with
   `StreamViewType = NEW_AND_OLD_IMAGES`. Audit with:

   ```bash
   .venv/bin/python -m source.optional.cms_ingest.enable_streams \
       --table-arn arn:aws:dynamodb:us-east-1:<account>:table/cms-prod-vehicle-state
   ```

   If the audit fails, re-run with `--enable` to fix idempotently
   (coordinate with the CMS operator first — toggling streams
   resets the shard iterator).
4. You have authored or sourced the **operator-supplied Lambda
   transformer** that bridges DDB Streams to Firehose. The
   transformer is documented in
   [`docs/cms-ingest-optional-module.md`](./cms-ingest-optional-module.md) § 6
   with a drop-in code template; ADP does not provision it
   because it lives in the CMS account's observability boundary.

### Enable command

```bash
make deploy-cms-ingest STAGE=staging \
    CMS_TABLE_ARN=arn:aws:dynamodb:us-east-1:${CDK_DEFAULT_ACCOUNT}:table/cms-prod-vehicle-state
```

The Makefile target dispatches to:

```bash
.venv/bin/cdk deploy --all -c stage=staging --require-approval never \
    -c enable_cms_ingest=true \
    -c cms_vehicle_state_table_arn=arn:aws:dynamodb:us-east-1:${CDK_DEFAULT_ACCOUNT}:table/cms-prod-vehicle-state
```

What gets created (per stage) — see
[`docs/cms-ingest-optional-module.md`](./cms-ingest-optional-module.md) § 3
for the full resource list. Summary:

* Glue database `adp_{stage}_cms_ingest`
* Glue tables: `_firehose_{stage}_records` (parquet conversion target), `vehicle_state` (Iceberg target)
* Kinesis Firehose stream `adp-{stage}-foundation-cms-vehicle-state` (60s/64MiB buffering, parquet+ZSTD)
* Glue MERGE job `adp-{stage}-foundation-cms-ingest-merge` (2× G.1X workers, 10-min timeout)
* EventBridge rule `adp-{stage}-foundation-cms-ingest-merge-schedule` (15-min cadence)
* IAM roles for Firehose, Glue MERGE job, EventBridge schedule

### Post-enable smoke

After `make deploy-cms-ingest` returns:

```bash
# 1. Confirm the optional stack exists.
aws cloudformation describe-stacks \
    --stack-name "adp-staging-foundation-cms-ingest" \
    --region us-east-1 --no-cli-pager \
    --query 'Stacks[0].StackStatus' --output text
# Expected: CREATE_COMPLETE or UPDATE_COMPLETE

# 2. Confirm the Glue ingest DB exists.
aws glue get-database --name "adp_staging_cms_ingest" \
    --region us-east-1 --no-cli-pager \
    --query 'Database.Name' --output text
# Expected: adp_staging_cms_ingest

# 3. Run the foundation smoke-test (still passes — cms-ingest enable is a no-op against the foundation contract).
make smoke-test STAGE=staging
echo "Exit code: $?"   # Must be 0

# 4. Run the post-enable CloudWatch scan from the previous section:
#    "CMS-ingest post-enable CloudWatch scan (only when enabled)"
```

End-to-end **wire → queryable** latency: typically 1–2 minutes
after the DDB write, plus the wait for the next 15-minute
EventBridge slot. Worst case (write at minute 0, slot at
minute 15): ~16 minutes.

### Disable command

```bash
.venv/bin/cdk destroy adp-staging-foundation-cms-ingest \
    -c stage=staging \
    -c enable_cms_ingest=true \
    -c cms_vehicle_state_table_arn=arn:aws:dynamodb:us-east-1:${CDK_DEFAULT_ACCOUNT}:table/cms-prod-vehicle-state \
    --require-approval never
```

> The `enable_cms_ingest=true` and `cms_vehicle_state_table_arn=...`
> context flags must be supplied to `cdk destroy` so the app
> instantiates the stack. Without them, CDK reports "no stack
> with name adp-staging-foundation-cms-ingest" because `app.py`
> skips the construct when the flag is OFF.

`cdk destroy` removes the Glue database, Iceberg tables (catalog
entries — the parquet on S3 stays under `cms-ingest/` and
`curated/cms-ingest/`), Firehose stream, IAM roles, and EventBridge
rule. The lake bucket itself stays (it is owned by
`adp-{stage}-foundation-lake`).

For full data archival/teardown, see
[`docs/cms-ingest-optional-module.md`](./cms-ingest-optional-module.md) § 7.

---

## Optional: Group 5 add-ons

Should-Have items per the spec (`spec.md` Risk #10). Each
self-deployable, all skip cleanly if not run.

### Quality dashboard (CloudWatch)

Single-stage CloudWatch dashboard reporting per-product row counts,
edge-case rates, drift-check pass/fail, last-seed-run timestamps.
~$3/mo flat dashboard fee on list price (first 3 dashboards per
account per region free).

```bash
./scripts/deploy-quality-dashboard.sh staging
```

Verify:

```bash
aws cloudwatch get-dashboard \
    --dashboard-name adp-staging-foundation-data-quality \
    --region us-east-1 --no-cli-pager \
    --query 'DashboardName' --output text
# Expected: adp-staging-foundation-data-quality
```

The metric publisher (`scripts/profile-data.py`) populates the
dashboard's metrics. Run after `make seed STAGE=staging`:

```bash
.venv/bin/python scripts/profile-data.py --stage staging
```

### CVX subscription auto-grant

Auto-subscribes a CVX-side DataZone consumer project to the 5
CVX-consumed ADP foundation data products in a single pass:

```bash
./scripts/auto-subscribe-cvx.sh staging \
    --cvx-project <cvx-data-consumer-project-id-or-arn-or-name>

# Dry-run mode (prints API calls without executing — use to validate input):
./scripts/auto-subscribe-cvx.sh staging \
    --cvx-project <cvx-data-consumer-project-id-or-arn-or-name> \
    --dry-run
```

Cross-domain subscriptions are out of scope per spec
Constraint #5; the CVX project must live in the foundation's
DataZone domain.

### Bedrock KB extended seed

Generates narrative-summarized service-records, charging-pattern,
and OTA-rollout documents for ingestion into a CVX-side Bedrock
Knowledge Base:

```bash
.venv/bin/python source/data-products/vehicle_knowledge_base/extended_seed.py \
    --output-root /tmp/adp-vkb-extended

# Upload to the lake's knowledge prefix:
.venv/bin/python source/data-products/vehicle_knowledge_base/extended_seed.py \
    --output-root /tmp/adp-vkb-extended \
    --upload \
    --s3-root s3://adp-staging-foundation-lake-${CDK_DEFAULT_ACCOUNT}-us-east-1/knowledge/vehicle_knowledge_base/extended/
```

The CDK construct for the Bedrock Knowledge Base itself (OpenSearch
Serverless collection, ingestion job) is **not** part of the
foundation; CVX provisions and owns its own KB. See
[Bedrock KB cross-account integration](#bedrock-kb-cross-account-integration)
under Troubleshooting for the IAM contract.

---

## Group 6 verification toolset

Run after `make seed STAGE=staging` lands curated data on disk
(or in S3). All scripts are stage-parameterised; default to
`--dry-run` mode where it makes sense for safety.

| Script | Purpose | Live verify | Dry-run mode |
|---|---|---|---|
| `make verify-standalone STAGE=staging` | Synth-time check that no CMS ARNs leak into the foundation templates | exits 0 | n/a (synth-time) |
| `./scripts/verify-cms-standalone.sh dev` | Synth-time check that CMS deploys cleanly with zero ADP dependency | exits 0 | n/a (synth-time) |
| `./scripts/verify-contract-queries.sh staging` | Run every SQL block in `docs/cvx-integration-contract.md` and `source/athena-queries/` against the deployed foundation | exits 0; per-query ≤30s flag | `--dry-run` prints query inventory |
| `.venv/bin/python scripts/profile-data.py --stage staging` | Per-product distribution profiling + dashboard metric publish | local + S3 reports + CloudWatch metrics | `--dry-run` prints product/metric inventory |

Per spec Constraint: queries that exceed 30s are flagged for
investigation. Do not silently raise the threshold.

---

## PySpark generators (Glue 5.1) — sample tier

Per spec `2026-06-09-adp-pyspark-glue-products`, the 2 PySpark-tier
data products (`vehicle_telemetry_aggregated` + `energy_usage`) ship
on **AWS Glue 5.1** (Spark 3.5.6 + Python 3.11 + Iceberg 1.10.0)
rather than via the local-venv `make seed` path. The local venv's
Python 3.14 cannot serialize the generator closures (cloudpickle
stack overflow); Glue-managed compute bypasses this incompat.

### Prereqs

1. `make deploy STAGE=staging` complete (5 baseline stacks + the
   new `adp-staging-foundation-data-products` stack from
   `2026-06-09-adp-pyspark-glue-products` Group 2).
2. `make seed-dimensions STAGE=staging` complete +
   `dimensions/vins/data.parquet` uploaded to the lake bucket
   (`s3://adp-staging-foundation-lake-{account}-us-east-1/dimensions/vins/`).
3. **Lake Formation grants on the 2 target databases** for both
   the Spark-ETL role AND the user running Athena queries (see the
   "Lake Formation grants" subsection below).

### Deploy command

```bash
cd platform-foundation
source .venv/bin/activate
python3 scripts/run-pyspark-products.py \
    --stage staging --product both \
    --action stage-and-run \
    --rows 10000000 --days 90 --partitions 256 --seed 42 \
    --workers 4 --worker-type G.2X \
    --timeout-min 30 --wait
```

The script's idempotent `--action stage-and-run` will:
1. Upload the 2 generator scripts + `product_generator.py` +
   `schema_loader.py` to `s3://<lake>/scripts/`.
2. Skip re-uploading `dimensions/vins/data.parquet` if already
   present (idempotency contract).
3. Delete-then-create the 2 Glue jobs (15s sleep for IAM
   eventual consistency).
4. Run each generator sequentially (telemetry first, then
   energy_usage); poll `get-job-run` until terminal state.

### Expected outcome

| Metric | `vehicle_telemetry_aggregated` | `energy_usage` |
|---|---|---|
| Wall clock | ~4 min | ~6 min |
| Iceberg table | Auto-registered as `Format=ICEBERG` | Same |
| S3 parquet | 1440 files (90 dates × 16 buckets) | 91 files (1/day × 90 days) |
| Total bytes | ~1.5 GiB | ~1.0 GiB |
| Athena `SELECT COUNT(*)` | 10,000,000 | 10,000,000 |
| Cost | ~$0.28 | ~$0.28 |

Total ≤ $1, well under the spec's $1 envelope.

### Smoke test

```bash
./scripts/verify-contract-queries.sh staging --workgroup primary
```

After the PySpark runs, **9/20 contract queries PASS** (up from 5
in the within-quota baseline). The 11 expected fails are
enumerated in `.kiro/specs/2026-06-09-adp-pyspark-glue-products/expected-failing-queries.txt`
across 3 documented categories: (A) Iceberg metadata virtual tables
on pandas products, (B) contract-vs-generator data-window mismatch,
(C) verify-script multi-statement parse error. All 3 categories are
P3 follow-ups outside this spec.

### Lake Formation grants

Glue 5.1's Iceberg writeTo path requires Lake Formation grants on
the 2 target databases for the Spark-ETL role; Athena queries
require LF grants for the user. Currently applied via:

```bash
ROLE_ARN="arn:aws:iam::<account>:role/adp-staging-foundation-spark-etl-role-us-east-1"
USER_ARN="arn:aws:iam::<account>:user/<your-username>"

for DB in adp_staging_vehicle_telemetry_aggregated adp_staging_energy_usage; do
  # Spark-ETL role (write side)
  aws lakeformation grant-permissions \
    --principal DataLakePrincipalIdentifier="$ROLE_ARN" \
    --resource "{\"Database\": {\"Name\": \"$DB\"}}" \
    --permissions CREATE_TABLE ALTER DESCRIBE DROP \
    --region us-east-1
  aws lakeformation grant-permissions \
    --principal DataLakePrincipalIdentifier="$ROLE_ARN" \
    --resource "{\"Table\": {\"DatabaseName\": \"$DB\", \"TableWildcard\": {}}}" \
    --permissions ALL \
    --region us-east-1
  # User (Athena query side)
  aws lakeformation grant-permissions \
    --principal DataLakePrincipalIdentifier="$USER_ARN" \
    --resource "{\"Table\": {\"DatabaseName\": \"$DB\", \"TableWildcard\": {}}}" \
    --permissions SELECT DESCRIBE \
    --region us-east-1
  aws lakeformation grant-permissions \
    --principal DataLakePrincipalIdentifier="$USER_ARN" \
    --resource "{\"Database\": {\"Name\": \"$DB\"}}" \
    --permissions DESCRIBE \
    --region us-east-1
done
```

> **P3 follow-up**: migrate these grants into
> `data_products_stack.py` as `aws_lakeformation.CfnPermissions`
> resources before the production-scale spec ships.

### Tear-down

```bash
python3 scripts/run-pyspark-products.py --stage staging --product both --action teardown
```

This deletes the 2 one-shot Glue jobs but PRESERVES:
- The persistent IAM role `adp-staging-foundation-spark-etl-role-us-east-1`
- The S3 scripts at `s3://<lake>/scripts/`
- The Iceberg tables + parquet at `s3://<lake>/curated/<product>/`
  (these are the deliverable)
- The Lake Formation grants

### Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Run > 30 min, hits Timeout | Spike-extrapolation drift; production-scale arg passed at sample tier | Surface, do NOT raise timeout. Check `--rows` arg. |
| `bytes_per_row` outside `[147, 180]` for telemetry | Generator output drift OR Iceberg 1.10.0 emitting different file footprints | Soft signal. Check Athena COUNT first; if 10M rows and table reads cleanly, log and ship. |
| `Format != ICEBERG` on `aws glue get-table` | Iceberg writeTo failed; generator fell back to plain parquet | Check CloudWatch logs for `Iceberg writeTo failed` — inspect the Java exception. Most common: missing LF grant or Iceberg+GlueCatalog Spark conf gone wrong. |
| `Athena returns 0 rows for substitute VIN` | VIN selection non-determinism in `_load_vins` | Already fixed 2026-06-11 via `.orderBy("vin")` in both generators. |
| Glue job FAIL with `MetadataFetchFailedException` | Off-heap memory pressure during Iceberg V2 bucketed write killed an executor container | Use `--workers 4 --worker-type G.2X`, `--partitions 256`, default `--conf` block (which includes `spark.executor.memoryOverhead=6g`). |
| Athena query: "Only one sql statement is allowed" | Multi-statement athena-query SQL file (e.g., `vin_full_360.sql`) | Known issue (P3 follow-up); listed in spec-local `expected-failing-queries.txt`. |

### Production-scale follow-up

Same orchestration script handles production scale (100M telemetry / 450M
energy_usage); pass `--rows 100000000` (telemetry) or `--rows 450000000`
(energy_usage) and scale `--workers` proportionally (e.g., `--workers 8
G.2X` for telemetry, `--workers 16 G.2X` for energy_usage). Tracked as P3
backlog row "ADP PySpark production-scale" pending CVX-on-foundation v1
prereq alignment.

---

## Vehicle Knowledge Base (Bedrock KB + AOSS) deploy

> ⚠️ **Cost commitment**: AOSS vectorsearch collections have a 2-OCU minimum.
> Each stage (staging, prod) costs **~$345/month** at idle, even with
> `STANDBY_REPLICAS=DISABLED`. Two stages = ~$700/month continuous.
> Validate the staging-MVP business case before deploying prod.

The Vehicle Knowledge Base stack (`adp-{stage}-foundation-vehicle-knowledge-base`)
creates a Bedrock Knowledge Base backed by an Amazon OpenSearch Serverless (AOSS)
vectorsearch collection. The KB is consumed by the CVX (Connected Vehicle Experience)
agent platform for retrieval-augmented generation (RAG) over vehicle maintenance
and diagnostic documentation.

### Operator runbook

#### Step 0: Resolve the deploy-role ARN

The AOSS data-access policy must include the principal running `cdk deploy`.
Identify your deploy principal using one of the following methods:

**Option A: Direct IAM role (most common)**
```bash
DEPLOY_ROLE_ARN=$(aws sts get-caller-identity --query Arn --output text)
echo "Deploy role: $DEPLOY_ROLE_ARN"
```

**Option B: CDK bootstrap CloudFormation execution role (if using `cdk bootstrap`)**
```bash
DEPLOY_ROLE_ARN=$(aws cloudformation describe-stacks \
  --stack-name CDKToolkit \
  --query "Stacks[0].Outputs[?OutputKey=='CloudFormationExecutionRoleArn'].OutputValue" \
  --output text --region us-east-1)
echo "Deploy role: $DEPLOY_ROLE_ARN"
```

**Default (if using standard CDK bootstrap qualifier `hnb659fds`)**: If you have never
customized your `cdk bootstrap` qualifier, the default is:
```
arn:aws:iam::<account-id>:role/cdk-hnb659fds-cfn-exec-role-<account-id>-us-east-1
```
The synth will log the resolved default so you can audit which principal it selected.

**Environment-variable fallback**: instead of the CDK context flag `-c adpKbDeployRoleArn=...`,
you can export the same value as `ADP_KB_DEPLOY_ROLE_ARN`. The resolver helper
`_resolve_kb_deploy_role_arn(app, env)` in `platform-foundation/app.py` honors this
order: CDK context → env var → synth-time `hnb659fds` default. Context takes
precedence over env when both are set. The same precedence pattern applies to the
cross-account principals: `-c cvxKbPrincipals=arn1,arn2` overrides
`ADP_KB_CVX_PRINCIPAL_ARNS=arn1,arn2`.

```bash
export DEPLOY_ROLE_ARN=$(aws sts get-caller-identity --query Arn --output text)
export ADP_KB_DEPLOY_ROLE_ARN=$DEPLOY_ROLE_ARN
export ADP_KB_CVX_PRINCIPAL_ARNS=arn:aws:iam::<account-id>:role/cvx-staging-kb-retrieval-role
# Subsequent `make deploy STAGE=staging` will pick these up without the -c flags.
```

#### Step 1: Verify Lake Formation prerequisite

The foundation lake requires Lake Formation v4 cross-account settings to be enabled:
```bash
aws lakeformation get-data-lake-settings --region us-east-1
```
Verify the response includes:
- `"CROSS_ACCOUNT_VERSION": 4`
- `"AllowExternalDataFiltering": true`

If either is missing or differs, the KB stack will fail during the LF permission
grant phase. Contact your account's data platform lead.

#### Step 2: Synthesize the stack

From the project root:
```bash
cd platform-foundation
make synth STAGE=staging
```

This generates the CloudFormation template and runs the CDK nag security checks.

#### Step 3: Deploy the stack

**With the resolved deploy role ARN** from Step 0, deploy the stack:
```bash
make deploy STAGE=staging \
  -c adpKbDeployRoleArn=$DEPLOY_ROLE_ARN \
  -c cvxKbPrincipals=arn:aws:iam::<account-id>:role/cvx-staging-kb-retrieval-role
```

Alternatively, use the direct `cdk deploy` command:
```bash
cdk deploy adp-staging-foundation-vehicle-knowledge-base \
  -c stage=staging \
  -c adpKbDeployRoleArn=$DEPLOY_ROLE_ARN \
  -c cvxKbPrincipals=arn:aws:iam::<account-id>:role/cvx-staging-kb-retrieval-role
```

The deployment typically takes 8–12 minutes. Monitor progress in the CloudFormation console
or via `aws cloudformation describe-stacks --stack-name adp-staging-foundation-vehicle-knowledge-base`.

#### Step 4: Capture the Knowledge Base ID and ARN

Once the stack reaches `CREATE_COMPLETE`, retrieve the stack outputs:
```bash
aws cloudformation describe-stacks \
  --stack-name adp-staging-foundation-vehicle-knowledge-base \
  --query 'Stacks[0].Outputs' \
  --region us-east-1
```

Save the `KnowledgeBaseId` and `KnowledgeBaseArn` from the output. Example:
```
[
  {
    "OutputKey": "KnowledgeBaseId",
    "OutputValue": "XXXXXXXXXX"
  },
  {
    "OutputKey": "KnowledgeBaseArn",
    "OutputValue": "arn:aws:bedrock:us-east-1:<account-id>:knowledge-base/XXXXXXXXXX"
  }
]
```

#### Step 5: Redeploy CVX with the KB ID

CVX agents consume the ADP KB for RAG. Redeploy CVX infrastructure with the new KB ID:
```bash
cd ../guidance-for-connected-vehicle-experience-on-aws/infrastructure
cdk deploy \
  -c adpKbId=XXXXXXXXXX \
  -c cvxKbPrincipals=arn:aws:iam::<account-id>:role/cvx-staging-kb-retrieval-role
```

This wires the KB ID into the CVX agent tools and tightens IAM permissions from
wildcard `knowledge-base/*` to the specific KB ARN.

#### Step 6: Trigger initial ingestion job

The KB requires an initial data ingestion from the vehicle knowledge source. The
data-source ID is **CFN-generated, not human-named** — capture it from the KB
right after deploy completes:

```bash
DS_ID=$(aws bedrock-agent list-data-sources \
  --knowledge-base-id XXXXXXXXXX \
  --region us-east-1 \
  --query 'dataSourceSummaries[?name==`vehicle-knowledge-base-sources`].dataSourceId' \
  --output text)
echo "DataSourceId: $DS_ID"
```

The data-source `name` is fixed by the CDK (`vehicle-knowledge-base-sources` per
spec.md § Implementation outline 1); only the underlying `dataSourceId` (10-char
hex e.g. `QZL8HLXQ1H` from the 2026-06-18 staging deploy) varies per stack. Pinning
the lookup to the name keeps the runbook stage-agnostic.

The `client-token` MUST be ≥33 characters (AWS quota); using `uuidgen` (yields 36
chars including hyphens, plus an optional prefix) satisfies this.

Trigger the ingestion job (replace `<KB_ID>` with the value from Step 4):
```bash
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id XXXXXXXXXX \
  --data-source-id $DS_ID \
  --client-token "vkb-initial-$(uuidgen)" \
  --region us-east-1
```

The response includes `ingestionJobId`. Save it for polling in Step 7.

#### Step 7: Poll ingestion job until complete

Poll the ingestion status (replace `<INGESTION_JOB_ID>` with the value from Step 6):
```bash
aws bedrock-agent get-ingestion-job \
  --knowledge-base-id XXXXXXXXXX \
  --data-source-id $DS_ID \
  --ingestion-job-id <INGESTION_JOB_ID> \
  --region us-east-1
```

Repeat every 20–30 seconds until `"status": "COMPLETE"`. Staging data (~50 docs,
~40KB total) ingests in ≤20 seconds; production-scale data takes 2–5 minutes.
On failure, check the `failureReasons` field and consult the operator runbook's
troubleshooting section.

#### Step 8: Smoke test retrieval

Verify the KB is queryable:
```bash
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id XXXXXXXXXX \
  --retrieval-query '{"text":"P0301 misfire cylinder"}' \
  --retrieval-configuration '{"vectorSearchConfiguration":{"numberOfResults":3}}' \
  --region us-east-1
```

The response should include `retrievalResults` with matching vehicle documentation.
The 2026-06-18 staging deploy returned top hit `dtc-P0301.md` at score `0.7458`
for this exact query. If your retrieve returns 0 hits, the query terms may not
semantically match indexed content — try broader phrasing first; if still empty,
ingestion may not have completed (re-check Step 7 status) or the vector index may
not be ACTIVE.

### Tear-down

**Before destroying the stack**, stop any in-flight ingestion jobs to prevent deletion
conflicts:
```bash
# List all ingestion jobs for the KB
aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id XXXXXXXXXX \
  --region us-east-1

# Stop any job with status IN_PROGRESS (replace <JOB_ID> with the actual ID)
aws bedrock-agent stop-ingestion-job \
  --knowledge-base-id XXXXXXXXXX \
  --data-source-id $DS_ID \
  --ingestion-job-id <JOB_ID> \
  --region us-east-1 || true
```

Once all ingestion jobs are stopped, tear down the stack:
```bash
cd platform-foundation
make teardown STAGE=staging YES=1
```

All AOSS resources are configured with `RemovalPolicy.DESTROY`, so they will be
automatically deleted by CloudFormation. The deletion typically takes 3–5 minutes.

---

## Stage-side teardown

Per-stage teardown removes a single stage's stacks while leaving
the shared bootstrap and the other stage untouched.

> ⚠️ **Destructive — synthetic data only**. The lake KMS CMK is
> retained per `RemovalPolicy.RETAIN` (encrypted data may outlive
> the stack). The Macie *session* in `adp-shared-bootstrap` is
> NOT touched.

> **Reversibility**: data is regenerable via `make seed STAGE=...`.
> CFN stack history, IDC group IDs, and DataZone project IDs are
> NOT recoverable; new IDs will be issued on the next deploy.

### Teardown command

The Makefile target defaults to **dry-run** per
`~/.kiro/steering/safety_guardrails`. Pass `YES=1` to actually
destroy:

```bash
cd platform-foundation

# Dry-run — prints what WOULD be deleted (default, safe).
make teardown STAGE=staging

# Actually destroy.
make teardown STAGE=staging YES=1

# Same for prod:
make teardown STAGE=prod YES=1
```

The Makefile invokes `./scripts/teardown.sh $(STAGE) --yes` (or
`--dry-run`). The script's six-step sequence:

1. Stop the stage CloudTrail trail gracefully (avoids logs into a
   soon-to-be-deleted bucket).
2. Empty the 3 S3 buckets (lake, lake-logs, trail-logs) — current
   objects + every version + every delete-marker. Versioned buckets
   cannot be CDK-destroyed otherwise.
3. Pre-empt the DataZone domain delete via
   `aws datazone delete-domain --skip-deletion-check` (cascades
   through the 10 retained `CfnProject` resources that block the
   stack delete).
4. `cdk destroy --force -c stage=<stage>` with an **explicit stack
   list** (NEVER `--all` — that would walk into
   `adp-shared-bootstrap`). Optional `cms-ingest` stack
   auto-detected and included if present.
5. Idempotent IDC group cleanup fallback (some CDK / CFN versions
   do not honor `RemovalPolicy.DESTROY` on `CfnGroup`).
6. Verify: assert no `adp-{stage}-foundation-*` stacks remain AND
   `adp-shared-bootstrap` is still
   `CREATE_COMPLETE`/`UPDATE_COMPLETE`.

### Verify teardown

```bash
STAGE=staging

# All 5 stage stacks should be DELETE_COMPLETE or absent.
aws cloudformation list-stacks \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
    --region us-east-1 \
    --query "StackSummaries[?starts_with(StackName, \`adp-${STAGE}-foundation-\`)].StackName" \
    --output text
# MUST be empty

# Lake bucket gone.
aws s3 ls s3://adp-${STAGE}-foundation-lake-${CDK_DEFAULT_ACCOUNT}-us-east-1/ 2>&1 | head -1
# MUST report NoSuchBucket

# Stage IDC groups gone.
aws identitystore list-groups --identity-store-id <idc-store-id> --region us-east-1 \
    --query "Groups[?starts_with(DisplayName, \`adp-${STAGE}-\`)].DisplayName" --output text
# MUST be empty

# Bootstrap stack untouched.
aws cloudformation describe-stacks --stack-name adp-shared-bootstrap --region us-east-1 \
    --query 'Stacks[0].StackStatus' --output text
# MUST return CREATE_COMPLETE or UPDATE_COMPLETE — Macie session preserved.

# OTHER stage's stacks untouched.
OTHER=prod  # if you tore down staging
aws cloudformation list-stacks \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
    --region us-east-1 \
    --query "StackSummaries[?starts_with(StackName, \`adp-${OTHER}-foundation-\`)].StackName" \
    --output text
# MUST be unchanged from before teardown
```

### Re-deploy after teardown

```bash
make deploy STAGE=staging
make seed STAGE=staging        # once Group 3 lands curated data
make smoke-test STAGE=staging
./scripts/macie-create-job.sh staging
```

The new deploy creates fresh resources with the same stage-prefixed
names. New CloudFormation stack IDs, new DataZone project IDs, new
IDC group IDs, fresh CloudTrail trail. **Same lake KMS CMK**
(retained — bound to the deterministic alias
`alias/adp-staging-foundation-lake`).

---

## Troubleshooting

### `cdk synth` fails with "stage is required"

`app.py` validates the `-c stage=...` context flag upfront. Run
via the Makefile (`make synth STAGE=staging`), not `cdk synth`
directly. If you must invoke CDK directly for debugging, prefix
with `-c stage=staging` or `-c stage=prod`.

### `cdk synth` fails on first run

* Check `aws-cdk-lib` is installed in the venv:
  `pip show aws-cdk-lib`
* Check Node.js is on PATH: `node --version` (CDK uses jsii
  bridge).
* Re-run `make venv` if the venv looks incomplete.

### DataZone domain creation hangs

* Check IAM Identity Center is in the same region (`us-east-1`).
* Check the domain name doesn't collide with an existing domain.
  The foundation uses `adp-{stage}-foundation-domain` to avoid
  collisions with legacy `automotive-data-platform` deployments.

### Subscription smoke test fails with "asset not found"

Expected pre-Group-3. The asset is published by the Group 3
`vehicle_telemetry_aggregated` generator. Until then, the smoke
test logs a warning and falls through to direct Athena read of
the Glue table.

After Group 3 lands and `make seed STAGE=staging` runs end-to-end,
the asset is auto-published; re-run `make smoke-test STAGE=staging`
to confirm row count > 0.

### `cdk-nag` errors on deploy

* Run `cdk synth -c stage=staging` and inspect
  `cdk.out/AwsSolutions-*-NagReport.csv` per stack.
* Errors block deploy; Warnings do not.
* Suppressions live alongside the constructs they exempt — search
  for `NagSuppressions` in `stacks/*.py`.

### Macie session error: "Macie is already enabled"

The bootstrap stack creates `AWS::Macie::Session`. If Macie was
previously enabled in the account by another workload, the
resource creation will fail.

Resolution:
* `aws macie2 disable-macie --region us-east-1` (lossy — 30-day
  cool-down before re-enable), OR
* `cdk import` the existing session into the bootstrap stack
  (preserves continuity).

### S3 bucket name conflict

Bucket names are global. If a different account already owns
`adp-{stage}-foundation-lake-<acct>-us-east-1`, deploy will fail.
The `<acct>` suffix usually prevents this. If the conflict is
real, the recovery is a different account or a one-off bucket
rename via `_naming.py` override.

### IAM Identity Center group creation fails

* Verify the IDC instance ID matches the user's:
  `aws sso-admin list-instances --region us-east-1 --query 'Instances[0].IdentityStoreId' --output text`
  (must return your `<idc-store-id>`; if it returns a different
  value, the deploy is targeting the wrong account or the
  Identity Center instance has been recreated).
* Identity Center group creation is idempotent — re-running
  deploy after a partial failure picks up where it left off.

### CMS-ingest post-enable: Glue MERGE job fails with `KMS AccessDenied`

The Firehose / Glue roles' KMS encryption-context conditions
were updated in 2026-05-30 (Fix Group E) to support the lake
bucket's `bucket_key_enabled=True` setting. If you see
`KMS AccessDenied` on `s3.GenerateDataKey`, ensure the deployed
cms-ingest stack post-dates that fix:

```bash
aws cloudformation describe-stacks \
    --stack-name "adp-staging-foundation-cms-ingest" \
    --region us-east-1 --no-cli-pager \
    --query 'Stacks[0].LastUpdatedTime' --output text
# Should be ≥ 2026-05-30
```

If older, redeploy the cms-ingest stack to pick up the fix.

### Bedrock KB cross-account integration

> Carry-forward clarification from the spec's security review
> cycle 3. Read this **before** wiring a CVX-side Bedrock
> Knowledge Base to the ADP lake.

**Bedrock Knowledge Base ingestion reads source documents via the
KB's data-source IAM role calling S3 directly** (`s3:ListBucket`
/ `s3:GetObject` against the lake bucket's
`knowledge/vehicle_knowledge_base/` prefix). It does **NOT** use
Lake Formation vended credentials.

Lake Formation's `lakeformation:GetDataAccess` issues short-lived
credentials only for **engine-mediated** reads (Athena, Redshift
Spectrum, EMR, Glue ETL). LF does **not** mediate Bedrock-KB S3
reads. A consumer following the DataZone subscription model alone
will hit `AccessDenied` at first KB ingestion run.

Two valid integration patterns:

**(a) Same-account** (recommended for the foundation's current
single-account topology):

* Deploy the Bedrock KB **in the same account** as the ADP lake
  (or in any account that owns the lake bucket).
* The KB's data-source role inherits the same IAM as any
  in-account principal — no bucket policy edit required, no LF
  grant required.
* Lake KMS CMK key policy already permits in-account principals
  via the standard `kms:ViaService = s3.us-east-1.amazonaws.com`
  condition.

**(b) Cross-account** (CVX KB in a different account from ADP):

* ADP **MUST** add an explicit bucket policy on
  `adp-{stage}-foundation-lake-<acct>-us-east-1` allowing the CVX
  KB data-source role ARN to call `s3:ListBucket` /
  `s3:GetObject` on the
  `knowledge/vehicle_knowledge_base/sources/*` prefix only.
* ADP **MUST** update the lake KMS key policy
  (`alias/adp-{stage}-foundation-lake`) to allow that role
  `kms:Decrypt` and `kms:DescribeKey`.
* DataZone subscription grants do **not** cover this path — they
  are LF-mediated, and LF does not vend credentials to Bedrock.

Pattern (b) requires ADP-side IaC change (bucket policy + KMS
policy edits, scoped to the explicit CVX KB role ARN). It is
**not** a default capability of the foundation; do not promise
it in CVX integration docs without filing an ADP-side spec to
add the cross-account grant.

For the same-account pattern, the foundation's existing IAM is
sufficient; the consumer-side IAM template in
`docs/cvx-integration-contract.md` § 2.1 + the additional
Bedrock invoke grants documented in the same doc cover the read
path.

### CMS-ingest post-enable: parquet not appearing in S3

* Confirm DDB Streams are enabled on the source table with
  `view_type = NEW_AND_OLD_IMAGES`:

  ```bash
  .venv/bin/python -m source.optional.cms_ingest.enable_streams \
      --table-arn arn:aws:dynamodb:us-east-1:<account>:table/cms-prod-vehicle-state
  ```

* Confirm the operator-supplied Lambda transformer is wired
  (Firehose `IncomingRecords` metric should be > 0).
* Confirm Firehose buffer hasn't yet flushed (60s/64MiB buffer).
  Wait up to 60s after the first DDB write.
* Check `_errors/` prefix under
  `s3://adp-{stage}-foundation-lake-*/cms-ingest/`. Sticky
  serialization errors land here.

---

## CI integration

The foundation includes the following CI gates:

| Gate | Script | Where |
|---|---|---|
| Standalone-deploy verify (no CMS leakage) | `./scripts/verify-standalone.sh <stage>` | `.github/workflows/lint.yml` |
| CMS-standalone verify (no ADP leakage) | `./scripts/verify-cms-standalone.sh <dev\|staging\|prod>` | runs CMS's own `cdk synth --all` against a synthetic account |
| Pytest suite (151 passed, 59 skipped) | `.venv/bin/pytest tests/ -v` | runs offline; `needs_curated` tests skip when curated data is absent |
| `cdk synth --all` (per stage) | `make synth STAGE=staging` and `STAGE=prod` | both must exit 0 with cdk-nag clean |

**Smoke-test contract** (per
`~/.kiro/steering/deploy-validation.md`): every
`make deploy STAGE=...` invocation MUST be followed by
`make smoke-test STAGE=...`. The smoke test exits non-zero on
failure; do not consider a deploy "complete" until the smoke test
passes. The CI gate runs the smoke test against the staging
environment after each merge to `main` that touches the
foundation.

CMS deps (for `verify-cms-standalone.sh`) must be bootstrapped on
the CI runner — the script gives a clear "bootstrap CMS deps"
message if `~/connected-mobility-guidance-on-aws/deployment/.venv/`
is absent.

---

## Appendix A: Migration history

> ℹ️ **Historical**. The migration from the pre-stage
> `adp-foundation-*` deploy to the stage-prefixed
> `adp-{staging|prod}-foundation-*` deploy completed
> **2026-05-29** per `decisions.md`'s "Stage rollout complete"
> entry. This appendix retains the runbook used at the time so
> operators reconciling logs from the migration window have a
> reference. **Do not run this for new deploys** — start from
> [One-time bootstrap (account-level)](#one-time-bootstrap-account-level).

The 13-step destructive migration runbook (per design §6 Option
A — destroy current `adp-foundation-*` deploy, redeploy as
`adp-staging-foundation-*`) has been preserved in version control
at the spec's `staging-prod-design.md` § 6. Key checkpoints:

1. Pre-flight (auth, account, region check).
2. Snapshot project / subscription metadata.
3. Drain active DataZone subscriptions (manual).
4. Empty 3 S3 buckets (lake, lake-logs, trail-logs).
5. Drop all object versions and delete markers.
6. `cdk destroy --all` on the 5 existing `adp-foundation-*`
   stacks (using the OLD code, before pulling A1–A4) — ~15 min.
7. Verify all 5 stacks `DELETE_COMPLETE`.
8. Verify (or manually delete) the 3 IDC groups.
9. Pull `main` containing fix-group A1–A4.
10. `make bootstrap`.
11. `make deploy STAGE=staging`.
12. `make seed STAGE=staging` (after Group 3 lands).
13. `make smoke-test STAGE=staging` — gating exit-0.

The migration was completed by the architect on 2026-05-29 with 4
in-flight defects discovered and fixed in-stride (all documented
in `decisions.md` "Stage rollout complete" entry). Prod deploy
remains gated on the user's L-F678F1CE quota raise approval per
the same entry.

### CFN export-name transition note

The pre-stage exports (`adp-foundation-*`) and the new
stage-prefixed exports (`adp-staging-foundation-*` /
`adp-prod-foundation-*`) **never coexisted**. The pre-stage
stacks were destroyed before the new stacks were deployed. No
transition collision was possible.

If a third-party stack ever
`Fn::ImportValue`-references a pre-stage export, it will fail
during the destroy. Audit
`aws cloudformation list-imports --export-name <pre-stage-export>`
before any future migration; if any imports exist, remediate the
consumer first.
