#!/bin/bash

# Update QuickSight datasets to use new Athena views
# Uses environment variables for account configuration

ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
REGION="${AWS_REGION:-us-east-1}"
DATA_SOURCE_ARN="arn:aws:quicksight:${REGION}:${ACCOUNT_ID}:datasource/cx-analytics-athena"

# Dataset mappings: dataset-id -> view-name
declare -A DATASETS
DATASETS["kpi-trends"]="kpi_trends"
DATASETS["operational-kpis"]="operational_kpis"
DATASETS["customer-health-scores"]="customer_health_scores"
DATASETS["at-risk-revenue"]="at_risk_revenue_view"
DATASETS["customer-360"]="customer_360_view"
DATASETS["issue-categories"]="issue_categories_view"
DATASETS["revenue-breakdown"]="revenue_breakdown"
DATASETS["top-revenue-stream"]="top_revenue_stream"

echo "Updating QuickSight datasets..."
echo "================================"

for dataset_id in "${!DATASETS[@]}"; do
    view_name="${DATASETS[$dataset_id]}"
    echo ""
    echo "Updating dataset: $dataset_id -> view: $view_name"
    
    # Delete existing dataset
    aws quicksight delete-data-set \
        --aws-account-id $ACCOUNT_ID \
        --data-set-id $dataset_id \
        --region $REGION 2>/dev/null
    
    sleep 2
    
    # Create new dataset with updated schema
    aws quicksight create-data-set \
        --aws-account-id $ACCOUNT_ID \
        --data-set-id $dataset_id \
        --name $dataset_id \
        --physical-table-map "{
            \"$dataset_id\": {
                \"RelationalTable\": {
                    \"DataSourceArn\": \"$DATA_SOURCE_ARN\",
                    \"Catalog\": \"AwsDataCatalog\",
                    \"Schema\": \"cx_analytics\",
                    \"Name\": \"$view_name\",
                    \"InputColumns\": []
                }
            }
        }" \
        --import-mode DIRECT_QUERY \
        --region $REGION \
        --query 'Status' \
        --output text
    
    if [ $? -eq 0 ]; then
        echo "  ✓ Dataset $dataset_id updated successfully"
    else
        echo "  ✗ Failed to update dataset $dataset_id"
    fi
done

echo ""
echo "================================"
echo "Dataset update complete!"
echo ""
echo "Next step: Import dashboard definition"
