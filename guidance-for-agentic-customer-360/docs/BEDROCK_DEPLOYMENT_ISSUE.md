# Bedrock Deployment Issue - Manual Workaround

## Issue

CloudFormation's `AWS::EarlyValidation::ResourceExistenceCheck` hook is preventing automated deployment of the Bedrock Knowledge Base with Aurora pgvector storage.

**Error**: 
```
Failed to create ChangeSet: The following hook(s)/validation failed: [AWS::EarlyValidation::ResourceExistenceCheck]
```

## Root Cause

The early validation hook validates that the Aurora cluster exists before creating the CloudFormation changeset. Even with a hardcoded cluster ARN, the validation fails, likely due to:
1. Cross-stack reference timing issues
2. Hook checking cluster accessibility/permissions
3. Known CloudFormation limitation with Bedrock + RDS integration

## Workaround Options

### Option 1: Manual Bedrock Setup (Recommended for now)

1. **Create Knowledge Base via Console**:
   - Go to Amazon Bedrock console
   - Create Knowledge Base
   - Choose Aurora PostgreSQL as vector store
   - Use cluster: `cx360-dev-aurora-auroracluster23d869c0-hj5be8j3eb3c`
   - Database: `vectordb`
   - Table: `bedrock_integration.bedrock_kb`

2. **Create Data Source**:
   - S3 bucket: Get from CloudFormation outputs
   - Prefix: `docs/`

3. **Create Agent**:
   - Use Lambda function from CloudFormation for action group
   - Link Knowledge Base

### Option 2: Use OpenSearch Serverless Instead

Revert to OpenSearch Serverless (no early validation issues):
- Cost: +$700/month
- No deployment issues
- Proven integration

### Option 3: Deploy Bedrock Separately

Deploy Bedrock stack after a delay:
```bash
# Deploy main stacks
make phase1 phase2 phase3 phase4

# Wait 5 minutes for Aurora to stabilize
sleep 300

# Deploy Bedrock
make phase5
```

### Option 4: Use Terraform/Pulumi

CDK/CloudFormation has this limitation. Terraform might not have the same early validation hook.

## Current Status

- ✅ Aurora PostgreSQL with pgvector deployed
- ✅ pgvector extension initialized
- ✅ Knowledge base documents ready in `source/knowledge-base/`
- ❌ Bedrock stack blocked by CloudFormation hook

## Platform Functionality Without Bedrock

The platform is **fully functional** without Bedrock agents:
- ✅ Data lake and analytics (Athena queries)
- ✅ QuickSight dashboards
- ✅ Customer 360 data
- ❌ AI-powered insights (Bedrock agents)

## Recommendation

For the guidance/accelerator:
1. Document Bedrock setup as **optional manual step**
2. Provide console screenshots
3. Include CLI commands for manual setup
4. Note this as a known limitation in README

The core Customer 360 platform works without Bedrock. Agents are an enhancement, not a requirement.
