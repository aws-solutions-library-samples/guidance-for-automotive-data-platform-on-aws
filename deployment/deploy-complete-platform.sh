#!/bin/bash

# Complete Automotive Data Platform Deployment
# This script deploys both the base infrastructure and SageMaker domain

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Complete Platform Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Step 1: Deploy base infrastructure
echo -e "${GREEN}Step 1/2: Deploying base infrastructure...${NC}"
./deployment/deploy-base-platform.sh

if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to deploy base infrastructure${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✓ Base infrastructure deployed${NC}"
echo ""

# Step 2: Create SageMaker domain
echo -e "${GREEN}Step 2/2: Creating SageMaker Unified Studio domain...${NC}"
./deployment/create-sagemaker-domain.sh

if [ $? -ne 0 ]; then
    echo -e "${YELLOW}Automated domain creation failed${NC}"
    echo -e "${YELLOW}Please create domain manually via AWS Console${NC}"
    echo ""
    echo "Use these values:"
    source deployment/stack-outputs.env
    echo "  VPC ID: $VPC_ID"
    echo "  Domain Name: automotive-data-platform"
    echo ""
    echo "Console: https://console.aws.amazon.com/sagemaker"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}🎉 Platform Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Load final outputs
source deployment/stack-outputs.env

echo -e "${GREEN}Platform Details:${NC}"
echo "  VPC ID: $VPC_ID"
echo "  Domain ID: $DOMAIN_ID"
echo "  Portal URL: $DOMAIN_URL"
echo ""

echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Configure IAM Identity Center users:"
echo "   https://console.aws.amazon.com/singlesignon"
echo ""
echo "2. Create user groups:"
echo "   - automotive-data-engineers"
echo "   - automotive-ml-engineers"
echo "   - automotive-admins"
echo ""
echo "3. Assign groups to SageMaker domain"
echo ""
echo "4. Share portal URL with users:"
echo "   $DOMAIN_URL"
echo ""
echo "5. Deploy tire prediction project:"
echo "   cd ../automotive-tire-prediction-model-on-aws"
echo ""

echo -e "${GREEN}For detailed instructions, see README.md${NC}"
