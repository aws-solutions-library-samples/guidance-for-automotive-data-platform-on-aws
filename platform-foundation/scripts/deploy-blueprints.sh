#!/bin/bash
# Legacy DataZone blueprint deployer (pre-foundation). Discovers the
# first DataZone domain and deploys blueprint roles + blueprint
# enablement.
#
# Per Fix Group A (staging-prod rollout), every script under
# platform-foundation/scripts/ that touches stage-bearing resources MUST
# accept a stage argument and fail closed if it is missing or invalid.
#
# Usage:
#   ./deploy-blueprints.sh <stage>
#   ./deploy-blueprints.sh --stage <stage>

set -e

LOG_PREFIX="[deploy-blueprints]"
err() { echo "$LOG_PREFIX ERROR: $*" >&2; }

# ----- Stage gating (Fix Group A — staging-prod rollout) --------------------
parse_stage() {
    case "$1" in
        --stage)
            if [ "$#" -lt 2 ]; then
                err "--stage requires a value. Usage: $0 --stage <staging|prod>"
                exit 1
            fi
            echo "$2"
            ;;
        --stage=*)
            echo "${1#--stage=}"
            ;;
        *)
            echo "$1"
            ;;
    esac
}

if [ "$#" -eq 0 ]; then
    err "stage is required. Usage: $0 <staging|prod>"
    exit 1
fi
STAGE="$(parse_stage "$@")"
if [ -z "$STAGE" ]; then
    err "stage is required. Usage: $0 <staging|prod>"
    exit 1
fi
if [ "$STAGE" != "staging" ] && [ "$STAGE" != "prod" ]; then
    err "stage must be 'staging' or 'prod' (lower-case). Got: '$STAGE'"
    exit 1
fi
export STAGE

REGION="us-east-1"
DOMAIN_ID=$(aws datazone list-domains --region $REGION --query 'items[0].id' --output text)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "=== DataZone Blueprint Deployment ==="
echo "Stage:   $STAGE"
echo "Domain:  $DOMAIN_ID"
echo "Account: $ACCOUNT_ID"
echo "Region:  $REGION"

# Get default VPC and subnets
echo -e "\n=== Getting VPC Configuration ==="
VPC_ID=$(aws ec2 describe-vpcs --region $REGION --filters "Name=is-default,Values=true" --query "Vpcs[0].VpcId" --output text)
if [ "$VPC_ID" == "None" ] || [ -z "$VPC_ID" ]; then
    echo "No default VPC found. Creating new VPC..."
    VPC_ID=$(aws ec2 create-vpc --region $REGION --cidr-block 10.0.0.0/16 --query 'Vpc.VpcId' --output text)
    aws ec2 create-tags --region $REGION --resources $VPC_ID --tags Key=Name,Value=datazone-vpc
    aws ec2 modify-vpc-attribute --region $REGION --vpc-id $VPC_ID --enable-dns-hostnames

    # Create subnets
    SUBNET1=$(aws ec2 create-subnet --region $REGION --vpc-id $VPC_ID --cidr-block 10.0.1.0/24 --availability-zone ${REGION}a --query 'Subnet.SubnetId' --output text)
    SUBNET2=$(aws ec2 create-subnet --region $REGION --vpc-id $VPC_ID --cidr-block 10.0.2.0/24 --availability-zone ${REGION}b --query 'Subnet.SubnetId' --output text)
    SUBNETS="$SUBNET1,$SUBNET2"
else
    SUBNETS=$(aws ec2 describe-subnets --region $REGION --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[0:2].SubnetId" --output text | tr '\t' ',')
fi

echo "VPC: $VPC_ID"
echo "Subnets: $SUBNETS"

# Create S3 bucket for environments
BUCKET_NAME="datazone-${DOMAIN_ID}-environments"
echo -e "\n=== Creating S3 Bucket ==="
if aws s3 ls s3://$BUCKET_NAME 2>/dev/null; then
    echo "Bucket already exists: $BUCKET_NAME"
else
    aws s3 mb s3://$BUCKET_NAME --region $REGION
    echo "Created bucket: $BUCKET_NAME"
fi

# Deploy blueprint roles
echo -e "\n=== Deploying Blueprint Roles ==="
ROLES_STACK="datazone-blueprint-roles"
aws cloudformation deploy \
    --region $REGION \
    --stack-name $ROLES_STACK \
    --template-file blueprint-roles.yaml \
    --parameter-overrides DomainId=$DOMAIN_ID \
    --capabilities CAPABILITY_NAMED_IAM

MANAGE_ROLE=$(aws cloudformation describe-stacks --region $REGION --stack-name $ROLES_STACK --query "Stacks[0].Outputs[?OutputKey=='ManageAccessRoleArn'].OutputValue" --output text)
PROVISION_ROLE=$(aws cloudformation describe-stacks --region $REGION --stack-name $ROLES_STACK --query "Stacks[0].Outputs[?OutputKey=='ProvisioningRoleArn'].OutputValue" --output text)

echo "ManageAccessRole: $MANAGE_ROLE"
echo "ProvisioningRole: $PROVISION_ROLE"

# Deploy blueprints
echo -e "\n=== Enabling Blueprints ==="
BLUEPRINT_STACK="datazone-blueprints"
aws cloudformation deploy \
    --region $REGION \
    --stack-name $BLUEPRINT_STACK \
    --template-file enable-blueprints.yaml \
    --parameter-overrides \
        DomainId=$DOMAIN_ID \
        ManageAccessRoleArn=$MANAGE_ROLE \
        ProvisioningRoleArn=$PROVISION_ROLE \
        S3Bucket=$BUCKET_NAME \
        VpcId=$VPC_ID \
        SubnetIds=$SUBNETS

echo -e "\n=== Blueprint Deployment Complete (stage=$STAGE) ==="
echo "You can now create environments in your DataZone project"
