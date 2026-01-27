#!/bin/bash
set -e

REGION="${AWS_REGION:-us-east-1}"

echo "=== Cleaning up DataZone Domain ==="

# Get domain ID
DOMAIN_ID=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-unified-studio-domain --query 'Stacks[0].Outputs[?OutputKey==`DomainId`].OutputValue' --output text 2>/dev/null || echo "")

if [ -z "$DOMAIN_ID" ]; then
    echo "No domain found"
    exit 0
fi

echo "Domain: $DOMAIN_ID"

# Delete all projects
echo "Deleting projects..."
PROJECTS=$(aws datazone list-projects --region $REGION --domain-identifier $DOMAIN_ID --query 'items[].id' --output text)
for PROJECT_ID in $PROJECTS; do
    echo "  Project: $PROJECT_ID"
    
    # Delete environments
    ENVS=$(aws datazone list-environments --region $REGION --domain-identifier $DOMAIN_ID --project-identifier $PROJECT_ID --query 'items[].id' --output text 2>/dev/null || echo "")
    for ENV_ID in $ENVS; do
        echo "    Deleting environment: $ENV_ID"
        aws datazone delete-environment --region $REGION --domain-identifier $DOMAIN_ID --identifier $ENV_ID 2>/dev/null || echo "    Failed to delete"
    done
    
    # Wait and delete project
    sleep 5
    aws datazone delete-project --region $REGION --domain-identifier $DOMAIN_ID --identifier $PROJECT_ID 2>/dev/null || echo "  Failed to delete project"
done

# Delete policy grants stack
echo "Deleting policy grants..."
aws cloudformation delete-stack --region $REGION --stack-name automotive-policy-grants 2>/dev/null || true

# Delete domain stack
echo "Deleting domain..."
aws cloudformation delete-stack --region $REGION --stack-name automotive-unified-studio-domain

echo ""
echo "⚠️  If deletion fails due to stuck resources:"
echo "  1. Go to DataZone console"
echo "  2. Manually delete projects and environments"
echo "  3. Re-run: make clean"
