#!/bin/bash
set -e

source /tmp/automotive-platform/config.env

echo "=== Publishing Data Sources to DataZone ==="
echo "Domain: $DOMAIN_ID"
echo "Catalog Project: $CATALOG_PROJECT"
echo ""

# Get Tooling environment from catalog project
CATALOG_ENV=$(aws datazone list-environments \
  --region $REGION \
  --domain-identifier $DOMAIN_ID \
  --project-identifier $CATALOG_PROJECT \
  --query 'items[?name==`Tooling` && status==`ACTIVE`].id|[0]' \
  --output text)

if [ -z "$CATALOG_ENV" ] || [ "$CATALOG_ENV" = "None" ]; then
    echo "❌ Catalog project Tooling environment not ACTIVE yet"
    echo "Wait for environments to be ACTIVE, then run this script again"
    exit 1
fi

echo "✓ Catalog environment: $CATALOG_ENV"
echo ""

# Get IAM connection from catalog project
CONNECTION_ID=$(aws datazone list-connections \
  --region $REGION \
  --domain-identifier $DOMAIN_ID \
  --project-identifier $CATALOG_PROJECT \
  --query 'items[?name==`project.iam`].connectionId|[0]' \
  --output text)

if [ -z "$CONNECTION_ID" ] || [ "$CONNECTION_ID" = "None" ]; then
    echo "❌ DataZone IAM connection not found"
    echo "Ensure catalog project environments are ACTIVE"
    exit 1
fi

echo "✓ DataZone connection: $CONNECTION_ID"
echo ""

# Create data sources
echo "Creating data sources..."

aws datazone create-data-source \
  --region $REGION \
  --domain-identifier $DOMAIN_ID \
  --project-identifier $CATALOG_PROJECT \
  --connection-identifier $CONNECTION_ID \
  --name "Tire Telemetry" \
  --type GLUE \
  --enable-setting ENABLED \
  --publish-on-import \
  --configuration '{"glueRunConfiguration":{"relationalFilterConfigurations":[{"databaseName":"tire_telemetry"}]}}' \
  --output json > /dev/null 2>&1 && echo "  ✓ Tire Telemetry" || echo "  Tire Telemetry exists"

aws datazone create-data-source \
  --region $REGION \
  --domain-identifier $DOMAIN_ID \
  --project-identifier $CATALOG_PROJECT \
  --connection-identifier $CONNECTION_ID \
  --name "Weather Data" \
  --type GLUE \
  --enable-setting ENABLED \
  --publish-on-import \
  --configuration '{"glueRunConfiguration":{"relationalFilterConfigurations":[{"databaseName":"weather_data"}]}}' \
  --output json > /dev/null 2>&1 && echo "  ✓ Weather Data" || echo "  Weather Data exists"

if [ -n "$SERVICE_HISTORY_TABLE" ]; then
    aws datazone create-data-source \
      --region $REGION \
      --domain-identifier $DOMAIN_ID \
      --project-identifier $CATALOG_PROJECT \
      --connection-identifier $CONNECTION_ID \
      --name "Service History" \
      --type GLUE \
      --enable-setting ENABLED \
      --publish-on-import \
      --configuration '{"glueRunConfiguration":{"relationalFilterConfigurations":[{"databaseName":"vehicle_service_history"}]}}' \
      --output json > /dev/null 2>&1 && echo "  ✓ Service History" || echo "  Service History exists"
fi

echo ""
echo "Running data source jobs..."

# Get data source IDs and run them
TELEMETRY_DS=$(aws datazone list-data-sources --region $REGION --domain-identifier $DOMAIN_ID --project-identifier $CATALOG_PROJECT --output json | jq -r '.items[] | select(.name=="Tire Telemetry") | .id // empty' | grep -v null | head -1)
WEATHER_DS=$(aws datazone list-data-sources --region $REGION --domain-identifier $DOMAIN_ID --project-identifier $CATALOG_PROJECT --output json | jq -r '.items[] | select(.name=="Weather Data") | .id // empty' | grep -v null | head -1)

if [ -n "$TELEMETRY_DS" ]; then
    aws datazone start-data-source-run \
      --region $REGION \
      --domain-identifier $DOMAIN_ID \
      --data-source-identifier $TELEMETRY_DS > /dev/null 2>&1 && \
    echo "  ✓ Started Tire Telemetry run"
fi

if [ -n "$WEATHER_DS" ]; then
    aws datazone start-data-source-run \
      --region $REGION \
      --domain-identifier $DOMAIN_ID \
      --data-source-identifier $WEATHER_DS > /dev/null 2>&1 && \
    echo "  ✓ Started Weather Data run"
fi

if [ -n "$SERVICE_HISTORY_TABLE" ]; then
    SERVICE_DS=$(aws datazone list-data-sources --region $REGION --domain-identifier $DOMAIN_ID --project-identifier $CATALOG_PROJECT --output json | jq -r '.items[] | select(.name=="Service History") | .id // empty' | grep -v null | head -1)
    if [ -n "$SERVICE_DS" ]; then
        aws datazone start-data-source-run \
          --region $REGION \
          --domain-identifier $DOMAIN_ID \
          --data-source-identifier $SERVICE_DS > /dev/null 2>&1 && \
        echo "  ✓ Started Service History run"
    fi
fi

echo ""
echo "=== ✓ Data Sources Published ==="
echo ""
echo "Data source runs are processing (~2-3 minutes)"
echo "Once complete, data will be available in DataZone catalog"
echo ""
echo "Check status:"
echo "  aws datazone list-data-sources --region $REGION \\"
echo "    --domain-identifier $DOMAIN_ID \\"
echo "    --project-identifier $CATALOG_PROJECT"
echo ""
echo "Next: Deploy tire-prediction project"
echo "  cd ~/automotive-tire-prediction-model-on-aws"
echo "  make deploy"
