#!/bin/bash

# Export Amazon Quick Suite Assets for Customer 360 Guidance
# This script exports dashboard definitions and dataset configurations

set -e

ACCOUNT_ID="${AWS_ACCOUNT_ID:-022035076260}"
REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-givenand-CMS}"
OUTPUT_DIR="../../source/quick-suite"

# Create output directories
mkdir -p "${OUTPUT_DIR}/dashboards"
mkdir -p "${OUTPUT_DIR}/datasets"

echo "Exporting Amazon Quick Suite assets from account ${ACCOUNT_ID}..."

# Export OEM Business Overview Dashboard
echo "Exporting OEM Business Overview dashboard..."
aws quicksight describe-dashboard-definition \
  --aws-account-id "${ACCOUNT_ID}" \
  --dashboard-id "32328b83-2444-4f82-8625-2b7b317bb798" \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --output json > "${OUTPUT_DIR}/dashboards/oem-business-overview.json"

# Export key datasets used by the dashboard
DATASETS=(
  "kpi-trends"
  "operational-kpis"
  "customer-health-scores"
  "at-risk-revenue"
  "top-revenue-stream"
  "customer-360"
  "issue-categories"
  "revenue-breakdown"
)

for dataset in "${DATASETS[@]}"; do
  echo "Exporting dataset: ${dataset}..."
  aws quicksight describe-data-set \
    --aws-account-id "${ACCOUNT_ID}" \
    --data-set-id "${dataset}" \
    --profile "${PROFILE}" \
    --region "${REGION}" \
    --output json > "${OUTPUT_DIR}/datasets/${dataset}.json"
done

echo ""
echo "Export complete! Assets saved to ${OUTPUT_DIR}"
echo ""
echo "Exported:"
echo "  • 1 dashboard definition (with complete formatting)"
echo "  • 8 dataset configurations"
echo ""
echo "Next steps:"
echo "1. Review exported JSON files"
echo "2. Dashboard can be deployed directly from definition (no analysis needed)"
echo "3. Run: cd deployment/scripts && ./deploy-dashboard.sh"
