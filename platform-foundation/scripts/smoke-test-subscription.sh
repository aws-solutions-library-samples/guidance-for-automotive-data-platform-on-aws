#!/usr/bin/env bash
# DataZone subscription end-to-end smoke test.
#
# Programmatically subscribes the data_consumer_test project to a
# published data product (SMOKE_PRODUCT, default vehicle_identity),
# waits for grant propagation, then executes a SELECT COUNT(*) Athena
# query as the consumer to confirm the subscription works end-to-end.
#
# Per ~/.kiro/steering/deploy-validation.md: this is the post-deploy
# smoke test for the DataZone subscription path. Deploy script MUST
# fail (exit non-zero) if this script fails.
#
# Usage:
#   ./smoke-test-subscription.sh <stage>
#   ./smoke-test-subscription.sh --stage <stage>
#
#   <stage> is REQUIRED — must be 'staging' or 'prod' (lower-case).
#   No silent default. Fails closed when the arg is missing/invalid.
#
# Pre-requisites:
# - adp-{stage}-foundation-datazone, adp-{stage}-foundation-datazone-projects,
#   adp-{stage}-foundation-lake stacks deployed and healthy
# - The probed product (SMOKE_PRODUCT, default vehicle_identity) has been
#   seeded and published, i.e. its Glue table is registered and non-empty.
#   Under the default SMOKE_REQUIRE_ROWS=1 a missing or empty table FAILS.
# - AWS credentials with datazone:* + athena:* scoped to this account
#
# Environment overrides:
#   SMOKE_PRODUCT       product to assert against (default: vehicle_identity)
#   SMOKE_REQUIRE_ROWS  1 = require a populated table (default); 0 = assert
#                       infrastructure reachability only, for an unseeded stage
#   SMOKE_REQUIRE_SUBSCRIPTION
#                       1 = the DataZone subscribe -> approve -> grant chain must
#                       actually run and reach APPROVED; 0 = tolerate a missing
#                       asset listing (default, because no product publishes one
#                       on either stage as of 2026-08-31)
#   ATHENA_WORKGROUP    default: primary
#
# SCOPE WARNING: despite the name, the subscription half of this script has
# never executed in a passing run — no product publishes a DataZone asset
# listing, so `search-listings` misses and it falls through to a direct Athena
# read. Every verdict line therefore states which halves were asserted; read it
# rather than assuming a PASS covers subscription. See
# issues/2026-08-31-adp-datazone-subscription-never-asserted/.
#
# History: this script probed vehicle_telemetry_aggregated unconditionally,
# which made it vacuous on prod — that product was never published there, so
# the run always took the table-absent branch and returned PASS. It reported
# the same green before and after ~152M rows were published on 2026-08-31.

set -euo pipefail

LOG_PREFIX="[smoke-subscription]"
log() { echo "$LOG_PREFIX $*" >&2; }
err() { echo "$LOG_PREFIX ERROR: $*" >&2; }

# ----- Stage gating (Fix Group A — staging-prod rollout) --------------------
# Accepts STAGE as $1 OR `--stage <value>`. Fails closed when missing or
# invalid. Lower-case only — `Staging`, `STAGING`, `production`, `prd`,
# `dev` all reject. There is NO default stage.
parse_stage() {
    if [ "$#" -eq 0 ]; then
        err "stage is required. Usage: $0 <staging|prod>"
        exit 1
    fi
    case "$1" in
        --stage)
            if [ "$#" -lt 2 ]; then
                err "--stage requires a value. Usage: $0 --stage <staging|prod>"
                exit 1
            fi
            echo "$2"
            ;;
        --stage=*)
            echo "${1#--stage=}"
            ;;
        *)
            echo "$1"
            ;;
    esac
}

if [ "$#" -eq 0 ]; then
    err "stage is required. Usage: $0 <staging|prod>"
    exit 1
fi
STAGE="$(parse_stage "$@")"
if [ -z "$STAGE" ]; then
    err "stage is required. Usage: $0 <staging|prod>"
    exit 1
fi
if [ "$STAGE" != "staging" ] && [ "$STAGE" != "prod" ]; then
    err "stage must be 'staging' or 'prod' (lower-case). Got: '$STAGE'"
    exit 1
fi
log "Stage: $STAGE"

# ----- Stage-prefixed identifiers -------------------------------------------
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="${ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text --no-cli-pager 2>/dev/null)}"

# Which data product this smoke test asserts against.
#
# Was hardcoded to vehicle_telemetry_aggregated, which made the gate VACUOUS on
# prod: that product has never been published there, so the run always took the
# "table not yet created -> PASS" branch and returned the identical verdict
# before and after ~152M rows landed on 2026-08-31. A gate that cannot
# distinguish those two states reads green while asserting nothing.
#
# Default is vehicle_identity because it is registered and populated on BOTH
# stages, and it is the one product whose row count matched its manifest
# exactly (5,000,000) — so it carries none of the cross-run vintage mixing
# described in issues/2026-08-31-adp-curated-cross-run-partition-accumulation.
#
# Override to probe a different product:
#   SMOKE_PRODUCT=charging_sessions ./smoke-test-subscription.sh prod
SMOKE_PRODUCT="${SMOKE_PRODUCT:-vehicle_identity}"

# Whether a missing table or a zero-row table is a FAILURE (default) or a
# tolerated deploy-gate pass. Strict by default: an empty lake should not
# report green. Set SMOKE_REQUIRE_ROWS=0 for a freshly-deployed stage whose
# seed has not run yet, where infrastructure reachability is all that can be
# asserted.
SMOKE_REQUIRE_ROWS="${SMOKE_REQUIRE_ROWS:-1}"

# Whether the DataZone subscribe -> approve -> grant chain must actually be
# exercised. Default 0, because as of 2026-08-31 **no product publishes a
# DataZone asset listing on either stage**, so `search-listings` returns nothing
# and the chain cannot run. That means roughly half of this script — the half it
# is named after — has never executed in a passing run, and a broken
# subscription path would not be detected.
#
# Kept opt-in rather than strict-by-default deliberately: with no listings
# anywhere, defaulting to 1 would turn both stages red for a *missing
# capability* rather than a regression, which is not what a deploy gate is for.
# Flip to 1 per-stage once asset listings are published — that is the point at
# which this becomes real coverage.
#
# See issues/2026-08-31-adp-datazone-subscription-never-asserted/.
SMOKE_REQUIRE_SUBSCRIPTION="${SMOKE_REQUIRE_SUBSCRIPTION:-0}"

# DataZone project exports use kebab-case; Glue databases use snake_case.
SMOKE_PRODUCT_KEBAB="$(echo "$SMOKE_PRODUCT" | tr '_' '-')"

DOMAIN_EXPORT="adp-${STAGE}-foundation-datazone-domain-id"
CONSUMER_PROJECT_EXPORT="adp-${STAGE}-foundation-datazone-project-data-consumer-test-id"
PRODUCER_PROJECT_EXPORT="adp-${STAGE}-foundation-datazone-project-${SMOKE_PRODUCT_KEBAB}-id"
ATHENA_WORKGROUP="${ATHENA_WORKGROUP:-primary}"
PRODUCT_DB="adp_${STAGE}_${SMOKE_PRODUCT}"
PRODUCT_TABLE="${SMOKE_PRODUCT}"

# Resolve a CFN exported value to its current value.
resolve_export() {
    local name="$1"
    aws cloudformation list-exports \
        --region "$REGION" \
        --query "Exports[?Name=='$name'].Value | [0]" \
        --output text \
        --no-cli-pager 2>/dev/null
}

# Athena query helper: returns query state.
athena_run() {
    local query="$1"
    local lake_bucket="${LAKE_BUCKET:-adp-${STAGE}-foundation-lake-${ACCOUNT_ID}-${REGION}}"
    local output_loc="s3://${lake_bucket}/athena-results/"
    local qid
    qid=$(aws athena start-query-execution \
        --query-string "$query" \
        --work-group "$ATHENA_WORKGROUP" \
        --result-configuration "OutputLocation=$output_loc" \
        --region "$REGION" \
        --query 'QueryExecutionId' \
        --output text \
        --no-cli-pager 2>/dev/null)
    log "  athena query id: $qid"
    # Poll until terminal
    for _ in $(seq 1 60); do
        local state
        state=$(aws athena get-query-execution \
            --query-execution-id "$qid" \
            --region "$REGION" \
            --query 'QueryExecution.Status.State' \
            --output text 2>/dev/null || echo "ERROR")
        case "$state" in
        SUCCEEDED) echo "$qid"; return 0 ;;
        FAILED|CANCELLED)
            local reason
            reason=$(aws athena get-query-execution \
                --query-execution-id "$qid" \
                --region "$REGION" \
                --query 'QueryExecution.Status.StateChangeReason' \
                --output text)
            err "athena query $qid $state: $reason"
            return 1
            ;;
        esac
        sleep 2
    done
    err "athena query $qid timed out"
    return 1
}

# Render what the subscription half actually proved, so a PASS verdict can never
# be misread as covering the subscribe -> approve -> grant chain. The script is
# named for that chain, so the verdict must say when it was not exercised.
subscription_scope() {
    case "${SUBSCRIPTION_RESULT:-SKIPPED_NO_LISTING}" in
        APPROVED)           echo "subscription=EXERCISED(APPROVED)" ;;
        NOT_APPROVED)       echo "subscription=RAN-BUT-NOT-APPROVED" ;;
        SKIPPED_NO_LISTING) echo "subscription=NOT-EXERCISED(no DataZone asset listing)" ;;
        *)                  echo "subscription=UNKNOWN" ;;
    esac
}

main() {
    log "Resolving stack outputs in $REGION (stage=$STAGE) ..."
    DOMAIN_ID=$(resolve_export "$DOMAIN_EXPORT")
    CONSUMER_PROJECT_ID=$(resolve_export "$CONSUMER_PROJECT_EXPORT")
    PRODUCER_PROJECT_ID=$(resolve_export "$PRODUCER_PROJECT_EXPORT")

    if [ -z "$DOMAIN_ID" ] || [ "$DOMAIN_ID" = "None" ]; then
        err "DataZone domain export '$DOMAIN_EXPORT' not found. Has the foundation stack deployed (stage=$STAGE)?"
        return 2
    fi
    if [ -z "$CONSUMER_PROJECT_ID" ] || [ "$CONSUMER_PROJECT_ID" = "None" ]; then
        err "Consumer project export '$CONSUMER_PROJECT_EXPORT' not found."
        return 2
    fi
    if [ -z "$PRODUCER_PROJECT_ID" ] || [ "$PRODUCER_PROJECT_ID" = "None" ]; then
        err "Producer project export '$PRODUCER_PROJECT_EXPORT' not found."
        return 2
    fi

    log "Domain: $DOMAIN_ID"
    log "Consumer project: $CONSUMER_PROJECT_ID"
    log "Producer project ($SMOKE_PRODUCT): $PRODUCER_PROJECT_ID"

    # Look up the asset that $SMOKE_PRODUCT has published in DataZone.
    #
    # SUBSCRIPTION_RESULT records what this half of the script actually proved,
    # so the final verdict can state its own scope instead of implying the
    # subscription chain was exercised when it was not:
    #   SKIPPED_NO_LISTING  no asset listing exists — the chain never ran
    #   APPROVED            request created, accepted, and observed APPROVED
    #   NOT_APPROVED        request created but never reached APPROVED
    SUBSCRIPTION_RESULT="SKIPPED_NO_LISTING"

    log "Looking up published $SMOKE_PRODUCT asset ..."
    ASSET_ID=$(aws datazone search-listings \
        --domain-identifier "$DOMAIN_ID" \
        --search-text "$SMOKE_PRODUCT" \
        --region "$REGION" \
        --query 'items[0].assetListing.entityId' \
        --output text 2>/dev/null || echo "")
    if [ -z "$ASSET_ID" ] || [ "$ASSET_ID" = "None" ]; then
        SUBSCRIPTION_RESULT="SKIPPED_NO_LISTING"
        if [ "$SMOKE_REQUIRE_SUBSCRIPTION" = "1" ]; then
            err "No published $SMOKE_PRODUCT asset listing in DataZone."
            err "SMOKE_REQUIRE_SUBSCRIPTION=1 requires the subscribe -> approve -> grant"
            err "chain to be exercised, and it cannot run without a listing."
            err "Publish the product as a DataZone asset, or set"
            err "SMOKE_REQUIRE_SUBSCRIPTION=0 to assert the data path only."
            return 1
        fi
        log "WARN: no published $SMOKE_PRODUCT asset in DataZone yet."
        log "      The subscribe -> approve -> grant chain is therefore NOT exercised."
        log "      Falling through to direct Athena read of the Glue table."
    else
        log "Asset: $ASSET_ID"
        # Create subscription request from consumer project to the asset.
        log "Creating subscription request ..."
        REQ_ID=$(aws datazone create-subscription-request \
            --domain-identifier "$DOMAIN_ID" \
            --request-reason "smoke test from data_consumer_test" \
            --subscribed-listings "{\"identifier\":\"$ASSET_ID\"}" \
            --subscribed-principals "{\"project\":{\"identifier\":\"$CONSUMER_PROJECT_ID\"}}" \
            --region "$REGION" \
            --query 'id' --output text)
        log "Subscription request: $REQ_ID — auto-approving (within-domain auto-grant)"
        aws datazone accept-subscription-request \
            --domain-identifier "$DOMAIN_ID" \
            --identifier "$REQ_ID" \
            --region "$REGION" >/dev/null
        # Wait for grant propagation.
        #
        # This loop previously fell through silently when APPROVED was never
        # reached, so a subscription that failed to grant produced the same
        # output as one that succeeded. Record the outcome instead.
        SUBSCRIPTION_RESULT="NOT_APPROVED"
        for _ in $(seq 1 30); do
            STATE=$(aws datazone get-subscription-request \
                --domain-identifier "$DOMAIN_ID" \
                --identifier "$REQ_ID" \
                --region "$REGION" \
                --query 'status' --output text 2>/dev/null || echo "PENDING")
            if [ "$STATE" = "APPROVED" ]; then
                log "  subscription APPROVED"
                SUBSCRIPTION_RESULT="APPROVED"
                break
            fi
            sleep 2
        done
        if [ "$SUBSCRIPTION_RESULT" != "APPROVED" ]; then
            if [ "$SMOKE_REQUIRE_SUBSCRIPTION" = "1" ]; then
                err "Subscription request $REQ_ID never reached APPROVED (last state: ${STATE:-unknown})."
                err "The grant did not propagate within 60s."
                return 1
            fi
            log "WARN: subscription request $REQ_ID never reached APPROVED (last state: ${STATE:-unknown})."
            log "      Not failing because SMOKE_REQUIRE_SUBSCRIPTION=0."
        fi
    fi

    # Direct Athena query as the deploy identity. In production CVX flows the
    # consumer would query as their own role; for smoke we use the deployer.
    #
    # Gate semantics (see SMOKE_REQUIRE_ROWS above):
    #   SMOKE_REQUIRE_ROWS=1 (default) — the table must exist AND return > 0
    #     rows. A missing or empty table FAILS. This is what makes the gate
    #     mean something.
    #   SMOKE_REQUIRE_ROWS=0 — infrastructure reachability only; a missing or
    #     empty table is tolerated. For a freshly-deployed, unseeded stage.
    log "Verifying Glue database $PRODUCT_DB exists ..."
    if ! aws glue get-database --name "$PRODUCT_DB" --region "$REGION" --no-cli-pager >/dev/null 2>&1; then
        err "Glue database $PRODUCT_DB does not exist — foundation lake stack may not have deployed (stage=$STAGE)."
        return 1
    fi
    log "  Glue database OK."

    # Probe whether the table exists yet.
    if aws glue get-table --database-name "$PRODUCT_DB" --name "$PRODUCT_TABLE" --region "$REGION" --no-cli-pager >/dev/null 2>&1; then
        log "Table $PRODUCT_DB.$PRODUCT_TABLE exists — running row-count smoke ..."
        QID=$(athena_run "SELECT COUNT(*) FROM $PRODUCT_DB.$PRODUCT_TABLE")
        ROWS=$(aws athena get-query-results \
            --query-execution-id "$QID" \
            --region "$REGION" \
            --query 'ResultSet.Rows[1].Data[0].VarCharValue' \
            --output text \
            --no-cli-pager)
        log "  COUNT(*) = $ROWS"
        if [ -z "$ROWS" ] || [ "$ROWS" = "None" ]; then
            err "Athena returned no rows result — query failed?"
            return 1
        fi
        if [ "$ROWS" -gt 0 ] 2>/dev/null; then
            log "Smoke test PASSED (stage=$STAGE | data=$SMOKE_PRODUCT populated, $ROWS rows | $(subscription_scope))."
            return 0
        fi
        # Table exists but is empty.
        if [ "$SMOKE_REQUIRE_ROWS" = "1" ]; then
            err "Table $PRODUCT_DB.$PRODUCT_TABLE exists but is EMPTY (0 rows)."
            err "The lake is not populated for $SMOKE_PRODUCT. Run 'make seed STAGE=$STAGE'"
            err "and 'make publish-product PRODUCT=$SMOKE_PRODUCT STAGE=$STAGE APPLY=1', or set"
            err "SMOKE_REQUIRE_ROWS=0 to assert infrastructure reachability only."
            return 1
        fi
        log "WARN: table is empty; SMOKE_REQUIRE_ROWS=0 so treating as deploy-gate PASS (stage=$STAGE | $(subscription_scope))."
        return 0
    else
        # Table absent. Under the default strict gate this is a failure: it is
        # exactly the state that silently read green on prod from July until
        # 2026-08-31, when prod turned out to have zero registered tables
        # across all 11 databases rather than merely zero rows.
        if [ "$SMOKE_REQUIRE_ROWS" = "1" ]; then
            err "Table $PRODUCT_DB.$PRODUCT_TABLE is NOT REGISTERED in the Glue catalog."
            err "The database exists but carries no table, so nothing is queryable."
            err "Run: make publish-product PRODUCT=$SMOKE_PRODUCT STAGE=$STAGE APPLY=1"
            err "(add ALLOW_PROD=1 for prod). If the publish already ran, check for a"
            err "Lake Formation CREATE_TABLE denial — see docs/DEPLOYMENT.md 'Lake Formation"
            err "permissions: new databases require grant-update'."
            err "Set SMOKE_REQUIRE_ROWS=0 to assert infrastructure reachability only."
            return 1
        fi
        log "Table $PRODUCT_DB.$PRODUCT_TABLE not yet created; SMOKE_REQUIRE_ROWS=0."
        log "Deploy-gate verification: Glue catalog reachable, DataZone domain healthy, projects exported (stage=$STAGE | data=NOT-ASSERTED, table absent | $(subscription_scope)). PASS."
        return 0
    fi
}

main
