#!/bin/bash
set -e

REGION="${AWS_REGION:-us-east-1}"

# Load domain info
if [ ! -f deployment/datazone-outputs.env ]; then
    echo "Error: DataZone domain not found. Run 'make deploy' first."
    exit 1
fi

source deployment/datazone-outputs.env

echo "=== Deploying Tire Prediction Project ==="
echo "Domain: $DOMAIN_ID"
echo "Region: $REGION"
echo ""

# Get project profile ID
if [ -z "$PROFILE_ID" ]; then
    echo "Getting project profile..."
    PROFILE_ID=$(aws datazone list-project-profiles \
        --domain-identifier $DOMAIN_ID \
        --region $REGION \
        --query 'items[0].id' --output text)
    echo "Profile ID: $PROFILE_ID"
fi

# Deploy CloudFormation stack
echo ""
echo "Creating project via CloudFormation..."
aws cloudformation create-stack \
    --stack-name tire-prediction-project \
    --template-body file://cloudformation/tire-prediction-project.yaml \
    --parameters \
        ParameterKey=DomainId,ParameterValue=$DOMAIN_ID \
        ParameterKey=ProjectProfileId,ParameterValue=$PROFILE_ID \
    --region $REGION 2>/dev/null || echo "Stack already exists"

echo ""
echo "Waiting for stack creation..."
aws cloudformation wait stack-create-complete \
    --stack-name tire-prediction-project \
    --region $REGION 2>/dev/null || echo "Stack already complete"

# Get project ID
PROJECT_ID=$(aws cloudformation describe-stacks \
    --stack-name tire-prediction-project \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ProjectId`].OutputValue' \
    --output text)

echo ""
echo "Project ID: $PROJECT_ID"

# Get current user ID from IAM Identity Center
echo ""
echo "Adding current user as project member..."
IDENTITY_STORE_ID=$(aws sso-admin list-instances --region $REGION --query 'Instances[0].IdentityStoreId' --output text)

# Try to get user ID from environment or prompt
if [ -z "$USER_EMAIL" ]; then
    read -p "Enter your email address: " USER_EMAIL
fi

USER_ID=$(aws identitystore list-users \
    --identity-store-id $IDENTITY_STORE_ID \
    --region $REGION \
    --filters AttributePath=UserName,AttributeValue=$USER_EMAIL \
    --query 'Users[0].UserId' --output text 2>/dev/null || echo "")

if [ -z "$USER_ID" ] || [ "$USER_ID" = "None" ]; then
    echo "Warning: Could not find user $USER_EMAIL in Identity Center"
    echo "You'll need to manually join the project or contact a project owner"
else
    # Add user as project member
    aws datazone create-project-membership \
        --domain-identifier $DOMAIN_ID \
        --project-identifier $PROJECT_ID \
        --designation PROJECT_OWNER \
        --member "{\"userIdentifier\":\"$USER_ID\"}" \
        --region $REGION 2>/dev/null || echo "User already a member"
    
    echo "✓ Added $USER_EMAIL as project owner"
fi

echo ""
echo "=== ✓ Project Created ==="
echo ""
echo "Project ID: $PROJECT_ID"
echo "Project Name: tire-prediction-ml"
echo ""
echo "Access the project:"
echo "1. Go to: $PORTAL_URL"
echo "2. Click on 'tire-prediction-ml' project"
echo "3. Start building your ML workflows"
