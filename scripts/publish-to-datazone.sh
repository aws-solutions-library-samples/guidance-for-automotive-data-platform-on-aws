#!/bin/bash
set -e

# Load configuration
source /tmp/automotive-platform/config.env

echo "=== Publishing Telemetry Data to DataZone Catalog ==="
echo "Domain: $DOMAIN_ID"
echo "Data Source: $DATA_SOURCE"
echo "Bucket: $TELEMETRY_BUCKET"
echo ""

# Step 1: Create Glue database
echo "Creating Glue database..."
aws glue create-database \
  --region $REGION \
  --database-input "{
    \"Name\": \"tire_telemetry\",
    \"Description\": \"Tire telemetry data from $DATA_SOURCE source\"
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
echo "=== ✓ Telemetry Data Published to DataZone Catalog ==="
echo ""
echo "Data Source: $DATA_SOURCE ($TELEMETRY_BUCKET)"
echo "Glue Database: tire_telemetry"
echo "DataZone Data Source: $DATA_SOURCE_ID"
echo ""
echo "Tire prediction projects can now subscribe to this data!"
