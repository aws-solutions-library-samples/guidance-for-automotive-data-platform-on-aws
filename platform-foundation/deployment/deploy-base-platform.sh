#!/bin/bash

# Automotive Data Platform - Base Infrastructure Deployment Script
# This script deploys the foundational VPC and networking for SageMaker Unified Studio

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
STACK_NAME="automotive-data-platform-network"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-default}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Automotive Data Platform Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Stack Name: $STACK_NAME"
echo "Region: $AWS_REGION"
echo "Profile: $AWS_PROFILE"
echo ""

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo -e "${RED}Error: AWS CLI is not installed${NC}"
    exit 1
fi

# Check if template exists
TEMPLATE_FILE="deployment/sagemaker_us_guidance_network_setup.yaml"
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo -e "${RED}Error: Template file not found: $TEMPLATE_FILE${NC}"
    exit 1
fi

# Check if stack already exists
echo -e "${YELLOW}Checking if stack already exists...${NC}"
if aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $AWS_REGION \
    --profile $AWS_PROFILE &> /dev/null; then
    
    echo -e "${YELLOW}Stack $STACK_NAME already exists${NC}"
    read -p "Do you want to update it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        ACTION="update"
    else
        echo -e "${YELLOW}Deployment cancelled${NC}"
        exit 0
    fi
else
    ACTION="create"
fi

# Deploy stack
if [ "$ACTION" == "create" ]; then
    echo -e "${GREEN}Creating CloudFormation stack...${NC}"
    aws cloudformation create-stack \
        --stack-name $STACK_NAME \
        --template-body file://$TEMPLATE_FILE \
        --capabilities CAPABILITY_IAM \
        --region $AWS_REGION \
        --profile $AWS_PROFILE
    
    echo -e "${YELLOW}Waiting for stack creation to complete...${NC}"
    aws cloudformation wait stack-create-complete \
        --stack-name $STACK_NAME \
        --region $AWS_REGION \
        --profile $AWS_PROFILE
else
    echo -e "${GREEN}Updating CloudFormation stack...${NC}"
    UPDATE_OUTPUT=$(aws cloudformation update-stack \
        --stack-name $STACK_NAME \
        --template-body file://$TEMPLATE_FILE \
        --capabilities CAPABILITY_IAM \
        --region $AWS_REGION \
        --profile $AWS_PROFILE 2>&1 || true)
    
    if echo "$UPDATE_OUTPUT" | grep -q "No updates are to be performed"; then
        echo -e "${GREEN}✓ Stack is already up to date${NC}"
        ACTION="none"
    elif echo "$UPDATE_OUTPUT" | grep -q "error\|Error"; then
        echo -e "${RED}Error updating stack: $UPDATE_OUTPUT${NC}"
        exit 1
    else
        echo -e "${YELLOW}Waiting for stack update to complete...${NC}"
        aws cloudformation wait stack-update-complete \
            --stack-name $STACK_NAME \
            --region $AWS_REGION \
            --profile $AWS_PROFILE || true
    fi
fi

# Get stack outputs
if [ "$ACTION" != "none" ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}Deployment Complete!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
fi

echo -e "${GREEN}Stack Outputs:${NC}"

# Get VPC ID from stack resources (not outputs)
VPC_ID=$(aws cloudformation describe-stack-resources \
    --stack-name $STACK_NAME \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'StackResources[?ResourceType==`AWS::EC2::VPC`].PhysicalResourceId' \
    --output text)

# Get Subnet IDs from stack resources
SUBNET_IDS=$(aws cloudformation describe-stack-resources \
    --stack-name $STACK_NAME \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'StackResources[?ResourceType==`AWS::EC2::Subnet`].PhysicalResourceId' \
    --output text | tr '\t' ',')

echo "VPC ID: $VPC_ID"
echo "Subnet IDs: $SUBNET_IDS"
echo ""

# Save outputs to file
cat > deployment/stack-outputs.env << EOF
# Automotive Data Platform Stack Outputs
# Generated: $(date)
export VPC_ID="$VPC_ID"
export SUBNET_IDS="$SUBNET_IDS"
export AWS_REGION="$AWS_REGION"
export STACK_NAME="$STACK_NAME"
EOF

echo -e "${GREEN}Outputs saved to: deployment/stack-outputs.env${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Source the outputs: source deployment/stack-outputs.env"
echo "2. Create SageMaker Unified Studio domain in AWS Console"
echo "3. Use VPC ID and Subnet IDs from above"
echo "4. Configure IAM Identity Center users"
echo "5. Deploy your first project (tire prediction)"
echo ""
echo -e "${GREEN}For detailed instructions, see README.md${NC}"
