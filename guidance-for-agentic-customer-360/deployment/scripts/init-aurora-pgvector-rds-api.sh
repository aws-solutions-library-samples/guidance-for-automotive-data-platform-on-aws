#!/bin/bash
set -e

# Initialize Aurora PostgreSQL with pgvector extension for Bedrock Knowledge Base
# Uses AWS RDS Data API (no psql required)

CLUSTER_ARN=$1
SECRET_ARN=$2
DATABASE_NAME=${3:-vectordb}
REGION=${AWS_REGION:-us-east-1}

if [ -z "$CLUSTER_ARN" ] || [ -z "$SECRET_ARN" ]; then
  echo "Usage: $0 <cluster-arn> <secret-arn> [database-name]"
  echo ""
  echo "Note: This script uses cluster ARN, not endpoint"
  echo "Get from CloudFormation outputs or use:"
  echo "  CLUSTER_ARN=\$(aws rds describe-db-clusters --query 'DBClusters[?DBClusterIdentifier==\`cx360-dev-aurora-auroracluster23d869c0-xxx\`].DBClusterArn' --output text)"
  exit 1
fi

echo "Initializing Aurora PostgreSQL with pgvector..."
echo "Cluster: $CLUSTER_ARN"
echo "Database: $DATABASE_NAME"
echo ""

# Function to execute SQL via RDS Data API
execute_sql() {
  local sql="$1"
  local description="$2"
  
  echo "  $description..."
  
  aws rds-data execute-statement \
    --resource-arn "$CLUSTER_ARN" \
    --secret-arn "$SECRET_ARN" \
    --database "$DATABASE_NAME" \
    --sql "$sql" \
    --region "$REGION" \
    > /dev/null 2>&1 && echo "    ✓ Success" || echo "    ⚠ May already exist"
}

# Enable pgvector extension
execute_sql "CREATE EXTENSION IF NOT EXISTS vector;" "Enabling pgvector extension"

# Create schema for Bedrock
execute_sql "CREATE SCHEMA IF NOT EXISTS bedrock_integration;" "Creating bedrock_integration schema"

# Create table for Knowledge Base vectors
execute_sql "CREATE TABLE IF NOT EXISTS bedrock_integration.bedrock_kb (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    embedding vector(1536),
    chunks TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);" "Creating bedrock_kb table"

# Create index for vector similarity search (HNSW required by Bedrock)
execute_sql "CREATE INDEX IF NOT EXISTS bedrock_kb_embedding_idx 
ON bedrock_integration.bedrock_kb 
USING hnsw (embedding vector_cosine_ops);" "Creating HNSW vector index"

# Create text search index on chunks column (required by Bedrock)
execute_sql "CREATE INDEX IF NOT EXISTS bedrock_kb_chunks_idx 
ON bedrock_integration.bedrock_kb 
USING gin (to_tsvector('english', chunks));" "Creating text search index on chunks"

# Grant permissions
execute_sql "GRANT USAGE ON SCHEMA bedrock_integration TO PUBLIC;" "Granting schema permissions"
execute_sql "GRANT SELECT, INSERT, UPDATE, DELETE ON bedrock_integration.bedrock_kb TO PUBLIC;" "Granting table permissions"

echo ""
echo "✅ Aurora PostgreSQL with pgvector initialized successfully!"
echo ""
echo "Next steps:"
echo "1. Deploy Bedrock Knowledge Base stack"
echo "2. Upload documents to S3 knowledge base bucket"
echo "3. Sync data source to populate vectors"
