#!/bin/bash

# Add user as DataZone domain owner
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-default}"

if [ -z "$DEFAULT_EMAIL" ]; then
    echo -e "${RED}Error: DEFAULT_EMAIL not set${NC}"
    exit 1
fi

# Load domain info
if [ -f "deployment/stack-outputs.env" ]; then
    source deployment/stack-outputs.env
else
    echo -e "${RED}Error: Stack outputs not found${NC}"
    exit 1
fi

if [ -z "$DATAZONE_DOMAIN_ID" ]; then
    echo -e "${RED}Error: DataZone domain not deployed${NC}"
    exit 1
fi

echo -e "${GREEN}Adding user as domain owner...${NC}"

# Get user ID
IDENTITY_STORE_ID=$(aws sso-admin list-instances \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'Instances[0].IdentityStoreId' \
    --output text)

SSO_USER_ID=$(aws identitystore list-users \
    --identity-store-id $IDENTITY_STORE_ID \
    --filters AttributePath=UserName,AttributeValue=$DEFAULT_EMAIL \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'Users[0].UserId' \
    --output text)

if [ -z "$SSO_USER_ID" ] || [ "$SSO_USER_ID" == "None" ]; then
    echo -e "${RED}Error: User not found${NC}"
    exit 1
fi

# Get root domain unit ID from stack outputs
ROOT_DOMAIN_UNIT_ID=$(aws cloudformation describe-stacks \
    --stack-name automotive-data-platform-datazone \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'Stacks[0].Outputs[?OutputKey==`RootDomainUnitId`].OutputValue' \
    --output text)

echo "Domain: $DATAZONE_DOMAIN_ID"
echo "Root Domain Unit: $ROOT_DOMAIN_UNIT_ID"
echo "User: $DEFAULT_EMAIL ($SSO_USER_ID)"
echo ""

# Add user as owner
aws datazone add-entity-owner \
    --domain-identifier $DATAZONE_DOMAIN_ID \
    --entity-identifier $ROOT_DOMAIN_UNIT_ID \
    --entity-type DOMAIN_UNIT \
    --owner "{\"user\":{\"userIdentifier\":\"$SSO_USER_ID\"}}" \
    --region $AWS_REGION \
    --profile $AWS_PROFILE

echo -e "${GREEN}✓ User added as domain owner${NC}"
