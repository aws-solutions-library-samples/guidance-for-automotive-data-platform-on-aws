#!/bin/bash

# Recreate SageMaker Domain with SSO Authentication
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-default}"

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Recreating Domain with SSO Auth${NC}"
echo -e "${YELLOW}========================================${NC}"
echo ""

# Load stack outputs
if [ -f "deployment/stack-outputs.env" ]; then
    source deployment/stack-outputs.env
else
    echo -e "${RED}Error: Stack outputs not found${NC}"
    exit 1
fi

if [ -z "$DOMAIN_ID" ]; then
    echo -e "${RED}Error: No existing domain found${NC}"
    exit 1
fi

# Check current auth mode
CURRENT_AUTH=$(aws sagemaker describe-domain \
    --domain-id $DOMAIN_ID \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'AuthMode' \
    --output text 2>/dev/null || echo "")

echo "Current domain: $DOMAIN_ID"
echo "Current auth mode: $CURRENT_AUTH"
echo ""

if [ "$CURRENT_AUTH" == "SSO" ]; then
    echo -e "${GREEN}Domain already uses SSO authentication${NC}"
    exit 0
fi

echo -e "${YELLOW}Deleting existing IAM-mode domain...${NC}"
aws sagemaker delete-domain \
    --domain-id $DOMAIN_ID \
    --region $AWS_REGION \
    --profile $AWS_PROFILE

echo -e "${YELLOW}Waiting for domain deletion (this may take 5-10 minutes)...${NC}"
sleep 30

# Wait for deletion
while true; do
    STATUS=$(aws sagemaker describe-domain \
        --domain-id $DOMAIN_ID \
        --region $AWS_REGION \
        --profile $AWS_PROFILE \
        --query 'Status' \
        --output text 2>&1 || echo "DELETED")
    
    if echo "$STATUS" | grep -q "could not be found\|DELETED"; then
        echo -e "${GREEN}✓ Domain deleted${NC}"
        break
    fi
    
    echo "Status: $STATUS - waiting..."
    sleep 30
done

echo ""
echo -e "${GREEN}Now run: make deploy-domain${NC}"
echo ""
