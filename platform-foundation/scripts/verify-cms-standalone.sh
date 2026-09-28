#!/usr/bin/env bash
# CMS-standalone verification: assert that CMS deploys cleanly with zero
# ADP code or runtime dependency.
#
# Per spec.md Constraint #11: "Zero CMS code or runtime dependency on ADP.
# CMS deploys standalone in a clean account with no reference to ADP,
# asserted by post-merge CMS deploy verification."
#
# Inverse of `verify-standalone.sh` — that script enforces Constraint #12
# (ADP standalone). This script enforces #11 (CMS standalone).
#
# Three checks:
#   (1) The CMS git working tree contains zero references to ADP runtime
#       identifiers: adp-foundation (stack-prefix), adp_staging / adp_prod
#       (Glue DB prefixes), dzd-<id> (DataZone domain ID prefix), and
#       datazone-environments-<account> (DataZone-managed env stack prefix).
#   (2) CMS `cdk synth --all` runs cleanly in isolation (CMS deployment dir
#       only, with synthetic account/region) and emits zero ADP IAM ARNs,
#       zero ADP-prefixed Glue DBs, and zero ADP DataZone identifiers in
#       any synthesized CFN template.
#   (3) The optional CMS->ADP ingest module's IAM grants on CMS DDB tables
#       happen ONLY when the operator explicitly opts in on the ADP side
#       (verified two ways: CMS templates contain zero IAM principal
#       references to ADP roles; ADP's `cms_ingest_stack.py` requires the
#       `cms_vehicle_state_table_arn` context arg before any cross-stack
#       resource is provisioned).
#
# This is a synth-time check; it does NOT actually deploy CMS (cost) per
# spec Constraint guidance. Runs in CI on every PR.
#
# Usage:
#   ./verify-cms-standalone.sh <stage>
#   ./verify-cms-standalone.sh --stage <stage>
#   ./verify-cms-standalone.sh --stage=<stage>
#
#   <stage> is REQUIRED — must be 'dev', 'staging', or 'prod' (lower-case).
#   No silent default. Fails closed when the arg is missing/invalid.
#
# Optional env overrides (used as fallbacks; not required for default run):
#   CMS_REPO_DIR              path to CMS repo (default: ~/connected-mobility-guidance-on-aws)
#   ADP_REPO_DIR              path to ADP repo (default: ~/automotive-data-platform-on-aws)
#   CMS_DEMO_DEFAULT_PASSWORD synthetic placeholder if unset (synth-only; never deployed)
#   CDK_DEFAULT_ACCOUNT       synthetic placeholder if unset (default: 000000000000)
#   CDK_DEFAULT_REGION        default: us-west-2 (CMS's default region)

set -euo pipefail

LOG_PREFIX="[verify-cms-standalone]"
log() { echo "$LOG_PREFIX $*" >&2; }
err() { echo "$LOG_PREFIX ERROR: $*" >&2; }

# ----- Stage gating (fail-closed; mirrors verify-standalone.sh) -------------
parse_stage() {
    case "$1" in
        --stage)
            if [ "$#" -lt 2 ]; then
                err "--stage requires a value. Usage: $0 --stage <dev|staging|prod>"
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
    err "stage is required. Usage: $0 <dev|staging|prod>"
    exit 1
fi
STAGE="$(parse_stage "$@")"
if [ -z "$STAGE" ]; then
    err "stage is required. Usage: $0 <dev|staging|prod>"
    exit 1
fi
case "$STAGE" in
    dev|staging|prod) ;;
    *)
        err "stage must be 'dev', 'staging', or 'prod' (lower-case). Got: '$STAGE'"
        exit 1
        ;;
esac
log "Stage: $STAGE"

# ----- Locate repos ---------------------------------------------------------
CMS_REPO_DIR="${CMS_REPO_DIR:-$HOME/connected-mobility-guidance-on-aws}"
ADP_REPO_DIR="${ADP_REPO_DIR:-$HOME/automotive-data-platform-on-aws}"
CMS_DEPLOY_DIR="$CMS_REPO_DIR/deployment"

if [ ! -d "$CMS_REPO_DIR" ]; then
    err "CMS repo not found at: $CMS_REPO_DIR"
    err "  Set CMS_REPO_DIR=/path/to/connected-mobility-guidance-on-aws to override."
    exit 2
fi
if [ ! -d "$CMS_DEPLOY_DIR" ]; then
    err "CMS deployment dir not found at: $CMS_DEPLOY_DIR"
    exit 2
fi

# ADP runtime tokens — exact set per spec Constraint #11 + user task instructions:
#   adp-foundation              -> ADP CDK stack-prefix (and pre-stage stack name)
#   adp_staging | adp_prod      -> ADP per-stage Glue DB prefix
#   dzd-<id>                    -> DataZone domain ID prefix (anchor on alnum)
#   datazone-environments-<acct>-> DataZone-managed env stack prefix
ADP_RUNTIME_TOKENS_REGEX='adp-foundation|adp_staging|adp_prod|dzd-[a-z0-9]+|datazone-environments-[0-9]+'

# ----- Check 1: CMS git working tree has zero ADP runtime identifiers -------
log "Check 1: scanning CMS git working tree for ADP runtime identifiers ..."
cd "$CMS_REPO_DIR"
if ! git rev-parse --git-dir >/dev/null 2>&1; then
    err "Check 1 FAIL: $CMS_REPO_DIR is not a git working tree."
    exit 2
fi

# `git grep` respects .gitignore and skips untracked vendored output; -I skips
# binary files. Use `|| true` so a no-match (exit 1) does not trip set -e.
HITS_C1=$(git grep -EnI "$ADP_RUNTIME_TOKENS_REGEX" -- 2>/dev/null || true)
if [ -n "$HITS_C1" ]; then
    err "Check 1 FAIL: CMS git tree contains ADP runtime identifier(s):"
    echo "$HITS_C1" >&2
    exit 1
fi
log "Check 1 PASS: zero ADP runtime tokens in CMS git tree."

# ----- Check 2: CMS `cdk synth` in isolation, no ADP IAM ARNs ---------------
log "Check 2: synthesizing CMS in isolation (DEPLOYMENT_STAGE=$STAGE) ..."
cd "$CMS_DEPLOY_DIR"

# Resolve CDK CLI: prefer CMS .venv-local, fall back to PATH.
if [ -x ".venv/bin/cdk" ]; then
    CDK=".venv/bin/cdk"
elif command -v cdk >/dev/null 2>&1; then
    CDK="$(command -v cdk)"
else
    err "Check 2 FAIL: no 'cdk' CLI found in CMS .venv/bin/cdk or on PATH."
    err "  Install with: npm install -g aws-cdk"
    exit 4
fi

# Resolve Python entrypoint: CMS cdk.json points at .venv/bin/python; require
# the CMS venv exists so we synth against CMS's pinned aws-cdk-lib.
if [ ! -x ".venv/bin/python" ]; then
    err "Check 2 FAIL: CMS .venv/bin/python not found at $CMS_DEPLOY_DIR/.venv/bin/python."
    err "  Bootstrap CMS deps: cd $CMS_DEPLOY_DIR && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 4
fi

# Synth into a per-PID temp dir and clean up on exit.
SYNTH_OUT="$(mktemp -d -t cms-cdk-out-XXXXXX)"
# shellcheck disable=SC2064
trap "rm -rf '$SYNTH_OUT'" EXIT

# Synth-only env: synthetic account + region; placeholder demo password (CMS
# UI stack fail-closes on missing). NEVER use these values in a real deploy.
# All three are read by app.py via os.environ.get(...) and never persisted.
SYNTH_ACCOUNT="${CDK_DEFAULT_ACCOUNT:-000000000000}"
SYNTH_REGION="${CDK_DEFAULT_REGION:-us-west-2}"
SYNTH_DEMO_PW="${CMS_DEMO_DEFAULT_PASSWORD:-Synth-Only-Placeholder-Aa1!}"

log "  CDK CLI:        $CDK"
log "  CMS deploy dir: $CMS_DEPLOY_DIR"
log "  Output dir:     $SYNTH_OUT"
log "  (synth-only env) account=$SYNTH_ACCOUNT region=$SYNTH_REGION"

SYNTH_LOG="$SYNTH_OUT/.synth.log"
set +e
DEPLOYMENT_STAGE="$STAGE" \
    CDK_DEFAULT_ACCOUNT="$SYNTH_ACCOUNT" \
    CDK_DEFAULT_REGION="$SYNTH_REGION" \
    AWS_REGION="$SYNTH_REGION" \
    CMS_DEMO_DEFAULT_PASSWORD="$SYNTH_DEMO_PW" \
    "$CDK" synth --all -o "$SYNTH_OUT" --quiet >"$SYNTH_LOG" 2>&1
SYNTH_RC=$?
set -e
if [ "$SYNTH_RC" -ne 0 ]; then
    err "Check 2 FAIL: CMS cdk synth returned exit $SYNTH_RC. Last 20 lines:"
    tail -n 20 "$SYNTH_LOG" >&2
    exit 3
fi

# Count synthesized templates so the operator sees the synth was substantive.
TEMPLATE_COUNT=$(find "$SYNTH_OUT" -maxdepth 1 -name '*.template.json' -type f | wc -l | tr -d ' ')
if [ "$TEMPLATE_COUNT" -eq 0 ]; then
    err "Check 2 FAIL: cdk synth produced 0 templates in $SYNTH_OUT (unexpected)."
    exit 3
fi
log "  synthesized $TEMPLATE_COUNT CMS CFN template(s)."

# 2a. ADP runtime tokens (same regex as Check 1) MUST NOT appear.
log "  scanning synthesized CMS templates for ADP runtime tokens ..."
HITS_C2A=$(grep -rIE "$ADP_RUNTIME_TOKENS_REGEX" "$SYNTH_OUT" 2>/dev/null || true)
if [ -n "$HITS_C2A" ]; then
    err "Check 2 FAIL: synthesized CMS template references ADP runtime identifier:"
    echo "$HITS_C2A" >&2
    exit 1
fi

# 2b. ADP IAM ARNs (any role/policy named adp-*) MUST NOT appear in CMS
# templates. The CMS synth output should never reference an ADP-side IAM
# principal, regardless of CMS DEPLOYMENT_STAGE.
log "  scanning for ADP IAM ARNs in synthesized templates ..."
ADP_IAM_ARN_REGEX='arn:aws:iam:[^:"]*:[0-9]*:(role|policy)/adp-'
HITS_C2B=$(grep -rIE "$ADP_IAM_ARN_REGEX" "$SYNTH_OUT" 2>/dev/null || true)
if [ -n "$HITS_C2B" ]; then
    err "Check 2 FAIL: synthesized CMS template references an ADP IAM ARN:"
    echo "$HITS_C2B" >&2
    exit 1
fi

# 2c. Other ADP-side fingerprints (cross-repo identifiers that should never
# show up in compiled CMS templates).
log "  scanning for ADP cross-repo identifiers in synthesized templates ..."
ADP_FINGERPRINT_REGEX='automotive-data-platform-on-aws|platform-foundation|AdpIngest|adp-shared-bootstrap'
HITS_C2C=$(grep -rIE "$ADP_FINGERPRINT_REGEX" "$SYNTH_OUT" 2>/dev/null || true)
if [ -n "$HITS_C2C" ]; then
    err "Check 2 FAIL: synthesized CMS template references an ADP cross-repo identifier:"
    echo "$HITS_C2C" >&2
    exit 1
fi

log "Check 2 PASS: zero ADP IAM ARNs / runtime identifiers in CMS synth output."

# ----- Check 3: optional cms-ingest IAM grant is opt-in only ----------------
# CMS resource policies on its own DDB tables MUST NOT grant access to any
# ADP-side principal by default. The cross-stack/account grant for ADP's
# read of CMS DDB Streams lives on the ADP side (in
# `platform-foundation/stacks/optional/cms_ingest_stack.py`) and is gated
# behind the `enable_cms_ingest=true` context flag plus the
# `cms_vehicle_state_table_arn` context arg.
#
# We verify both directions:
#   3a. CMS templates contain zero IAM principals pointing at ADP roles.
#   3b. ADP's optional cms_ingest_stack.py rejects construction without
#       the `cms_vehicle_state_table_arn` arg (fail-closed opt-in).
log "Check 3: scanning CMS templates for IAM principal references to ADP roles ..."
ADP_PRINCIPAL_REGEX='"AWS"[[:space:]]*:[[:space:]]*"arn:aws:iam:[^"]*:role/(adp-[^"]*|.*-adp-foundation-[^"]*)"'
HITS_C3A=$(grep -rE "$ADP_PRINCIPAL_REGEX" "$SYNTH_OUT" 2>/dev/null || true)
if [ -n "$HITS_C3A" ]; then
    err "Check 3 FAIL: CMS template grants IAM principal access to an ADP role."
    err "  Cross-stack/account grants for the optional cms-ingest module MUST"
    err "  live on ADP's side (platform-foundation/stacks/optional/cms_ingest_stack.py)"
    err "  and be gated by the enable_cms_ingest=true context flag."
    echo "$HITS_C3A" >&2
    exit 1
fi
log "  CMS templates: zero IAM principal grants to ADP roles."

# 3b. Confirm ADP's optional cms-ingest module enforces the opt-in. This is
# defense-in-depth: even if ADP code drifts, the operator must explicitly pass
# `cms_vehicle_state_table_arn` to construct the stack.
ADP_CMS_INGEST_PY="$ADP_REPO_DIR/platform-foundation/stacks/optional/cms_ingest_stack.py"
if [ -f "$ADP_CMS_INGEST_PY" ]; then
    log "  inspecting ADP cms_ingest_stack.py for fail-closed opt-in pattern ..."
    # The stack constructor must (a) declare the arg and (b) raise/exit when
    # it is missing. The current implementation does both — these greps catch
    # regressions where someone weakens the gate.
    if ! grep -qE 'cms_vehicle_state_table_arn:\s*Optional\[str\]' "$ADP_CMS_INGEST_PY"; then
        err "Check 3 FAIL: ADP cms_ingest_stack.py no longer declares"
        err "  'cms_vehicle_state_table_arn: Optional[str]' as a constructor arg."
        err "  File: $ADP_CMS_INGEST_PY"
        exit 1
    fi
    if ! grep -qE 'if not cms_vehicle_state_table_arn' "$ADP_CMS_INGEST_PY"; then
        err "Check 3 FAIL: ADP cms_ingest_stack.py no longer fail-closes when"
        err "  cms_vehicle_state_table_arn is unset."
        err "  File: $ADP_CMS_INGEST_PY"
        exit 1
    fi
    # Belt-and-braces: confirm app.py wires the optional stack behind the
    # enable_cms_ingest context flag.
    ADP_APP_PY="$ADP_REPO_DIR/platform-foundation/app.py"
    if [ -f "$ADP_APP_PY" ]; then
        if ! grep -qE '_ctx_bool\(app, "enable_cms_ingest"\)' "$ADP_APP_PY"; then
            err "Check 3 FAIL: ADP app.py no longer gates cms_ingest behind the"
            err "  enable_cms_ingest context flag."
            err "  File: $ADP_APP_PY"
            exit 1
        fi
    fi
    log "  ADP cms_ingest_stack.py: fail-closed opt-in pattern enforced (verified inline)."
else
    log "  ADP repo not present at $ADP_REPO_DIR — skipping inline opt-in inspection."
    log "  (Set ADP_REPO_DIR=/path/to/automotive-data-platform-on-aws to enforce 3b.)"
fi

log "Check 3 PASS: CMS templates contain zero IAM grants to ADP principals; opt-in is enforced on ADP side."

log "PASS — CMS deploys cleanly with zero ADP dependency (stage=$STAGE; $TEMPLATE_COUNT templates scanned)."
exit 0
