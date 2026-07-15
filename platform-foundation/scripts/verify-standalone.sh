#!/usr/bin/env bash
# Standalone-deploy verification: assert that the foundation has no
# cross-account / CMS dependency surfaced when the optional CMS ingest
# module is OFF (the default).
#
# Per spec.md Constraint #12: "Zero ADP code or runtime dependency on
# CMS. ADP deploys standalone in a clean account with no reference to
# CMS, asserted by foundation deploy verification."
#
# Approach: synth without context flags (other than the required
# `-c stage=...`), then inspect the synthesized CFN templates for:
#   - Any ARN belonging to a CMS-style table (cms-prod-*, etc.)
#   - Any DynamoDB::Stream resource
#   - Any KinesisFirehose::DeliveryStream resource
#   - Any Glue database named adp_{stage}_cms_ingest
# Any match → exit 1.
#
# This is a synth-time check; it does NOT require CMS to be deployed
# anywhere. Runs in CI on every PR.
#
# Usage:
#   ./verify-standalone.sh <stage>
#   ./verify-standalone.sh --stage <stage>
#
#   <stage> is REQUIRED — must be 'staging' or 'prod' (lower-case).
#   No silent default. Fails closed when the arg is missing/invalid.

set -euo pipefail

LOG_PREFIX="[verify-standalone]"
log() { echo "$LOG_PREFIX $*" >&2; }
err() { echo "$LOG_PREFIX ERROR: $*" >&2; }

# ----- Stage gating (Fix Group A — staging-prod rollout) --------------------
parse_stage() {
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
ACCOUNT="${CDK_DEFAULT_ACCOUNT:-${AWS_ACCOUNT_ID:-000000000000}}"
CMS_INGEST_STACK_TEMPLATE="adp-${STAGE}-foundation-cms-ingest.template.json"
CMS_INGEST_DB_TOKEN="adp_${STAGE}_cms_ingest"

cd "$(dirname "$0")/.."  # platform-foundation/

if [ ! -d ".venv" ]; then
    err ".venv not found. Run 'python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt' first."
    exit 2
fi

# shellcheck disable=SC1091
source .venv/bin/activate

OUT_DIR="cdk.out.standalone.${STAGE}"
log "Synthesizing with default context (stage=${STAGE}, cms_ingest=false) into $OUT_DIR ..."
rm -rf "$OUT_DIR"
CDK_DEFAULT_ACCOUNT="$ACCOUNT" CDK_DEFAULT_REGION="$REGION" \
    cdk synth --all -c "stage=${STAGE}" -o "$OUT_DIR" --quiet >/dev/null 2>&1 || {
    err "cdk synth failed (stage=${STAGE})."
    exit 3
}

# 1. No CMS-style ARNs in any synthesized template.
log "Scanning for CMS-prod ARNs in synthesized templates ..."
if grep -rIE "cms-(prod|dev|staging)-[a-z0-9-]+" "$OUT_DIR" 2>/dev/null; then
    err "Found CMS-style ARN in synthesized templates. Foundation deploy is NOT standalone."
    exit 1
fi

# 2. No DynamoDB::Stream resources.
log "Scanning for AWS::DynamoDB::Stream resources ..."
HITS=$( (grep -rIE 'AWS::DynamoDB::(Stream|Table)' "$OUT_DIR" 2>/dev/null || true) | wc -l | tr -d ' ')
if [ "$HITS" -gt 0 ]; then
    err "Found $HITS DynamoDB resource references with cms_ingest=false. The foundation should not provision DDB resources by default."
    grep -rIE 'AWS::DynamoDB::(Stream|Table)' "$OUT_DIR" >&2 || true
    exit 1
fi

# 3. No KinesisFirehose::DeliveryStream resources.
log "Scanning for AWS::KinesisFirehose::DeliveryStream resources ..."
HITS=$( (grep -rIE 'AWS::KinesisFirehose::DeliveryStream' "$OUT_DIR" 2>/dev/null || true) | wc -l | tr -d ' ')
if [ "$HITS" -gt 0 ]; then
    err "Found $HITS Firehose stream resources with cms_ingest=false. The foundation should not provision Firehose by default."
    exit 1
fi

# 4. No adp_{stage}_cms_ingest database.
log "Scanning for ${CMS_INGEST_DB_TOKEN} database ..."
if grep -rIE "${CMS_INGEST_DB_TOKEN}" "$OUT_DIR" 2>/dev/null; then
    err "Found ${CMS_INGEST_DB_TOKEN} database with cms_ingest=false."
    exit 1
fi

# 5. The optional cms-ingest stack must NOT have been synthesized.
log "Verifying ${CMS_INGEST_STACK_TEMPLATE%.template.json} stack was NOT synthesized ..."
if [ -f "$OUT_DIR/${CMS_INGEST_STACK_TEMPLATE}" ]; then
    err "Found cms-ingest stack template in $OUT_DIR with cms_ingest=false."
    exit 1
fi

# Affirmative: with cms_ingest=true + arn provided, the optional stack DOES synthesize.
log "Inverse-check: with cms_ingest=true the optional stack DOES synth ..."
TMP_OUT="cdk.out.cms-on.${STAGE}"
rm -rf "$TMP_OUT"
CDK_DEFAULT_ACCOUNT="$ACCOUNT" CDK_DEFAULT_REGION="$REGION" \
    cdk synth --all \
    -c "stage=${STAGE}" \
    -c enable_cms_ingest=true \
    -c "cms_vehicle_state_table_arn=arn:aws:dynamodb:$REGION:$ACCOUNT:table/cms-prod-vehicle-state" \
    -o "$TMP_OUT" --quiet >/dev/null 2>&1 || {
    err "cdk synth with cms_ingest=true failed (stage=${STAGE})."
    exit 4
}
if [ ! -f "$TMP_OUT/${CMS_INGEST_STACK_TEMPLATE}" ]; then
    err "Optional cms-ingest stack did NOT synthesize even with enable_cms_ingest=true (stage=${STAGE}). The opt-in is broken."
    exit 1
fi
rm -rf "$TMP_OUT"

log "PASS — foundation deploys standalone with no CMS dependency by default; opt-in works as designed (stage=${STAGE})."
exit 0
