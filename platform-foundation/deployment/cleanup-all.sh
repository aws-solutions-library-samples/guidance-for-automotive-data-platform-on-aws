#!/bin/bash
set -e

REGION="us-east-1"

echo "=== Cleaning up Automotive Data Platform ==="
echo "Region: $REGION"
echo ""

# Delete CloudFormation stacks
STACKS=(
    "datazone-all-blueprints"
    "datazone-blueprints"
    "datazone-blueprint-roles"
    "tire-prediction-project"
    "tire-prediction-ml-resources"
    "automotive-data-platform-datazone"
    "automotive-shared-resources"
    "automotive-data-platform-network"
)

for stack in "${STACKS[@]}"; do
    if aws cloudformation describe-stacks --region $REGION --stack-name $stack > /dev/null 2>&1; then
        echo "Deleting stack: $stack"
        aws cloudformation delete-stack --region $REGION --stack-name $stack
    fi
done

echo ""
echo "Waiting for stacks to delete..."
for stack in "${STACKS[@]}"; do
    if aws cloudformation describe-stacks --region $REGION --stack-name $stack > /dev/null 2>&1; then
        aws cloudformation wait stack-delete-complete --region $REGION --stack-name $stack 2>/dev/null || true
    fi
done

# Delete DataZone domain
DOMAIN_ID=$(aws datazone list-domains --region $REGION --query 'items[0].id' --output text 2>/dev/null || echo "")
if [ -n "$DOMAIN_ID" ] && [ "$DOMAIN_ID" != "None" ] && aws datazone get-domain --region $REGION --identifier $DOMAIN_ID > /dev/null 2>&1; then
    echo "Deleting DataZone domain: $DOMAIN_ID"
    aws datazone delete-domain --region $REGION --identifier $DOMAIN_ID
fi

echo ""
echo "✓ Cleanup complete"
