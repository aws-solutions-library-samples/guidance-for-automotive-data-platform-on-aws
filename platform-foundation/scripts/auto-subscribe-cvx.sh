#!/usr/bin/env bash
# Auto-subscribe a CVX-side DataZone consumer project to the 5
# CVX-consumed ADP foundation data products.
#
# Per spec.md Group 5 "DataZone subscription automation": given a
# STAGE and a CVX-deploy-time project identifier (project ID, ARN,
# or display name), auto-creates a subscription request from the
# CVX consumer project to each product's published asset listing
# and auto-approves the request (within-domain auto-grant). After
# this script lands, CVX role(s) attached to the consumer project
# can query the products via Athena per `cvx-integration-contract.md`.
#
# Reference flow (canonical implementation):
#   `platform-foundation/scripts/smoke-test-subscription.sh` —
#   `search-listings` → `create-subscription-request` →
#   `accept-subscription-request`. This script generalizes that
#   flow across the 5 CVX-consumed products and adds dry-run +
#   idempotency.
#
# Products subscribed (per Group 5 spec):
#   1. vehicle_telemetry_aggregated
#   2. customer_360
#   3. charging_sessions
#   4. energy_usage
#   5. vehicle_knowledge_base
#
# Usage:
#   ./auto-subscribe-cvx.sh <stage> --cvx-project <id|arn|name> [--dry-run] [--region <region>]
#   ./auto-subscribe-cvx.sh --stage <stage> --cvx-project <id|arn|name> [--dry-run]
#
#   <stage> is REQUIRED — must be 'staging' or 'prod' (lower-case).
#   <cvx-project> is REQUIRED — accepts:
#       - DataZone project ID (e.g., 'cw3vq4ljr3kopz')
#       - DataZone project ARN (extracts the project ID after 'project/')
#       - DataZone project display name (resolved via list-projects)
#
# Dry-run mode (`--dry-run`):
#   Prints every API call (search-listings, list-subscriptions,
#   create-subscription-request, accept-subscription-request) with
#   placeholder identifiers for values that would normally be
#   resolved at runtime (DOMAIN_ID, CONSUMER_PROJECT_ID, ASSET_ID,
#   REQ_ID). Does NOT make any AWS API calls — safe to run without
#   credentials. Useful for review/audit and CI verification.
#
# Live mode (default):
#   Resolves the DataZone domain ID from CFN export
#   `adp-{stage}-foundation-datazone-domain-id`, resolves the CVX
#   consumer project, then per product:
#     - search-listings to find the published asset
#     - list-subscriptions to check if an APPROVED subscription
#       already exists (idempotent re-runs are safe)
#     - if absent: create-subscription-request +
#       accept-subscription-request (auto-approve)
#     - if asset not yet published (Group 3 generator hasn't run):
#       warn and continue
#
# Pre-requisites (live mode):
#   - adp-{stage}-foundation-* stacks deployed and healthy
#   - CVX consumer project exists in the foundation DataZone domain
#     and has a Project Member role attached
#   - AWS credentials with datazone:* scoped to this account
#
# Non-interactive — passes --no-cli-pager on every aws call. Exits
# non-zero on any hard failure (auth, missing domain, missing CVX
# project). Per-product warnings (asset not yet published) do NOT
# fail the script.

set -euo pipefail

LOG_PREFIX="[auto-subscribe-cvx]"
log() { echo "$LOG_PREFIX $*" >&2; }
warn() { echo "$LOG_PREFIX WARN: $*" >&2; }
err() { echo "$LOG_PREFIX ERROR: $*" >&2; }
ok()  { echo "$LOG_PREFIX OK: $*" >&2; }

# ---------------------------------------------------------------------------
# Constants — the 5 CVX-consumed products per Group 5 spec
# ---------------------------------------------------------------------------
CVX_PRODUCTS=(
    "vehicle_telemetry_aggregated"
    "customer_360"
    "charging_sessions"
    "energy_usage"
    "vehicle_knowledge_base"
)

# ---------------------------------------------------------------------------
# Argument parsing — accept positional STAGE and/or --stage flag,
# require --cvx-project, optional --dry-run / --region
# ---------------------------------------------------------------------------
STAGE=""
CVX_PROJECT=""
DRY_RUN="false"
REGION="${AWS_REGION:-us-east-1}"

usage() {
    cat <<EOF >&2
Usage:
  $(basename "$0") <staging|prod> --cvx-project <id|arn|name> [--dry-run] [--region <region>]
  $(basename "$0") --stage <staging|prod> --cvx-project <id|arn|name> [--dry-run]

Required:
  <stage>           positional, or --stage <value>: 'staging' or 'prod'
  --cvx-project     CVX consumer project: ID, ARN, or display name

Optional:
  --dry-run         print API calls without executing (no creds needed)
  --region          AWS region (default: \$AWS_REGION or us-east-1)
EOF
}

if [ "$#" -eq 0 ]; then
    err "stage is required."
    usage
    exit 1
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        --stage)
            if [ "$#" -lt 2 ]; then
                err "--stage requires a value."
                exit 1
            fi
            STAGE="$2"
            shift 2
            ;;
        --stage=*)
            STAGE="${1#--stage=}"
            shift
            ;;
        --cvx-project)
            if [ "$#" -lt 2 ]; then
                err "--cvx-project requires a value."
                exit 1
            fi
            CVX_PROJECT="$2"
            shift 2
            ;;
        --cvx-project=*)
            CVX_PROJECT="${1#--cvx-project=}"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --region)
            if [ "$#" -lt 2 ]; then
                err "--region requires a value."
                exit 1
            fi
            REGION="$2"
            shift 2
            ;;
        --region=*)
            REGION="${1#--region=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        -*)
            err "unknown flag: $1"
            usage
            exit 1
            ;;
        *)
            # First non-flag positional arg = stage. Subsequent positionals reject.
            if [ -z "$STAGE" ]; then
                STAGE="$1"
                shift
            else
                err "unexpected positional argument: $1"
                usage
                exit 1
            fi
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Validation — fail closed (matches Makefile / smoke-test contract)
# ---------------------------------------------------------------------------
if [ -z "$STAGE" ]; then
    err "stage is required. Usage: $(basename "$0") <staging|prod> --cvx-project <id|arn|name>"
    exit 1
fi
if [ "$STAGE" != "staging" ] && [ "$STAGE" != "prod" ]; then
    err "stage must be 'staging' or 'prod' (lower-case). Got: '$STAGE'"
    exit 1
fi
if [ -z "$CVX_PROJECT" ]; then
    err "--cvx-project is required (DataZone project ID, ARN, or display name)."
    exit 1
fi

log "Stage: $STAGE"
log "Region: $REGION"
log "CVX project (input): $CVX_PROJECT"
log "Dry-run: $DRY_RUN"
log "Products to subscribe: ${CVX_PRODUCTS[*]}"

# ---------------------------------------------------------------------------
# CVX project ID parsing — accept ID, ARN, or display name
# ---------------------------------------------------------------------------
# DataZone project ID is a 14-character alphanumeric string (e.g.,
# 'cw3vq4ljr3kopz'). ARN format:
#   arn:aws:datazone:<region>:<account>:domain/<domain-id>/project/<project-id>
# Display names are arbitrary strings (resolved via list-projects).

parse_cvx_project_kind() {
    local input="$1"
    # ARN form: contains 'arn:aws:datazone:' and '/project/'
    if [[ "$input" == arn:aws:datazone:*:*:domain/*/project/* ]]; then
        echo "arn"
        return
    fi
    # ID form: 12-16 character alphanumeric (DataZone project IDs are
    # currently 14 chars; range allows for slight format drift).
    if [[ "$input" =~ ^[a-z0-9]{12,16}$ ]]; then
        echo "id"
        return
    fi
    # Otherwise treat as display name.
    echo "name"
}

extract_project_id_from_arn() {
    # arn:aws:datazone:us-east-1:123456789012:domain/dzd-XXX/project/cw3vq4ljr3kopz
    #                                                              -^- after this
    echo "${1##*/project/}"
}

CVX_PROJECT_KIND="$(parse_cvx_project_kind "$CVX_PROJECT")"
log "CVX project input kind: $CVX_PROJECT_KIND"

# ---------------------------------------------------------------------------
# Stage-prefixed CFN export name for the foundation DataZone domain
# ---------------------------------------------------------------------------
DOMAIN_EXPORT="adp-${STAGE}-foundation-datazone-domain-id"

# ---------------------------------------------------------------------------
# Helpers — resolve_export and aws-call wrappers
# ---------------------------------------------------------------------------
resolve_export() {
    # Returns the current value of a CFN exported name, or empty if missing.
    local name="$1"
    aws cloudformation list-exports \
        --region "$REGION" \
        --query "Exports[?Name=='$name'].Value | [0]" \
        --output text \
        --no-cli-pager 2>/dev/null
}

resolve_project_id_by_name() {
    # Page through datazone list-projects, return the ID of the first
    # project whose `name` matches the given display name (case-sensitive).
    local domain_id="$1"
    local target_name="$2"
    aws datazone list-projects \
        --domain-identifier "$domain_id" \
        --region "$REGION" \
        --query "items[?name=='${target_name}'].id | [0]" \
        --output text \
        --no-cli-pager 2>/dev/null
}

# ---------------------------------------------------------------------------
# Resolve DOMAIN_ID and CONSUMER_PROJECT_ID
# ---------------------------------------------------------------------------
DOMAIN_ID=""
CONSUMER_PROJECT_ID=""

if [ "$DRY_RUN" = "true" ]; then
    # Dry-run uses placeholders so the script runs without credentials.
    DOMAIN_ID="<DOMAIN_ID_FOR_${STAGE}>"
    case "$CVX_PROJECT_KIND" in
        id)   CONSUMER_PROJECT_ID="$CVX_PROJECT" ;;
        arn)  CONSUMER_PROJECT_ID="$(extract_project_id_from_arn "$CVX_PROJECT")" ;;
        name) CONSUMER_PROJECT_ID="<CONSUMER_PROJECT_ID_FOR_${CVX_PROJECT}>" ;;
    esac
    log "[DRY-RUN] would resolve domain export: $DOMAIN_EXPORT"
    log "[DRY-RUN] domain id placeholder:        $DOMAIN_ID"
    log "[DRY-RUN] consumer project id:          $CONSUMER_PROJECT_ID"
else
    log "Resolving DataZone domain export '$DOMAIN_EXPORT' ..."
    DOMAIN_ID="$(resolve_export "$DOMAIN_EXPORT")"
    if [ -z "$DOMAIN_ID" ] || [ "$DOMAIN_ID" = "None" ]; then
        err "DataZone domain export '$DOMAIN_EXPORT' not found. Has the foundation deployed (stage=$STAGE)?"
        exit 2
    fi
    log "Domain: $DOMAIN_ID"

    case "$CVX_PROJECT_KIND" in
        id)
            CONSUMER_PROJECT_ID="$CVX_PROJECT"
            log "Using CVX project ID directly: $CONSUMER_PROJECT_ID"
            ;;
        arn)
            CONSUMER_PROJECT_ID="$(extract_project_id_from_arn "$CVX_PROJECT")"
            log "Extracted CVX project ID from ARN: $CONSUMER_PROJECT_ID"
            ;;
        name)
            log "Resolving CVX project by display name '$CVX_PROJECT' ..."
            CONSUMER_PROJECT_ID="$(resolve_project_id_by_name "$DOMAIN_ID" "$CVX_PROJECT")"
            if [ -z "$CONSUMER_PROJECT_ID" ] || [ "$CONSUMER_PROJECT_ID" = "None" ]; then
                err "CVX project '$CVX_PROJECT' not found in domain $DOMAIN_ID. Has CVX deployed and joined the foundation domain?"
                exit 2
            fi
            log "Resolved CVX project ID: $CONSUMER_PROJECT_ID"
            ;;
    esac

    # Sanity check — the resolved project ID must look like a DataZone ID.
    if ! [[ "$CONSUMER_PROJECT_ID" =~ ^[a-z0-9]{12,16}$ ]]; then
        err "Resolved CONSUMER_PROJECT_ID '$CONSUMER_PROJECT_ID' does not match expected DataZone project ID format."
        exit 2
    fi
fi

# ---------------------------------------------------------------------------
# Per-product subscribe — search-listings → check-existing →
# create-subscription-request → accept-subscription-request
# ---------------------------------------------------------------------------
SUCCESS_COUNT=0
SKIP_ALREADY_SUBSCRIBED=0
SKIP_NOT_PUBLISHED=0
FAIL_COUNT=0

print_create_subscription_call() {
    local product="$1"
    local domain_id="$2"
    local asset_id="$3"
    local consumer="$4"
    cat <<EOF
[DRY-RUN] aws datazone create-subscription-request \\
  --domain-identifier "$domain_id" \\
  --request-reason "CVX consumer auto-subscribe: $product" \\
  --subscribed-listings '[{"identifier":"'"$asset_id"'"}]' \\
  --subscribed-principals '[{"project":{"identifier":"'"$consumer"'"}}]' \\
  --region "$REGION" \\
  --no-cli-pager
EOF
}

print_accept_subscription_call() {
    local domain_id="$1"
    local req_id="$2"
    cat <<EOF
[DRY-RUN] aws datazone accept-subscription-request \\
  --domain-identifier "$domain_id" \\
  --identifier "$req_id" \\
  --region "$REGION" \\
  --no-cli-pager
EOF
}

print_search_listings_call() {
    local product="$1"
    local domain_id="$2"
    cat <<EOF
[DRY-RUN] aws datazone search-listings \\
  --domain-identifier "$domain_id" \\
  --search-text "$product" \\
  --region "$REGION" \\
  --no-cli-pager \\
  --query 'items[0].assetListing.entityId' \\
  --output text
EOF
}

print_list_subscriptions_call() {
    local domain_id="$1"
    local consumer="$2"
    local asset_id="$3"
    cat <<EOF
[DRY-RUN] aws datazone list-subscriptions \\
  --domain-identifier "$domain_id" \\
  --owning-project-id "$consumer" \\
  --subscribed-listing-id "$asset_id" \\
  --status APPROVED \\
  --region "$REGION" \\
  --no-cli-pager \\
  --query 'items[0].id' \\
  --output text
EOF
}

subscribe_product() {
    local product="$1"
    log "----- $product -----"

    # Resolve asset listing ID for this product.
    local asset_id=""
    if [ "$DRY_RUN" = "true" ]; then
        asset_id="<ASSET_ID_FOR_${product}>"
        print_search_listings_call "$product" "$DOMAIN_ID"
        log "[DRY-RUN] asset id placeholder: $asset_id"
    else
        asset_id=$(aws datazone search-listings \
            --domain-identifier "$DOMAIN_ID" \
            --search-text "$product" \
            --region "$REGION" \
            --query 'items[0].assetListing.entityId' \
            --output text \
            --no-cli-pager 2>/dev/null || echo "")
        if [ -z "$asset_id" ] || [ "$asset_id" = "None" ]; then
            warn "no published asset listing for '$product' yet — Group 3 generator may not have run for this product. Skipping."
            SKIP_NOT_PUBLISHED=$((SKIP_NOT_PUBLISHED + 1))
            return 0
        fi
        log "asset id: $asset_id"
    fi

    # Idempotency — check if an APPROVED subscription already exists for
    # this listing + consumer project.
    local existing=""
    if [ "$DRY_RUN" = "true" ]; then
        print_list_subscriptions_call "$DOMAIN_ID" "$CONSUMER_PROJECT_ID" "$asset_id"
        existing=""
    else
        existing=$(aws datazone list-subscriptions \
            --domain-identifier "$DOMAIN_ID" \
            --owning-project-id "$CONSUMER_PROJECT_ID" \
            --subscribed-listing-id "$asset_id" \
            --status APPROVED \
            --region "$REGION" \
            --query 'items[0].id' \
            --output text \
            --no-cli-pager 2>/dev/null || echo "")
        if [ -n "$existing" ] && [ "$existing" != "None" ]; then
            ok "subscription already APPROVED for '$product' (subscription id: $existing) — skip."
            SKIP_ALREADY_SUBSCRIBED=$((SKIP_ALREADY_SUBSCRIBED + 1))
            return 0
        fi
    fi

    # Create subscription request.
    local req_id=""
    if [ "$DRY_RUN" = "true" ]; then
        print_create_subscription_call "$product" "$DOMAIN_ID" "$asset_id" "$CONSUMER_PROJECT_ID"
        req_id="<REQ_ID_FOR_${product}>"
        log "[DRY-RUN] req id placeholder: $req_id"
    else
        req_id=$(aws datazone create-subscription-request \
            --domain-identifier "$DOMAIN_ID" \
            --request-reason "CVX consumer auto-subscribe: $product" \
            --subscribed-listings "[{\"identifier\":\"$asset_id\"}]" \
            --subscribed-principals "[{\"project\":{\"identifier\":\"$CONSUMER_PROJECT_ID\"}}]" \
            --region "$REGION" \
            --query 'id' \
            --output text \
            --no-cli-pager 2>/dev/null || echo "")
        if [ -z "$req_id" ] || [ "$req_id" = "None" ]; then
            err "create-subscription-request failed for '$product'."
            FAIL_COUNT=$((FAIL_COUNT + 1))
            return 1
        fi
        log "subscription request created: $req_id"
    fi

    # Accept (auto-approve) the subscription request.
    if [ "$DRY_RUN" = "true" ]; then
        print_accept_subscription_call "$DOMAIN_ID" "$req_id"
    else
        aws datazone accept-subscription-request \
            --domain-identifier "$DOMAIN_ID" \
            --identifier "$req_id" \
            --region "$REGION" \
            --no-cli-pager >/dev/null 2>&1 || {
            err "accept-subscription-request failed for '$product' (request id: $req_id)."
            FAIL_COUNT=$((FAIL_COUNT + 1))
            return 1
        }
        # Wait for grant propagation.
        local approved="false"
        for _ in $(seq 1 30); do
            local state
            state=$(aws datazone get-subscription-request \
                --domain-identifier "$DOMAIN_ID" \
                --identifier "$req_id" \
                --region "$REGION" \
                --query 'status' --output text \
                --no-cli-pager 2>/dev/null || echo "PENDING")
            if [ "$state" = "APPROVED" ]; then
                approved="true"
                break
            fi
            sleep 2
        done
        if [ "$approved" = "true" ]; then
            ok "subscription APPROVED for '$product' (request id: $req_id)."
        else
            warn "subscription request '$req_id' for '$product' did not reach APPROVED within 60s. Check the DataZone portal."
        fi
    fi

    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    return 0
}

# ---------------------------------------------------------------------------
# Run the per-product loop
# ---------------------------------------------------------------------------
log ""
log "Subscribing CVX consumer project ($CONSUMER_PROJECT_ID) to ${#CVX_PRODUCTS[@]} products ..."
log ""

for product in "${CVX_PRODUCTS[@]}"; do
    # Per-product failures are accumulated; we don't abort on first failure
    # so the operator gets a complete picture of what worked / what didn't.
    subscribe_product "$product" || true
done

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log ""
log "===== Summary ====="
log "Success (newly subscribed): $SUCCESS_COUNT"
log "Skipped (already APPROVED): $SKIP_ALREADY_SUBSCRIBED"
log "Skipped (asset not published): $SKIP_NOT_PUBLISHED"
log "Failed: $FAIL_COUNT"

if [ "$DRY_RUN" = "true" ]; then
    log ""
    log "Dry-run complete — no AWS API calls were executed."
    log "Re-run without --dry-run against staging or prod to apply the subscriptions."
    exit 0
fi

if [ "$FAIL_COUNT" -gt 0 ]; then
    err "$FAIL_COUNT product subscription(s) failed. See per-product errors above."
    exit 1
fi

ok "Auto-subscribe complete (stage=$STAGE)."
exit 0
