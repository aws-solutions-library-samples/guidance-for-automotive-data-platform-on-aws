#!/bin/bash

# Create SageMaker User Profile with SSO
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_PROFILE="${AWS_PROFILE:-default}"

# Interactive prompt for email if not provided
if [ -z "$DEFAULT_EMAIL" ]; then
    echo -e "${YELLOW}Enter email address for SSO user:${NC}"
    read -p "Email: " DEFAULT_EMAIL
    
    if [ -z "$DEFAULT_EMAIL" ]; then
        echo -e "${RED}Error: Email address is required${NC}"
        exit 1
    fi
fi

# Use email as username by default (best practice for SSO)
DEFAULT_USERNAME="${DEFAULT_USERNAME:-$DEFAULT_EMAIL}"

# Sanitize profile name for SageMaker (no @ or . allowed)
PROFILE_NAME=$(echo "$DEFAULT_USERNAME" | sed 's/@/-at-/g' | sed 's/\./-/g')

# Load stack outputs
if [ -f "deployment/stack-outputs.env" ]; then
    source deployment/stack-outputs.env
else
    echo -e "${RED}Error: Stack outputs not found${NC}"
    exit 1
fi

if [ -z "$DOMAIN_ID" ]; then
    echo -e "${RED}Error: Domain not created yet. Run 'make deploy-domain' first${NC}"
    exit 1
fi

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Creating SageMaker SSO User${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Get IAM Identity Center instance
IDENTITY_STORE_ID=$(aws sso-admin list-instances \
    --query 'Instances[0].IdentityStoreId' \
    --output text \
    --region $AWS_REGION \
    --profile $AWS_PROFILE)

SSO_INSTANCE_ID=$(aws sso-admin list-instances \
    --query 'Instances[0].InstanceArn' \
    --output text \
    --region $AWS_REGION \
    --profile $AWS_PROFILE | grep -o 'ssoins-[^"]*' | sed 's/ssoins-//')

if [ -z "$IDENTITY_STORE_ID" ] || [ "$IDENTITY_STORE_ID" == "None" ]; then
    echo -e "${RED}Error: IAM Identity Center not found${NC}"
    exit 1
fi

echo "Identity Store: $IDENTITY_STORE_ID"
echo "Instance ID: $SSO_INSTANCE_ID"
echo ""

# Check if SSO user already exists
EXISTING_SSO_USER=$(aws identitystore list-users \
    --identity-store-id $IDENTITY_STORE_ID \
    --filters AttributePath=UserName,AttributeValue=$DEFAULT_USERNAME \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'Users[0].UserId' \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_SSO_USER" ] && [ "$EXISTING_SSO_USER" != "None" ]; then
    echo -e "${YELLOW}SSO user '$DEFAULT_USERNAME' already exists: $EXISTING_SSO_USER${NC}"
    SSO_USER_ID=$EXISTING_SSO_USER
else
    echo -e "${YELLOW}Creating SSO user: $DEFAULT_USERNAME${NC}"
    
    # Create SSO user
    SSO_USER_ID=$(aws identitystore create-user \
        --identity-store-id $IDENTITY_STORE_ID \
        --user-name $DEFAULT_USERNAME \
        --display-name "$DEFAULT_USERNAME" \
        --name Formatted=string,FamilyName=User,GivenName=Admin \
        --emails Value=$DEFAULT_EMAIL,Primary=true \
        --region $AWS_REGION \
        --profile $AWS_PROFILE \
        --query 'UserId' \
        --output text 2>&1)
    
    if echo "$SSO_USER_ID" | grep -q "error\|Error"; then
        echo -e "${RED}Error creating SSO user: $SSO_USER_ID${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ SSO user created: $SSO_USER_ID${NC}"
    echo -e "${YELLOW}Sending password setup email...${NC}"
    
    # Note: AWS CLI doesn't support sending invitation emails directly
    # User must set password via IAM Identity Center console
    echo -e "${YELLOW}Note: Admin must send password reset email via console${NC}"
fi

echo ""

# Wait for domain to be ready
echo -e "${YELLOW}Waiting for domain to be ready (this may take 5-10 minutes)...${NC}"
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
        echo -e "${RED}Error: Domain not found${NC}"
        exit 1
    else
        echo "Domain status: $STATUS - waiting..."
        sleep 30
    fi
done

echo ""

# Check if SageMaker user profile already exists
EXISTING_PROFILE=$(aws sagemaker list-user-profiles \
    --domain-id $DOMAIN_ID \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query "UserProfiles[?UserProfileName=='$PROFILE_NAME'].UserProfileName" \
    --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_PROFILE" ]; then
    echo -e "${YELLOW}SageMaker user profile '$PROFILE_NAME' already exists${NC}"
else
    echo -e "${YELLOW}Creating SageMaker user profile: $PROFILE_NAME${NC}"
    
    aws sagemaker create-user-profile \
        --domain-id $DOMAIN_ID \
        --user-profile-name $PROFILE_NAME \
        --single-sign-on-user-identifier UserName \
        --single-sign-on-user-value $DEFAULT_USERNAME \
        --user-settings ExecutionRole=$EXECUTION_ROLE_ARN \
        --region $AWS_REGION \
        --profile $AWS_PROFILE > /dev/null
    
    echo -e "${GREEN}✓ SageMaker user profile created${NC}"
fi

echo ""

# Get domain URL
DOMAIN_URL=$(aws sagemaker describe-domain \
    --domain-id $DOMAIN_ID \
    --region $AWS_REGION \
    --profile $AWS_PROFILE \
    --query 'Url' \
    --output text 2>/dev/null || echo "https://${DOMAIN_ID}.studio.${AWS_REGION}.sagemaker.aws")

# Save credentials
cat > deployment/user-credentials.txt << EOF
========================================
SageMaker Unified Studio Access (SSO)
========================================

Domain ID:       $DOMAIN_ID
Username:        $DEFAULT_USERNAME
Email:           $DEFAULT_EMAIL
SSO User ID:     $SSO_USER_ID
Region:          $AWS_REGION

Studio URL:      $DOMAIN_URL

Authentication:  IAM Identity Center (SSO)
Identity Store:  $IDENTITY_STORE_ID

========================================
REQUIRED: Complete These 2 Steps
========================================

STEP 1: Send Password Reset Email
----------------------------------
1. Click this direct link:
   https://us-east-1.console.aws.amazon.com/singlesignon/home?region=$AWS_REGION#/instances/$SSO_INSTANCE_ID/users/userDetails/userId=$SSO_USER_ID&directoryId=&realm=

2. Click "Reset password" button

3. Choose "Send email with instructions"
   Email will be sent to: $DEFAULT_EMAIL

STEP 2: Assign User to SageMaker Application
---------------------------------------------
1. Go to IAM Identity Center Applications:
   https://us-east-1.console.aws.amazon.com/singlesignon/applications/home?region=$AWS_REGION#/instances/$SSO_INSTANCE_ID/

2. Find application: "Amazon SageMaker Studio ($DOMAIN_ID)"

3. Click on application → "Assign users" button

4. Select user: $DEFAULT_USERNAME

5. Click "Assign users"

STEP 3: Login
-------------
After completing steps 1 & 2, user can login at:
$DOMAIN_URL

========================================
EOF

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}User Created Successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "SSO Username:    ${GREEN}$DEFAULT_USERNAME${NC}"
echo -e "Profile Name:    ${GREEN}$PROFILE_NAME${NC}"
echo -e "Email:           ${GREEN}$DEFAULT_EMAIL${NC}"
echo -e "Studio URL:      ${GREEN}$DOMAIN_URL${NC}"
echo ""
echo -e "${YELLOW}REQUIRED: Complete these 2 steps:${NC}"
echo ""
echo -e "${YELLOW}Step 1: Send password reset email${NC}"
echo -e "Direct link: ${GREEN}https://us-east-1.console.aws.amazon.com/singlesignon/home?region=$AWS_REGION#/instances/$SSO_INSTANCE_ID/users/userDetails/userId=$SSO_USER_ID&directoryId=&realm=${NC}"
echo -e "  → Click 'Reset password' → 'Send email with instructions'"
echo ""
echo -e "${YELLOW}Step 2: Assign user to SageMaker application${NC}"
echo -e "Direct link: ${GREEN}https://us-east-1.console.aws.amazon.com/singlesignon/applications/home?region=$AWS_REGION#/instances/$SSO_INSTANCE_ID/${NC}"
echo -e "  → Find 'Amazon SageMaker Studio ($DOMAIN_ID)'"
echo -e "  → Click application → 'Assign users'"
echo -e "  → Select '$DEFAULT_USERNAME' → 'Assign users'"
echo ""
echo -e "${GREEN}✓ Saved to: deployment/user-credentials.txt${NC}"
echo ""
