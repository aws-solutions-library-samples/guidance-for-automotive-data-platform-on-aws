#!/bin/bash
set -e

# Create Bedrock Agent with Knowledge Base and Lambda action group

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-us-east-1}"
PROFILE="${AWS_PROFILE:-default}"

echo "🤖 Creating Bedrock Agent"
echo "========================="
echo ""

# Get Knowledge Base ID from previous output
KB_ID=$(cat /tmp/bedrock-outputs.txt 2>/dev/null | grep "Knowledge Base ID:" | cut -d' ' -f4)

if [ -z "$KB_ID" ]; then
  echo "❌ Knowledge Base ID not found. Run create-bedrock-kb-cli.sh first."
  exit 1
fi

echo "Knowledge Base ID: ${KB_ID}"
echo ""

# Create IAM role for Agent
echo "Creating IAM role for Bedrock Agent..."

AGENT_ROLE_NAME="BedrockAgentRole-CX360-${REGION}"

# Trust policy
cat > /tmp/agent-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "${ACCOUNT_ID}"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock:${REGION}:${ACCOUNT_ID}:agent/*"
        }
      }
    }
  ]
}
EOF

aws iam create-role \
  --role-name "${AGENT_ROLE_NAME}" \
  --assume-role-policy-document file:///tmp/agent-trust-policy.json \
  --profile "${PROFILE}" 2>/dev/null && echo "  ✓ Role created" || echo "  ⚠ Role already exists"

# Agent policy
cat > /tmp/agent-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:${REGION}::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0"
    },
    {
      "Effect": "Allow",
      "Action": "bedrock:Retrieve",
      "Resource": "arn:aws:bedrock:${REGION}:${ACCOUNT_ID}:knowledge-base/${KB_ID}"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name "${AGENT_ROLE_NAME}" \
  --policy-name "BedrockAgentPolicy" \
  --policy-document file:///tmp/agent-policy.json \
  --profile "${PROFILE}" && echo "  ✓ Policy attached"

sleep 5

AGENT_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${AGENT_ROLE_NAME}"
echo "Agent Role ARN: ${AGENT_ROLE_ARN}"
echo ""

# Create Agent
echo "Creating Bedrock Agent..."

AGENT_NAME="customer-360-analyzer"

# Check if agent already exists
EXISTING_AGENT=$(aws bedrock-agent list-agents \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query "agentSummaries[?agentName=='${AGENT_NAME}'].agentId" \
  --output text 2>/dev/null)

if [ -n "$EXISTING_AGENT" ]; then
  echo "  ⚠ Agent already exists: ${EXISTING_AGENT}"
  AGENT_ID="${EXISTING_AGENT}"
else
  AGENT_ID=$(aws bedrock-agent create-agent \
  --agent-name "${AGENT_NAME}" \
  --agent-resource-role-arn "${AGENT_ROLE_ARN}" \
  --foundation-model "anthropic.claude-3-sonnet-20240229-v1:0" \
  --instruction "You are a customer success AI agent for an automotive company's Customer 360 platform.

Your responsibilities:
1. Monitor customer health scores and identify at-risk customers
2. Analyze churn probability and revenue at risk
3. Recommend intervention strategies based on customer data
4. Answer questions about customer analytics and trends

When analyzing customers:
- Health scores below 40 are critical (immediate action needed)
- Health scores 40-70 are at-risk (proactive outreach recommended)
- Health scores above 70 are healthy (maintain engagement)

Use the knowledge base for best practices and intervention strategies.
Always provide specific, actionable recommendations with data to support your analysis." \
  --idle-session-ttl-in-seconds 600 \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query 'agent.agentId' \
  --output text)

  echo "  ✓ Agent created: ${AGENT_ID}"
fi
echo ""

# Associate Knowledge Base
echo "Associating Knowledge Base with Agent..."

aws bedrock-agent associate-agent-knowledge-base \
  --agent-id "${AGENT_ID}" \
  --agent-version "DRAFT" \
  --knowledge-base-id "${KB_ID}" \
  --description "Customer 360 platform documentation and best practices" \
  --knowledge-base-state "ENABLED" \
  --profile "${PROFILE}" \
  --region "${REGION}" > /dev/null && echo "  ✓ Knowledge Base associated"

echo ""

# Prepare Agent
echo "Preparing Agent..."

aws bedrock-agent prepare-agent \
  --agent-id "${AGENT_ID}" \
  --profile "${PROFILE}" \
  --region "${REGION}" > /dev/null && echo "  ✓ Agent prepared"

echo ""

# Create Agent Alias
echo "Creating Agent Alias..."

# Check if alias already exists
EXISTING_ALIAS=$(aws bedrock-agent list-agent-aliases \
  --agent-id "${AGENT_ID}" \
  --profile "${PROFILE}" \
  --region "${REGION}" \
  --query "agentAliasSummaries[?agentAliasName=='production'].agentAliasId" \
  --output text 2>/dev/null)

if [ -n "$EXISTING_ALIAS" ]; then
  echo "  ⚠ Alias already exists: ${EXISTING_ALIAS}"
  ALIAS_ID="${EXISTING_ALIAS}"
else
  ALIAS_ID=$(aws bedrock-agent create-agent-alias \
    --agent-id "${AGENT_ID}" \
    --agent-alias-name "production" \
    --profile "${PROFILE}" \
    --region "${REGION}" \
    --query 'agentAlias.agentAliasId' \
    --output text)

  echo "  ✓ Alias created: ${ALIAS_ID}"
fi
echo ""

# Save outputs
cat >> /tmp/bedrock-outputs.txt <<EOF
Agent ID: ${AGENT_ID}
Agent Alias ID: ${ALIAS_ID}
Agent Role ARN: ${AGENT_ROLE_ARN}
EOF

echo "========================="
echo "✅ Bedrock Agent created!"
echo "========================="
echo ""
cat /tmp/bedrock-outputs.txt
echo ""
echo "Test the agent:"
echo "aws bedrock-agent-runtime invoke-agent \\"
echo "  --agent-id ${AGENT_ID} \\"
echo "  --agent-alias-id ${ALIAS_ID} \\"
echo "  --session-id test-session-1 \\"
echo "  --input-text 'Show me customers at risk' \\"
echo "  output.txt"
echo ""

# Cleanup
rm -f /tmp/agent-trust-policy.json /tmp/agent-policy.json
