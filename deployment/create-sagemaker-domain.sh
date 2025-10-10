#!/bin/bash

# Automated SageMaker Unified Studio Domain Creation
# Note: This uses AWS CLI as CloudFormation/CDK support is not yet available

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Configuration
DOMAIN_NAME="${DOMAIN_NAME:-automotive-data-platform}"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-default}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}SageMaker Unified Studio Domain Setup${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check for existing domain first
EXISTING_DOMAIN=$(aws datazone list-domains --region $AWS_REGION --query 'items[0].{Id:id,Name:name}' --output json 2>/dev/null || echo '{}')
DOMAIN_ID=$(echo "$EXISTING_DOMAIN" | jq -r '.Id // empty')

if [ ! -z "$DOMAIN_ID" ] && [ "$DOMAIN_ID" != "null" ]; then
    DOMAIN_NAME=$(echo "$EXISTING_DOMAIN" | jq -r '.Name')
    echo -e "${GREEN}✓ Found existing domain: $DOMAIN_NAME ($DOMAIN_ID)${NC}"
    
    # Create outputs file
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    cat > deployment/datazone-outputs.env << EOF
DOMAIN_ID=$DOMAIN_ID
DOMAIN_ARN=arn:aws:datazone:$AWS_REGION:$ACCOUNT_ID:domain/$DOMAIN_ID
DOMAIN_PORTAL_URL=https://$DOMAIN_ID.datazone.$AWS_REGION.on.aws
EOF
    
    echo -e "${GREEN}✓ Using existing domain${NC}"
    exit 0
fi

echo "No existing domain found. Creating new domain..."
echo ""

echo -e "${GREEN}========================================${NC}"
echo ""

# Load stack outputs
if [ -f "deployment/stack-outputs.env" ]; then
    source deployment/stack-outputs.env
    echo -e "${GREEN}✓ Loaded stack outputs${NC}"
else
    echo -e "${RED}Error: Stack outputs not found. Run deploy-base-platform.sh first${NC}"
    exit 1
fi

# Verify VPC and subnets
if [ -z "$VPC_ID" ]; then
    echo -e "${RED}Error: VPC_ID not set${NC}"
    exit 1
fi

# Get subnet IDs as array - get first 3 subnets in VPC
SUBNET_ARRAY=($(aws ec2 describe-subnets \
    --filters "Name=vpc-id,Values=$VPC_ID" \
    --query 'Subnets[0:3].SubnetId' \
    --output text \
    --region $AWS_REGION \
    --profile $AWS_PROFILE))

if [ ${#SUBNET_ARRAY[@]} -lt 2 ]; then
    echo -e "${RED}Error: Need at least 2 subnets, found ${#SUBNET_ARRAY[@]}${NC}"
    echo "Available subnets in VPC $VPC_ID:"
    aws ec2 describe-subnets \
        --filters "Name=vpc-id,Values=$VPC_ID" \
        --query 'Subnets[*].[SubnetId,AvailabilityZone,CidrBlock]' \
        --output table \
        --region $AWS_REGION \
        --profile $AWS_PROFILE
    exit 1
fi

echo "VPC ID: $VPC_ID"
echo "Subnets: ${SUBNET_ARRAY[@]}"
echo ""

# Check if IAM Identity Center is configured
echo -e "${YELLOW}Checking IAM Identity Center...${NC}"
IDENTITY_STORE_ID=$(aws sso-admin list-instances \
    --query 'Instances[0].IdentityStoreId' \
    --output text \
    --region $AWS_REGION \
    --profile $AWS_PROFILE 2>/dev/null || echo "")

if [ -z "$IDENTITY_STORE_ID" ] || [ "$IDENTITY_STORE_ID" == "None" ]; then
    echo -e "${RED}Error: IAM Identity Center not configured${NC}"
    echo "Please set up IAM Identity Center first:"
    echo "https://console.aws.amazon.com/singlesignon"
    exit 1
fi

echo -e "${GREEN}✓ IAM Identity Center found: $IDENTITY_STORE_ID${NC}"
echo ""

# Get execution role ARN (create if doesn't exist)
echo -e "${YELLOW}Setting up execution role...${NC}"
ROLE_NAME="SageMakerUnifiedStudioExecutionRole"

# Check if role exists
if aws iam get-role --role-name $ROLE_NAME --profile $AWS_PROFILE &>/dev/null; then
    EXECUTION_ROLE_ARN=$(aws iam get-role \
        --role-name $ROLE_NAME \
        --query 'Role.Arn' \
        --output text \
        --profile $AWS_PROFILE)
    echo -e "${GREEN}✓ Using existing role: $EXECUTION_ROLE_ARN${NC}"
else
    echo -e "${YELLOW}Creating execution role...${NC}"
    
    # Create trust policy
    cat > /tmp/trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "sagemaker.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

    # Create role
    EXECUTION_ROLE_ARN=$(aws iam create-role \
        --role-name $ROLE_NAME \
        --assume-role-policy-document file:///tmp/trust-policy.json \
        --query 'Role.Arn' \
        --output text \
        --profile $AWS_PROFILE)
    
    # Attach policies
    aws iam attach-role-policy \
        --role-name $ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/AmazonSageMakerFullAccess \
        --profile $AWS_PROFILE
    
    aws iam attach-role-policy \
        --role-name $ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/AmazonRedshiftFullAccess \
        --profile $AWS_PROFILE
    
    aws iam attach-role-policy \
        --role-name $ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess \
        --profile $AWS_PROFILE
    
    echo -e "${GREEN}✓ Created role: $EXECUTION_ROLE_ARN${NC}"
    echo -e "${YELLOW}Waiting 10 seconds for role propagation...${NC}"
    sleep 10
fi

echo ""

# Create domain configuration
echo -e "${YELLOW}Creating SageMaker Unified Studio domain...${NC}"

# Note: As of now, SageMaker Unified Studio doesn't have direct CLI support
# We need to use SageMaker Domain API as a workaround

# Create domain settings JSON
cat > /tmp/domain-settings.json << EOF
{
  "ExecutionRole": "$EXECUTION_ROLE_ARN",
  "SecurityGroups": [],
  "SharingSettings": {
    "NotebookOutputOption": "Allowed",
    "S3OutputPath": "s3://sagemaker-$AWS_REGION-$(aws sts get-caller-identity --query Account --output text --profile $AWS_PROFILE)/studio"
  }
}
EOF

# Create domain with SSO authentication
echo -e "${YELLOW}Creating domain with SSO authentication...${NC}"
DOMAIN_OUTPUT=$(aws sagemaker create-domain \
    --domain-name $DOMAIN_NAME \
    --auth-mode SSO \
    --default-user-settings file:///tmp/domain-settings.json \
    --subnet-ids ${SUBNET_ARRAY[@]} \
    --vpc-id $VPC_ID \
    --region $AWS_REGION \
    --profile $AWS_PROFILE 2>&1)

# Check for errors
if echo "$DOMAIN_OUTPUT" | grep -qi "error"; then
    echo -e "${RED}Error creating domain:${NC}"
    echo "$DOMAIN_OUTPUT"
    echo ""
    echo -e "${YELLOW}Possible issues:${NC}"
    echo "1. Domain with same name may exist"
    echo "2. IAM Identity Center configuration issue"
    echo "3. VPC/subnet configuration issue"
    echo ""
    exit 1
fi

# Extract domain ID
DOMAIN_ID=$(echo "$DOMAIN_OUTPUT" | grep -o '"DomainId": *"[^"]*"' | cut -d'"' -f4)

if [ -z "$DOMAIN_ID" ]; then
    # Try alternative extraction
    DOMAIN_ID=$(echo "$DOMAIN_OUTPUT" | grep -o 'd-[a-z0-9]*' | head -1)
fi

if [ -z "$DOMAIN_ID" ]; then
    echo -e "${RED}Error: Could not extract domain ID${NC}"
    echo "Response: $DOMAIN_OUTPUT"
    exit 1
fi

echo -e "${GREEN}✓ Domain created: $DOMAIN_ID${NC}"
echo ""

# Wait for domain to be ready
echo -e "${YELLOW}Waiting for domain to be ready (this may take 10-15 minutes)...${NC}"
while true; do
    STATUS=$(aws sagemaker describe-domain \
        --domain-id $DOMAIN_ID \
        --region $AWS_REGION \
        --profile $AWS_PROFILE \
        --query 'Status' \
        --output text 2>&1 || echo "UNKNOWN")
    
    if [ "$STATUS" == "InService" ]; then
        echo -e "${GREEN}✓ Domain is ready${NC}"
        break
    elif echo "$STATUS" | grep -q "does not exist"; then
        echo -e "${RED}Error: Domain creation failed${NC}"
        exit 1
    else
        echo "Domain status: $STATUS - waiting..."
        sleep 30
    fi
done

# Get domain URL
DOMAIN_URL=$(aws sagemaker describe-domain \
    --domain-id $DOMAIN_ID \
    --query 'Url' \
    --output text \
    --region $AWS_REGION \
    --profile $AWS_PROFILE)

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Domain Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Domain ID: $DOMAIN_ID"
echo "Domain URL: $DOMAIN_URL"
echo ""

# Save to outputs
cat >> deployment/stack-outputs.env << EOF

# SageMaker Unified Studio Domain
export DOMAIN_ID="$DOMAIN_ID"
export DOMAIN_URL="$DOMAIN_URL"
export EXECUTION_ROLE_ARN="$EXECUTION_ROLE_ARN"
EOF

echo -e "${GREEN}✓ Configuration saved to deployment/stack-outputs.env${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "1. Configure IAM Identity Center users and groups"
echo "2. Assign groups to domain in SageMaker console"
echo "3. Share portal URL with users: $DOMAIN_URL"
echo "4. Deploy tire prediction project"
