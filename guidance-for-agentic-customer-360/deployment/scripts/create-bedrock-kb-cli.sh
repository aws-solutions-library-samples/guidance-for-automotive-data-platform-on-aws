#!/bin/bash
set -e

# Create Bedrock Knowledge Base with Aurora pgvector using AWS CLI
# Bypasses CloudFormation early validation hook issues

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-default}"

echo "🚀 Creating Bedrock Knowledge Base with Aurora pgvector"
echo "========================================================="
echo "Account: ${ACCOUNT_ID}"
echo "Region: ${REGION}"
echo ""

# Get Aurora cluster ARN
CLUSTER_ARN=$(aws rds describe-db-clusters \
  --query 'DBClusters[?starts_with(DBClusterIdentifier, `cx360-dev-aurora`)].DBClusterArn' \
  --output text \
  --profile "${PROFILE}" \
  --region "${REGION}")

echo "Aurora Cluster: ${CLUSTER_ARN}"

# Get secret ARN
SECRET_ARN=$(aws cloudformation describe-stacks \
  --stack-name cx360-dev-aurora \
  --query 'Stacks[0].Outputs[?OutputKey==`SecretArn`].OutputValue' \
  --output text \
  --profile "${PROFILE}" \
  --region "${REGION}")

echo "Secret: ${SECRET_ARN}"
echo ""

# Create IAM role for Knowledge Base
echo "Creating IAM role for Knowledge Base..."

ROLE_NAME="BedrockKBRole-CX360-${REGION}"

# Create trust policy
cat > /tmp/kb-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create role
aws iam create-role \
  --role-name "${ROLE_NAME}" \
  --assume-role-policy-document file:///tmp/kb-trust-policy.json \
  --profile "${PROFILE}" 2>/dev/null && echo "  ✓ Role created" || echo "  ⚠ Role already exists"

# Create policy for Aurora access
cat > /tmp/kb-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "rds-data:ExecuteStatement",
        "rds-data:BatchExecuteStatement"
      ],
      "Resource": "${CLUSTER_ARN}"
    },
    {
      "Effect": "Allow",
      "Action": "rds:DescribeDBClusters",
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "${SECRET_ARN}"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "arn:aws:bedrock:${REGION}::foundation-model/amazon.titan-embed-text-v1"
    }
  ]
}
EOF

# Attach policy
aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "BedrockKBPolicy" \
  --policy-document file:///tmp/kb-policy.json \
  --profile "${PROFILE}" && echo "  ✓ Policy attached"

# Wait for role to propagate
echo "Waiting for IAM role to propagate..."
sleep 10

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "Role ARN: ${ROLE_ARN}"
echo ""

# Create Knowledge Base
echo "Creating Knowledge Base..."

KB_NAME="customer-360-kb-$(date +%Y%m%d)"

# Check if KB already exists
EXISTING_KB=$(aws bedrock-agent list-knowledge-bases \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query "knowledgeBaseSummaries[?name=='${KB_NAME}'].knowledgeBaseId" \
  --output text 2>/dev/null)

if [ -n "$EXISTING_KB" ]; then
  echo "  ⚠ Knowledge Base already exists: ${EXISTING_KB}"
  KB_ID="${EXISTING_KB}"
else
  KB_ID=$(aws bedrock-agent create-knowledge-base \
    --name "${KB_NAME}" \
  --description "Customer 360 analytics platform documentation and best practices" \
  --role-arn "${ROLE_ARN}" \
  --knowledge-base-configuration '{
    "type": "VECTOR",
    "vectorKnowledgeBaseConfiguration": {
      "embeddingModelArn": "arn:aws:bedrock:'${REGION}'::foundation-model/amazon.titan-embed-text-v1"
    }
  }' \
  --storage-configuration '{
    "type": "RDS",
    "rdsConfiguration": {
      "resourceArn": "'${CLUSTER_ARN}'",
      "credentialsSecretArn": "'${SECRET_ARN}'",
      "databaseName": "vectordb",
      "tableName": "bedrock_integration.bedrock_kb",
      "fieldMapping": {
        "primaryKeyField": "id",
        "vectorField": "embedding",
        "textField": "chunks",
        "metadataField": "metadata"
      }
    }
  }' \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query 'knowledgeBase.knowledgeBaseId' \
  --output text)

  echo "  ✓ Knowledge Base created: ${KB_ID}"
fi
echo ""

# Create S3 bucket for documents
echo "Creating S3 bucket for knowledge base documents..."

BUCKET_NAME="cx360-kb-docs-${ACCOUNT_ID}"

aws s3 mb s3://${BUCKET_NAME} \
  --profile "${PROFILE}" \
  --region "${REGION}" 2>/dev/null && echo "  ✓ Bucket created" || echo "  ⚠ Bucket already exists"

# Grant Bedrock access to S3
cat > /tmp/kb-s3-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::${BUCKET_NAME}",
        "arn:aws:s3:::${BUCKET_NAME}/*"
      ]
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name "BedrockKBS3Policy" \
  --policy-document file:///tmp/kb-s3-policy.json \
  --profile "${PROFILE}" && echo "  ✓ S3 policy attached"

echo ""

# Create data source
echo "Creating data source..."

# Check if data source already exists
EXISTING_DS=$(aws bedrock-agent list-data-sources \
  --knowledge-base-id "${KB_ID}" \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query "dataSourceSummaries[?name=='cx360-documentation'].dataSourceId" \
  --output text 2>/dev/null | tr -d '\n')

if [ -n "$EXISTING_DS" ] && [ "$EXISTING_DS" != "None" ]; then
  echo "  ⚠ Data source already exists: ${EXISTING_DS}"
  DATA_SOURCE_ID="${EXISTING_DS}"
else
  DATA_SOURCE_ID=$(aws bedrock-agent create-data-source \
  --knowledge-base-id "${KB_ID}" \
  --name "cx360-documentation" \
  --description "Customer 360 platform documentation" \
  --data-source-configuration '{
    "type": "S3",
    "s3Configuration": {
      "bucketArn": "arn:aws:s3:::'${BUCKET_NAME}'",
      "inclusionPrefixes": ["docs/"]
    }
  }' \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query 'dataSource.dataSourceId' \
  --output text)

  echo "  ✓ Data source created: ${DATA_SOURCE_ID}"
fi
echo ""

# Upload documents
echo "Uploading knowledge base documents..."

aws s3 sync ../../source/knowledge-base/ s3://${BUCKET_NAME}/docs/ \
  --exclude "README.md" \
  --exclude "*.csv" \
  --profile "${PROFILE}" && echo "  ✓ Documents uploaded"

echo ""

# Start ingestion
echo "Starting data source ingestion..."

INGESTION_JOB_ID=$(aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "${KB_ID}" \
  --data-source-id "${DATA_SOURCE_ID}" \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query 'ingestionJob.ingestionJobId' \
  --output text)

echo "  ✓ Ingestion job started: ${INGESTION_JOB_ID}"
echo ""

# Save outputs
cat > /tmp/bedrock-outputs.txt <<EOF
Knowledge Base ID: ${KB_ID}
Data Source ID: ${DATA_SOURCE_ID}
S3 Bucket: ${BUCKET_NAME}
Role ARN: ${ROLE_ARN}
Ingestion Job ID: ${INGESTION_JOB_ID}
EOF

echo "========================================================="
echo "✅ Bedrock Knowledge Base created successfully!"
echo "========================================================="
echo ""
cat /tmp/bedrock-outputs.txt
echo ""
echo "Next steps:"
echo "1. Wait for ingestion to complete (~5-10 minutes)"
echo "2. Check status: aws bedrock-agent get-ingestion-job --knowledge-base-id ${KB_ID} --data-source-id ${DATA_SOURCE_ID} --ingestion-job-id ${INGESTION_JOB_ID}"
echo "3. Create Bedrock agent (manual or via CLI)"
echo ""

# Cleanup temp files
rm -f /tmp/kb-trust-policy.json /tmp/kb-policy.json /tmp/kb-s3-policy.json
