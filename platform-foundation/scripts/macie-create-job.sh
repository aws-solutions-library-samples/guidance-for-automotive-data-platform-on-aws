#!/usr/bin/env bash
# Create the Macie scheduled classification job for the ADP
# foundation lake bucket. CloudFormation does NOT expose
# AWS::Macie::ClassificationJob; this script uses the CLI API.
#
# Idempotent: skips if a job named "adp-{stage}-foundation-pii-classification"
# already exists.
#
# Excluded prefixes (per spec.md governance design):
# - dimensions/                                  (no PII)
# - curated/vehicle_telemetry_aggregated/        (high-row, no PII)
# - curated/energy_usage/                        (high-row, no PII)
# - knowledge/                                   (KB artifacts; handled via Bedrock)
#
# Usage:
#   ./macie-create-job.sh <stage>
#   ./macie-create-job.sh --stage <stage>
#
#   <stage> is REQUIRED — must be 'staging' or 'prod' (lower-case).

set -euo pipefail

LOG_PREFIX="[macie-create-job]"
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
ACCOUNT="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null)}"
LAKE_BUCKET="adp-${STAGE}-foundation-lake-${ACCOUNT}-${REGION}"
JOB_NAME="adp-${STAGE}-foundation-pii-classification"

main() {
    if [ -z "$ACCOUNT" ] || [ "$ACCOUNT" = "None" ]; then
        err "could not determine AWS account ID. Run 'aws sts get-caller-identity' first."
        exit 2
    fi
    log "Account: $ACCOUNT, Region: $REGION, Stage: $STAGE, Bucket: $LAKE_BUCKET"

    # Idempotency: search for existing job by name.
    EXISTING=$(aws macie2 list-classification-jobs \
        --region "$REGION" \
        --filter-criteria '{"includes":[{"key":"name","values":["'"$JOB_NAME"'"]}]}' \
        --query 'items[0].jobId' --output text 2>/dev/null || echo "")
    if [ -n "$EXISTING" ] && [ "$EXISTING" != "None" ]; then
        log "Macie job '$JOB_NAME' already exists ($EXISTING) — nothing to do."
        return 0
    fi

    # Job definition payload — weekly schedule, scoped to the lake bucket
    # with PII-free prefixes excluded.
    PAYLOAD=$(cat <<JSON
{
    "name": "$JOB_NAME",
    "description": "Weekly PII classification for ADP foundation lake bucket (stage=$STAGE). Excludes high-row, non-PII surfaces (telemetry, energy, dimensions, knowledge).",
    "jobType": "SCHEDULED",
    "scheduleFrequency": {"weeklySchedule": {"dayOfWeek": "MONDAY"}},
    "samplingPercentage": 100,
    "s3JobDefinition": {
        "bucketDefinitions": [
            {"accountId": "$ACCOUNT", "buckets": ["$LAKE_BUCKET"]}
        ],
        "scoping": {
            "excludes": {
                "and": [
                    {
                        "simpleScopeTerm": {
                            "comparator": "STARTS_WITH",
                            "key": "OBJECT_KEY",
                            "values": [
                                "dimensions/",
                                "curated/vehicle_telemetry_aggregated/",
                                "curated/energy_usage/",
                                "knowledge/"
                            ]
                        }
                    }
                ]
            }
        }
    },
    "tags": {
        "adp:project": "adp-foundation",
        "adp:spec": "2026-05-28-adp-ev-startup-foundation",
        "adp:stage": "$STAGE"
    }
}
JSON
)
    log "Creating Macie classification job '$JOB_NAME' ..."
    JOB_ID=$(aws macie2 create-classification-job \
        --region "$REGION" \
        --cli-input-json "$PAYLOAD" \
        --query jobId --output text)
    log "Created job: $JOB_ID"
    return 0
}

main
