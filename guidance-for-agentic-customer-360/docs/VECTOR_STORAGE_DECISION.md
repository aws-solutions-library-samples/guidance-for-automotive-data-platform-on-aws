# Vector Storage Decision: Aurora PostgreSQL with pgvector

## Decision Summary

**Selected**: Aurora PostgreSQL Serverless v2 with pgvector extension  
**Replaced**: OpenSearch Serverless  
**Cost Savings**: ~$500-700/month  
**Date**: January 2026

## Context

The Customer 360 platform uses Bedrock Knowledge Bases for semantic search over operational documentation, customer remediation playbooks, and analytics metadata. This requires vector storage for embeddings.

## Options Evaluated

### 1. OpenSearch Serverless (Previous Approach)
**Pros**:
- Purpose-built for search
- Managed service with auto-scaling
- Rich query capabilities (filters, aggregations)
- Native integration with Bedrock

**Cons**:
- ❌ **High cost**: ~$700/month minimum (2 OCUs × 730 hours × $0.24/OCU-hour)
- ❌ Always-on pricing (no true serverless)
- ❌ Overkill for small demo/accelerator workloads
- ❌ Complex access policies and networking

**Monthly Cost**: $700-1,000

### 2. Amazon Kendra
**Pros**:
- Enterprise search with ML
- Built-in connectors for various data sources
- Natural language understanding

**Cons**:
- ❌ **Very expensive**: $810/month base + $0.40 per 1,000 documents
- ❌ Designed for large-scale enterprise search
- ❌ Not suitable for small accelerators

**Monthly Cost**: $810+

### 3. Aurora PostgreSQL with pgvector (Selected)
**Pros**:
- ✅ **Cost-effective**: $100-300/month with Serverless v2
- ✅ True serverless scaling (0.5-2 ACUs)
- ✅ Familiar SQL interface
- ✅ Native Bedrock Knowledge Base support
- ✅ Can store both vectors and relational data
- ✅ Automatic backups and point-in-time recovery
- ✅ Scales to zero when not in use (Serverless v2)

**Cons**:
- Requires manual pgvector extension setup
- Less specialized for vector search than OpenSearch
- Query performance may be lower at very large scale (>1M vectors)

**Monthly Cost**: $100-300 (depending on usage)

## Cost Breakdown

### Aurora PostgreSQL Serverless v2
```
Base Configuration:
- Min capacity: 0.5 ACU
- Max capacity: 2 ACU
- Storage: ~10 GB (for demo data)

Compute Cost:
- Average usage: 1 ACU × 730 hours × $0.12/ACU-hour = $87.60/month
- Peak usage: 2 ACU × 100 hours × $0.12/ACU-hour = $24/month
- Total compute: ~$110/month

Storage Cost:
- 10 GB × $0.10/GB-month = $1/month
- Backup storage (7 days): ~$1/month

I/O Cost:
- Estimated 1M I/O operations × $0.20/1M = $0.20/month

Total: ~$112-150/month (typical)
Peak: ~$200-300/month (high usage)
```

### OpenSearch Serverless (Previous)
```
Minimum Configuration:
- 2 OCUs (minimum for production)
- 730 hours/month
- $0.24/OCU-hour

Total: 2 × 730 × $0.24 = $350/month (absolute minimum)
Typical: $700-1,000/month (with indexing OCUs)
```

**Savings**: $500-700/month

## Technical Considerations

### Vector Dimensions
- Titan Embed Text v1: 1,536 dimensions
- Titan Embed Text v2: 1,024 dimensions
- Storage per vector: ~6-8 KB (including metadata)

### Scale Estimates
For this accelerator:
- Documents: ~100-500 markdown files
- Chunks: ~5,000-10,000 (after chunking)
- Vectors: ~5,000-10,000
- Total storage: ~50-80 MB

Aurora pgvector handles this easily. OpenSearch would be massive overkill.

### Performance
**Aurora pgvector**:
- Query latency: 50-200ms (for k-NN search)
- Suitable for: <100K vectors
- Index type: IVFFlat (Inverted File with Flat compression)

**OpenSearch Serverless**:
- Query latency: 20-100ms
- Suitable for: >100K vectors
- Index type: HNSW (Hierarchical Navigable Small World)

For demo/accelerator scale, Aurora is sufficient.

## Migration Path to Production

### For Customers Deploying to Production

**Small Scale (<50K vectors)**:
- ✅ Keep Aurora pgvector
- Cost-effective and performant

**Medium Scale (50K-500K vectors)**:
- Consider Aurora with HNSW index (PostgreSQL 16+)
- Or migrate to OpenSearch Serverless

**Large Scale (>500K vectors)**:
- ✅ Migrate to OpenSearch Serverless
- Better performance at scale
- Advanced search features (filters, facets)

### Migration Steps (Aurora → OpenSearch)

1. **Export vectors from Aurora**:
   ```sql
   COPY (
     SELECT id, embedding, chunks, metadata 
     FROM bedrock_integration.bedrock_kb
   ) TO '/tmp/vectors.csv' WITH CSV HEADER;
   ```

2. **Create OpenSearch collection**:
   ```bash
   aws opensearchserverless create-collection \
     --name customer360-vectors \
     --type VECTORSEARCH
   ```

3. **Update Bedrock Knowledge Base**:
   ```typescript
   storageConfiguration: {
     type: 'OPENSEARCH_SERVERLESS',
     opensearchServerlessConfiguration: {
       collectionArn: 'arn:aws:aoss:...',
       vectorIndexName: 'bedrock-kb-index',
     }
   }
   ```

4. **Re-sync data sources** (Bedrock handles migration automatically)

## Implementation Details

### Aurora Setup
```sql
-- Enable pgvector
CREATE EXTENSION vector;

-- Create schema
CREATE SCHEMA bedrock_integration;

-- Create table
CREATE TABLE bedrock_integration.bedrock_kb (
    id UUID PRIMARY KEY,
    embedding vector(1536),
    chunks TEXT,
    metadata JSONB
);

-- Create index
CREATE INDEX ON bedrock_integration.bedrock_kb 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

### Bedrock Configuration
```typescript
storageConfiguration: {
  type: 'RDS',
  rdsConfiguration: {
    resourceArn: cluster.clusterArn,
    credentialsSecretArn: secret.secretArn,
    databaseName: 'vectordb',
    tableName: 'bedrock_integration.bedrock_kb',
    fieldMapping: {
      primaryKeyField: 'id',
      vectorField: 'embedding',
      textField: 'chunks',
      metadataField: 'metadata',
    },
  },
}
```

## Recommendation

**For Guidance/Accelerator Projects**:
- ✅ Use Aurora PostgreSQL with pgvector
- Document OpenSearch as production alternative
- Provide migration guide for scale-up

**For Production Deployments**:
- Evaluate based on scale and budget
- Aurora for <50K vectors
- OpenSearch for >50K vectors or advanced search needs

## References

- [Aurora PostgreSQL pgvector](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/AuroraPostgreSQL.VectorDB.html)
- [Bedrock Knowledge Base with RDS](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-setup.html)
- [OpenSearch Serverless Pricing](https://aws.amazon.com/opensearch-service/pricing/)
- [Aurora Serverless v2 Pricing](https://aws.amazon.com/rds/aurora/pricing/)
