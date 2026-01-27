#!/bin/bash

# Deploy Amazon Quick Suite Dashboard from Template
# This script creates the OEM Business Overview dashboard with all formatting

set -e

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-default}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_FILE="${SCRIPT_DIR}/../../source/quick-suite/dashboards/oem-business-overview.json"

echo "🚀 Deploying Amazon Quick Suite Dashboard"
echo "=========================================="
echo "Account: ${ACCOUNT_ID}"
echo "Region: ${REGION}"
echo ""

# Check if template exists
if [ ! -f "${TEMPLATE_FILE}" ]; then
  echo "❌ Dashboard template not found: ${TEMPLATE_FILE}"
  echo "Run: cd deployment/scripts && ./export-quick-suite-assets.sh"
  exit 1
fi

# Get Quick Suite username
QS_USERNAME="${QUICKSIGHT_USERNAME:-admin}"
QS_USER_ARN="arn:aws:quicksight:${REGION}:${ACCOUNT_ID}:user/default/${QS_USERNAME}"

echo "Using Quick Suite user: ${QS_USERNAME}"
echo ""

# Parameterize the template (replace account IDs and regions)
echo "Preparing dashboard template..."
TEMP_FILE=$(mktemp)
cat "${TEMPLATE_FILE}" | \
  sed "s/022035076260/${ACCOUNT_ID}/g" | \
  sed "s/us-east-1/${REGION}/g" > "${TEMP_FILE}"

# Extract definition
DEFINITION=$(cat "${TEMP_FILE}" | jq '.Definition')

# Create dashboard from template
echo "Creating OEM Business Overview dashboard..."
DASHBOARD_ID="oem-business-overview-${ACCOUNT_ID}"

aws quicksight create-dashboard \
  --aws-account-id "${ACCOUNT_ID}" \
  --dashboard-id "${DASHBOARD_ID}" \
  --name "OEM Business Overview" \
  --definition "${DEFINITION}" \
  --permissions "[{
    \"Principal\": \"${QS_USER_ARN}\",
    \"Actions\": [
      \"quicksight:DescribeDashboard\",
      \"quicksight:ListDashboardVersions\",
      \"quicksight:UpdateDashboardPermissions\",
      \"quicksight:QueryDashboard\",
      \"quicksight:UpdateDashboard\",
      \"quicksight:DeleteDashboard\",
      \"quicksight:DescribeDashboardPermissions\",
      \"quicksight:UpdateDashboardPublishedVersion\"
    ]
  }]" \
  --profile "${PROFILE}" \
  --region "${REGION}" 2>&1 | tee /tmp/dashboard-create.log

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ Dashboard created successfully!"
  echo ""
  echo "Dashboard ID: ${DASHBOARD_ID}"
  echo "URL: https://${REGION}.quicksight.aws.amazon.com/sn/dashboards/${DASHBOARD_ID}"
  echo ""
  echo "The dashboard includes:"
  echo "  • Executive Overview sheet (20+ KPIs)"
  echo "  • Customer 360 sheet"
  echo "  • All formatting and visualizations preserved"
else
  echo ""
  echo "⚠️  Dashboard creation failed. Check error above."
  echo ""
  echo "Common issues:"
  echo "  - Datasets not created yet (run: make phase4 first)"
  echo "  - Dashboard already exists (delete it first)"
  echo "  - Permissions issue (check Quick Suite user)"
  
  # Check if it's a "already exists" error
  if grep -q "already exists" /tmp/dashboard-create.log; then
    echo ""
    echo "Dashboard already exists. To update:"
    echo "  aws quicksight update-dashboard --aws-account-id ${ACCOUNT_ID} --dashboard-id ${DASHBOARD_ID} ..."
  fi
fi

# Cleanup
rm -f "${TEMP_FILE}"
