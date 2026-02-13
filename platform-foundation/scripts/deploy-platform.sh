#!/bin/bash
set -e

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "=== Deploying Automotive Data Platform ==="
echo "Region: $REGION"
echo "Account: $ACCOUNT_ID"
echo ""

# Step 1: Create Unified Studio domain
echo "Step 1: Creating Unified Studio domain..."
aws cloudformation deploy \
    --region $REGION \
    --stack-name automotive-unified-studio-domain \
    --template-file cloudformation/datazone-domain.yaml \
    --parameter-overrides DomainName=automotive-data-platform \
    --capabilities CAPABILITY_NAMED_IAM \
    --no-fail-on-empty-changeset

DOMAIN_ID=$(aws cloudformation describe-stacks \
    --region $REGION \
    --stack-name automotive-unified-studio-domain \
    --query 'Stacks[0].Outputs[?OutputKey==`DomainId`].OutputValue' \
    --output text)

ROOT_DOMAIN_UNIT=$(aws cloudformation describe-stacks \
    --region $REGION \
    --stack-name automotive-unified-studio-domain \
    --query 'Stacks[0].Outputs[?OutputKey==`RootDomainUnitId`].OutputValue' \
    --output text)

MANAGE_ROLE=$(aws cloudformation describe-stacks \
    --region $REGION \
    --stack-name automotive-unified-studio-domain \
    --query 'Stacks[0].Outputs[?OutputKey==`SageMakerManageAccessRoleArn`].OutputValue' \
    --output text)

PROVISIONING_ROLE=$(aws cloudformation describe-stacks \
    --region $REGION \
    --stack-name automotive-unified-studio-domain \
    --query 'Stacks[0].Outputs[?OutputKey==`SageMakerProvisioningRoleArn`].OutputValue' \
    --output text)

echo "✓ Domain: $DOMAIN_ID"

# Step 2: Create S3 bucket and get VPC
echo ""
echo "Step 2: Setting up shared resources..."
BUCKET_NAME="datazone-environments-$ACCOUNT_ID"
aws s3 mb s3://$BUCKET_NAME --region $REGION 2>/dev/null || echo "Bucket exists"

VPC_ID=$(aws ec2 describe-vpcs --region $REGION --filters "Name=isDefault,Values=false" --query 'Vpcs[0].VpcId' --output text)
SUBNETS=$(aws ec2 describe-subnets --region $REGION --filters "Name=vpc-id,Values=$VPC_ID" --query 'Subnets[0:2].SubnetId' --output text | tr '\t' ',')

echo "✓ S3 Bucket: $BUCKET_NAME"
echo "✓ VPC: $VPC_ID"

# Step 3: Enable blueprints
echo ""
echo "Step 3: Enabling blueprints..."

# Tooling
aws datazone put-environment-blueprint-configuration \
    --region $REGION \
    --domain-identifier $DOMAIN_ID \
    --environment-blueprint-identifier cjegf7f6kky6w7 \
    --manage-access-role-arn "$MANAGE_ROLE" \
    --provisioning-role-arn "$PROVISIONING_ROLE" \
    --enabled-regions $REGION \
    --regional-parameters "{\"$REGION\":{\"VpcId\":\"$VPC_ID\",\"Subnets\":\"$SUBNETS\",\"S3Location\":\"$BUCKET_NAME\"}}" \
    --output json > /dev/null

echo "✓ Tooling blueprint enabled"

# MLExperiments
aws datazone put-environment-blueprint-configuration \
    --region $REGION \
    --domain-identifier $DOMAIN_ID \
    --environment-blueprint-identifier b5u742v3kgqup3 \
    --manage-access-role-arn "$MANAGE_ROLE" \
    --provisioning-role-arn "$PROVISIONING_ROLE" \
    --enabled-regions $REGION \
    --regional-parameters "{\"$REGION\":{\"VpcId\":\"$VPC_ID\",\"Subnets\":\"$SUBNETS\",\"S3Location\":\"$BUCKET_NAME\"}}" \
    --output json > /dev/null

echo "✓ MLExperiments blueprint enabled"

# Step 4: Create policy grants
echo ""
echo "Step 4: Creating policy grants..."

cat > /tmp/platform-policy-grants.yaml << 'EOF'
AWSTemplateFormatVersion: '2010-09-09'
Parameters:
  DomainId:
    Type: String
  DomainUnitId:
    Type: String
  AccountId:
    Type: String
Resources:
  ToolingGrant:
    Type: AWS::DataZone::PolicyGrant
    Properties:
      DomainIdentifier: !Ref DomainId
      EntityType: ENVIRONMENT_BLUEPRINT_CONFIGURATION
      EntityIdentifier: !Sub '${AccountId}:cjegf7f6kky6w7'
      PolicyType: CREATE_ENVIRONMENT_FROM_BLUEPRINT
      Detail:
        CreateEnvironmentFromBlueprint: {}
      Principal:
        Project:
          ProjectDesignation: CONTRIBUTOR
          ProjectGrantFilter:
            DomainUnitFilter:
              DomainUnit: !Ref DomainUnitId
              IncludeChildDomainUnits: true
  MLExperimentsGrant:
    Type: AWS::DataZone::PolicyGrant
    Properties:
      DomainIdentifier: !Ref DomainId
      EntityType: ENVIRONMENT_BLUEPRINT_CONFIGURATION
      EntityIdentifier: !Sub '${AccountId}:b5u742v3kgqup3'
      PolicyType: CREATE_ENVIRONMENT_FROM_BLUEPRINT
      Detail:
        CreateEnvironmentFromBlueprint: {}
      Principal:
        Project:
          ProjectDesignation: CONTRIBUTOR
          ProjectGrantFilter:
            DomainUnitFilter:
              DomainUnit: !Ref DomainUnitId
              IncludeChildDomainUnits: true
EOF

aws cloudformation deploy \
    --region $REGION \
    --stack-name automotive-policy-grants \
    --template-file /tmp/platform-policy-grants.yaml \
    --parameter-overrides \
        DomainId=$DOMAIN_ID \
        DomainUnitId=$ROOT_DOMAIN_UNIT \
        AccountId=$ACCOUNT_ID \
    --no-fail-on-empty-changeset

echo "✓ Policy grants created"

# Step 5: Create project profile
echo ""
echo "Step 5: Creating project profile..."

PROFILE_OUTPUT=$(aws datazone create-project-profile \
    --region $REGION \
    --domain-identifier $DOMAIN_ID \
    --domain-unit-identifier $ROOT_DOMAIN_UNIT \
    --name "All capabilities" \
    --description "ML and data analytics capabilities" \
    --environment-configurations "[{\"name\":\"Tooling\",\"environmentBlueprintId\":\"cjegf7f6kky6w7\",\"awsAccount\":{\"awsAccountId\":\"$ACCOUNT_ID\"},\"awsRegion\":{\"regionName\":\"$REGION\"},\"deploymentOrder\":0},{\"name\":\"MLExperiments\",\"environmentBlueprintId\":\"b5u742v3kgqup3\",\"awsAccount\":{\"awsAccountId\":\"$ACCOUNT_ID\"},\"awsRegion\":{\"regionName\":\"$REGION\"},\"deploymentOrder\":1}]" \
    --output json 2>&1 || aws datazone list-project-profiles --region $REGION --domain-identifier $DOMAIN_ID --query 'items[0]' --output json)

PROFILE_ID=$(echo "$PROFILE_OUTPUT" | jq -r '.id')

# Enable profile
aws datazone update-project-profile \
    --region $REGION \
    --domain-identifier $DOMAIN_ID \
    --identifier $PROFILE_ID \
    --status ENABLED \
    --output json > /dev/null 2>&1 || true

echo "✓ Project profile: $PROFILE_ID"

# Save outputs
cat > /tmp/platform-outputs.env << EOF
export DOMAIN_ID=$DOMAIN_ID
export PROFILE_ID=$PROFILE_ID
export ROOT_DOMAIN_UNIT=$ROOT_DOMAIN_UNIT
export REGION=$REGION
EOF

echo ""
echo "=== ✓ Platform Deployment Complete ==="
echo ""
echo "Domain ID: $DOMAIN_ID"
echo "Profile ID: $PROFILE_ID"
echo "Portal: https://dzd-$DOMAIN_ID.sagemaker.us-east-1.on.aws"
echo ""
echo "Platform configuration saved to: /tmp/platform-outputs.env"
echo "Source this file in project deployments: source /tmp/platform-outputs.env"
