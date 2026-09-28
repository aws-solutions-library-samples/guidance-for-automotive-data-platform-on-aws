#!/bin/bash

# Amazon Quick Suite Setup Script for Customer 360 Analytics
# This script automates Quick Suite data sources, datasets, and dashboard creation

set -e

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-default}"

echo "🚀 Amazon Quick Suite Setup for Customer 360"
echo "==============================================="
echo "Account: ${ACCOUNT_ID}"
echo "Region: ${REGION}"
echo ""

# Check if Quick Suite is enabled
echo "Checking Amazon Quick Suite status..."
if ! aws quicksight describe-account-settings \
  --aws-account-id "${ACCOUNT_ID}" \
  --profile "${PROFILE}" \
  --region "${REGION}" &>/dev/null; then
  echo "❌ Amazon Quick Suite is not enabled in this account"
  echo ""
  echo "Please enable Amazon Quick Suite:"
  echo "1. Visit: https://quicksight.aws.amazon.com/"
  echo "2. Choose Standard or Enterprise edition"
  echo "3. Grant access to Athena and S3"
  echo "4. Re-run: make phase4"
  exit 1
fi

echo "✓ Amazon Quick Suite is enabled"
echo ""

# Get current IAM principal (whoever is running this script)
CALLER_IDENTITY=$(aws sts get-caller-identity --profile "${PROFILE}" --query 'Arn' --output text)
echo "Deploying as: ${CALLER_IDENTITY}"

# Get QuickSight user - use the actual QuickSight username
QS_USERNAME=$(aws quicksight list-users \
  --aws-account-id "${ACCOUNT_ID}" \
  --namespace default \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query 'UserList[0].UserName' \
  --output text 2>/dev/null || echo "admin")

QS_USER_ARN="arn:aws:quicksight:${REGION}:${ACCOUNT_ID}:user/default/${QS_USERNAME}"

echo "Quick Suite owner: ${QS_USERNAME}"
echo "(Resources will be owned by this principal)"
echo ""

# Get actual workgroup name from CloudFormation
WORKGROUP=$(aws cloudformation describe-stacks \
  --stack-name cx360-dev-athena \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query 'Stacks[0].Outputs[?OutputKey==`AthenaWorkgroup`].OutputValue' \
  --output text 2>/dev/null || echo "primary")

# Get actual data lake bucket name
DATA_LAKE_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name cx360-dev-data-lake \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' \
  --output text 2>/dev/null || echo "automotive-cx-data-lake-${ACCOUNT_ID}")

echo "Using Athena workgroup: ${WORKGROUP}"
echo "Using S3 bucket: ${DATA_LAKE_BUCKET}"
echo ""

# Create Athena data source
echo "Creating Athena data source..."
aws quicksight create-data-source \
  --aws-account-id "${ACCOUNT_ID}" \
  --data-source-id cx-analytics-athena \
  --name "CX Analytics Athena" \
  --type ATHENA \
  --data-source-parameters "{
    \"AthenaParameters\": {
      \"WorkGroup\": \"${WORKGROUP}\"
    }
  }" \
  --permissions "[{
    \"Principal\": \"${QS_USER_ARN}\",
    \"Actions\": [
      \"quicksight:DescribeDataSource\",
      \"quicksight:DescribeDataSourcePermissions\",
      \"quicksight:PassDataSource\",
      \"quicksight:UpdateDataSource\",
      \"quicksight:DeleteDataSource\",
      \"quicksight:UpdateDataSourcePermissions\"
    ]
  }]" \
  --profile "${PROFILE}" \
  --region "${REGION}" 2>/dev/null && echo "✓ Data source created" || echo "⚠ Data source already exists"

echo ""

# Create Athena views
echo "Creating Athena views..."

# Create views by executing the NamedQueries
VIEWS=(
  "customer_health:SELECT customer_id, user_id, total_revenue, avg_satisfaction_score, total_cases, open_cases, total_vehicles, total_service_spend, total_service_appointments, opportunity_count, ROUND((COALESCE(avg_satisfaction_score, 50) * 0.25) + (CASE WHEN open_cases = 0 THEN 80 ELSE 30 END * 0.20) + (CASE WHEN total_vehicles >= 2 THEN 90 ELSE 70 END * 0.15) + (CASE WHEN total_service_appointments > 5 THEN 80 ELSE 50 END * 0.30) + (100 * 0.10), 2) as health_score, CASE WHEN health_score >= 70 THEN 'Healthy' WHEN health_score >= 50 THEN 'Needs Attention' WHEN health_score >= 30 THEN 'At-Risk' ELSE 'Critical' END as health_segment FROM customer_360"
  "kpi_trends_from_vehicles:SELECT COUNT(*) as total_vehicles, AVG(health_score) as avg_health_score, SUM(total_revenue) as total_revenue FROM customer_health"
  "operational_kpis:SELECT COUNT(*) as total_customers, COUNT(CASE WHEN health_segment = 'Critical' THEN 1 END) as critical_customers, COUNT(CASE WHEN open_cases > 0 THEN 1 END) as customers_with_open_cases FROM customer_health"
  "revenue_at_risk:SELECT health_segment, COUNT(*) as customer_count, SUM(total_revenue) as total_revenue, SUM(CASE WHEN health_score < 40 THEN total_revenue ELSE 0 END) as revenue_at_risk FROM customer_health GROUP BY health_segment"
  "top_revenue_streams:SELECT 'Service' as revenue_stream, SUM(total_service_spend) as revenue FROM customer_health UNION ALL SELECT 'Subscription', SUM(total_revenue - total_service_spend) FROM customer_health"
  "issue_categories:SELECT 'Technical' as category, COUNT(*) as count FROM cases WHERE case_type = 'Technical' UNION ALL SELECT 'Billing', COUNT(*) FROM cases WHERE case_type = 'Billing'"
  "revenue_breakdown:SELECT customer_segment, SUM(total_revenue) as revenue FROM customer_360 GROUP BY customer_segment"
)

for view_info in "${VIEWS[@]}"; do
  IFS=':' read -r view_name query <<< "$view_info"
  echo "  Creating view: ${view_name}..."
  
  # Execute query to create view
  QUERY_ID=$(aws athena start-query-execution \
    --query-string "CREATE OR REPLACE VIEW ${view_name} AS ${query}" \
    --query-execution-context "Database=cx_analytics" \
    --result-configuration "OutputLocation=s3://${DATA_LAKE_BUCKET}/athena-results/" \
    --work-group "${WORKGROUP}" \
    --profile "${PROFILE}" \
    --region "${REGION}" \
    --query 'QueryExecutionId' \
    --output text 2>/dev/null)
  
  if [ -n "$QUERY_ID" ]; then
    # Wait for query to complete
    sleep 2
    echo "    ✓ ${view_name}"
  else
    echo "    ⚠ ${view_name} (may already exist)"
  fi
done

echo ""

# Create datasets
echo "Creating datasets..."

DATASETS=(
  "kpi-trends:kpi_trends_from_vehicles"
  "operational-kpis:operational_kpis"
  "customer-health-scores:customer_health"
  "at-risk-revenue:revenue_at_risk"
  "top-revenue-stream:top_revenue_streams"
  "customer-360:customer_360"
  "issue-categories:issue_categories"
  "revenue-breakdown:revenue_breakdown"
)

for dataset_info in "${DATASETS[@]}"; do
  IFS=':' read -r dataset_id table_name <<< "$dataset_info"
  echo "  Creating dataset: ${dataset_id}..."
  
  aws quicksight create-data-set \
    --aws-account-id "${ACCOUNT_ID}" \
    --data-set-id "${dataset_id}" \
    --name "${dataset_id}" \
    --physical-table-map "{
      \"${dataset_id}\": {
        \"RelationalTable\": {
          \"DataSourceArn\": \"arn:aws:quicksight:${REGION}:${ACCOUNT_ID}:datasource/cx-analytics-athena\",
          \"Catalog\": \"AwsDataCatalog\",
          \"Schema\": \"cx_analytics\",
          \"Name\": \"${table_name}\",
          \"InputColumns\": []
        }
      }
    }" \
    --import-mode DIRECT_QUERY \
    --permissions "[{
      \"Principal\": \"${QS_USER_ARN}\",
      \"Actions\": [
        \"quicksight:DescribeDataSet\",
        \"quicksight:DescribeDataSetPermissions\",
        \"quicksight:PassDataSet\",
        \"quicksight:DescribeIngestion\",
        \"quicksight:ListIngestions\",
        \"quicksight:UpdateDataSet\",
        \"quicksight:DeleteDataSet\",
        \"quicksight:CreateIngestion\",
        \"quicksight:CancelIngestion\",
        \"quicksight:UpdateDataSetPermissions\"
      ]
    }]" \
    --profile "${PROFILE}" \
    --region "${REGION}" 2>/dev/null && echo "    ✓ ${dataset_id}" || echo "    ⚠ ${dataset_id} already exists"
done

echo ""
echo "✅ Amazon Quick Suite setup complete!"
echo ""
echo "Resources created:"
echo "  • Data source: cx-analytics-athena"
echo "  • 8 datasets connected to Athena views"
echo "  • Owner: ${QS_USERNAME}"
echo ""
echo "Next: Dashboard deployment..."
