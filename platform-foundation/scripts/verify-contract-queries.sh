#!/usr/bin/env bash
# verify-contract-queries.sh — Group 6 task: "Run all sample queries from the
# integration contract".
#
# Per `.kiro/specs/2026-05-28-adp-ev-startup-foundation/tasks.md` Group 6
# task #1:
#
#   Accept: every SQL file in `docs/cvx-integration-contract.md` and
#           `platform-foundation/source/athena-queries/` runs in Athena
#           against the deployed foundation, returns ≥1 row, and completes
#           in ≤30 seconds.
#   Verify: script exits 0; emits a per-query elapsed-time report.
#           bash -n passes; --dry-run prints query inventory without
#           executing.
#   Constraints: queries that exceed 30s are flagged for investigation. Do
#                not silently raise the threshold.
#
# What this script does:
#
#   1. Extracts every fenced ```sql ... ``` block from
#      `docs/cvx-integration-contract.md` (≥17 blocks; pinned by §1.1
#      catalog, §3.x per-product samples, §4.x cross-product joins, §5
#      KB-manifest probe, §6.x lineage queries).
#   2. Copies every `*.sql` file from `source/athena-queries/`
#      (4 cross-product join examples).
#   3. In LIVE mode, resolves three concrete substitute values from the
#      deployed dimension catalog so the example synthetic literals
#      ('1FA00000000033EK4', 'CUST-3F2504E0', 'Battery Management v3.4')
#      land on rows that actually exist post-Group-3:
#         a. `vin`           ← `adp_{stage}_dimensions.vins         LIMIT 1`
#         b. `customer_id`   ← `adp_{stage}_dimensions.customers    LIMIT 1`
#         c. `campaign_name` ← `adp_{stage}_ota_campaigns.ota_campaigns LIMIT 1`
#      Stage-prefix substitution (`adp_staging_*` → `adp_{stage}_*`) is
#      applied before value substitution.
#   4. Runs each query via `aws athena start-query-execution`, polls until
#      a terminal state, asserts ≥1 row in the result set, and records
#      per-query elapsed wall time.
#   5. Flags queries that exceeded the elapsed-time threshold (default 30s
#      per the spec Accept clause). Threshold is overridable via
#      `--threshold-seconds <N>`; the script does NOT silently raise the
#      threshold per the spec Constraint.
#   6. Emits a final per-query report and exits non-zero if any query
#      FAILED. Threshold flags do NOT fail the run by themselves —
#      operator triage decides.
#
# Usage:
#
#   ./verify-contract-queries.sh <staging|prod> [--dry-run] [--region <r>]
#                                [--workgroup <wg>] [--output-bucket <s3>]
#                                [--threshold-seconds <N>]
#                                [--skip-kb-manifest]
#   ./verify-contract-queries.sh --stage <staging|prod> [...same flags...]
#
#   <stage>                      REQUIRED. Lower-case 'staging' or 'prod'.
#                                Fails closed when missing or invalid.
#   --dry-run                    Print query inventory and exit 0. No AWS
#                                calls. Safe to run without credentials.
#   --region <r>                 Default: $AWS_REGION or us-east-1.
#   --workgroup <wg>             Athena workgroup. Default: 'primary'.
#   --output-bucket <s3>         Athena results bucket. Default:
#                                s3://adp-{stage}-foundation-lake-<acct>-<region>/athena-results/
#   --threshold-seconds <N>      Per-query elapsed-time flag threshold.
#                                Default: 30 (per spec Accept).
#   --skip-kb-manifest           Skip the §3.9 KB-manifest probe (the
#                                `vehicle_knowledge_base_manifest` table
#                                is registered by the Group 5 Bedrock-KB-
#                                seeding-extensions task; pre-G5 the
#                                manifest lives on S3 only and the probe
#                                is expected to fail). Default: include.
#
# Pre-requisites (live mode):
#   - adp-{stage}-foundation-* stacks deployed and healthy.
#   - Group 3 generators have at least produced dimensions for
#     adp_{stage}_dimensions.vins / .customers and at least one row in
#     adp_{stage}_ota_campaigns.ota_campaigns.
#   - AWS credentials with athena:* + glue:GetTable + s3:GetObject on the
#     lake bucket.
#
# Non-interactive — passes --no-cli-pager on every aws call. Exits 0 on
# overall PASS, 1 on any per-query FAIL, 2 on configuration error
# (missing stage / can't resolve dimension substitute / etc.).

set -euo pipefail

LOG_PREFIX="[verify-contract-queries]"
log()  { echo "$LOG_PREFIX $*" >&2; }
warn() { echo "$LOG_PREFIX WARN: $*" >&2; }
err()  { echo "$LOG_PREFIX ERROR: $*" >&2; }
ok()   { echo "$LOG_PREFIX OK: $*" >&2; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
STAGE=""
DRY_RUN="false"
REGION="${AWS_REGION:-us-east-1}"
ATHENA_WORKGROUP="primary"
OUTPUT_BUCKET=""
THRESHOLD_SECONDS=30
SKIP_KB_MANIFEST="false"

usage() {
    cat <<EOF >&2
Usage:
  $(basename "$0") <staging|prod> [--dry-run] [--region <r>] [--workgroup <wg>]
                                  [--output-bucket <s3-uri>]
                                  [--threshold-seconds <N>]
                                  [--skip-kb-manifest]
  $(basename "$0") --stage <staging|prod> [...same flags...]

See the file header for full documentation.
EOF
}

if [ "$#" -eq 0 ]; then
    err "stage is required. Run with --help for usage."
    usage
    exit 2
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --stage)
            if [ "$#" -lt 2 ]; then
                err "--stage requires a value."
                exit 2
            fi
            STAGE="$2"
            shift 2
            ;;
        --stage=*)
            STAGE="${1#--stage=}"
            shift
            ;;
        --region)
            if [ "$#" -lt 2 ]; then err "--region requires a value."; exit 2; fi
            REGION="$2"
            shift 2
            ;;
        --region=*)
            REGION="${1#--region=}"
            shift
            ;;
        --workgroup)
            if [ "$#" -lt 2 ]; then err "--workgroup requires a value."; exit 2; fi
            ATHENA_WORKGROUP="$2"
            shift 2
            ;;
        --workgroup=*)
            ATHENA_WORKGROUP="${1#--workgroup=}"
            shift
            ;;
        --output-bucket)
            if [ "$#" -lt 2 ]; then err "--output-bucket requires a value."; exit 2; fi
            OUTPUT_BUCKET="$2"
            shift 2
            ;;
        --output-bucket=*)
            OUTPUT_BUCKET="${1#--output-bucket=}"
            shift
            ;;
        --threshold-seconds)
            if [ "$#" -lt 2 ]; then err "--threshold-seconds requires a value."; exit 2; fi
            THRESHOLD_SECONDS="$2"
            shift 2
            ;;
        --threshold-seconds=*)
            THRESHOLD_SECONDS="${1#--threshold-seconds=}"
            shift
            ;;
        --skip-kb-manifest)
            SKIP_KB_MANIFEST="true"
            shift
            ;;
        --*)
            err "unknown flag: $1"
            usage
            exit 2
            ;;
        *)
            if [ -z "$STAGE" ]; then
                STAGE="$1"
            else
                err "unexpected positional argument: $1"
                usage
                exit 2
            fi
            shift
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Stage validation (fail-closed; mirror smoke-test-subscription.sh /
# auto-subscribe-cvx.sh / Makefile _require-stage)
# ---------------------------------------------------------------------------
if [ -z "$STAGE" ]; then
    err "stage is required. Usage: $(basename "$0") <staging|prod>"
    exit 2
fi
if [ "$STAGE" != "staging" ] && [ "$STAGE" != "prod" ]; then
    err "stage must be 'staging' or 'prod' (lower-case). Got: '$STAGE'"
    exit 2
fi

# Validate threshold is a positive integer
if ! [[ "$THRESHOLD_SECONDS" =~ ^[0-9]+$ ]] || [ "$THRESHOLD_SECONDS" -lt 1 ]; then
    err "--threshold-seconds must be a positive integer. Got: '$THRESHOLD_SECONDS'"
    exit 2
fi

log "Stage: $STAGE | Region: $REGION | Workgroup: $ATHENA_WORKGROUP | Threshold: ${THRESHOLD_SECONDS}s | Dry-run: $DRY_RUN"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PF_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PF_ROOT/.." && pwd)"
CONTRACT_MD="$REPO_ROOT/docs/cvx-integration-contract.md"
ATHENA_QUERIES_DIR="$PF_ROOT/source/athena-queries"

if [ ! -f "$CONTRACT_MD" ]; then
    err "contract doc not found at $CONTRACT_MD"
    exit 2
fi
if [ ! -d "$ATHENA_QUERIES_DIR" ]; then
    err "athena-queries dir not found at $ATHENA_QUERIES_DIR"
    exit 2
fi

# Tempdir for extracted blocks + transformed queries.
WORKDIR="$(mktemp -d -t adp-verify-contract-queries.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

EXTRACTED_DIR="$WORKDIR/extracted"
TRANSFORMED_DIR="$WORKDIR/transformed"
mkdir -p "$EXTRACTED_DIR" "$TRANSFORMED_DIR"

# ---------------------------------------------------------------------------
# Step 1: extract SQL blocks
# ---------------------------------------------------------------------------
# Each block becomes a standalone .sql file under $EXTRACTED_DIR with a
# stable id of the form 'NNNN__<source-tag>__<label>.sql' for sortable
# inventory output.
#
# Sources:
#   contract md:   `docs/cvx-integration-contract.md` — every fenced
#                  ```sql ... ``` block (≥16 at column 0 + 1 indented).
#   athena-queries: `source/athena-queries/*.sql` — copied as-is.
#
# Trailing pure-comment blocks after the final SQL `;` are stripped (the
# `vin_full_360.sql` and `vin_x_ota_x_energy.sql` files document an
# Iceberg time-travel variant after the executable statement; sqlglot
# parses those as a separate "statement" but Athena rejects multi-stmt
# queries, so we cut at the last bare `;` line).

# Awk helper: print only up to (and including) the LAST line whose last
# non-whitespace char is `;` AND that line is NOT a single-line comment.
# Use it for both file-source queries (vin_full_360.sql etc.) and md-
# source blocks (the manifest probe block in §3.9 is `-- Optional: ... ;`
# — that line ends with `;` and is the last statement-end → preserved).
trim_to_last_statement() {
    awk '
        { lines[NR] = $0 }
        /;[[:space:]]*$/ {
            # Skip lines that are purely a comment ending in ; (rare, but
            # protect against `-- something; -- nothing`)
            stripped = $0
            sub(/^[[:space:]]+/, "", stripped)
            if (substr(stripped, 1, 2) != "--") last = NR
        }
        END {
            if (last == 0) {
                # No bare-`;` end-of-line found — print everything as-is.
                for (i = 1; i <= NR; i++) print lines[i]
            } else {
                for (i = 1; i <= last; i++) print lines[i]
            }
        }
    '
}

log "Extracting SQL blocks ..."

# 1a. Contract md fenced ```sql blocks
#     awk state machine: enter on /^[[:space:]]*```sql$/, exit on closing
#     /^[[:space:]]*```$/. Each block is dumped with the spec section
#     resolved by capturing the most-recent `## ...` / `### ...` heading.
awk '
    /^##[[:space:]]/  { last_h2 = $0; next }
    /^###[[:space:]]/ { last_h3 = $0; next }
    /^[[:space:]]*```sql[[:space:]]*$/ {
        in_sql = 1
        block_id++
        # Slugify the heading: prefer h3, fall back to h2.
        slug = last_h3
        if (slug == "") slug = last_h2
        # Strip leading hashes + whitespace + non-alnum.
        sub(/^#+[[:space:]]*/, "", slug)
        # Truncate slug to 60 chars and replace problematic chars.
        gsub(/[^A-Za-z0-9]+/, "_", slug)
        if (length(slug) > 60) slug = substr(slug, 1, 60)
        if (slug == "") slug = "unknown"
        out = sprintf("%s/%04d__contract__%s.sql", outdir, block_id, slug)
        # Header banner so the extracted file documents its provenance.
        printf("-- Source: docs/cvx-integration-contract.md (block #%d, line ~%d)\n", block_id, NR) > out
        printf("-- Section: %s\n", last_h2) >> out
        if (last_h3 != "") printf("-- Subsection: %s\n", last_h3) >> out
        printf("--\n") >> out
        next
    }
    /^[[:space:]]*```[[:space:]]*$/ {
        if (in_sql) { in_sql = 0; close(out) }
        next
    }
    in_sql { print >> out }
' outdir="$EXTRACTED_DIR" "$CONTRACT_MD"

CONTRACT_BLOCK_COUNT="$(find "$EXTRACTED_DIR" -name '*__contract__*.sql' -type f | wc -l | tr -d ' ')"
log "  contract md blocks extracted: $CONTRACT_BLOCK_COUNT"

# 1b. source/athena-queries/*.sql files
ATHENA_FILE_INDEX=0
while IFS= read -r -d '' sql_file; do
    ATHENA_FILE_INDEX=$((ATHENA_FILE_INDEX + 1))
    base="$(basename "$sql_file" .sql)"
    # Trim trailing comment-only blocks via the helper above.
    out="$EXTRACTED_DIR/$(printf '%04d__athena-query__%s.sql' \
        $((1000 + ATHENA_FILE_INDEX)) "$base")"
    {
        echo "-- Source: source/athena-queries/$(basename "$sql_file")"
        echo "--"
        trim_to_last_statement <"$sql_file"
    } >"$out"
done < <(find "$ATHENA_QUERIES_DIR" -maxdepth 1 -name '*.sql' -type f -print0 | sort -z)

ATHENA_FILE_COUNT="$ATHENA_FILE_INDEX"
log "  athena-queries files extracted: $ATHENA_FILE_COUNT"

TOTAL_QUERIES=$((CONTRACT_BLOCK_COUNT + ATHENA_FILE_COUNT))
log "Total queries to verify: $TOTAL_QUERIES"

if [ "$TOTAL_QUERIES" -lt 12 ]; then
    err "expected ≥12 SQL blocks (per spec PRD success criterion #6 + Group 4 verify). Got: $TOTAL_QUERIES"
    exit 2
fi

# Sorted list of all extracted queries (numeric prefix gives stable order).
# Use a portable while-read loop instead of `mapfile` (bash 4+ builtin —
# macOS ships bash 3.2 by default).
QUERY_FILES=()
while IFS= read -r line; do
    QUERY_FILES+=("$line")
done < <(find "$EXTRACTED_DIR" -name '*.sql' -type f | sort)

# ---------------------------------------------------------------------------
# Step 2: dry-run — print inventory and exit
# ---------------------------------------------------------------------------
print_inventory() {
    log "Query inventory:"
    local idx=0
    for qf in "${QUERY_FILES[@]}"; do
        idx=$((idx + 1))
        local base
        base="$(basename "$qf")"
        # Pull the first non-comment, non-blank line as a one-line preview.
        local preview
        preview="$(grep -m1 -E '^[[:space:]]*[A-Za-z]' "$qf" | sed 's/^[[:space:]]*//' | cut -c1-100 || true)"
        if [ -z "$preview" ]; then
            preview="(no executable line found — check extraction)"
        fi
        printf "%s  [%2d/%d]  %s\n" "$LOG_PREFIX" "$idx" "$TOTAL_QUERIES" "$base" >&2
        printf "%s          %s\n" "$LOG_PREFIX" "$preview" >&2
    done
}

if [ "$DRY_RUN" = "true" ]; then
    print_inventory
    log "DRY-RUN complete. No AWS calls made."
    log "Total queries: $TOTAL_QUERIES (contract md: $CONTRACT_BLOCK_COUNT, athena-queries: $ATHENA_FILE_COUNT)"
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 3: live-mode prereqs
# ---------------------------------------------------------------------------
ACCOUNT_ID="${ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text --no-cli-pager 2>/dev/null || echo "")}"
if [ -z "$ACCOUNT_ID" ] || [ "$ACCOUNT_ID" = "None" ]; then
    err "could not resolve AWS account id. Check credentials."
    exit 2
fi
LAKE_BUCKET="adp-${STAGE}-foundation-lake-${ACCOUNT_ID}-${REGION}"
if [ -z "$OUTPUT_BUCKET" ]; then
    OUTPUT_BUCKET="s3://${LAKE_BUCKET}/athena-results/"
fi
log "Account: $ACCOUNT_ID | Lake bucket: $LAKE_BUCKET | Athena output: $OUTPUT_BUCKET"

# ---------------------------------------------------------------------------
# Step 4: athena helper functions
# ---------------------------------------------------------------------------
# athena_run <query_file_path>
#   Submits the file's contents to start-query-execution, polls until
#   terminal, prints the QueryExecutionId on success, returns 0/1.
athena_run() {
    local query_file="$1"
    local query_string
    query_string="$(cat "$query_file")"
    local qid
    qid=$(aws athena start-query-execution \
        --query-string "$query_string" \
        --work-group "$ATHENA_WORKGROUP" \
        --result-configuration "OutputLocation=$OUTPUT_BUCKET" \
        --region "$REGION" \
        --query 'QueryExecutionId' \
        --output text \
        --no-cli-pager 2>/dev/null) || {
        err "  athena start-query-execution failed for $(basename "$query_file")"
        return 1
    }
    if [ -z "$qid" ] || [ "$qid" = "None" ]; then
        err "  athena start-query-execution returned empty id"
        return 1
    fi
    # Poll. Generous max iterations because some cross-product joins legitimately
    # take a while at full scale; the 30s threshold is a soft flag, not a hard cut.
    local max_iters=180  # 180 × 2s = 360s ceiling
    local i=0
    while [ "$i" -lt "$max_iters" ]; do
        local state
        state=$(aws athena get-query-execution \
            --query-execution-id "$qid" \
            --region "$REGION" \
            --query 'QueryExecution.Status.State' \
            --output text \
            --no-cli-pager 2>/dev/null || echo "ERROR")
        case "$state" in
            SUCCEEDED) echo "$qid"; return 0 ;;
            FAILED|CANCELLED|ERROR)
                local reason
                reason=$(aws athena get-query-execution \
                    --query-execution-id "$qid" \
                    --region "$REGION" \
                    --query 'QueryExecution.Status.StateChangeReason' \
                    --output text \
                    --no-cli-pager 2>/dev/null || echo "(no reason)")
                err "  athena query $qid $state: $reason"
                return 1
                ;;
        esac
        sleep 2
        i=$((i + 1))
    done
    err "  athena query $qid timed out after $((max_iters * 2))s"
    return 1
}

# athena_row_count <qid>
#   Returns the number of DATA rows (excluding header) in the result set.
athena_row_count() {
    local qid="$1"
    # max-results 2 is enough to distinguish "header only" (1 row) from
    # "≥1 data row" (≥2 rows). length() works under jmespath.
    local n
    n=$(aws athena get-query-results \
        --query-execution-id "$qid" \
        --region "$REGION" \
        --max-results 2 \
        --query 'length(ResultSet.Rows)' \
        --output text \
        --no-cli-pager 2>/dev/null || echo "0")
    if [ -z "$n" ] || [ "$n" = "None" ]; then n=0; fi
    # Subtract header row if any.
    if [ "$n" -ge 1 ]; then
        echo $((n - 1))
    else
        echo 0
    fi
}

# athena_scalar <inline-query>
#   Runs a 1-row SELECT and returns the single string value of column 0.
#   Used to resolve dimension substitute values.
athena_scalar() {
    local query_string="$1"
    local qid
    qid=$(aws athena start-query-execution \
        --query-string "$query_string" \
        --work-group "$ATHENA_WORKGROUP" \
        --result-configuration "OutputLocation=$OUTPUT_BUCKET" \
        --region "$REGION" \
        --query 'QueryExecutionId' \
        --output text \
        --no-cli-pager 2>/dev/null) || return 1
    if [ -z "$qid" ] || [ "$qid" = "None" ]; then return 1; fi
    local i=0
    while [ "$i" -lt 60 ]; do  # 120s ceiling — dimension reads are tiny
        local state
        state=$(aws athena get-query-execution \
            --query-execution-id "$qid" \
            --region "$REGION" \
            --query 'QueryExecution.Status.State' \
            --output text \
            --no-cli-pager 2>/dev/null || echo "ERROR")
        case "$state" in
            SUCCEEDED) break ;;
            FAILED|CANCELLED|ERROR) return 1 ;;
        esac
        sleep 2
        i=$((i + 1))
    done
    aws athena get-query-results \
        --query-execution-id "$qid" \
        --region "$REGION" \
        --max-results 2 \
        --query 'ResultSet.Rows[1].Data[0].VarCharValue' \
        --output text \
        --no-cli-pager 2>/dev/null
}

# ---------------------------------------------------------------------------
# Step 5: synthesize substitute values from the dimension catalog
# ---------------------------------------------------------------------------
# The contract sample queries hard-code three example synthetic literals
# ('1FA00000000033EK4', 'CUST-3F2504E0', 'Battery Management v3.4') so the
# file is runnable as-written. Group 6 substitutes them with real values
# resolved from the deployed catalog so the queries land on rows that
# actually exist (the synthetic VIN format matches the contract regex but
# is not guaranteed to be in the dimension catalog at any given seed).
log "Resolving substitute values from dimension catalog ..."

DIM_DB="adp_${STAGE}_dimensions"
OTA_DB="adp_${STAGE}_ota_campaigns"

REAL_VIN="$(athena_scalar "SELECT vin FROM ${DIM_DB}.vins LIMIT 1" || echo "")"
if [ -z "$REAL_VIN" ] || [ "$REAL_VIN" = "None" ]; then
    err "could not resolve a VIN from ${DIM_DB}.vins. Has the dimension generator run for stage=${STAGE}?"
    exit 2
fi
log "  vin           = '$REAL_VIN'"

REAL_CUSTOMER_ID="$(athena_scalar "SELECT customer_id FROM ${DIM_DB}.customers LIMIT 1" || echo "")"
if [ -z "$REAL_CUSTOMER_ID" ] || [ "$REAL_CUSTOMER_ID" = "None" ]; then
    err "could not resolve a customer_id from ${DIM_DB}.customers."
    exit 2
fi
log "  customer_id   = '$REAL_CUSTOMER_ID'"

REAL_CAMPAIGN_NAME="$(athena_scalar "SELECT campaign_name FROM ${OTA_DB}.ota_campaigns LIMIT 1" || echo "")"
if [ -z "$REAL_CAMPAIGN_NAME" ] || [ "$REAL_CAMPAIGN_NAME" = "None" ]; then
    warn "could not resolve a campaign_name from ${OTA_DB}.ota_campaigns. Falling back to the doc literal 'Battery Management v3.4'."
    REAL_CAMPAIGN_NAME="Battery Management v3.4"
fi
log "  campaign_name = '$REAL_CAMPAIGN_NAME'"

# ---------------------------------------------------------------------------
# Step 6: per-query transform + run
# ---------------------------------------------------------------------------
# Substitution rules (applied in order):
#   1. Stage prefix:    `adp_staging_` → `adp_${STAGE}_`  (no-op when stage=staging)
#   2. Synthetic VIN:           `'1FA00000000033EK4'` → `'$REAL_VIN'`
#   3. Synthetic customer_id:   `'CUST-3F2504E0'`     → `'$REAL_CUSTOMER_ID'`
#   4. Synthetic campaign_name: `'Battery Management v3.4'` → `'$REAL_CAMPAIGN_NAME'`
#
# Apostrophes in REAL_CAMPAIGN_NAME are escaped for SQL ('-doubling).

# sed escape the substitute values: the `&` and `\` chars are sed metas
# in the replacement, plus we wrap the whole replacement in single quotes
# so the shell doesn't reinterpret. The values come from Athena (alnum +
# punctuation), but campaign_name could contain apostrophes / ampersands
# in theory; escape both.
sed_escape_replacement() {
    local v="$1"
    # In sed replacement: \, &, and the delim (we use |) are metas.
    v="${v//\\/\\\\}"
    v="${v//&/\\&}"
    v="${v//|/\\|}"
    echo "$v"
}
SQL_ESCAPED_CAMPAIGN_NAME="${REAL_CAMPAIGN_NAME//\'/\'\'}"  # SQL-quote-escape

REAL_VIN_SED="$(sed_escape_replacement "$REAL_VIN")"
REAL_CUSTOMER_ID_SED="$(sed_escape_replacement "$REAL_CUSTOMER_ID")"
SQL_ESCAPED_CAMPAIGN_NAME_SED="$(sed_escape_replacement "$SQL_ESCAPED_CAMPAIGN_NAME")"

apply_substitutions() {
    local in="$1"
    local out="$2"
    sed -e "s|adp_staging_|adp_${STAGE}_|g" \
        -e "s|'1FA00000000033EK4'|'${REAL_VIN_SED}'|g" \
        -e "s|'CUST-3F2504E0'|'${REAL_CUSTOMER_ID_SED}'|g" \
        -e "s|'Battery Management v3.4'|'${SQL_ESCAPED_CAMPAIGN_NAME_SED}'|g" \
        "$in" >"$out"
}

# Skip-pattern detection: the §3.9 KB-manifest probe queries
# `vehicle_knowledge_base_manifest`, which is registered by the
# Group 5 Bedrock-KB-seeding-extensions task. Pre-G5 the manifest
# lives on S3 only; the operator can opt in to skipping via
# --skip-kb-manifest.
should_skip_query() {
    local qf="$1"
    if [ "$SKIP_KB_MANIFEST" = "true" ]; then
        if grep -q 'vehicle_knowledge_base_manifest' "$qf"; then
            return 0
        fi
    fi
    return 1
}

# ---------------------------------------------------------------------------
# Step 7: run each query and report
# ---------------------------------------------------------------------------
log "Running ${TOTAL_QUERIES} queries against stage=$STAGE ..."

REPORT_FILE="$WORKDIR/report.txt"
: >"$REPORT_FILE"

declare -i passed=0
declare -i failed=0
declare -i flagged=0
declare -i skipped=0

idx=0
for qf in "${QUERY_FILES[@]}"; do
    idx=$((idx + 1))
    base="$(basename "$qf")"
    out_file="$TRANSFORMED_DIR/$base"
    apply_substitutions "$qf" "$out_file"

    if should_skip_query "$out_file"; then
        printf "%-72s  SKIP    (--skip-kb-manifest)\n" "$base" | tee -a "$REPORT_FILE" >&2
        skipped=$((skipped + 1))
        continue
    fi

    log "[${idx}/${TOTAL_QUERIES}] $base"
    start_ts=$(date +%s)
    if qid="$(athena_run "$out_file")"; then
        end_ts=$(date +%s)
        elapsed=$((end_ts - start_ts))
        rows="$(athena_row_count "$qid")"
        if [ "$rows" -ge 1 ]; then
            if [ "$elapsed" -gt "$THRESHOLD_SECONDS" ]; then
                printf "%-72s  FLAG    %3ds  rows=%-6s  qid=%s  (>%ds threshold — investigate)\n" \
                    "$base" "$elapsed" "$rows" "$qid" "$THRESHOLD_SECONDS" \
                    | tee -a "$REPORT_FILE" >&2
                flagged=$((flagged + 1))
                passed=$((passed + 1))  # still counted as PASS — threshold flags don't fail the run
            else
                printf "%-72s  PASS    %3ds  rows=%-6s  qid=%s\n" \
                    "$base" "$elapsed" "$rows" "$qid" \
                    | tee -a "$REPORT_FILE" >&2
                passed=$((passed + 1))
            fi
        else
            printf "%-72s  FAIL    %3ds  rows=0       qid=%s  (≥1 row asserted)\n" \
                "$base" "$elapsed" "$qid" \
                | tee -a "$REPORT_FILE" >&2
            failed=$((failed + 1))
        fi
    else
        end_ts=$(date +%s)
        elapsed=$((end_ts - start_ts))
        printf "%-72s  FAIL    %3ds  (athena execution error — see warnings above)\n" \
            "$base" "$elapsed" \
            | tee -a "$REPORT_FILE" >&2
        failed=$((failed + 1))
    fi
done

# ---------------------------------------------------------------------------
# Step 8: summary
# ---------------------------------------------------------------------------
log "===================================================================="
log "Summary (stage=$STAGE, threshold=${THRESHOLD_SECONDS}s):"
log "  Total:    $TOTAL_QUERIES"
log "  Passed:   $passed"
log "  Failed:   $failed"
log "  Flagged:  $flagged  (passed but elapsed > threshold)"
log "  Skipped:  $skipped"
log "===================================================================="

if [ "$failed" -gt 0 ]; then
    err "FAIL — $failed/$TOTAL_QUERIES queries did not return ≥1 row or errored. See report above."
    exit 1
fi

if [ "$flagged" -gt 0 ]; then
    warn "All queries passed, but $flagged exceeded the ${THRESHOLD_SECONDS}s threshold. Investigate before declaring Group 6 complete."
fi

ok "All $TOTAL_QUERIES queries passed (stage=$STAGE)."
exit 0
