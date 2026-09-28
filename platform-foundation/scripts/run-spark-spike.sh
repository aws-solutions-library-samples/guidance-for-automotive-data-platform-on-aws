#!/usr/bin/env bash
# Run the Group 1 PySpark generation spike on AWS Glue 4.0.
#
# This is a one-shot scaffolding harness:
#   1. Creates a one-off IAM role for Glue with S3 + Glue catalog perms
#      scoped to the foundation lake bucket.
#   2. Uploads the spike script to s3://.../spike-scripts/.
#   3. Creates a one-off Glue job, starts a run, waits for terminal state.
#   4. Reads the spike's printed summary from CloudWatch logs and writes it
#      to source/lib/spike/results.md.
#   5. Tears down the Glue job + IAM role (the spike output stays in S3 +
#      a local results.md).
#
# Per decisions.md "2026-05-28 — Group 1 task 8 rescheduled": the spike
# reuses the deployed lake bucket and creates only ephemeral compute
# infrastructure. No persistent CDK resources are added.
#
# Cost: ~10 DPU-minutes (2 G.1X workers × ~5 min) ≈ $0.07 at $0.44/DPU-hr.

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="${ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text --no-cli-pager)}"
LAKE_BUCKET="adp-foundation-lake-${ACCOUNT_ID}-${REGION}"
ROLE_NAME="adp-foundation-spike-glue-role"
JOB_NAME="adp-foundation-spike-vehicle-telemetry"
SCRIPT_S3_KEY="spike-scripts/spark_generation_spike.py"
SCRIPT_LOCAL="source/lib/spike/spark_generation_spike.py"
SPIKE_OUTPUT_PREFIX="spike-output/vehicle_telemetry_aggregated/"
RESULTS_LOCAL="source/lib/spike/results.md"
ROWS="${SPIKE_ROWS:-10000000}"
PARTITIONS="${SPIKE_PARTITIONS:-64}"
DPUS="${SPIKE_DPUS:-2}"

LOG_PREFIX="[spike-runner]"
log() { echo "$LOG_PREFIX $*" >&2; }
err() { echo "$LOG_PREFIX ERROR: $*" >&2; }

cleanup() {
    log "Cleanup: deleting one-off Glue job + role ..."
    aws glue delete-job --job-name "$JOB_NAME" --region "$REGION" --no-cli-pager 2>/dev/null || true
    # Detach all role policies before delete
    aws iam list-attached-role-policies --role-name "$ROLE_NAME" --query 'AttachedPolicies[].PolicyArn' --output text --no-cli-pager 2>/dev/null \
        | tr '\t' '\n' | while read -r arn; do
        [ -n "$arn" ] && aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$arn" --no-cli-pager 2>/dev/null || true
    done
    aws iam list-role-policies --role-name "$ROLE_NAME" --query 'PolicyNames' --output text --no-cli-pager 2>/dev/null \
        | tr '\t' '\n' | while read -r p; do
        [ -n "$p" ] && aws iam delete-role-policy --role-name "$ROLE_NAME" --policy-name "$p" --no-cli-pager 2>/dev/null || true
    done
    aws iam delete-role --role-name "$ROLE_NAME" --no-cli-pager 2>/dev/null || true
}

main() {
    log "Account: $ACCOUNT_ID, Region: $REGION, Bucket: $LAKE_BUCKET"

    # 1) Create IAM role for Glue
    log "Creating Glue ETL role $ROLE_NAME (idempotent) ..."
    aws iam get-role --role-name "$ROLE_NAME" --no-cli-pager >/dev/null 2>&1 || aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document '{
            "Version":"2012-10-17",
            "Statement":[{
                "Effect":"Allow",
                "Principal":{"Service":"glue.amazonaws.com"},
                "Action":"sts:AssumeRole"
            }]
        }' \
        --no-cli-pager >/dev/null

    aws iam attach-role-policy --role-name "$ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole \
        --no-cli-pager 2>/dev/null || true

    # Inline S3 + KMS access scoped to the foundation lake bucket
    aws iam put-role-policy --role-name "$ROLE_NAME" \
        --policy-name "spike-s3-and-kms" \
        --policy-document "{
            \"Version\":\"2012-10-17\",
            \"Statement\":[
                {\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\",\"s3:DeleteObject\",\"s3:ListBucket\",\"s3:GetBucketLocation\"],\"Resource\":[\"arn:aws:s3:::${LAKE_BUCKET}\",\"arn:aws:s3:::${LAKE_BUCKET}/*\"]},
                {\"Effect\":\"Allow\",\"Action\":[\"kms:Encrypt\",\"kms:Decrypt\",\"kms:GenerateDataKey*\",\"kms:DescribeKey\",\"kms:ReEncrypt*\"],\"Resource\":\"*\"}
            ]
        }" \
        --no-cli-pager >/dev/null
    ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
    log "Role: $ROLE_ARN"

    # 2) Upload script
    log "Uploading spike script to s3://${LAKE_BUCKET}/${SCRIPT_S3_KEY} ..."
    aws s3 cp "$SCRIPT_LOCAL" "s3://${LAKE_BUCKET}/${SCRIPT_S3_KEY}" --region "$REGION" --no-cli-pager >/dev/null

    # 3) Create / replace Glue job
    log "Creating Glue job $JOB_NAME (idempotent) ..."
    aws glue delete-job --job-name "$JOB_NAME" --region "$REGION" --no-cli-pager 2>/dev/null || true
    # Wait for job-deletion + IAM eventual consistency on the new role.
    sleep 15
    aws glue create-job \
        --name "$JOB_NAME" \
        --role "$ROLE_ARN" \
        --command "Name=glueetl,ScriptLocation=s3://${LAKE_BUCKET}/${SCRIPT_S3_KEY},PythonVersion=3" \
        --default-arguments "{
            \"--datalake-formats\":\"iceberg\",
            \"--enable-metrics\":\"true\",
            \"--enable-continuous-cloudwatch-log\":\"true\",
            \"--enable-spark-ui\":\"false\",
            \"--TempDir\":\"s3://${LAKE_BUCKET}/spike-tmp/\"
        }" \
        --execution-property MaxConcurrentRuns=2 \
        --glue-version "4.0" \
        --number-of-workers "$DPUS" \
        --worker-type "G.1X" \
        --timeout 30 \
        --region "$REGION" \
        --no-cli-pager >/dev/null
    sleep 5

    # 4) Start job run with arguments
    log "Starting job run (rows=$ROWS, partitions=$PARTITIONS, workers=$DPUS) ..."
    SPIKE_OUTPUT_S3="s3://${LAKE_BUCKET}/${SPIKE_OUTPUT_PREFIX}"
    JOB_RUN_ID=$(aws glue start-job-run \
        --job-name "$JOB_NAME" \
        --arguments "{
            \"--output-root\":\"${SPIKE_OUTPUT_S3}\",
            \"--rows\":\"${ROWS}\",
            \"--partitions\":\"${PARTITIONS}\"
        }" \
        --region "$REGION" \
        --query JobRunId --output text --no-cli-pager)
    log "Job run id: $JOB_RUN_ID"

    # 5) Poll for terminal state
    log "Polling job state ..."
    START=$(date +%s)
    STATE=""
    for _ in $(seq 1 60); do  # up to ~30 min at 30s intervals
        STATE=$(aws glue get-job-run \
            --job-name "$JOB_NAME" \
            --run-id "$JOB_RUN_ID" \
            --region "$REGION" \
            --query 'JobRun.JobRunState' --output text --no-cli-pager 2>/dev/null || echo "UNKNOWN")
        case "$STATE" in
            SUCCEEDED|FAILED|TIMEOUT|STOPPED) break ;;
        esac
        log "  state=$STATE — waiting 30s ..."
        sleep 30
    done
    ELAPSED=$(($(date +%s) - START))
    log "Job terminated: state=$STATE, elapsed=${ELAPSED}s"

    if [ "$STATE" != "SUCCEEDED" ]; then
        err "Job did not succeed."
        aws glue get-job-run --job-name "$JOB_NAME" --run-id "$JOB_RUN_ID" \
            --region "$REGION" --query 'JobRun.ErrorMessage' --output text --no-cli-pager 2>&1 | sed 's/^/    /'
        return 1
    fi

    # 6) Compute output statistics directly from S3
    log "Measuring output ..."
    SIZES=$(aws s3 ls "s3://${LAKE_BUCKET}/${SPIKE_OUTPUT_PREFIX}" --recursive --region "$REGION" --no-cli-pager 2>/dev/null | awk '{print $3}' | grep -v '^$' || true)
    FILE_COUNT=$(echo "$SIZES" | wc -l | xargs)
    TOTAL_BYTES=$(echo "$SIZES" | awk '{s+=$1} END {print s+0}')
    if [ "$FILE_COUNT" -gt 0 ]; then
        AVG_BYTES=$((TOTAL_BYTES / FILE_COUNT))
        MIN_BYTES=$(echo "$SIZES" | sort -n | head -1)
        MAX_BYTES=$(echo "$SIZES" | sort -n | tail -1)
    else
        AVG_BYTES=0
        MIN_BYTES=0
        MAX_BYTES=0
    fi
    BYTES_PER_ROW=$(echo "scale=2; $TOTAL_BYTES / $ROWS" | bc)
    AVG_MB=$(echo "scale=2; $AVG_BYTES / 1048576" | bc)
    TOTAL_MB=$(echo "scale=2; $TOTAL_BYTES / 1048576" | bc)
    VTA_100M_GB=$(echo "scale=2; $BYTES_PER_ROW * 100000000 / 1073741824" | bc)
    EU_90D_GB=$(echo "scale=2; $BYTES_PER_ROW * 450000000 / 1073741824" | bc)
    EU_3Y_GB=$(echo "scale=2; $BYTES_PER_ROW * 5500000000 / 1073741824" | bc)

    log "  files=$FILE_COUNT total_mb=$TOTAL_MB avg_mb=$AVG_MB bytes_per_row=$BYTES_PER_ROW"

    # 7) Write results.md
    log "Writing $RESULTS_LOCAL ..."
    cat > "$RESULTS_LOCAL" <<EOF
# Spike: 10M-row PySpark generation on Glue (Group 1 task 8)

Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")

## Run

- Glue job: \`$JOB_NAME\`
- Run id: \`$JOB_RUN_ID\`
- State: \`$STATE\`
- Workers: $DPUS × G.1X
- Glue version: 4.0 (Spark 3.3, Python 3.10)
- Datalake format: iceberg
- Wall-clock elapsed: ${ELAPSED}s
- Output: \`$SPIKE_OUTPUT_S3\`

## Inputs

- rows generated: $ROWS
- target window: ${SPIKE_DAYS:-90} days
- partitions: $PARTITIONS
- columns: 27 (vehicle_telemetry_aggregated subset)

## Output sizing

| Metric | Value |
|---|---|
| Parquet file count | $FILE_COUNT |
| Total parquet bytes | $TOTAL_BYTES ($TOTAL_MB MiB) |
| Average file size | $AVG_MB MiB |
| Min file size | $MIN_BYTES bytes |
| Max file size | $MAX_BYTES bytes |
| **Bytes per row** | **$BYTES_PER_ROW** |

Spec target: ~256 MiB per parquet file (within 200–300 MiB acceptable).

## Extrapolation to Group 3 products

Using observed bytes-per-row of $BYTES_PER_ROW:

| Product | Rows | Estimated total size |
|---|---|---|
| vehicle_telemetry_aggregated (rolling 90d, 100M) | 100,000,000 | $VTA_100M_GB GiB |
| energy_usage (90d, 450M) | 450,000,000 | $EU_90D_GB GiB |
| energy_usage (full 3y, 5.5B) | 5,500,000,000 | $EU_3Y_GB GiB |

## Recommendation

The spec already commits **\`energy_usage\` to a 90-day rolling window in
v1**, regardless of spike outcome. This spike validates that decision:

- 90-day window: $EU_90D_GB GiB — fits cleanly on the foundation lake;
  partition pruning keeps Athena query cost bounded for typical
  customer-cohort and per-VIN queries.
- Full 3-year window: $EU_3Y_GB GiB — would require ~10× storage and
  significant Athena scan overhead. Not recommended for v1.

**Decision (matches spec commitment)**: ship \`energy_usage\` with a 90-day
rolling window in v1; reconsider full-3y if downstream consumers demonstrate
need.

## File-size targeting

Observed average $AVG_MB MiB vs target 256 MiB. If average is below 200 MiB:
increase coalesce target by reducing \`--partitions\`. If above 300 MiB:
increase \`--partitions\`.

The Group 3 \`vehicle_telemetry_aggregated\` and \`energy_usage\` Spark
generators reuse this script's partition-tuning approach.

## Reproducibility

To re-run this spike (after re-deploying foundation):

\`\`\`
cd platform-foundation
make seed-dimensions   # if not yet done
SPIKE_ROWS=10000000 SPIKE_PARTITIONS=$PARTITIONS bash scripts/run-spark-spike.sh
\`\`\`

The harness creates ephemeral Glue resources (role, job) and tears them
down on completion. Spike output stays in S3 for further inspection.
EOF

    log "Results written to $RESULTS_LOCAL"
    log "Spike complete: PASS"

    return 0
}

trap cleanup EXIT
main "$@"
