#!/usr/bin/env bash
# ADP foundation per-stage teardown.
#
# Tears down a single stage's foundation cleanly, in the order proven by
# the migration runbook in `docs/DEPLOYMENT.md` ("Stage-side teardown" +
# "Migration from `adp-foundation-*` to `adp-staging-foundation-*`"
# steps 3, 4, 5, 7):
#
#   1. Inventory + summary (always shown — even in --yes mode)
#   2. Stop CloudTrail trail (graceful; avoids logs into a soon-to-be-
#      deleted bucket)
#   3. Empty the 3 S3 buckets (lake, lake-logs, trail-logs) — current
#      objects, every version, and every delete marker. Versioned buckets
#      cannot be CDK-destroyed otherwise.
#   4. Delete the DataZone domain via
#      `aws datazone delete-domain --skip-deletion-check`. This cascades
#      project + project-profile delete and side-steps the
#      `RemovalPolicy.RETAIN` block on `CfnProject` resources documented
#      in `decisions.md` 2026-05-29 (A6 in-flight issue #2).
#   5. `cdk destroy --force -c stage=<stage>` on the 5 stage stacks (and
#      the optional cms-ingest stack if it exists).
#   6. Idempotent IDC group cleanup (fallback per
#      `docs/DEPLOYMENT.md` "Stage-side teardown" — some CDK versions do
#      not honor RemovalPolicy.DESTROY on CfnGroup).
#   7. Verify no `adp-{stage}-foundation-*` stacks remain;
#      `adp-shared-bootstrap` is untouched.
#
# DOES NOT TOUCH
# --------------
#   - `adp-shared-bootstrap` (account-singular Macie::Session — Macie has
#     a 30-day session-deletion cool-down; tearing it down is rarely the
#     right move).
#   - The OTHER stage's stacks.
#   - The Lake KMS CMK (`alias/adp-{stage}-foundation-lake`,
#     `alias/adp-{stage}-foundation-trail`) — `RemovalPolicy.RETAIN` by
#     design (encrypted data may outlive the stack).
#   - Pre-existing unprefixed `adp-foundation-*` stacks (those are owned
#     by the migration runbook, not by per-stage teardown).
#
# SAFETY MODEL
# ------------
# Per `~/.kiro/steering/safety_guardrails`, this script defaults to
# **dry-run** — every destructive AWS API call prints `DRY-RUN: ...` and
# does NOT execute. Pass `--yes` to actually destroy. The inventory +
# summary block runs in BOTH modes so the operator sees what would happen
# before they commit.
#
# USAGE
# -----
#   ./teardown.sh <staging|prod> [--dry-run | --yes] [--region <r>]
#   ./teardown.sh --stage <staging|prod> [--dry-run | --yes]
#
# Examples:
#   ./teardown.sh staging                 # dry-run (default)
#   ./teardown.sh staging --dry-run       # explicit dry-run
#   ./teardown.sh staging --yes           # actually destroy
#   ./teardown.sh --stage prod --yes      # actually destroy prod
#
# Exit codes:
#   0 — success (dry-run or actual teardown)
#   1 — bad args / unknown stage
#   2 — environment problem (.venv / cdk / aws not found)
#   3 — verify step found stacks still present after destroy
#   4 — cdk destroy failed (operator must investigate)

set -euo pipefail

LOG_PREFIX="[teardown]"
log()  { echo "$LOG_PREFIX $*" >&2; }
warn() { echo "$LOG_PREFIX WARN: $*" >&2; }
err()  { echo "$LOG_PREFIX ERROR: $*" >&2; }

# ---------------------------------------------------------------------------
# Arg parsing — fail-closed stage gate matching the rest of the foundation.
# ---------------------------------------------------------------------------
STAGE=""
MODE="dry-run"
REGION="${AWS_REGION:-us-east-1}"

usage() {
    cat <<EOF >&2
Usage:
  $(basename "$0") <staging|prod> [--dry-run | --yes] [--region <region>]
  $(basename "$0") --stage <staging|prod> [--dry-run | --yes]

Required:
  <stage>           positional, or --stage <value>: 'staging' or 'prod'

Optional:
  --dry-run         (default) print destructive actions WITHOUT executing
  --yes             actually destroy. Required for any AWS state change.
  --region          AWS region (default: \$AWS_REGION or us-east-1)

Notes:
  * Defaults to dry-run per safety_guardrails. A live tear-down requires
    explicitly passing --yes.
  * Does NOT touch adp-shared-bootstrap, the OTHER stage's stacks, or
    the Lake KMS CMK (RemovalPolicy.RETAIN by design).
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
            if [ "$#" -lt 2 ]; then err "--stage requires a value."; exit 1; fi
            STAGE="$2"; shift 2
            ;;
        --stage=*)
            STAGE="${1#--stage=}"; shift
            ;;
        --dry-run)
            MODE="dry-run"; shift
            ;;
        --yes)
            MODE="execute"; shift
            ;;
        --region)
            if [ "$#" -lt 2 ]; then err "--region requires a value."; exit 1; fi
            REGION="$2"; shift 2
            ;;
        --region=*)
            REGION="${1#--region=}"; shift
            ;;
        -h|--help)
            usage; exit 0
            ;;
        -*)
            err "unknown flag: $1"; usage; exit 1
            ;;
        *)
            if [ -n "$STAGE" ]; then
                err "unexpected positional arg: $1 (stage already set to '$STAGE')"
                usage
                exit 1
            fi
            STAGE="$1"; shift
            ;;
    esac
done

if [ -z "$STAGE" ]; then
    err "stage is required. Usage: $(basename "$0") <staging|prod>"
    exit 1
fi
if [ "$STAGE" != "staging" ] && [ "$STAGE" != "prod" ]; then
    err "stage must be 'staging' or 'prod' (lower-case). Got: '$STAGE'"
    exit 1
fi

# ---------------------------------------------------------------------------
# Resolve identifiers.
# ---------------------------------------------------------------------------
ACCOUNT="${CDK_DEFAULT_ACCOUNT:-}"
if [ -z "$ACCOUNT" ]; then
    ACCOUNT="$(aws sts get-caller-identity --query Account --output text --no-cli-pager 2>/dev/null || echo '')"
fi
if [ -z "$ACCOUNT" ]; then
    err "Could not resolve AWS account. Configure credentials and retry."
    exit 2
fi

LAKE_BUCKET="adp-${STAGE}-foundation-lake-${ACCOUNT}-${REGION}"
LAKE_LOGS_BUCKET="adp-${STAGE}-foundation-lake-logs-${ACCOUNT}-${REGION}"
TRAIL_LOGS_BUCKET="adp-${STAGE}-foundation-trail-logs-${ACCOUNT}-${REGION}"
BUCKETS=("$LAKE_BUCKET" "$LAKE_LOGS_BUCKET" "$TRAIL_LOGS_BUCKET")

TRAIL_NAME="adp-${STAGE}-foundation-lake-trail"

CMS_INGEST_STACK="adp-${STAGE}-foundation-cms-ingest"
GOVERNANCE_STACK="adp-${STAGE}-foundation-governance"
DATAZONE_PROJECTS_STACK="adp-${STAGE}-foundation-datazone-projects"
DATAZONE_STACK="adp-${STAGE}-foundation-datazone"
LAKE_STACK="adp-${STAGE}-foundation-lake"
NETWORK_STACK="adp-${STAGE}-foundation-network"

# Reverse-deploy order. cdk destroy resolves dependencies, but listing
# in dependency-reverse order keeps log output legible for operators.
ORDERED_STACKS=(
    "$CMS_INGEST_STACK"
    "$GOVERNANCE_STACK"
    "$DATAZONE_PROJECTS_STACK"
    "$DATAZONE_STACK"
    "$LAKE_STACK"
    "$NETWORK_STACK"
)

IDC_GROUPS=(
    "adp-${STAGE}-data-owners"
    "adp-${STAGE}-data-consumers"
    "adp-${STAGE}-platform-admins"
)
# IDC store id used by the IDC-group cleanup step. The default is a
# placeholder per `governance_stack.py:_DEFAULT_IDENTITY_STORE_ID`;
# operators MUST supply a real value via the `IDC_STORE_ID` env var,
# e.g.:
#     IDC_STORE_ID=d-XXXXXXXXXX ./teardown.sh staging --yes
IDC_STORE_ID="${IDC_STORE_ID:-d-XXXXXXXXXX}"

DOMAIN_EXPORT="adp-${STAGE}-foundation-datazone-domain-id"
DOMAIN_NAME="adp-${STAGE}-foundation-domain"

# Project root (platform-foundation/)
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CDK_BIN="$PROJECT_DIR/.venv/bin/cdk"

# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------

# `run` executes the given command in --yes mode and prints what would
# have run in --dry-run mode. Use this for any destructive AWS API call
# that does not need its output captured.
run() {
    if [ "$MODE" = "execute" ]; then
        log "RUN: $*"
        "$@"
    else
        log "DRY-RUN: $*"
    fi
}

# Returns 0 if the stack exists in CFN (any non-deleted status), 1 otherwise.
stack_exists() {
    local name="$1"
    local status
    status=$(aws cloudformation describe-stacks \
        --stack-name "$name" --region "$REGION" --no-cli-pager \
        --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "MISSING")
    case "$status" in
        MISSING|DELETE_COMPLETE|"") return 1 ;;
        *) return 0 ;;
    esac
}

# Returns 0 if bucket exists + caller has access, 1 otherwise.
# Redirect stdout AND stderr — head-bucket emits a JSON body on stdout
# in AWS CLI v2 even on success; we only care about the exit code.
bucket_exists() {
    aws s3api head-bucket --bucket "$1" --region "$REGION" --no-cli-pager >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# Pre-flight checks.
# ---------------------------------------------------------------------------
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    err ".venv not found at $PROJECT_DIR/.venv. Run 'make venv' first."
    exit 2
fi
if [ ! -x "$CDK_BIN" ]; then
    err "cdk binary not found at $CDK_BIN. Re-run 'make venv'."
    exit 2
fi
if ! command -v aws >/dev/null 2>&1; then
    err "aws CLI not on PATH."
    exit 2
fi
if ! command -v jq >/dev/null 2>&1; then
    err "jq not on PATH (needed to drop S3 object versions + delete markers)."
    exit 2
fi

# ---------------------------------------------------------------------------
# Inventory + summary banner (always shown).
# ---------------------------------------------------------------------------
log ""
log "================================================================"
log "  ADP foundation tear-down inventory"
log "================================================================"
log "  Stage:    $STAGE"
log "  Mode:     $MODE  $( [ "$MODE" = "dry-run" ] && echo "(no AWS state changes)" || echo "(DESTRUCTIVE — real deletes)" )"
log "  Account:  $ACCOUNT"
log "  Region:   $REGION"
log ""
log "  S3 buckets to empty + delete (current + versions + delete markers):"
for b in "${BUCKETS[@]}"; do
    if bucket_exists "$b"; then
        log "    [present] s3://$b"
    else
        log "    [absent ] s3://$b"
    fi
done
log ""
log "  CloudTrail trail to stop (then destroyed by stack delete):"
log "    $TRAIL_NAME"
log ""
log "  CloudFormation stacks to destroy (reverse-deploy order):"
for s in "${ORDERED_STACKS[@]}"; do
    if stack_exists "$s"; then
        log "    [present] $s"
    else
        log "    [absent ] $s"
    fi
done
log ""
log "  IDC groups to clean up (idempotent fallback):"
for g in "${IDC_GROUPS[@]}"; do
    log "    $g"
done
log ""
log "  NOT touched:"
log "    - adp-shared-bootstrap (account-singular Macie::Session — 30d cool-down)"
log "    - the OTHER stage's adp-*-foundation-* stacks"
log "    - alias/adp-${STAGE}-foundation-lake / -trail KMS CMKs (RetainOnDelete by design)"
log "================================================================"
log ""

if [ "$MODE" = "dry-run" ]; then
    log ">>> DRY-RUN MODE — no AWS state changes will be made <<<"
    log ">>> To actually destroy, re-run with --yes:"
    log ">>>     $(basename "$0") $STAGE --yes"
    log ""
else
    log ">>> --yes — destroying resources NOW <<<"
    log ""
fi

# ---------------------------------------------------------------------------
# Step 1/6 — Stop CloudTrail trail (graceful).
# ---------------------------------------------------------------------------
log "Step 1/6 — stop CloudTrail trail (graceful, avoids logs into soon-to-be-deleted bucket)"
TRAIL_FOUND=$(aws cloudtrail describe-trails \
    --trail-name-list "$TRAIL_NAME" \
    --region "$REGION" --no-cli-pager \
    --query "trailList[?Name=='$TRAIL_NAME'].Name" \
    --output text 2>/dev/null \
    | tr '\t' '\n' | grep -v '^None$' | grep -v '^$' | head -1 \
    || true)
if [ -n "$TRAIL_FOUND" ]; then
    run aws cloudtrail stop-logging --name "$TRAIL_NAME" --region "$REGION" --no-cli-pager
else
    log "  (trail $TRAIL_NAME not found — skip; idempotent)"
fi

# ---------------------------------------------------------------------------
# Step 2/6 — Empty S3 buckets.
#
# CDK destroy fails on non-empty versioned buckets. We must drop:
#   (a) current objects
#   (b) every version
#   (c) every delete marker
# All three are fatal to `cdk destroy` if left behind.
# ---------------------------------------------------------------------------
log ""
log "Step 2/6 — empty + drop versions/delete-markers on 3 S3 buckets"
for b in "${BUCKETS[@]}"; do
    if ! bucket_exists "$b"; then
        log "  (bucket s3://$b not found — skip; idempotent)"
        continue
    fi

    log "  Processing s3://$b"
    # (a) current objects
    run aws s3 rm "s3://$b" --recursive --region "$REGION" --no-cli-pager

    # (b) versions
    if [ "$MODE" = "execute" ]; then
        VERSIONS_FILE=$(mktemp -t adp-tearown-versions.XXXXXX)
        # `|| true` so an empty bucket (no Versions[]) doesn't trip pipefail.
        aws s3api list-object-versions \
            --bucket "$b" --region "$REGION" --no-cli-pager \
            --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
            --output json > "$VERSIONS_FILE" 2>/dev/null \
            || echo '{"Objects":[]}' > "$VERSIONS_FILE"
        N_VER=$(jq '.Objects // [] | length' "$VERSIONS_FILE")
        if [ "${N_VER:-0}" -gt 0 ]; then
            log "    Dropping $N_VER object versions ..."
            aws s3api delete-objects \
                --bucket "$b" --region "$REGION" --no-cli-pager \
                --delete "file://$VERSIONS_FILE" >/dev/null
        fi
        rm -f "$VERSIONS_FILE"

        # (c) delete markers
        DM_FILE=$(mktemp -t adp-teardown-deletemarkers.XXXXXX)
        aws s3api list-object-versions \
            --bucket "$b" --region "$REGION" --no-cli-pager \
            --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' \
            --output json > "$DM_FILE" 2>/dev/null \
            || echo '{"Objects":[]}' > "$DM_FILE"
        N_DM=$(jq '.Objects // [] | length' "$DM_FILE")
        if [ "${N_DM:-0}" -gt 0 ]; then
            log "    Dropping $N_DM delete markers ..."
            aws s3api delete-objects \
                --bucket "$b" --region "$REGION" --no-cli-pager \
                --delete "file://$DM_FILE" >/dev/null
        fi
        rm -f "$DM_FILE"
    else
        log "    DRY-RUN: aws s3api list-object-versions --bucket $b ... | aws s3api delete-objects (versions + delete markers)"
    fi
done

# ---------------------------------------------------------------------------
# Step 3/6 — Pre-empt the DataZone domain delete via --skip-deletion-check.
#
# Per `decisions.md` 2026-05-29 (A6 in-flight issue #2): `cdk destroy` of
# the datazone stack is blocked by `RemovalPolicy.RETAIN` on the 10
# `CfnProject` resources. The proven workaround is
#   aws datazone delete-domain --skip-deletion-check
# which cascade-deletes projects, the project profile, and the domain in
# a single call. We run this BEFORE `cdk destroy` so the subsequent stack
# delete becomes a clean no-op on the underlying domain.
# ---------------------------------------------------------------------------
log ""
log "Step 3/6 — pre-empt DataZone domain delete (--skip-deletion-check)"
DOMAIN_ID=""
if stack_exists "$DATAZONE_STACK"; then
    # Prefer the CFN export; fall back to a list-domains scan by name.
    # `--query "... | [0]"` with `--output text` and a paginated response
    # emits `value\nNone\n` (one line per page) — strip "None" tokens
    # and take the first remaining line.
    DOMAIN_ID=$(aws cloudformation list-exports \
        --region "$REGION" --no-cli-pager \
        --query "Exports[?Name=='$DOMAIN_EXPORT'].Value" \
        --output text 2>/dev/null \
        | tr '\t' '\n' | grep -v '^None$' | grep -v '^$' | head -1 \
        || true)
    if [ -z "$DOMAIN_ID" ]; then
        DOMAIN_ID=$(aws datazone list-domains \
            --region "$REGION" --no-cli-pager \
            --query "items[?name=='$DOMAIN_NAME'].id" \
            --output text 2>/dev/null \
            | tr '\t' '\n' | grep -v '^None$' | grep -v '^$' | head -1 \
            || true)
    fi
fi

if [ -n "$DOMAIN_ID" ]; then
    log "  Found DataZone domain: $DOMAIN_ID ($DOMAIN_NAME)"
    run aws datazone delete-domain \
        --identifier "$DOMAIN_ID" \
        --skip-deletion-check \
        --region "$REGION" --no-cli-pager
    if [ "$MODE" = "execute" ]; then
        # delete-domain returns immediately and the domain enters DELETING.
        # cdk destroy on the datazone stack will move forward once CFN sees
        # the resource gone. We do not poll here — cdk destroy + the
        # verify step at the end cover the latency.
        log "  (DataZone domain delete is async; cdk destroy waits on the resource)"
    fi
else
    log "  (no DataZone domain found for stage=$STAGE — skip; idempotent)"
fi

# ---------------------------------------------------------------------------
# Step 4/6 — cdk destroy --force -c stage=<stage> (5 stage stacks + optional
# cms-ingest if it exists). Explicit stack list — NEVER --all, because
# --all would also walk into adp-shared-bootstrap.
#
# If the optional cms-ingest stack exists in CFN, app.py needs both
# `enable_cms_ingest=true` and `cms_vehicle_state_table_arn=<non-empty>`
# at synth time. The ARN value is irrelevant for destroy — we only need
# app.py to construct the stack object so cdk can match it to the
# deployed CFN stack and issue the delete.
# ---------------------------------------------------------------------------
log ""
log "Step 4/6 — cdk destroy --force -c stage=$STAGE (explicit stack list — bootstrap is NOT in scope)"

DESTROY_LIST=()
if stack_exists "$CMS_INGEST_STACK"; then
    log "  Optional cms-ingest stack present — including in destroy with placeholder context"
    DESTROY_LIST+=("$CMS_INGEST_STACK")
    CMS_INGEST_CTX=(
        -c "enable_cms_ingest=true"
        -c "cms_vehicle_state_table_arn=arn:aws:dynamodb:${REGION}:${ACCOUNT}:table/cms-teardown-placeholder"
    )
else
    CMS_INGEST_CTX=()
fi
DESTROY_LIST+=(
    "$GOVERNANCE_STACK"
    "$DATAZONE_PROJECTS_STACK"
    "$DATAZONE_STACK"
    "$LAKE_STACK"
    "$NETWORK_STACK"
)

if [ "$MODE" = "execute" ]; then
    log "  RUN: $CDK_BIN destroy --force -c stage=$STAGE ${CMS_INGEST_CTX[*]:-} ${DESTROY_LIST[*]}"
    (
        cd "$PROJECT_DIR"
        AWS_REGION="$REGION" \
        AWS_DEFAULT_REGION="$REGION" \
        CDK_DEFAULT_ACCOUNT="$ACCOUNT" \
        CDK_DEFAULT_REGION="$REGION" \
            "$CDK_BIN" destroy --force \
                -c "stage=$STAGE" \
                "${CMS_INGEST_CTX[@]}" \
                "${DESTROY_LIST[@]}"
    ) || {
        err "cdk destroy failed. Operator action required:"
        err "  - Inspect: aws cloudformation describe-stack-events --stack-name <stack> --region $REGION"
        err "  - Common cause: DataZone projects with RemovalPolicy.RETAIN block the domain delete."
        err "    Workaround: aws datazone delete-domain --identifier <domain-id> --skip-deletion-check --region $REGION"
        err "    (this script attempts that pre-emptively in step 3, but a stale list-exports cache can miss it)"
        exit 4
    }
else
    log "  DRY-RUN: $CDK_BIN destroy --force -c stage=$STAGE ${CMS_INGEST_CTX[*]:-} ${DESTROY_LIST[*]}"
fi

# ---------------------------------------------------------------------------
# Step 5/6 — Idempotent IDC group cleanup.
#
# Some CDK / CloudFormation versions don't honor RemovalPolicy.DESTROY on
# CfnGroup, leaving stage-prefixed IDC groups behind after destroy. The
# DEPLOYMENT.md "Stage-side teardown — IDC group cleanup (manual fallback)"
# section codifies the cleanup; we automate it here.
# ---------------------------------------------------------------------------
log ""
log "Step 5/6 — IDC group cleanup (idempotent fallback)"
for g in "${IDC_GROUPS[@]}"; do
    GID=$(aws identitystore list-groups \
        --identity-store-id "$IDC_STORE_ID" \
        --region "$REGION" --no-cli-pager \
        --filters "[{\"AttributePath\":\"DisplayName\",\"AttributeValue\":\"$g\"}]" \
        --query 'Groups[0].GroupId' --output text 2>/dev/null || echo "None")
    if [ -n "$GID" ] && [ "$GID" != "None" ]; then
        log "  Found $g ($GID)"
        run aws identitystore delete-group \
            --identity-store-id "$IDC_STORE_ID" \
            --group-id "$GID" \
            --region "$REGION" --no-cli-pager
    else
        log "  (group $g already gone — skip; idempotent)"
    fi
done

# ---------------------------------------------------------------------------
# Step 6/6 — Verify.
# ---------------------------------------------------------------------------
log ""
log "Step 6/6 — verify"
if [ "$MODE" = "execute" ]; then
    REMAINING=$(aws cloudformation list-stacks \
        --region "$REGION" --no-cli-pager \
        --stack-status-filter \
            CREATE_COMPLETE UPDATE_COMPLETE \
            CREATE_IN_PROGRESS UPDATE_IN_PROGRESS \
            UPDATE_ROLLBACK_COMPLETE DELETE_FAILED \
        --query "StackSummaries[?starts_with(StackName, \`adp-${STAGE}-foundation-\`)].StackName" \
        --output text 2>/dev/null || echo "")
    if [ -n "$REMAINING" ] && [ "$REMAINING" != "None" ]; then
        warn "Stacks still present after destroy:"
        for s in $REMAINING; do
            warn "  $s"
        done
        warn "Investigate with:"
        warn "  aws cloudformation describe-stack-events --stack-name <stack> --region $REGION"
        exit 3
    fi
    log "  PASS — no adp-${STAGE}-foundation-* stacks remain"

    BS_STATUS=$(aws cloudformation describe-stacks \
        --stack-name adp-shared-bootstrap \
        --region "$REGION" --no-cli-pager \
        --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "MISSING")
    if [ "$BS_STATUS" = "CREATE_COMPLETE" ] || [ "$BS_STATUS" = "UPDATE_COMPLETE" ]; then
        log "  PASS — adp-shared-bootstrap untouched ($BS_STATUS)"
    elif [ "$BS_STATUS" = "MISSING" ]; then
        warn "adp-shared-bootstrap is MISSING. Macie session may need to be re-bootstrapped before next deploy."
    else
        warn "adp-shared-bootstrap status is $BS_STATUS (expected CREATE_COMPLETE / UPDATE_COMPLETE)."
    fi
else
    log "  DRY-RUN: would assert no adp-${STAGE}-foundation-* stacks remain"
    log "  DRY-RUN: would assert adp-shared-bootstrap is CREATE_COMPLETE / UPDATE_COMPLETE"
fi

# ---------------------------------------------------------------------------
# Done.
# ---------------------------------------------------------------------------
log ""
if [ "$MODE" = "execute" ]; then
    log "================================================================"
    log "  Tear-down complete (stage=$STAGE)"
    log "================================================================"
    log ""
    log "  Re-deploy with:"
    log "    make deploy STAGE=$STAGE"
    log "    make seed STAGE=$STAGE      # once Group 3 generators land"
    log "    make smoke-test STAGE=$STAGE"
    log "    ./scripts/macie-create-job.sh $STAGE"
else
    log "================================================================"
    log "  DRY-RUN complete — no AWS state changes were made"
    log "================================================================"
    log ""
    log "  To actually destroy, re-run:"
    log "    $(basename "$0") $STAGE --yes"
    log "  Or via the Makefile:"
    log "    make teardown STAGE=$STAGE YES=1"
fi

exit 0
