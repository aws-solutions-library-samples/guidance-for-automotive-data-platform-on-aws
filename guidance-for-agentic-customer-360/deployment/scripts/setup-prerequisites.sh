#!/bin/bash
# Prerequisites setup for Customer 360 deployment
# Run this once before make phase3

set -e

REGION=${AWS_REGION:-us-east-1}
PROFILE=${AWS_PROFILE:-default}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile $PROFILE)
BUCKET_NAME="automotive-cx-data-lake-${ACCOUNT_ID}"

echo "Setting up prerequisites for Customer 360 deployment..."
echo "Account: $ACCOUNT_ID"
echo "Region: $REGION"
echo ""

# 1. Create Glue Crawler
echo "Creating Glue crawler..."
GLUE_ROLE=$(aws iam list-roles --query 'Roles[?contains(RoleName, `cx360`) && contains(RoleName, `Glue`)].RoleName' --output text --profile $PROFILE --region $REGION | head -1)

if [ -z "$GLUE_ROLE" ]; then
    echo "  ✗ Glue role not found. Run 'make phase1' first."
    exit 1
fi

aws glue create-crawler \
    --name cx-analytics-crawler \
    --role $GLUE_ROLE \
    --database-name cx_analytics \
    --targets "{\"S3Targets\":[{\"Path\":\"s3://${BUCKET_NAME}/raw/\"}]}" \
    --schema-change-policy "{\"UpdateBehavior\":\"UPDATE_IN_DATABASE\",\"DeleteBehavior\":\"LOG\"}" \
    --region $REGION \
    --profile $PROFILE 2>/dev/null && echo "  ✓ Crawler created" || echo "  ℹ Crawler already exists"

# 2. Grant Lake Formation permissions
echo ""
echo "Granting Lake Formation permissions..."

# Get current user
USER_ARN=$(aws sts get-caller-identity --query Arn --output text --profile $PROFILE)

# Grant database permissions
aws lakeformation grant-permissions \
    --principal DataLakePrincipalIdentifier=$USER_ARN \
    --resource "{\"Database\":{\"Name\":\"cx_analytics\"}}" \
    --permissions "CREATE_TABLE" "ALTER" "DROP" \
    --region $REGION \
    --profile $PROFILE 2>/dev/null && echo "  ✓ Database permissions granted" || echo "  ℹ Permissions already exist"

# Grant table permissions
aws lakeformation grant-permissions \
    --principal DataLakePrincipalIdentifier=$USER_ARN \
    --resource "{\"Table\":{\"DatabaseName\":\"cx_analytics\",\"TableWildcard\":{}}}" \
    --permissions "SELECT" "ALTER" "DROP" "DELETE" "INSERT" \
    --region $REGION \
    --profile $PROFILE 2>/dev/null && echo "  ✓ Table permissions granted" || echo "  ℹ Permissions already exist"

# Grant permissions to Glue role
GLUE_ROLE_ARN=$(aws iam get-role --role-name $GLUE_ROLE --query 'Role.Arn' --output text --profile $PROFILE)

aws lakeformation grant-permissions \
    --principal DataLakePrincipalIdentifier=$GLUE_ROLE_ARN \
    --resource "{\"Database\":{\"Name\":\"cx_analytics\"}}" \
    --permissions "CREATE_TABLE" "ALTER" "DROP" \
    --region $REGION \
    --profile $PROFILE 2>/dev/null && echo "  ✓ Glue role database permissions granted" || echo "  ℹ Permissions already exist"

aws lakeformation grant-permissions \
    --principal DataLakePrincipalIdentifier=$GLUE_ROLE_ARN \
    --resource "{\"Table\":{\"DatabaseName\":\"cx_analytics\",\"TableWildcard\":{}}}" \
    --permissions "SELECT" "ALTER" "DROP" "DELETE" "INSERT" \
    --region $REGION \
    --profile $PROFILE 2>/dev/null && echo "  ✓ Glue role table permissions granted" || echo "  ℹ Permissions already exist"

# 3. Create QuickSight data source
echo ""
echo "Creating QuickSight data source..."

# Check if QuickSight is set up
aws quicksight list-users \
    --aws-account-id $ACCOUNT_ID \
    --namespace default \
    --region $REGION \
    --profile $PROFILE >/dev/null 2>&1 || {
    echo "  ✗ QuickSight not set up in this account"
    echo "  Please sign up for QuickSight at: https://quicksight.aws.amazon.com/"
    exit 1
}

# Create Athena data source
aws quicksight create-data-source \
    --aws-account-id $ACCOUNT_ID \
    --data-source-id cx-analytics-athena \
    --name "Customer 360 Analytics (Athena)" \
    --type ATHENA \
    --data-source-parameters "{\"AthenaParameters\":{\"WorkGroup\":\"cx-analytics-workgroup\"}}" \
    --region $REGION \
    --profile $PROFILE 2>/dev/null && echo "  ✓ QuickSight data source created" || echo "  ℹ Data source already exists"

# Grant QuickSight permissions to Lake Formation
QS_ROLE=$(aws iam list-roles --query 'Roles[?contains(RoleName, `quicksight`)].Arn' --output text --profile $PROFILE | head -1)

if [ -n "$QS_ROLE" ]; then
    aws lakeformation grant-permissions \
        --principal DataLakePrincipalIdentifier=$QS_ROLE \
        --resource "{\"Table\":{\"DatabaseName\":\"cx_analytics\",\"TableWildcard\":{}}}" \
        --permissions "SELECT" \
        --region $REGION \
        --profile $PROFILE 2>/dev/null && echo "  ✓ QuickSight Lake Formation permissions granted" || echo "  ℹ Permissions already exist"
fi

echo ""
echo "✓ Prerequisites setup complete!"
echo ""
echo "Next steps:"
echo "  1. make phase3  # Generate data"
echo "  2. make phase4  # Create QuickSight dashboard"
echo "  3. make phase5  # Deploy Bedrock Agent"
