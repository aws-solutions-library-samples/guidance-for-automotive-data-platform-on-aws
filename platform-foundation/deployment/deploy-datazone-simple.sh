#!/bin/bash
set -e

REGION="${AWS_REGION:-us-east-1}"
DOMAIN_NAME="${DOMAIN_NAME:-automotive-data-platform}"

echo "=== DataZone V2 Deployment ==="
echo "Region: $REGION"
echo "Domain: $DOMAIN_NAME"
echo ""

# Get account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region $REGION)
echo "Account: $ACCOUNT_ID"

# Check for IAM Identity Center
echo ""
echo "Checking IAM Identity Center..."
IDC_ARN=$(aws sso-admin list-instances --region $REGION --query 'Instances[0].InstanceArn' --output text 2>/dev/null || echo "")

if [ -z "$IDC_ARN" ] || [ "$IDC_ARN" = "None" ]; then
    echo ""
    echo "❌ IAM Identity Center is not enabled in this account"
    echo ""
    echo "DataZone V2 requires IAM Identity Center. This is a one-time setup:"
    echo ""
    echo "1. Open: https://console.aws.amazon.com/singlesignon/home?region=$REGION"
    echo "2. Click 'Enable'"
    echo "3. Wait 30 seconds"
    echo "4. Run 'make deploy' again"
    echo ""
    echo "This only needs to be done once per AWS account."
    exit 1
fi

echo "✓ IAM Identity Center enabled: $IDC_ARN"

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
        \"Principal\": {\"Service\": \"datazone.amazonaws.com\"},
        \"Action\": [\"sts:AssumeRole\", \"sts:TagSession\", \"sts:SetContext\"],
        \"Condition\": {
          \"StringEquals\": {\"aws:SourceAccount\": \"${ACCOUNT_ID}\"},
          \"ForAllValues:StringLike\": {\"aws:TagKeys\": \"datazone*\"}
        }
      }
    ]
  }" --region $REGION 2>/dev/null || echo "  ✓ Role already exists"

aws iam attach-role-policy --role-name $EXEC_ROLE_NAME --policy-arn arn:aws:iam::aws:policy/service-role/SageMakerStudioDomainExecutionRolePolicy --region $REGION 2>/dev/null || true

# Create service role
echo "Creating service role..."
SVC_ROLE_NAME="${DOMAIN_NAME}-service-role"
aws iam create-role \
  --role-name $SVC_ROLE_NAME \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "datazone.amazonaws.com"}, "Action": "sts:AssumeRole"}]
  }' --region $REGION 2>/dev/null || echo "  ✓ Role already exists"

aws iam attach-role-policy --role-name $SVC_ROLE_NAME --policy-arn arn:aws:iam::aws:policy/service-role/SageMakerStudioDomainServiceRolePolicy --region $REGION 2>/dev/null || true

echo "Waiting for IAM propagation..."
sleep 15

# Create DataZone domain
echo ""
echo "Creating DataZone domain..."
DOMAIN_OUTPUT=$(aws datazone create-domain \
  --name $DOMAIN_NAME \
  --domain-execution-role arn:aws:iam::${ACCOUNT_ID}:role/${EXEC_ROLE_NAME} \
  --service-role arn:aws:iam::${ACCOUNT_ID}:role/${SVC_ROLE_NAME} \
  --single-sign-on type=IAM_IDC,userAssignment=AUTOMATIC \
  --domain-version V2 \
  --region $REGION 2>&1)

DOMAIN_ID=$(echo "$DOMAIN_OUTPUT" | grep -o '"id": "[^"]*"' | cut -d'"' -f4)

if [ -z "$DOMAIN_ID" ]; then
    echo "❌ ERROR creating domain:"
    echo "$DOMAIN_OUTPUT"
    exit 1
fi

echo "✓ Domain ID: $DOMAIN_ID"
echo "Waiting for domain to be available..."
sleep 30

# Get domain details
DOMAIN_INFO=$(aws datazone get-domain --identifier $DOMAIN_ID --region $REGION 2>&1)
ROOT_UNIT=$(echo "$DOMAIN_INFO" | grep -o '"rootDomainUnitId": "[^"]*"' | cut -d'"' -f4)
PORTAL_URL=$(echo "$DOMAIN_INFO" | grep -o '"portalUrl": "[^"]*"' | cut -d'"' -f4)

echo "✓ Root Domain Unit: $ROOT_UNIT"
echo "✓ Portal URL: $PORTAL_URL"

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
    echo "✓ Profile ID: $PROFILE_ID"
fi

# Save outputs
cat > deployment/datazone-outputs.env << EOF
DOMAIN_ID=$DOMAIN_ID
DOMAIN_NAME=$DOMAIN_NAME
ROOT_DOMAIN_UNIT=$ROOT_UNIT
PORTAL_URL=$PORTAL_URL
PROFILE_ID=$PROFILE_ID
REGION=$REGION
ACCOUNT_ID=$ACCOUNT_ID
IDC_ARN=$IDC_ARN
EOF

echo ""
echo "=== ✓ Deployment Complete ==="
echo ""
echo "Domain ID:    $DOMAIN_ID"
echo "Portal URL:   $PORTAL_URL"
echo ""
echo "Outputs saved to: deployment/datazone-outputs.env"
echo ""

# Prompt to create SSO user
read -p "Create an SSO user now? (y/n): " CREATE_USER
if [ "$CREATE_USER" = "y" ] || [ "$CREATE_USER" = "Y" ]; then
    echo ""
    ./deployment/add-sso-user.sh
else
    echo ""
    echo "Next steps:"
    echo "1. Create SSO user: make datazone-add-user EMAIL=user@example.com"
    echo "2. Access via console: https://console.aws.amazon.com/datazone"
    echo "3. Or get IAM login URL: make datazone-login"
fi
