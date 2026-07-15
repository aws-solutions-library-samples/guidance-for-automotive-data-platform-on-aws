#!/bin/bash
# Legacy DataZone catalog publisher (pre-foundation). Reads
# /tmp/automotive-platform/config.env and creates a Glue DB + crawler
# + DataZone data source for tire telemetry.
#
# Per Fix Group A (staging-prod rollout), every script under
# platform-foundation/scripts/ that touches stage-bearing resources MUST
# accept a stage argument and fail closed if it is missing or invalid.
#
# Usage:
#   ./publish-to-datazone.sh <stage>
#   ./publish-to-datazone.sh --stage <stage>

set -e

LOG_PREFIX="[publish-to-datazone]"
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
export STAGE

# Load configuration
source /tmp/automotive-platform/config.env

echo "=== Publishing Telemetry Data to DataZone Catalog ==="
echo "Stage:       $STAGE"
echo "Domain:      $DOMAIN_ID"
echo "Data Source: $DATA_SOURCE"
echo "Bucket:      $TELEMETRY_BUCKET"
echo ""

# Step 1: Create Glue database
echo "Creating Glue database..."
aws glue create-database \
  --region $REGION \
  --database-input "{
    \"Name\": \"tire_telemetry\",
    \"Description\": \"Tire telemetry data from $DATA_SOURCE source (stage=$STAGE)\"
  }" 2>/dev/null || echo "Database exists"

# Step 2: Create Glue crawler
echo "Creating Glue crawler..."
CRAWLER_ROLE=$(aws cloudformation describe-stacks \
  --region $REGION \
  --stack-name automotive-unified-studio-domain \
  --query 'Stacks[0].Outputs[?OutputKey==`SageMakerManageAccessRoleArn`].OutputValue' \
  --output text)

aws glue create-crawler \
  --region $REGION \
  --name tire-telemetry-crawler \
  --role "$CRAWLER_ROLE" \
  --database-name tire_telemetry \
  --targets "{
    \"S3Targets\": [{
      \"Path\": \"s3://$TELEMETRY_BUCKET/$TELEMETRY_PREFIX/\"
    }]
  }" \
  --schema-change-policy "{
    \"UpdateBehavior\": \"UPDATE_IN_DATABASE\",
    \"DeleteBehavior\": \"LOG\"
  }" 2>/dev/null || echo "Crawler exists"

# Step 3: Run crawler
echo "Running crawler..."
aws glue start-crawler --region $REGION --name tire-telemetry-crawler 2>/dev/null || true
sleep 5

# Step 4: Create DataZone data source
echo "Creating DataZone data source..."
DATA_SOURCE_OUTPUT=$(aws datazone create-data-source \
  --region $REGION \
  --domain-identifier $DOMAIN_ID \
  --project-identifier $ROOT_DOMAIN_UNIT \
  --name "Tire Telemetry Data" \
  --type GLUE \
  --enable-setting ENABLED \
  --configuration "{
    \"glueRunConfiguration\": {
      \"relationalFilterConfigurations\": [{
        \"databaseName\": \"tire_telemetry\",
        \"filterExpressions\": []
      }]
    }
  }" \
  --output json 2>&1 || echo '{"id":"exists"}')

DATA_SOURCE_ID=$(echo "$DATA_SOURCE_OUTPUT" | jq -r '.id')

echo "✓ Data source created: $DATA_SOURCE_ID"

# Step 5: Run data source
echo "Publishing to catalog..."
aws datazone start-data-source-run \
  --region $REGION \
  --domain-identifier $DOMAIN_ID \
  --data-source-identifier $DATA_SOURCE_ID \
  --output json > /dev/null 2>&1 || true

echo ""
echo "=== ✓ Telemetry Data Published to DataZone Catalog (stage=$STAGE) ==="
echo ""
echo "Data Source: $DATA_SOURCE ($TELEMETRY_BUCKET)"
echo "Glue Database: tire_telemetry"
echo "DataZone Data Source: $DATA_SOURCE_ID"
echo ""
echo "Tire prediction projects can now subscribe to this data!"
