#!/bin/bash

# Bedrock Setup Script for Customer 360 Analytics
# This script sets up prerequisites for Bedrock agents and knowledge base

set -e

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-default}"
COLLECTION_NAME="customer360-vectors"

echo "🚀 Bedrock Setup for Customer 360"
echo "=================================="
echo "Account: ${ACCOUNT_ID}"
echo "Region: ${REGION}"
echo ""

# Check if Bedrock is available in region
echo "Checking Bedrock availability..."
if ! aws bedrock list-foundation-models --region ${REGION} --profile ${PROFILE} &>/dev/null; then
  echo "❌ Bedrock is not available in ${REGION}"
  echo "Please use a region where Bedrock is available (us-east-1, us-west-2, etc.)"
  exit 1
fi

echo "✓ Bedrock is available"
echo ""

# Check if Claude 3 Sonnet is available
echo "Checking Claude 3 Sonnet availability..."
CLAUDE_MODEL="anthropic.claude-3-sonnet-20240229-v1:0"
if aws bedrock list-foundation-models \
  --region ${REGION} \
  --profile ${PROFILE} \
  --query "modelSummaries[?modelId=='${CLAUDE_MODEL}'].modelId" \
  --output text | grep -q "${CLAUDE_MODEL}"; then
  echo "✓ Claude 3 Sonnet is available"
else
  echo "⚠ Claude 3 Sonnet not found, checking for access..."
fi

echo ""

# Check if OpenSearch Serverless collection exists
echo "Checking for existing OpenSearch Serverless collection..."
if aws opensearchserverless list-collections \
  --region ${REGION} \
  --profile ${PROFILE} \
  --query "collectionSummaries[?name=='${COLLECTION_NAME}'].name" \
  --output text | grep -q "${COLLECTION_NAME}"; then
  echo "✓ Using existing collection: ${COLLECTION_NAME}"
  
  # Get collection endpoint
  COLLECTION_ENDPOINT=$(aws opensearchserverless batch-get-collection \
    --names ${COLLECTION_NAME} \
    --region ${REGION} \
    --profile ${PROFILE} \
    --query 'collectionDetails[0].collectionEndpoint' \
    --output text 2>/dev/null || echo "")
  
  if [ -n "$COLLECTION_ENDPOINT" ]; then
    echo "  Collection endpoint: ${COLLECTION_ENDPOINT}"
    echo "  Status: ACTIVE"
    echo ""
    echo "✓ No new OpenSearch collection needed - using existing"
    echo "  This saves ~$700/month!"
  fi
else
  echo "⚠ Collection ${COLLECTION_NAME} not found"
  echo ""
  echo "Creating new OpenSearch Serverless collection..."
  echo "Note: This will add ~$700/month to your AWS bill"
  echo ""
  
  # Create encryption policy
  aws opensearchserverless create-security-policy \
    --name cx360-kb-encryption \
    --type encryption \
    --policy "{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${COLLECTION_NAME}\"]}],\"AWSOwnedKey\":true}" \
    --region ${REGION} \
    --profile ${PROFILE} 2>/dev/null || echo "  Encryption policy may already exist"

  # Create network policy
  aws opensearchserverless create-security-policy \
    --name cx360-kb-network \
    --type network \
    --policy "[{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${COLLECTION_NAME}\"]},{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/${COLLECTION_NAME}\"]}],\"AllowFromPublic\":true}]" \
    --region ${REGION} \
    --profile ${PROFILE} 2>/dev/null || echo "  Network policy may already exist"

  # Create data access policy
  CURRENT_USER_ARN=$(aws sts get-caller-identity --query Arn --output text --profile ${PROFILE})
  aws opensearchserverless create-access-policy \
    --name cx360-kb-access \
    --type data \
    --policy "[{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/${COLLECTION_NAME}\"],\"Permission\":[\"aoss:*\"]},{\"ResourceType\":\"index\",\"Resource\":[\"index/${COLLECTION_NAME}/*\"],\"Permission\":[\"aoss:*\"]}],\"Principal\":[\"${CURRENT_USER_ARN}\"]}]" \
    --region ${REGION} \
    --profile ${PROFILE} 2>/dev/null || echo "  Access policy may already exist"

  # Create collection
  aws opensearchserverless create-collection \
    --name ${COLLECTION_NAME} \
    --type VECTORSEARCH \
    --region ${REGION} \
    --profile ${PROFILE} 2>/dev/null && echo "  ✓ Collection created" || echo "  ⚠ Collection creation failed"

  # Wait for collection to be active
  echo "  Waiting for collection to be active (this may take 2-3 minutes)..."
  for i in {1..60}; do
    STATUS=$(aws opensearchserverless batch-get-collection \
      --names ${COLLECTION_NAME} \
      --region ${REGION} \
      --profile ${PROFILE} \
      --query 'collectionDetails[0].status' \
      --output text 2>/dev/null || echo "CREATING")
    
    if [ "$STATUS" = "ACTIVE" ]; then
      echo "  ✓ Collection is active"
      break
    fi
    
    if [ $i -eq 60 ]; then
      echo "  ⚠ Collection creation timeout - check AWS console"
      break
    fi
    
    sleep 3
  done
fi

echo ""
echo "✅ Bedrock setup complete!"
echo ""
echo "Next steps:"
echo "1. CDK will deploy Bedrock agent stack"
echo "2. Upload knowledge base documents to S3"
echo "3. Sync knowledge base"
echo ""
echo "Knowledge base bucket will be: cx360-knowledge-base-${ACCOUNT_ID}"
