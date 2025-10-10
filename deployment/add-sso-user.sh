#!/bin/bash
set -e

# Load domain info
if [ ! -f deployment/datazone-outputs.env ]; then
    echo "Error: DataZone domain not found. Run 'make deploy' first."
    exit 1
fi

source deployment/datazone-outputs.env

EMAIL="${1:-}"
if [ -z "$EMAIL" ]; then
    read -p "Enter email address for SSO user: " EMAIL
fi

echo "=== Adding SSO User to DataZone ==="
echo "Domain: $DOMAIN_ID"
echo "Email: $EMAIL"
echo ""

# Get Identity Store ID
IDENTITY_STORE_ID=$(aws sso-admin list-instances --region $REGION --query 'Instances[0].IdentityStoreId' --output text)

# Check if user exists
echo "Checking if user exists..."
USER_ID=$(aws identitystore list-users \
    --identity-store-id $IDENTITY_STORE_ID \
    --region $REGION \
    --filters AttributePath=UserName,AttributeValue=$EMAIL \
    --query 'Users[0].UserId' --output text 2>/dev/null || echo "")

if [ -z "$USER_ID" ] || [ "$USER_ID" = "None" ]; then
    echo "Creating new SSO user..."
    USER_ID=$(aws identitystore create-user \
        --identity-store-id $IDENTITY_STORE_ID \
        --user-name $EMAIL \
        --display-name $EMAIL \
        --name Formatted=string,FamilyName=User,GivenName=Admin \
        --emails Value=$EMAIL,Primary=true \
        --region $REGION \
        --query 'UserId' --output text)
    echo "✓ User created: $USER_ID"
else
    echo "✓ User already exists: $USER_ID"
fi

# Add user as domain owner
echo "Adding user as domain owner..."
aws datazone add-entity-owner \
    --domain-identifier $DOMAIN_ID \
    --entity-identifier $ROOT_DOMAIN_UNIT \
    --entity-type DOMAIN_UNIT \
    --owner "{\"user\":{\"userIdentifier\":\"$USER_ID\"}}" \
    --region $REGION 2>/dev/null || echo "✓ User already a domain owner"

# Create permission set for DataZone access
echo "Creating permission set..."
PERMISSION_SET_ARN=$(aws sso-admin create-permission-set \
    --instance-arn $IDC_ARN \
    --name DataZoneAccess \
    --description "Permissions for DataZone users" \
    --session-duration PT12H \
    --region $REGION \
    --query 'PermissionSet.PermissionSetArn' --output text 2>/dev/null || \
    aws sso-admin list-permission-sets \
        --instance-arn $IDC_ARN \
        --region $REGION \
        --query 'PermissionSets[0]' --output text)

# Add inline policy to permission set
aws sso-admin put-inline-policy-to-permission-set \
    --instance-arn $IDC_ARN \
    --permission-set-arn $PERMISSION_SET_ARN \
    --inline-policy "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"datazone:*\",\"sagemaker:*\",\"sts:AssumeRole\"],\"Resource\":\"*\"}]}" \
    --region $REGION 2>/dev/null || true

# Assign permission set to user
echo "Assigning permissions to user..."
aws sso-admin create-account-assignment \
    --instance-arn $IDC_ARN \
    --permission-set-arn $PERMISSION_SET_ARN \
    --principal-type USER \
    --principal-id $USER_ID \
    --target-type AWS_ACCOUNT \
    --target-id $ACCOUNT_ID \
    --region $REGION 2>/dev/null || echo "✓ Permission already assigned"

# Provision permission set
aws sso-admin provision-permission-set \
    --instance-arn $IDC_ARN \
    --permission-set-arn $PERMISSION_SET_ARN \
    --target-type AWS_ACCOUNT \
    --target-id $ACCOUNT_ID \
    --region $REGION 2>/dev/null || true

echo ""
echo "=== ✓ User Setup Complete ==="
echo ""
echo "User ID: $USER_ID"
echo "Email: $EMAIL"
echo ""
echo "Access the portal:"
echo "1. Go to: https://${IDENTITY_STORE_ID}.awsapps.com/start"
echo "2. Log in with: $EMAIL"
echo "3. Click the DataZone application tile"
