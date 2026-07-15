#!/usr/bin/env bash
# Deploy the ADP Foundation data-quality CloudWatch dashboard.
#
# Usage:
#   ./scripts/deploy-quality-dashboard.sh <stage>
#
# Stage is one of {staging, prod}. Region is pinned to us-east-1 per
# the foundation pin in staging-prod-design.md. The script:
#
#   1. Validates the stage argument (fail-closed, matching Makefile contract)
#   2. Builds the dashboard body via dashboard.py CLI
#   3. Validates the body parses as JSON
#   4. Runs aws cloudwatch put-dashboard
#   5. Verifies via aws cloudwatch get-dashboard
#
# Non-interactive — passes --no-cli-pager on every aws call.
#
# Exits non-zero on any failure. Prints the dashboard URL on success.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

readonly REGION="us-east-1"
readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly DASHBOARD_PY="${REPO_ROOT}/platform-foundation/source/quality-dashboard/dashboard.py"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

log() { printf '\033[36m[deploy-quality-dashboard]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[31m[deploy-quality-dashboard ERROR]\033[0m %s\n' "$*" >&2; }
ok()  { printf '\033[32m[deploy-quality-dashboard OK]\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# Stage validation (fail-closed; matches Makefile contract from Fix Group A3)
# ---------------------------------------------------------------------------

if [[ $# -lt 1 ]]; then
    err "stage is required (positional arg or --stage <value>)"
    err "Usage: $(basename "$0") <staging|prod>"
    exit 1
fi

# Accept both `script staging` and `script --stage staging` / `script --stage=staging`
case "$1" in
    --stage=*) STAGE="${1#--stage=}" ;;
    --stage)
        if [[ $# -lt 2 ]]; then
            err "--stage requires a value"
            exit 1
        fi
        STAGE="$2"
        ;;
    *) STAGE="$1" ;;
esac

if [[ -z "${STAGE}" ]]; then
    err "stage must not be empty"
    exit 1
fi

if [[ "${STAGE}" != "staging" && "${STAGE}" != "prod" ]]; then
    err "stage must be 'staging' or 'prod' (got '${STAGE}'); case-sensitive"
    exit 1
fi

readonly STAGE
readonly DASHBOARD_NAME="adp-${STAGE}-foundation-data-quality"

# ---------------------------------------------------------------------------
# Pre-flight: AWS creds, python, dashboard.py reachable
# ---------------------------------------------------------------------------

log "Pre-flight checks"

if ! command -v aws >/dev/null 2>&1; then
    err "aws CLI not found on PATH"
    exit 1
fi

if ! aws sts get-caller-identity --no-cli-pager >/dev/null 2>&1; then
    err "AWS credentials not configured or invalid (aws sts get-caller-identity failed)"
    err "  fix: aws sso login   (or set AWS_PROFILE / AWS_ACCESS_KEY_ID)"
    exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --no-cli-pager --query Account --output text)"
log "Account: ${ACCOUNT_ID}, region: ${REGION}, stage: ${STAGE}"

if [[ ! -f "${DASHBOARD_PY}" ]]; then
    err "dashboard.py not found at ${DASHBOARD_PY}"
    exit 1
fi

# Prefer the project venv if it exists; fall back to system python3.
PYTHON_BIN="${REPO_ROOT}/platform-foundation/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
    if [[ -z "${PYTHON_BIN}" ]]; then
        err "no python3 on PATH and no venv at platform-foundation/.venv/"
        exit 1
    fi
    log "Using system python3 at ${PYTHON_BIN} (venv not found)"
else
    log "Using venv python at ${PYTHON_BIN}"
fi

# ---------------------------------------------------------------------------
# Build the dashboard body
# ---------------------------------------------------------------------------

BODY_FILE="$(mktemp -t adp-quality-dashboard.XXXXXX.json)"
trap 'rm -f "${BODY_FILE}"' EXIT

log "Building dashboard body for stage=${STAGE}"
"${PYTHON_BIN}" "${DASHBOARD_PY}" --stage "${STAGE}" --region "${REGION}" --output "${BODY_FILE}"

# Validate the body parses as JSON before sending it to CloudWatch.
"${PYTHON_BIN}" -c "import json,sys; json.load(open(sys.argv[1])); print('json-valid')" \
    "${BODY_FILE}" >/dev/null

BYTE_COUNT="$(wc -c < "${BODY_FILE}" | tr -d ' ')"
log "Dashboard body: ${BYTE_COUNT} bytes (limit: 100 KB / 102400 bytes)"

if [[ "${BYTE_COUNT}" -gt 102400 ]]; then
    err "dashboard body exceeds 100 KB limit"
    exit 1
fi

# ---------------------------------------------------------------------------
# put-dashboard
# ---------------------------------------------------------------------------

log "aws cloudwatch put-dashboard --dashboard-name ${DASHBOARD_NAME}"

aws cloudwatch put-dashboard \
    --dashboard-name "${DASHBOARD_NAME}" \
    --dashboard-body "file://${BODY_FILE}" \
    --region "${REGION}" \
    --no-cli-pager > /tmp/.adp-put-dashboard-output.json

# put-dashboard returns DashboardValidationMessages on partial failure
# (e.g., metric typos). Surface them — they're warnings not errors,
# but we want operators to see them.
VALIDATION_MSGS="$(jq -r '.DashboardValidationMessages // [] | .[].Message' \
    /tmp/.adp-put-dashboard-output.json 2>/dev/null || true)"
if [[ -n "${VALIDATION_MSGS}" ]]; then
    err "CloudWatch returned validation messages (non-fatal but review):"
    echo "${VALIDATION_MSGS}" | sed 's/^/    /' >&2
fi

# ---------------------------------------------------------------------------
# Post-deploy verify
# ---------------------------------------------------------------------------

log "Verifying via aws cloudwatch get-dashboard"

aws cloudwatch get-dashboard \
    --dashboard-name "${DASHBOARD_NAME}" \
    --region "${REGION}" \
    --no-cli-pager \
    --query 'DashboardArn' --output text

DASHBOARD_URL="https://${REGION}.console.aws.amazon.com/cloudwatch/home?region=${REGION}#dashboards:name=${DASHBOARD_NAME}"
ok "Dashboard deployed: ${DASHBOARD_NAME}"
ok "URL: ${DASHBOARD_URL}"

exit 0
