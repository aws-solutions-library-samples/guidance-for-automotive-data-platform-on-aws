# Bedrock Agent & Knowledge Base Setup

## Overview

Phase 5 deploys AI-powered agents using Amazon Bedrock to monitor customer health, identify at-risk customers, and recommend interventions.

## Architecture

```
Knowledge Base (S3 + OpenSearch Serverless)
    ↓
Bedrock Agent (Claude 3 Sonnet)
    ↓
Action Group (Lambda + Athena)
    ↓
Customer Data (Glue + S3)
```

## Components

### 1. Knowledge Base

**Purpose**: Store and retrieve Customer 360 best practices, intervention strategies, and platform documentation.

**Storage**:
- S3 bucket: `cx360-knowledge-base-{account-id}`
- Vector store: OpenSearch Serverless
- Embeddings: Amazon Titan Embed Text v1

**Documents to Upload**:
```
docs/
├── customer-health-scoring.md
├── churn-prevention-strategies.md
├── intervention-playbooks.md
├── clv-optimization.md
└── platform-user-guide.md
```

### 2. Customer Health Agent

**Model**: Claude 3 Sonnet
**Capabilities**:
- Monitor customer health scores
- Identify at-risk customers (health < 70)
- Calculate revenue at risk
- Recommend intervention strategies
- Answer questions about customer analytics

**Action Group**: Athena Queries
- `/customer-health` - Get health scores with filters
- `/revenue-at-risk` - Calculate total revenue exposure
- `/customer-trends` - Analyze trends over time

### 3. Lambda Function

**Purpose**: Execute Athena queries on behalf of the agent

**Queries Supported**:
```python
# Customer health
SELECT customer_id, health_score, churn_probability, lifetime_value
FROM customer_health
WHERE health_score BETWEEN {min} AND {max}

# Revenue at risk
SELECT SUM(lifetime_value) as revenue_at_risk
FROM customer_health
WHERE health_score < 70

# Trends
SELECT date, AVG(health_score), COUNT(*) as customers
FROM customer_health
GROUP BY date
```

## Deployment

### Prerequisites

1. **Enable Bedrock Models**:
```bash
# Enable Claude 3 Sonnet in your region
aws bedrock put-model-invocation-logging-configuration \
  --logging-config '{...}'
```

2. **Create OpenSearch Serverless Collection**:
```bash
aws opensearchserverless create-collection \
  --name cx360-kb \
  --type VECTORSEARCH
```

### Deploy Stack

```bash
make phase5
```

This creates:
- Knowledge Base with S3 bucket
- OpenSearch Serverless collection
- Bedrock Agent with action group
- Lambda function for Athena queries
- IAM roles and permissions

### Upload Knowledge Base Documents

```bash
# Upload documentation
aws s3 cp docs/ s3://cx360-knowledge-base-{account}/docs/ --recursive

# Sync knowledge base
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id {kb-id} \
  --data-source-id {ds-id}
```

## Usage

### Test Agent via Console

1. Navigate to Bedrock → Agents
2. Select "customer-health-monitor"
3. Click "Test"
4. Try queries:
   - "Show me customers with health scores below 40"
   - "What's our total revenue at risk?"
   - "What intervention strategies work best for at-risk customers?"

### Invoke via API

```python
import boto3

bedrock_agent_runtime = boto3.client('bedrock-agent-runtime')

response = bedrock_agent_runtime.invoke_agent(
    agentId='AGENT_ID',
    agentAliasId='TSTALIASID',
    sessionId='session-123',
    inputText='Show me the top 10 at-risk customers'
)

# Stream response
for event in response['completion']:
    if 'chunk' in event:
        print(event['chunk']['bytes'].decode())
```

### Integrate with Applications

```typescript
// Web application integration
import { BedrockAgentRuntimeClient, InvokeAgentCommand } from "@aws-sdk/client-bedrock-agent-runtime";

const client = new BedrockAgentRuntimeClient({ region: "us-east-1" });

const command = new InvokeAgentCommand({
  agentId: process.env.AGENT_ID,
  agentAliasId: "TSTALIASID",
  sessionId: userId,
  inputText: userQuery
});

const response = await client.send(command);
```

## Agent Instructions

The agent is configured with these instructions:

```
You are a customer success AI agent for an automotive company's Customer 360 platform.

Your responsibilities:
1. Monitor customer health scores and identify at-risk customers
2. Analyze churn probability and revenue at risk
3. Recommend intervention strategies based on customer data
4. Answer questions about customer analytics and trends

When analyzing customers:
- Health scores below 40 are critical (immediate action needed)
- Health scores 40-70 are at-risk (proactive outreach recommended)
- Health scores above 70 are healthy (maintain engagement)

Use the Athena query action to retrieve customer data. Reference the knowledge base for best practices and intervention strategies.

Always provide specific, actionable recommendations with data to support your analysis.
```

## Knowledge Base Content

### Recommended Documents

1. **customer-health-scoring.md**
   - How health scores are calculated
   - Component weights and formulas
   - Interpretation guidelines

2. **churn-prevention-strategies.md**
   - Proven intervention tactics
   - Timing recommendations
   - Success metrics

3. **intervention-playbooks.md**
   - Step-by-step playbooks by risk level
   - Communication templates
   - Escalation procedures

4. **clv-optimization.md**
   - Revenue stream analysis
   - Upsell/cross-sell opportunities
   - Retention strategies

## Monitoring

### CloudWatch Metrics

```bash
# Agent invocations
aws cloudwatch get-metric-statistics \
  --namespace AWS/Bedrock \
  --metric-name AgentInvocations \
  --dimensions Name=AgentId,Value={agent-id}

# Lambda executions
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=athena-query-function
```

### CloudWatch Logs

- Agent logs: `/aws/bedrock/agent/{agent-id}`
- Lambda logs: `/aws/lambda/athena-query-function`

## Cost Estimate

| Component | Monthly Cost | Notes |
|-----------|-------------|-------|
| Bedrock Agent | $0 | Pay per invocation |
| Claude 3 Sonnet | $3-15/1M tokens | Input: $3, Output: $15 |
| Knowledge Base | $0.10/GB | Storage + queries |
| OpenSearch Serverless | $700/month | 4 OCUs minimum |
| Lambda | $1-5 | Depends on usage |
| **Total** | **~$700-720/month** | |

**Note**: OpenSearch Serverless is the main cost driver. For lower costs, consider using Amazon Kendra or Pinecone for vector storage.

## Troubleshooting

### Agent not responding
- Check agent status in console
- Verify IAM role permissions
- Check CloudWatch logs

### Athena queries failing
- Verify Glue database exists
- Check Lambda has Athena permissions
- Ensure workgroup is configured

### Knowledge Base not returning results
- Verify documents are uploaded to S3
- Run ingestion job
- Check vector index configuration

## Future Enhancements

1. **Additional Agents**:
   - Churn Prevention Agent
   - Revenue Optimization Agent
   - Customer Engagement Agent

2. **Advanced Actions**:
   - Send emails/notifications
   - Create support tickets
   - Update CRM records

3. **Multi-Agent Collaboration**:
   - Agents work together on complex tasks
   - Shared context and memory

## References

- [Bedrock Agents Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
- [Knowledge Bases Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
- [Action Groups Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-action-groups.html)
