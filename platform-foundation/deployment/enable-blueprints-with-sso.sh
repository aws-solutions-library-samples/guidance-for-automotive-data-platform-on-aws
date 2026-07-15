#!/bin/bash
set -e

REGION="us-east-1"

# Load domain ID from outputs
if [ -f "datazone-outputs.env" ]; then
    source datazone-outputs.env
else
    echo "Error: datazone-outputs.env not found"
    echo "Run domain deployment first"
    exit 1
fi

echo "=== DataZone Blueprint Enablement ==="
echo "Domain: $DOMAIN_ID"
echo ""
echo "Step 1: Login with SSO"
echo "----------------------"
aws sso login --profile datazone-admin

echo ""
echo "Step 2: Access DataZone portal (auto-adds user to domain)"
echo "----------------------------------------------------------"
echo "Open: https://us-east-1.console.aws.amazon.com/datazone/home?region=us-east-1#/domains/$DOMAIN_ID"
echo ""
echo "This will automatically add your SSO user to the domain."
echo ""
read -p "Have you accessed the DataZone portal? (y/n): " PORTAL_ACCESSED

if [ "$PORTAL_ACCESSED" != "y" ]; then
    echo "Please access the portal first, then run this script again."
    exit 1
fi

echo ""
echo "Step 3: Test DataZone API access"
echo "---------------------------------"
if AWS_PROFILE=datazone-admin aws datazone get-domain --region $REGION --identifier $DOMAIN_ID > /dev/null 2>&1; then
    echo "✓ SSO user has DataZone API access"
else
    echo "✗ SSO user cannot access DataZone API yet"
    echo "  Wait a moment and try again"
    exit 1
fi

echo ""
echo "Step 4: Enable all blueprints"
echo "------------------------------"

# Get configuration from stacks
MANAGE_ROLE=$(aws cloudformation describe-stacks --region $REGION --stack-name datazone-blueprint-roles --query "Stacks[0].Outputs[?OutputKey=='ManageAccessRoleArn'].OutputValue" --output text)
PROVISION_ROLE=$(aws cloudformation describe-stacks --region $REGION --stack-name datazone-blueprint-roles --query "Stacks[0].Outputs[?OutputKey=='ProvisioningRoleArn'].OutputValue" --output text)
VPC_ID=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-shared-resources --query "Stacks[0].Outputs[?OutputKey=='VpcId'].OutputValue" --output text)
SUBNETS=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-shared-resources --query "Stacks[0].Outputs[?OutputKey=='SubnetIds'].OutputValue" --output text)
BUCKET=$(aws cloudformation describe-stacks --region $REGION --stack-name automotive-shared-resources --query "Stacks[0].Outputs[?OutputKey=='EnvironmentBucket'].OutputValue" --output text)

AWS_PROFILE=datazone-admin aws cloudformation deploy \
    --region $REGION \
    --stack-name datazone-all-blueprints \
    --template-file ../cloudformation/enable-all-blueprints.yaml \
    --parameter-overrides \
        DomainId=$DOMAIN_ID \
        AmazonSageMakerManageAccessRole=$MANAGE_ROLE \
        AmazonSageMakerProvisioningRole=$PROVISION_ROLE \
        DZS3Bucket=$BUCKET \
        SageMakerSubnets=$SUBNETS \
        AmazonSageMakerVpcId=$VPC_ID

echo ""
echo "=== ✓ All 17 Blueprints Enabled ==="
echo ""
echo "Blueprints enabled:"
echo "  - MLExperiments, Tooling, LakehouseCatalog"
echo "  - RedshiftServerless, EmrServerless, EmrOnEc2"
echo "  - DataLake, Workflows, QuickSight"
echo "  - AmazonBedrock* (8 blueprints)"
echo "  - PartnerApps"
