# OpenSearch Serverless - Using Existing Collection

## Answer: YES - You Already Have OpenSearch Serverless

### Existing Collections

Found 2 active OpenSearch Serverless collections in your account:
1. **`customer360-vectors`** - Can be reused for Customer 360 knowledge base
2. **`fleet-kb-collection-cms`** - Existing fleet knowledge base

## Cost Savings

**Without reuse**: $700/month for new collection
**With reuse**: $0/month (already paying for existing collection)
**Savings**: ~$700/month

## Why OpenSearch Serverless is Needed

**For Bedrock Knowledge Base**:
- Stores document embeddings (vector representations)
- Enables semantic search across documents
- Powers RAG (Retrieve and Generate) capability
- Required for knowledge base functionality

**How it works**:
```
Documents → Embeddings (Titan) → Vector Storage (OpenSearch) → Retrieval → Agent
```

## Changes Made

### 1. Updated bedrock-agent-stack.ts
```typescript
opensearchServerlessConfiguration: {
  // Use existing collection
  collectionArn: `arn:aws:aoss:${this.region}:${this.account}:collection/customer360-vectors`,
  vectorIndexName: 'cx360-kb-index',  // New index in existing collection
  ...
}
```

### 2. Updated setup-bedrock.sh
- Checks for existing `customer360-vectors` collection
- Uses it if found (saves $700/month)
- Only creates new collection if not found
- Creates new vector index: `cx360-kb-index`

### 3. Updated Cost Estimates
**README.md**:
- OpenSearch Serverless: $0 (using existing)
- Total platform: $192-380/month (was $892-1080)
- **Savings: ~$700/month**

## Multiple Knowledge Bases, One Collection

**Best Practice**: Multiple knowledge bases can share one OpenSearch collection

```
OpenSearch Serverless Collection: customer360-vectors
├── Index: cx360-kb-index          (Customer 360 knowledge base)
├── Index: fleet-kb-index           (Fleet management KB)
└── Index: maintenance-kb-index     (Predictive maintenance KB)
```

**Benefits**:
- Single $700/month cost
- Shared infrastructure
- Centralized vector storage
- Easier management

## Deployment Impact

### Before
```bash
make phase5
# Creates new OpenSearch collection
# Cost: +$700/month
```

### After
```bash
make phase5
# Uses existing customer360-vectors collection
# Creates new index: cx360-kb-index
# Cost: +$0/month (already paying for collection)
```

## Verification

Check existing collection:
```bash
aws opensearchserverless batch-get-collection \
  --names customer360-vectors \
  --region us-east-1 \
  --profile givenand-CMS

# Output:
# Status: ACTIVE
# Endpoint: https://8ejwvoopky4afyxpnpca.us-east-1.aoss.amazonaws.com
```

## Summary

✅ **You already have OpenSearch Serverless** (`customer360-vectors`)
✅ **Updated CDK to reuse existing collection**
✅ **Updated setup script to detect and use existing**
✅ **Cost savings: ~$700/month**

The Customer 360 platform now leverages your existing OpenSearch infrastructure, making Bedrock agents much more cost-effective!
