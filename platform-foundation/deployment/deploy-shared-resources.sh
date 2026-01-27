#!/bin/bash
set -e

REGION="${AWS_REGION:-us-east-1}"
BUCKET_NAME="${CONNECTED_MOBILITY_BUCKET:-}"

echo "=== Deploying Shared Resources ==="
echo "Region: $REGION"
echo ""

# Try to auto-detect connected-mobility datalake bucket
if [ -z "$BUCKET_NAME" ]; then
    echo "Searching for connected-mobility datalake bucket..."
    
    # Look for buckets matching pattern: *-datalake-* (excluding frontend/ui buckets)
    FOUND_BUCKETS=$(aws s3api list-buckets --query 'Buckets[?contains(Name, `datalake`)].Name' --output text 2>/dev/null | tr '\t' '\n' | grep -v "frontend\|uiuserinterface\|distribution" || echo "")
    
    if [ -n "$FOUND_BUCKETS" ]; then
        echo "Found datalake buckets:"
        echo "$FOUND_BUCKETS" | nl
        echo ""
        read -p "Enter bucket number to use (or 0 to create new): " BUCKET_NUM
        
        if [ "$BUCKET_NUM" != "0" ]; then
            BUCKET_NAME=$(echo "$FOUND_BUCKETS" | sed -n "${BUCKET_NUM}p")
        fi
    fi
fi

if [ -z "$BUCKET_NAME" ]; then
    echo "No existing bucket selected."
    echo "Creating new S3 bucket for tire data..."
    BUCKET_PARAM=""
else
    echo "Using existing bucket: $BUCKET_NAME"
    BUCKET_PARAM="ParameterKey=ConnectedMobilityBucketName,ParameterValue=$BUCKET_NAME"
fi

echo ""

# Deploy CloudFormation stack
if [ -z "$BUCKET_PARAM" ]; then
    aws cloudformation create-stack \
        --stack-name automotive-shared-resources \
        --template-body file://cloudformation/shared-resources.yaml \
        --capabilities CAPABILITY_NAMED_IAM \
        --region $REGION 2>/dev/null || \
    aws cloudformation update-stack \
        --stack-name automotive-shared-resources \
        --template-body file://cloudformation/shared-resources.yaml \
        --capabilities CAPABILITY_NAMED_IAM \
        --region $REGION 2>/dev/null || echo "Stack already up to date"
else
    aws cloudformation create-stack \
        --stack-name automotive-shared-resources \
        --template-body file://cloudformation/shared-resources.yaml \
        --parameters $BUCKET_PARAM \
        --capabilities CAPABILITY_NAMED_IAM \
        --region $REGION 2>/dev/null || \
    aws cloudformation update-stack \
        --stack-name automotive-shared-resources \
        --template-body file://cloudformation/shared-resources.yaml \
        --parameters $BUCKET_PARAM \
        --capabilities CAPABILITY_NAMED_IAM \
        --region $REGION 2>/dev/null || echo "Stack already up to date"
fi

echo "Waiting for stack to be ready..."
aws cloudformation wait stack-create-complete \
    --stack-name automotive-shared-resources \
    --region $REGION 2>/dev/null || \
aws cloudformation wait stack-update-complete \
    --stack-name automotive-shared-resources \
    --region $REGION 2>/dev/null || true

# Get outputs
FINAL_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name automotive-shared-resources \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
    --output text)

GLUE_DB=$(aws cloudformation describe-stacks \
    --stack-name automotive-shared-resources \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`GlueDatabaseName`].OutputValue' \
    --output text)

ROLE_ARN=$(aws cloudformation describe-stacks \
    --stack-name automotive-shared-resources \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`DataAccessRoleArn`].OutputValue' \
    --output text)

BUCKET_SOURCE=$(aws cloudformation describe-stacks \
    --stack-name automotive-shared-resources \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`BucketSource`].OutputValue' \
    --output text)

# Save outputs
cat >> deployment/datazone-outputs.env << EOF

# Shared Resources
TIRE_DATA_BUCKET=$FINAL_BUCKET
GLUE_DATABASE=$GLUE_DB
DATA_ACCESS_ROLE=$ROLE_ARN
EOF

echo ""
echo "=== ✓ Shared Resources Deployed ==="
echo ""
echo "Data Bucket: $FINAL_BUCKET"
echo "Source: $BUCKET_SOURCE"
echo "Glue Database: $GLUE_DB"
echo "Data Access Role: $ROLE_ARN"
echo ""
echo "Next steps:"
if [ "$BUCKET_SOURCE" = "Created new bucket" ]; then
    echo "1. Standalone mode: Upload tire data to s3://$FINAL_BUCKET/warehouse/"
    echo "2. Or configure connected-mobility-workspace to write to this bucket"
else
    echo "1. Ensure connected-mobility-workspace writes to: s3://$FINAL_BUCKET/warehouse/"
fi
echo "3. Deploy tire prediction project: make deploy-tire-project"
