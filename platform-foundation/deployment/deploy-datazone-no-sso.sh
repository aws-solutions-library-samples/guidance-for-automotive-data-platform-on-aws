#!/bin/bash
set -e

REGION="${AWS_REGION:-us-east-1}"
DOMAIN_NAME="${DOMAIN_NAME:-automotive-data-platform}"

echo "=== DataZone V2 Deployment (No SSO) ==="
echo "Region: $REGION"
echo "Domain: $DOMAIN_NAME"
echo ""

# Get account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region $REGION)
echo "Account: $ACCOUNT_ID"

# Create execution role
echo ""
echo "Creating execution role..."
EXEC_ROLE_NAME="${DOMAIN_NAME}-execution-role"
aws iam create-role \
  --role-name $EXEC_ROLE_NAME \
  --assume-role-policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [
      {
        \"Effect\": \"Allow\",
        \"Principal\": {\"Service\": [\"datazone.amazonaws.com\", \"sagemaker.amazonaws.com\"]},
        \"Action\": \"sts:AssumeRole\"
      },
      {
        \"Effect\": \"Allow\",
        \"Principal\": {\"AWS\": \"arn:aws:iam::${ACCOUNT_ID}:root\"},
        \"Action\": \"sts:AssumeRole\"
      }
    ]
  }" --region $REGION 2>/dev/null || echo "  Role already exists"

aws iam attach-role-policy --role-name $EXEC_ROLE_NAME --policy-arn arn:aws:iam::aws:policy/AmazonSageMakerFullAccess --region $REGION 2>/dev/null || true
aws iam attach-role-policy --role-name $EXEC_ROLE_NAME --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess --region $REGION 2>/dev/null || true
aws iam attach-role-policy --role-name $EXEC_ROLE_NAME --policy-arn arn:aws:iam::aws:policy/AWSGlueConsoleFullAccess --region $REGION 2>/dev/null || true

# Create service role
echo "Creating service role..."
SVC_ROLE_NAME="${DOMAIN_NAME}-service-role"
aws iam create-role \
  --role-name $SVC_ROLE_NAME \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "datazone.amazonaws.com"}, "Action": "sts:AssumeRole"}]
  }' --region $REGION 2>/dev/null || echo "  Role already exists"

aws iam attach-role-policy --role-name $SVC_ROLE_NAME --policy-arn arn:aws:iam::aws:policy/AmazonDataZoneFullAccess --region $REGION 2>/dev/null || true

echo "Waiting for IAM propagation..."
sleep 15

# Create DataZone domain WITHOUT SSO
echo ""
echo "Creating DataZone domain (IAM-only mode)..."
DOMAIN_OUTPUT=$(aws datazone create-domain \
  --name $DOMAIN_NAME \
  --domain-execution-role arn:aws:iam::${ACCOUNT_ID}:role/${EXEC_ROLE_NAME} \
  --service-role arn:aws:iam::${ACCOUNT_ID}:role/${SVC_ROLE_NAME} \
  --domain-version V2 \
  --region $REGION 2>&1)

DOMAIN_ID=$(echo "$DOMAIN_OUTPUT" | grep -o '"id": "[^"]*"' | cut -d'"' -f4)

if [ -z "$DOMAIN_ID" ]; then
    echo "ERROR creating domain:"
    echo "$DOMAIN_OUTPUT"
    exit 1
fi

echo "Domain ID: $DOMAIN_ID"
echo "Waiting for domain to be available..."
sleep 30

# Get domain details
DOMAIN_INFO=$(aws datazone get-domain --identifier $DOMAIN_ID --region $REGION 2>&1)
ROOT_UNIT=$(echo "$DOMAIN_INFO" | grep -o '"rootDomainUnitId": "[^"]*"' | cut -d'"' -f4)
PORTAL_URL=$(echo "$DOMAIN_INFO" | grep -o '"portalUrl": "[^"]*"' | cut -d'"' -f4)

echo "Root Domain Unit: $ROOT_UNIT"
echo "Portal URL: $PORTAL_URL"

# Create project profile
echo ""
echo "Creating project profile..."
PROFILE_ID=$(aws datazone create-project-profile \
  --domain-identifier $DOMAIN_ID \
  --domain-unit-identifier $ROOT_UNIT \
  --name default-profile \
  --status ENABLED \
  --region $REGION \
  --query 'id' --output text 2>/dev/null || echo "")

if [ -n "$PROFILE_ID" ]; then
    echo "Profile ID: $PROFILE_ID"
fi

# Get IAM portal login URL
echo ""
echo "Getting IAM portal login URL..."
LOGIN_URL=$(aws datazone get-iam-portal-login-url --domain-identifier $DOMAIN_ID --region $REGION --query 'authCodeUrl' --output text 2>/dev/null || echo "")

# Save outputs
cat > deployment/datazone-outputs.env << EOF
DOMAIN_ID=$DOMAIN_ID
DOMAIN_NAME=$DOMAIN_NAME
ROOT_DOMAIN_UNIT=$ROOT_UNIT
PORTAL_URL=$PORTAL_URL
PROFILE_ID=$PROFILE_ID
REGION=$REGION
ACCOUNT_ID=$ACCOUNT_ID
EOF

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Domain ID:    $DOMAIN_ID"
echo "Portal URL:   $PORTAL_URL"
echo ""
if [ -n "$LOGIN_URL" ]; then
    echo "IAM Login URL (valid for 5 minutes):"
    echo "$LOGIN_URL"
    echo ""
    echo "Copy and paste this URL in your browser NOW"
fi
echo ""
echo "Outputs saved to: deployment/datazone-outputs.env"
