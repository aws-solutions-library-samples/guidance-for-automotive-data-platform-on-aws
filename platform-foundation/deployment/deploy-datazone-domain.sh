#!/bin/bash

# Deploy DataZone Domain via CloudFormation
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-default}"
DATAZONE_STACK_NAME="automotive-data-platform-datazone"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}DataZone Domain Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Load network stack outputs
if [ -f "deployment/stack-outputs.env" ]; then
    source deployment/stack-outputs.env
else
    echo -e "${RED}Error: Network stack outputs not found${NC}"
    echo "Run 'make deploy-network' first"
    exit 1
fi

# Get IAM Identity Center instance ARN
echo -e "${YELLOW}Getting IAM Identity Center instance...${NC}"
IDC_INSTANCE_ARN=$(aws sso-admin list-instances \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'Instances[0].InstanceArn' \
    --output text)

if [ -z "$IDC_INSTANCE_ARN" ] || [ "$IDC_INSTANCE_ARN" == "None" ]; then
    echo -e "${RED}Error: IAM Identity Center not configured${NC}"
    echo "Please enable IAM Identity Center first"
    exit 1
fi

echo -e "${GREEN}✓ IAM Identity Center: $IDC_INSTANCE_ARN${NC}"
echo ""

# Get first 3 subnet IDs
SUBNET_ARRAY=($(echo $SUBNET_IDS | tr ',' ' '))
SUBNET1=${SUBNET_ARRAY[0]}
SUBNET2=${SUBNET_ARRAY[1]}
SUBNET3=${SUBNET_ARRAY[2]:-${SUBNET_ARRAY[1]}}

# Deploy CloudFormation stack
echo -e "${YELLOW}Deploying DataZone domain...${NC}"
aws cloudformation deploy \
    --template-file cloudformation/datazone-domain.yaml \
    --stack-name $DATAZONE_STACK_NAME \
    --parameter-overrides \
        DomainName=automotive-data-platform \
        VpcId=$VPC_ID \
        SubnetIds="$SUBNET1,$SUBNET2,$SUBNET3" \
        IdentityCenterInstanceArn=$IDC_INSTANCE_ARN \
    --capabilities CAPABILITY_NAMED_IAM \
    --region $AWS_REGION \
    --profile $AWS_PROFILE

echo ""
echo -e "${GREEN}✓ Domain deployment initiated${NC}"
echo -e "${YELLOW}Waiting for domain to be ready (10-15 minutes)...${NC}"

# Wait for stack completion
aws cloudformation wait stack-create-complete \
    --stack-name $DATAZONE_STACK_NAME \
    --region $AWS_REGION \
    --profile $AWS_PROFILE 2>/dev/null || \
aws cloudformation wait stack-update-complete \
    --stack-name $DATAZONE_STACK_NAME \
    --region $AWS_REGION \
    --profile $AWS_PROFILE 2>/dev/null || true

# Get stack outputs
DOMAIN_ID=$(aws cloudformation describe-stacks \
    --stack-name $DATAZONE_STACK_NAME \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'Stacks[0].Outputs[?OutputKey==`DomainId`].OutputValue' \
    --output text)

PORTAL_URL=$(aws cloudformation describe-stacks \
    --stack-name $DATAZONE_STACK_NAME \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'Stacks[0].Outputs[?OutputKey==`PortalUrl`].OutputValue' \
    --output text)

EXECUTION_ROLE_ARN=$(aws cloudformation describe-stacks \
    --stack-name $DATAZONE_STACK_NAME \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'Stacks[0].Outputs[?OutputKey==`DomainExecutionRoleArn`].OutputValue' \
    --output text)

# Save outputs
cat >> deployment/stack-outputs.env << EOF

# DataZone Domain
export DATAZONE_DOMAIN_ID="$DOMAIN_ID"
export PORTAL_URL="$PORTAL_URL"
export DOMAIN_EXECUTION_ROLE_ARN="$EXECUTION_ROLE_ARN"
EOF

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Domain Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Domain ID:       ${GREEN}$DOMAIN_ID${NC}"
echo -e "Portal URL:      ${GREEN}$PORTAL_URL${NC}"
echo -e "Execution Role:  ${GREEN}$EXECUTION_ROLE_ARN${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Create SSO user: DEFAULT_EMAIL=your@email.com ./deployment/create-user-profile.sh"
echo "2. User logs in at: $PORTAL_URL"
echo ""
