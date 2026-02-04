#!/bin/bash
# Create Athena tables and views for QuickSight dashboard
# Usage: ./create_athena_tables.sh <bucket-name> <aws-profile> <aws-region>

set -e

BUCKET=$1
PROFILE=${2:-default}
REGION=${3:-us-east-1}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DDL_DIR="$SCRIPT_DIR/../athena-queries/ddl/simple"

echo "Creating Athena tables and views..."
echo "Bucket: $BUCKET"
echo "Profile: $PROFILE"
echo "Region: $REGION"

# Function to execute Athena query
run_query() {
    local sql="$1"
    local query_id=$(aws athena start-query-execution \
        --query-string "$sql" \
        --query-execution-context Database=cx_analytics \
        --result-configuration OutputLocation=s3://$BUCKET/athena-results/ \
        --work-group primary \
        --region $REGION \
        --profile $PROFILE \
        --query 'QueryExecutionId' --output text)
    
    # Wait for completion
    while true; do
        status=$(aws athena get-query-execution \
            --query-execution-id $query_id \
            --region $REGION \
            --profile $PROFILE \
            --query 'QueryExecution.Status.State' --output text)
        
        if [ "$status" = "SUCCEEDED" ]; then
            echo "  ✓ Query succeeded"
            break
        elif [ "$status" = "FAILED" ] || [ "$status" = "CANCELLED" ]; then
            echo "  ✗ Query failed"
            aws athena get-query-execution \
                --query-execution-id $query_id \
                --region $REGION \
                --profile $PROFILE \
                --query 'QueryExecution.Status.StateChangeReason' --output text
            return 1
        fi
        sleep 2
    done
}

# Create tables first
echo ""
echo "Creating tables..."
for file in "$DDL_DIR/tables"/*.sql; do
    if [ -f "$file" ]; then
        table_name=$(basename "$file" .sql)
        echo "  Creating table: $table_name"
        sql=$(cat "$file" | sed "s|\${BUCKET}|$BUCKET|g")
        run_query "$sql"
    fi
done

# Create views
echo ""
echo "Creating views..."
for file in "$DDL_DIR/views"/*.sql; do
    if [ -f "$file" ]; then
        view_name=$(basename "$file" .sql)
        echo "  Creating view: $view_name"
        sql=$(cat "$file")
        run_query "$sql"
    fi
done

echo ""
echo "✓ All tables and views created successfully"
