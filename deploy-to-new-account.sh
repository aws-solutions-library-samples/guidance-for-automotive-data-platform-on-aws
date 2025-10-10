#!/bin/bash
set -e

NEW_ACCOUNT_ID="008549259336"
ROLE_NAME="OrganizationAccountAccessRole"

echo "=== Deploying DataZone to New Account ==="
echo "Account ID: $NEW_ACCOUNT_ID"
echo ""

# Assume role in new account
echo "Assuming role in new account..."
CREDS=$(aws sts assume-role \
  --role-arn "arn:aws:iam::${NEW_ACCOUNT_ID}:role/${ROLE_NAME}" \
  --role-session-name datazone-deployment \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)

export AWS_ACCESS_KEY_ID=$(echo $CREDS | awk '{print $1}')
export AWS_SECRET_ACCESS_KEY=$(echo $CREDS | awk '{print $2}')
export AWS_SESSION_TOKEN=$(echo $CREDS | awk '{print $3}')

echo "Credentials configured for account $NEW_ACCOUNT_ID"
echo ""

# Enable IAM Identity Center
echo "Enabling IAM Identity Center..."
IDC_ARN=$(aws sso-admin create-instance --region us-east-1 --query 'InstanceArn' --output text 2>&1 || \
  aws sso-admin list-instances --region us-east-1 --query 'Instances[0].InstanceArn' --output text)

if [ -z "$IDC_ARN" ] || [ "$IDC_ARN" = "None" ]; then
    echo "ERROR: Could not enable IAM Identity Center"
    echo "Please enable manually at: https://console.aws.amazon.com/singlesignon"
    echo "Then run: cd ~/automotive-data-platform-on-aws && make deploy"
    exit 1
fi

echo "IAM Identity Center enabled: $IDC_ARN"
echo ""

# Deploy DataZone
echo "Deploying DataZone..."
cd ~/automotive-data-platform-on-aws
./deployment/deploy-datazone-simple.sh

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "To access the portal:"
echo "1. Switch to account $NEW_ACCOUNT_ID in AWS Console"
echo "2. Or run: make datazone-login"
