.PHONY: help venv install bootstrap synth deploy deploy-cms-ingest \
        seed-dimensions seed-dimensions-dry seed smoke-test \
        seed-vehicle-identity seed-customer-360 seed-charging-sessions \
        seed-ota-campaigns seed-customer-interactions seed-service-records \
        seed-tire-health \
        seed-vehicle-telemetry-aggregated seed-energy-usage \
        seed-vehicle-knowledge-base seed-integrity \
        publish-product publish-product-with-purge \
        verify-standalone verify test teardown clean-cdk-out \
        _require-stage

# ----------------------------------------------------------------------------
# Colors
# ----------------------------------------------------------------------------
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
NC     := \033[0m

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
AWS_REGION ?= us-east-1
AWS_PROFILE ?= default
SEED ?= 42
CDK_DEFAULT_REGION := $(AWS_REGION)

# Master seed configuration. Local-dev defaults; override at command line.
SEED_DIM_ROOT      ?= dimensions
SEED_OUTPUT_ROOT   ?= curated
# Local PySpark sample-tier sizing — full Glue runs deferred per
# `.kiro/specs/2026-05-28-adp-ev-startup-foundation/decisions.md`
# ("Group 3 scope: pandas-full, Spark-sample, KB-artifacts-only").
PYSPARK_LOCAL_ROWS       ?= 100000
PYSPARK_LOCAL_DAYS_TEL   ?= 7
PYSPARK_LOCAL_DAYS_NRG   ?= 30
PYSPARK_LOCAL_PARTITIONS ?= 4

# tire_health scale — MUST be explicit. Do not remove.
#
# The generator's --scale defaults to 1.0, meaning *every VIN in the dimension
# pool* x WINDOW_DAYS=60 x 4 tire positions, materialised in pandas. Against
# the prod dimension set (5,000,000 VINs) that is:
#
#     5,000,000 x 60 x 4 = ~1.2 BILLION rows
#
# which is unsatisfiable on a 32 GB workstation. Omitting --scale here is what
# OOM-killed `make seed STAGE=prod` at product 7/10 on 2026-08-30 (SIGKILL);
# because the seed chain is strictly sequential that silently skipped products
# 8-10 AND the seed-integrity gate. See
# issues/2026-08-31-adp-prod-seed-oom-tire-health/.
#
# 0.005 x 5,000,000 = 25,000 VINs -> 25,000 x 60 x 4 = 6,000,000 rows, which
# matches the established portfolio size for this product (staging currently
# holds 6,000,800 rows; the prior prod artifact held 6,000,000).
#
# NOTE: scale slices the VIN pool, so tire_health deliberately covers a
# 25,000-VIN subset while other products cover all 5,000,000. That is a
# reviewable decision rather than an emergent consequence of pool size — which
# is the whole point of pinning it here.
#
# Raising it is a memory decision, and the budget is measured, not estimated:
# scale=0.005 (6,000,000 rows) peaks at ~8.7 GB RSS in 133 s, i.e. ~1.45 KB per
# row at peak. Scale linearly from there and leave headroom — 0.02 (24M rows)
# already approaches 32 GB.
TIRE_HEALTH_SCALE        ?= 0.005

PY := .venv/bin/python

# Resolve the AWS account ID once. Override by exporting before invoking make.
ifeq ($(origin CDK_DEFAULT_ACCOUNT),undefined)
CDK_DEFAULT_ACCOUNT := $(shell aws sts get-caller-identity --query Account --output text 2>/dev/null)
endif

# Common env block. ALL targets that invoke aws/cdk must source this.
# AWS_DEFAULT_REGION is required so SDK calls (e.g. cdk asset publishing,
# `aws sts get-caller-identity`) target us-east-1 even when the user's
# ~/.aws/config defaults to a different region.
AWS_ENV := AWS_REGION=$(AWS_REGION) \
	AWS_DEFAULT_REGION=$(AWS_REGION) \
	CDK_DEFAULT_REGION=$(CDK_DEFAULT_REGION) \
	CDK_DEFAULT_ACCOUNT=$(CDK_DEFAULT_ACCOUNT)

# ----------------------------------------------------------------------------
# Stage gating (Fix Group A — staging-prod rollout, design §1, §4)
#
# Every per-stage target depends on `_require-stage`, which fails closed
# (exit 1) when STAGE is unset, empty, or not in {staging, prod}.
# Lower-case only — `Staging`, `STAGING`, `production`, `prd`, `dev` all
# reject. There is NO default stage — see staging-prod-design.md §1.
#
# CDK_CTX is the `-c stage=...` flag every per-stage cdk invocation must
# carry. The Makefile is the only sanctioned entry point; running
# `cdk deploy` directly without `-c stage=...` triggers app.py's
# fail-closed guard.
# ----------------------------------------------------------------------------
CDK_CTX = -c stage=$(STAGE)

_require-stage:
	@if [ -z "$(STAGE)" ]; then \
		echo "$(RED)ERROR: STAGE is required. Usage: make <target> STAGE=staging|prod$(NC)" >&2; \
		exit 1; \
	fi
	@if [ "$(STAGE)" != "staging" ] && [ "$(STAGE)" != "prod" ]; then \
		echo "$(RED)ERROR: STAGE must be 'staging' or 'prod' (lower-case). Got: '$(STAGE)'$(NC)" >&2; \
		exit 1; \
	fi

# Default goal
.DEFAULT_GOAL := help

help: ## Show this help message
	@printf "$(GREEN)ADP Foundation — Deploy Commands$(NC)\n"
	@printf "\n"
	@printf "Usage: make [target] STAGE=staging|prod\n"
	@printf "\n"
	@printf "$(YELLOW)STAGE is REQUIRED for every per-stage target (synth, deploy,$(NC)\n"
	@printf "$(YELLOW)seed, smoke-test, teardown, verify-standalone). Lower-case only.$(NC)\n"
	@printf "$(YELLOW)'make bootstrap' is account-singular and does NOT take STAGE.$(NC)\n"
	@printf "\n"
	@printf "Stage-agnostic targets:\n"
	@printf "  venv               Create Python venv (.venv/) and install requirements\n"
	@printf "  install            Alias for venv\n"
	@printf "  bootstrap          Deploy adp-shared-bootstrap (account-singular Macie::Session)\n"
	@printf "  clean-cdk-out      Remove cdk.out/ and cdk.out.standalone/\n"
	@printf "  help               Show this help message\n"
	@printf "\n"
	@printf "Per-stage targets (require STAGE=staging|prod):\n"
	@printf "  synth              cdk synth all per-stage stacks\n"
	@printf "  deploy             Deploy per-stage stacks (~15-25 min)\n"
	@printf "  deploy-cms-ingest  Deploy + optional CMS->ADP ingest (requires CMS_TABLE_ARN)\n"
	@printf "  seed-dimensions    Generate the 7 dimensions to local filesystem\n"
	@printf "  seed               Run dimensions then all 9 product generators in dependency\n"
	@printf "                     order, then referential-integrity + drift tests. Idempotent.\n"
	@printf "                     PySpark generators run locally at sample scale; full Glue\n"
	@printf "                     runs deferred per decisions.md.\n"
	@printf "  smoke-test         Post-deploy DataZone subscription smoke test\n"
	@printf "  verify-standalone  Synth-time check: foundation has no CMS dependency by default\n"
	@printf "  teardown           Tear down per-stage stacks (default dry-run; YES=1 to destroy)\n"
	@printf "\n"
	@printf "Publish target (step 2+3 of the product publish flow):\n"
	@printf "  publish-product    Sync curated/<PRODUCT>/ to S3 and register the Glue table.\n"
	@printf "                     Requires PRODUCT= and STAGE=. Dry-run by default.\n"
	@printf "                     Pass APPLY=1 to execute; also pass ALLOW_PROD=1 for prod.\n"
	@printf "\n"
	@printf "Examples:\n"
	@printf "  make bootstrap                              # one-time, account-level\n"
	@printf "  make synth STAGE=staging\n"
	@printf "  make deploy STAGE=staging\n"
	@printf "  make smoke-test STAGE=staging\n"
	@printf "\n"
	@printf "Environment:\n"
	@printf "  AWS_REGION          = $(AWS_REGION)\n"
	@printf "  CDK_DEFAULT_ACCOUNT = $(CDK_DEFAULT_ACCOUNT)\n"
	@printf "  SEED                = $(SEED)\n"
	@printf "  STAGE               = $(if $(STAGE),$(STAGE),<unset>)\n"

# ----------------------------------------------------------------------------
# Environment setup (stage-agnostic)
# ----------------------------------------------------------------------------

venv: ## Create Python venv (.venv/) and install requirements.txt
	@echo "$(GREEN)Setting up venv ...$(NC)"
	@python3 -m venv .venv
	@./.venv/bin/pip install -q --upgrade pip
	@./.venv/bin/pip install -q -r requirements.txt
	@echo "$(GREEN)venv ready. Activate: source .venv/bin/activate$(NC)"

install: venv ## Alias for venv

# ----------------------------------------------------------------------------
# Bootstrap (account-singular — NO STAGE)
#
# Deploys ONLY the `adp-shared-bootstrap` stack (Macie::Session). Run once
# per account; per-stage stacks assume the bootstrap session is live.
# Per design §3 / §4 "Help-output update": this target MUST NOT take STAGE.
# ----------------------------------------------------------------------------

bootstrap: ## Deploy adp-shared-bootstrap (account-singular, no STAGE). CDK_EXTRA passes extra -c flags.
	@echo "$(GREEN)Deploying adp-shared-bootstrap (Macie::Session + Lake Formation SLR) ...$(NC)"
	@# `-c stage=staging` is a synth-time placeholder; SharedBootstrapStack
	@# is stage-agnostic (does not take a stage arg, does not carry the
	@# adp:stage tag) per design §3. Required because app.py validates
	@# stage upfront before instantiating any stack.
	@#
	@# CDK_EXTRA forwards additional context. The one that matters:
	@#   make bootstrap CDK_EXTRA="-c createLakeFormationSlr=false"
	@# in an account where Lake Formation was already in use before ADP --
	@# CloudFormation cannot create a service-linked role that already exists,
	@# and without the opt-out this target fails and rolls back the update.
	@# Run `docs/DEPLOYMENT.md` § "Bootstrap command" existence check first.
	@#
	@# This variable did not exist until 2026-09-20: DEPLOYMENT.md documented
	@# the opt-out as `CDK_EXTRA=...` while the Makefile ignored it, so the
	@# documented escape silently deployed the default. Review Cycle 8 W2.
	@$(AWS_ENV) .venv/bin/cdk deploy adp-shared-bootstrap -c stage=staging --require-approval never $(CDK_EXTRA)

# ----------------------------------------------------------------------------
# CDK (per-stage)
# ----------------------------------------------------------------------------

synth: _require-stage ## cdk synth all foundation stacks (requires STAGE)
	@echo "$(GREEN)Synthesizing all foundation stacks (stage=$(STAGE)) ...$(NC)"
	@$(AWS_ENV) .venv/bin/cdk synth --all $(CDK_CTX)

deploy: _require-stage ## Deploy all per-stage foundation stacks (requires STAGE)
	@echo "$(GREEN)Deploying ADP foundation stage=$(STAGE) to $(AWS_REGION) (account $(CDK_DEFAULT_ACCOUNT)) ...$(NC)"
	@$(AWS_ENV) .venv/bin/cdk deploy $(CDK_CTX) --require-approval never \
		--exclusively \
		adp-$(STAGE)-foundation-network \
		adp-$(STAGE)-foundation-lake \
		adp-$(STAGE)-foundation-datazone \
		adp-$(STAGE)-foundation-datazone-projects \
		adp-$(STAGE)-foundation-governance \
		adp-$(STAGE)-foundation-data-products \
		adp-$(STAGE)-foundation-parts-domain \
		adp-$(STAGE)-foundation-dealer-domain \
		adp-$(STAGE)-foundation-vehicle-knowledge-base
	@echo ""
	@echo "$(GREEN)Foundation deployed. Next:$(NC)"
	@echo "  make seed-dimensions STAGE=$(STAGE)   # generate dimension catalog"
	@echo "  make smoke-test STAGE=$(STAGE)        # post-deploy verification"

deploy-cms-ingest: _require-stage ## Deploy with optional CMS->ADP ingest module enabled (requires STAGE + CMS_TABLE_ARN)
	@if [ -z "$(CMS_TABLE_ARN)" ]; then \
		echo "$(RED)ERROR: CMS_TABLE_ARN not set. Example:$(NC)" >&2; \
		echo "  make deploy-cms-ingest STAGE=$(STAGE) CMS_TABLE_ARN=arn:aws:dynamodb:us-east-1:$(CDK_DEFAULT_ACCOUNT):table/cms-prod-vehicle-state" >&2; \
		exit 1; \
	fi
	@$(AWS_ENV) .venv/bin/cdk deploy --all $(CDK_CTX) --require-approval never \
		-c enable_cms_ingest=true \
		-c cms_vehicle_state_table_arn=$(CMS_TABLE_ARN)

clean-cdk-out: ## Remove cdk.out/ and cdk.out.standalone/
	@rm -rf cdk.out cdk.out.standalone cdk.out.cms-on

# ----------------------------------------------------------------------------
# Data (per-stage)
# ----------------------------------------------------------------------------

seed-dimensions: _require-stage ## Generate the 7 dimensions to local filesystem (requires STAGE)
	@echo "$(GREEN)Generating dimensions @ seed=$(SEED) (stage=$(STAGE)) ...$(NC)"
	@$(PY) source/dimensions/generate_all.py --seed $(SEED) --output-root $(SEED_DIM_ROOT)

seed-dimensions-dry: ## Dry-run dimension generation (1% scale, ~1 min) for fast iteration
	@$(PY) source/dimensions/generate_all.py --seed $(SEED) --dry-run --output-root /tmp/adp-dim-dry

# ----------------------------------------------------------------------------
# Master `seed` orchestration
#
# Phase 2 (Group 3 follow-up) — runs all 10 product generators after the
# dimension catalog. Order matches the spec's dependency layering: the
# six pandas products first (vehicle_identity → customer_360 → ...),
# then the two PySpark products (telemetry → energy_usage), then the
# knowledge-base artifacts. PySpark generators run LOCALLY at sample
# scale (~100K rows each) — full Glue runs are deferred per
# `decisions.md` "Group 3 scope: pandas-full, Spark-sample,
# KB-artifacts-only".
#
# Per Spec Constraint #5 ("zero orphan FKs across products") and the
# drift-detection design, two pytest suites run AFTER all 10 products
# land: referential-integrity (FK closure) + data-contracts (drift).
#
# Idempotent — every generator overwrites its `curated/<product>/`
# tree from the deterministic seed; re-running yields byte-identical
# output. Re-runs are safe.
# ----------------------------------------------------------------------------

seed-vehicle-identity: _require-stage seed-dimensions ## [1/10] Generate vehicle_identity (pandas)
	@echo "$(GREEN)[1/10] vehicle_identity (pandas, seed=$(SEED)) ...$(NC)"
	@$(PY) source/data-products/vehicle_identity/generator.py \
		--seed $(SEED) --dim-root $(SEED_DIM_ROOT) --output-root $(SEED_OUTPUT_ROOT)

seed-customer-360: _require-stage seed-vehicle-identity ## [2/10] Generate customer_360 (pandas)
	@echo "$(GREEN)[2/10] customer_360 (pandas, seed=$(SEED)) ...$(NC)"
	@$(PY) source/data-products/customer_360/generator.py \
		--seed $(SEED) --dim-root $(SEED_DIM_ROOT) --output-root $(SEED_OUTPUT_ROOT)

seed-charging-sessions: _require-stage seed-customer-360 ## [3/10] Generate charging_sessions (pandas)
	@echo "$(GREEN)[3/10] charging_sessions (pandas, seed=$(SEED)) ...$(NC)"
	@$(PY) source/data-products/charging_sessions/generator.py \
		--seed $(SEED) --dim-root $(SEED_DIM_ROOT) --output-root $(SEED_OUTPUT_ROOT)

seed-ota-campaigns: _require-stage seed-charging-sessions ## [4/10] Generate ota_campaigns (pandas, 2 tables)
	@echo "$(GREEN)[4/10] ota_campaigns (pandas, seed=$(SEED)) ...$(NC)"
	@$(PY) source/data-products/ota_campaigns/generator.py \
		--seed $(SEED) --dim-root $(SEED_DIM_ROOT) --output-root $(SEED_OUTPUT_ROOT)

seed-customer-interactions: _require-stage seed-ota-campaigns ## [5/10] Generate customer_interactions (pandas)
	@echo "$(GREEN)[5/10] customer_interactions (pandas, seed=$(SEED)) ...$(NC)"
	@$(PY) source/data-products/customer_interactions/generator.py \
		--seed $(SEED) --dim-root $(SEED_DIM_ROOT) --output-root $(SEED_OUTPUT_ROOT)

seed-service-records: _require-stage seed-customer-interactions ## [6/10] Generate service_records (pandas)
	@echo "$(GREEN)[6/10] service_records (pandas, seed=$(SEED)) ...$(NC)"
	@$(PY) source/data-products/service_records/generator.py \
		--seed $(SEED) --dim-root $(SEED_DIM_ROOT) --output-root $(SEED_OUTPUT_ROOT)

seed-tire-health: _require-stage seed-service-records ## [7/10] Generate tire_health (pandas, daily per-VIN per-tire)
	@echo "$(GREEN)[7/10] tire_health (pandas, seed=$(SEED), scale=$(TIRE_HEALTH_SCALE)) ...$(NC)"
	@$(PY) source/data-products/tire_health/generator.py \
		--seed $(SEED) --scale $(TIRE_HEALTH_SCALE) \
		--dim-root $(SEED_DIM_ROOT) --output-root $(SEED_OUTPUT_ROOT)

seed-vehicle-telemetry-aggregated: _require-stage seed-tire-health ## [8/10] Generate vehicle_telemetry_aggregated (PySpark, local sample)
	@echo "$(GREEN)[8/10] vehicle_telemetry_aggregated (PySpark local-sample, $(PYSPARK_LOCAL_ROWS) rows / $(PYSPARK_LOCAL_DAYS_TEL) days) ...$(NC)"
	@echo "$(YELLOW)  Local mode falls back to plain parquet (no Iceberg classpath); full Glue run deferred per decisions.md.$(NC)"
	@$(PY) source/data-products/vehicle_telemetry_aggregated/generator.py \
		--rows $(PYSPARK_LOCAL_ROWS) \
		--days $(PYSPARK_LOCAL_DAYS_TEL) \
		--partitions $(PYSPARK_LOCAL_PARTITIONS) \
		--seed $(SEED) \
		--vins-source $(SEED_DIM_ROOT)/vins/data.parquet \
		--output-root $(SEED_OUTPUT_ROOT)/vehicle_telemetry_aggregated

seed-energy-usage: _require-stage seed-vehicle-telemetry-aggregated ## [9/10] Generate energy_usage (PySpark, local sample)
	@echo "$(GREEN)[9/10] energy_usage (PySpark local-sample, $(PYSPARK_LOCAL_ROWS) rows / $(PYSPARK_LOCAL_DAYS_NRG) days) ...$(NC)"
	@echo "$(YELLOW)  Local mode falls back to plain parquet (no Iceberg classpath); full Glue run deferred per decisions.md.$(NC)"
	@$(PY) source/data-products/energy_usage/generator.py \
		--rows $(PYSPARK_LOCAL_ROWS) \
		--days $(PYSPARK_LOCAL_DAYS_NRG) \
		--partitions $(PYSPARK_LOCAL_PARTITIONS) \
		--seed $(SEED) \
		--vins-source $(SEED_DIM_ROOT)/vins/data.parquet \
		--output-root $(SEED_OUTPUT_ROOT)/energy_usage

seed-vehicle-knowledge-base: _require-stage seed-energy-usage ## [10/10] Generate vehicle_knowledge_base (text/markdown artifacts)
	@echo "$(GREEN)[10/10] vehicle_knowledge_base (text/markdown artifacts; Bedrock KB ingest deferred to Group 5) ...$(NC)"
	@$(PY) source/data-products/vehicle_knowledge_base/generator.py \
		--output-root $(SEED_OUTPUT_ROOT)/vehicle_knowledge_base \
		--region $(AWS_REGION)

seed-integrity: _require-stage seed-vehicle-knowledge-base ## Run referential-integrity + drift-detection tests against generated curated/
	@echo "$(GREEN)Running referential-integrity + drift-detection tests against $(SEED_OUTPUT_ROOT)/ ...$(NC)"
	@ADP_CURATED_ROOT=$(abspath $(SEED_OUTPUT_ROOT)) \
	 ADP_DIMENSION_ROOT=$(abspath $(SEED_DIM_ROOT)) \
	 .venv/bin/pytest \
		tests/test_referential_integrity.py \
		tests/test_data_contracts.py \
		-v

seed: _require-stage seed-integrity ## Master seed: dimensions, 10 products in dependency order, integrity + drift tests (requires STAGE)
	@echo "$(GREEN)Master seed complete (stage=$(STAGE), seed=$(SEED), curated=$(SEED_OUTPUT_ROOT)/).$(NC)"

# ----------------------------------------------------------------------------
# Publish (per-stage, per-product)
#
# Covers the two steps that have historically been manual:
#   Step 2: aws s3 sync local curated/<PRODUCT>/ -> s3://adp-<stage>-foundation-lake-…/
#   Step 3: Athena DDL to register the Glue table (column list derived from schema.yaml)
#
# Safety defaults (spec § D4, ~/.kiro/steering/non-interactive.md):
#   - Dry-run by default; pass APPLY=1 to execute
#   - prod requires APPLY=1 AND ALLOW_PROD=1
#   - Never --delete on sync
#   - Account ID resolved at runtime, never hardcoded
#
# Usage:
#   make publish-product PRODUCT=tire_health STAGE=staging            # dry-run
#   make publish-product PRODUCT=tire_health STAGE=staging APPLY=1    # apply
#   make publish-product PRODUCT=tire_health STAGE=prod APPLY=1 ALLOW_PROD=1
# ----------------------------------------------------------------------------

# PRODUCT, APPLY, ALLOW_PROD are optional at .PHONY level; validated inside the script.
PRODUCT     ?=
APPLY       ?=
ALLOW_PROD  ?=

publish-product: _require-stage ## Sync curated/<PRODUCT>/ to lake + register Glue table (dry-run default; APPLY=1 to execute)
	@if [ -z "$(PRODUCT)" ]; then \
		echo "$(RED)ERROR: PRODUCT is required. Usage: make publish-product PRODUCT=<name> STAGE=staging|prod$(NC)" >&2; \
		exit 1; \
	fi
	@$(PY) source/scripts/publish_product.py \
		--product $(PRODUCT) \
		--stage $(STAGE) \
		$(if $(APPLY),--apply,) \
		$(if $(ALLOW_PROD),--allow-prod,)

# ----------------------------------------------------------------------------
# Publish with purge — single-vintage only
#
# Mirrors publish-product but enables --allow-purge for single-vintage tables
# that have accumulated >1 partition on disk. ONLY applicable to tables
# declared provenance=single-vintage in schema.yaml. DO NOT use for
# cumulative-snapshot tables (customer_360) — those are always additive.
#
# Three-gate posture (spec 2026-08-31-adp-curated-vintage-provenance § D3):
#   Staging: APPLY=1 ALLOW_PURGE=1
#   Prod:    APPLY=1 ALLOW_PROD=1 ALLOW_PURGE=1
#
# Usage:
#   # Dry-run to preview what would be purged (NOTE: --allow-purge requires
#   # --apply at the CLI; use publish-product with --apply=0 for inspection):
#   make publish-product PRODUCT=service_records STAGE=staging
#
#   # Apply purge on staging:
#   make publish-product-with-purge PRODUCT=service_records STAGE=staging APPLY=1 ALLOW_PURGE=1
#
#   # Apply purge on prod (three gates required):
#   make publish-product-with-purge PRODUCT=service_records STAGE=prod APPLY=1 ALLOW_PROD=1 ALLOW_PURGE=1
# ----------------------------------------------------------------------------

ALLOW_PURGE ?=

publish-product-with-purge: _require-stage ## [single-vintage only] Sync + purge extra partitions via --delete; ALLOW_PURGE=1 required
	@if [ -z "$(PRODUCT)" ]; then \
		echo "$(RED)ERROR: PRODUCT is required. Usage: make publish-product-with-purge PRODUCT=<name> STAGE=staging|prod$(NC)" >&2; \
		exit 1; \
	fi
	@if [ -z "$(ALLOW_PURGE)" ]; then \
		echo "$(RED)ERROR: ALLOW_PURGE=1 is required for publish-product-with-purge.$(NC)" >&2; \
		echo "$(RED)       This target is for single-vintage tables only. It passes --delete to aws s3 sync.$(NC)" >&2; \
		echo "$(RED)       If you want additive sync (no delete), use: make publish-product PRODUCT=$(PRODUCT) STAGE=$(STAGE)$(NC)" >&2; \
		exit 1; \
	fi
	@$(PY) source/scripts/publish_product.py \
		--product $(PRODUCT) \
		--stage $(STAGE) \
		$(if $(APPLY),--apply,) \
		$(if $(ALLOW_PROD),--allow-prod,) \
		--allow-purge

# ----------------------------------------------------------------------------
# Verification (per-stage)
# ----------------------------------------------------------------------------

smoke-test: _require-stage ## Post-deploy DataZone subscription smoke test (requires STAGE)
	@./scripts/smoke-test-subscription.sh $(STAGE)

verify-standalone: _require-stage ## Synth-time check: foundation has no CMS dependency by default (requires STAGE)
	@./scripts/verify-standalone.sh $(STAGE)

verify: verify-standalone ## Run all verification scripts (requires STAGE)
	@.venv/bin/pytest tests/ -v

test: verify ## Alias for verify (requires STAGE)

# ----------------------------------------------------------------------------
# Tear-down (per-stage)
#
# Default behavior: dry-run (safe per ~/.kiro/steering/safety_guardrails).
# To actually destroy, set YES=1:
#   make teardown STAGE=staging          # dry-run — prints what WOULD be deleted
#   make teardown STAGE=staging YES=1    # actually destroy
#
# The script does NOT touch:
#   - adp-shared-bootstrap (account-singular Macie session — 30d cool-down)
#   - the OTHER stage's stacks
#   - the Lake KMS CMK (RetainOnDelete by design)
# ----------------------------------------------------------------------------

teardown: _require-stage ## Tear down per-stage foundation stacks (default dry-run; pass YES=1 to destroy)
	@./scripts/teardown.sh $(STAGE) $(if $(YES),--yes,--dry-run)
