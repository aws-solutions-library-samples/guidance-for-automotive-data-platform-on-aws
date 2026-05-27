#!/bin/bash
set -e

# Initialize Aurora PostgreSQL with pgvector extension for Bedrock Knowledge Base

CLUSTER_ENDPOINT=$1
SECRET_ARN=$2
DATABASE_NAME=${3:-vectordb}
REGION=${AWS_REGION:-us-east-1}

if [ -z "$CLUSTER_ENDPOINT" ] || [ -z "$SECRET_ARN" ]; then
  echo "Usage: $0 <cluster-endpoint> <secret-arn> [database-name]"
  echo ""
  echo "Example:"
  echo "  $0 cx360-cluster.cluster-xxx.us-east-1.rds.amazonaws.com arn:aws:secretsmanager:us-east-1:123456789012:secret:xxx vectordb"
  exit 1
fi

echo "Initializing Aurora PostgreSQL with pgvector..."

# Get credentials from Secrets Manager
SECRET=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --region "$REGION" --query SecretString --output text)
DB_USER=$(echo "$SECRET" | jq -r .username)
DB_PASSWORD=$(echo "$SECRET" | jq -r .password)

# Create SQL initialization script
cat > /tmp/init_pgvector.sql <<EOF
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create schema for Bedrock
CREATE SCHEMA IF NOT EXISTS bedrock_integration;

-- Create table for Knowledge Base vectors
CREATE TABLE IF NOT EXISTS bedrock_integration.bedrock_kb (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    embedding vector(1536),
    chunks TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for vector similarity search
CREATE INDEX IF NOT EXISTS bedrock_kb_embedding_idx 
ON bedrock_integration.bedrock_kb 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Grant permissions to Bedrock service
-- Note: Bedrock uses IAM authentication, this is for manual testing
GRANT USAGE ON SCHEMA bedrock_integration TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON bedrock_integration.bedrock_kb TO PUBLIC;

-- Verify setup
SELECT 
    'pgvector extension' as component,
    extversion as version,
    'installed' as status
FROM pg_extension 
WHERE extname = 'vector';

SELECT 
    'bedrock_kb table' as component,
    COUNT(*) as row_count,
    'ready' as status
FROM bedrock_integration.bedrock_kb;
EOF

echo "Connecting to Aurora cluster: $CLUSTER_ENDPOINT"
echo "Database: $DATABASE_NAME"

# Execute initialization script
PGPASSWORD="$DB_PASSWORD" psql \
  -h "$CLUSTER_ENDPOINT" \
  -U "$DB_USER" \
  -d "$DATABASE_NAME" \
  -f /tmp/init_pgvector.sql

# Clean up
rm /tmp/init_pgvector.sql

echo ""
echo "✅ Aurora PostgreSQL with pgvector initialized successfully!"
echo ""
echo "Next steps:"
echo "1. Deploy Bedrock Knowledge Base stack"
echo "2. Upload documents to S3 knowledge base bucket"
echo "3. Sync data source to populate vectors"
