#!/bin/bash

# Setup IAM Identity Center Permission Set and User Assignment
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-default}"

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}IAM Identity Center Permission Setup${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Get IAM Identity Center instance
IDC_INSTANCE_ARN=$(aws sso-admin list-instances \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'Instances[0].InstanceArn' \
    --output text)

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile $AWS_PROFILE)

echo "Instance ARN: $IDC_INSTANCE_ARN"
echo "Account ID: $ACCOUNT_ID"
echo ""

# Check if permission set exists
PERMISSION_SET_ARN=$(aws sso-admin list-permission-sets \
    --instance-arn $IDC_INSTANCE_ARN \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'PermissionSets[0]' \
    --output text 2>/dev/null || echo "")

if [ -z "$PERMISSION_SET_ARN" ] || [ "$PERMISSION_SET_ARN" == "None" ]; then
    echo -e "${YELLOW}Creating permission set...${NC}"
    
    PERMISSION_SET_ARN=$(aws sso-admin create-permission-set \
        --instance-arn $IDC_INSTANCE_ARN \
        --name DataZoneUserAccess \
        --description "Permission set for DataZone users" \
        --session-duration PT12H \
        --region $AWS_REGION \
        --profile $AWS_PROFILE \
        --query 'PermissionSet.PermissionSetArn' \
        --output text)
    
    echo -e "${GREEN}✓ Permission set created: $PERMISSION_SET_ARN${NC}"
    
    # Attach PowerUserAccess policy
    aws sso-admin attach-managed-policy-to-permission-set \
        --instance-arn $IDC_INSTANCE_ARN \
        --permission-set-arn $PERMISSION_SET_ARN \
        --managed-policy-arn arn:aws:iam::aws:policy/PowerUserAccess \
        --region $AWS_REGION \
        --profile $AWS_PROFILE
    
    echo -e "${GREEN}✓ PowerUserAccess policy attached${NC}"
    
    # Add inline policy for DataZone with execution role access
    cat > /tmp/datazone-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "datazone:*",
        "sts:AssumeRole",
        "iam:PassRole"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::*:role/automotive-data-platform-datazone-*"
    }
  ]
}
EOF
    
    aws sso-admin put-inline-policy-to-permission-set \
        --instance-arn $IDC_INSTANCE_ARN \
        --permission-set-arn $PERMISSION_SET_ARN \
        --inline-policy file:///tmp/datazone-policy.json \
        --region $AWS_REGION \
        --profile $AWS_PROFILE
    
    echo -e "${GREEN}✓ DataZone inline policy added${NC}"
    
    # Provision the permission set
    echo -e "${YELLOW}Provisioning permission set...${NC}"
    aws sso-admin provision-permission-set \
        --instance-arn $IDC_INSTANCE_ARN \
        --permission-set-arn $PERMISSION_SET_ARN \
        --target-type AWS_ACCOUNT \
        --target-id $ACCOUNT_ID \
        --region $AWS_REGION \
        --profile $AWS_PROFILE > /dev/null
    
    echo -e "${YELLOW}Waiting 30 seconds for provisioning...${NC}"
    sleep 30
    
    # Add inline policy for DataZone
    cat > /tmp/datazone-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "datazone:*",
        "sts:AssumeRole",
        "iam:PassRole"
      ],
      "Resource": "*"
    }
  ]
}
EOF
    
    aws sso-admin put-inline-policy-to-permission-set \
        --instance-arn $IDC_INSTANCE_ARN \
        --permission-set-arn $PERMISSION_SET_ARN \
        --inline-policy file:///tmp/datazone-policy.json \
        --region $AWS_REGION \
        --profile $AWS_PROFILE
    
    echo -e "${GREEN}✓ DataZone inline policy added${NC}"
else
    echo -e "${GREEN}✓ Permission set already exists: $PERMISSION_SET_ARN${NC}"
fi

# Get user ID
if [ -z "$SSO_USER_ID" ]; then
    if [ -z "$DEFAULT_EMAIL" ]; then
        echo -e "${RED}Error: DEFAULT_EMAIL not set${NC}"
        exit 1
    fi
    
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
fi

if [ -z "$SSO_USER_ID" ] || [ "$SSO_USER_ID" == "None" ]; then
    echo -e "${RED}Error: User not found. Create user first.${NC}"
    exit 1
fi

echo "User ID: $SSO_USER_ID"
echo ""

# Check if assignment exists
EXISTING_ASSIGNMENT=$(aws sso-admin list-account-assignments \
    --instance-arn $IDC_INSTANCE_ARN \
    --account-id $ACCOUNT_ID \
    --permission-set-arn $PERMISSION_SET_ARN \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query "AccountAssignments[?PrincipalId=='$SSO_USER_ID'].PrincipalId" \
    --output text 2>/dev/null || echo "")

if [ -z "$EXISTING_ASSIGNMENT" ]; then
    echo -e "${YELLOW}Assigning permission set to user...${NC}"
    
    aws sso-admin create-account-assignment \
        --instance-arn $IDC_INSTANCE_ARN \
        --target-id $ACCOUNT_ID \
        --target-type AWS_ACCOUNT \
        --permission-set-arn $PERMISSION_SET_ARN \
        --principal-type USER \
        --principal-id $SSO_USER_ID \
        --region $AWS_REGION \
        --profile $AWS_PROFILE > /dev/null
    
    echo -e "${GREEN}✓ Permission set assigned to user${NC}"
    echo -e "${YELLOW}Waiting for assignment to complete (30 seconds)...${NC}"
    sleep 30
else
    echo -e "${GREEN}✓ User already has permission set assigned${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Setup Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
SSO_START_URL=$(aws sso-admin list-instances --region $REGION --query 'Instances[0].IdentityStoreId' --output text)
echo "User can now login at: https://${SSO_START_URL}.awsapps.com/start"
echo ""
