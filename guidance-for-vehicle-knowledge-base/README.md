# Vehicle Knowledge Base on AWS

An AI-ready knowledge base for automotive technical reference, diagnostic procedures, maintenance schedules, and warranty policies.

## Overview

This guidance deploys a Bedrock Knowledge Base (RAG system) backed by 4 automotive data sources on AWS. The knowledge base supports natural language queries for vehicle diagnostics, maintenance, recalls, and service policies — enabling AI agents and customer support systems to provide accurate, context-aware responses.

Use cases include:
- **AI agent backends** — queries resolved via Bedrock Agents with retrieval-augmented generation
- **Customer support** — self-service knowledge base for vehicle owners and technicians
- **Diagnostic assistance** — DTC (Diagnostic Trouble Code) interpretation and troubleshooting procedures
- **Warranty and service** — policy lookups, recall notifications, and escalation rules

## Architecture

```
┌──────────────────────────────┐
│ Bedrock Knowledge Base       │
│ (Titan text embeddings)      │
└──────────────────┬───────────┘
                   │
                   ▼
┌──────────────────────────────┐
│ OpenSearch Serverless        │
│ (vector storage + search)    │
└──────────────────┬───────────┘
                   │
                   ▼
┌──────────────────────────────────────────┐
│ S3 Data Sources (4 categories)           │
├──────────────────────────────────────────┤
│ • technical-reference (DTCs, diagnostics)│
│ • tsb-recalls (TSBs, NHTSA recalls)      │
│ • owner-manuals (maintenance, fluid specs)│
│ • service-policy (warranty, escalation)  │
└──────────────────────────────────────────┘
```

The stack creates an S3 bucket, Bedrock Knowledge Base resource, and 4 data sources (one per content category). Bedrock automatically manages OpenSearch Serverless vector storage and ingestion.

## Prerequisites

- AWS account with Bedrock service enabled in your region
- AWS CLI with credentials configured
- Python 3.9+
- AWS CDK CLI (`npm install -g aws-cdk`)

## Deployment

### 1. Install dependencies

```bash
cd guidance-for-vehicle-knowledge-base
pip install -r requirements.txt
npm install -g aws-cdk
```

### 2. Deploy the Knowledge Base

```bash
make deploy STAGE=dev AWS_REGION=us-east-1
```

Or manually:

```bash
export STAGE=dev
export AWS_REGION=us-east-1
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=$AWS_REGION

cdk deploy --require-approval never
```

The stack outputs the Knowledge Base ID — save this for use in AI agents or applications.

### 3. Upload and ingest data

```bash
# Upload documents to S3
make upload-data STAGE=dev AWS_REGION=us-east-1

# Trigger Bedrock ingestion for all 4 data sources
make sync-data STAGE=dev AWS_REGION=us-east-1
```

Ingestion typically completes in 5–10 minutes. Check progress in the AWS Console: Bedrock > Knowledge Bases > Ingestion jobs.

## Folder Structure

```
guidance-for-vehicle-knowledge-base/
├── README.md (this file)
├── app.py                                 # CDK app entrypoint
├── requirements.txt                       # Python dependencies
├── cdk.json                              # CDK configuration
├── Makefile                              # Deployment targets
│
├── stacks/
│   ├── __init__.py
│   └── knowledge_base_stack.py           # Bedrock KB + S3 + IAM stack
│
├── data-sources/                         # Pre-ingested content
│   ├── technical-reference/              # DTC guides, diagnostic procedures
│   ├── tsb-recalls/                      # Technical Service Bulletins, recalls
│   ├── owner-manuals/                    # Maintenance schedules, warnings
│   └── service-policy/                   # Warranty, SLA, escalation policies
│
├── datasource/                           # Reference data for data product generation
│   ├── vehicle-identity/                 # VIN, model, year, variant
│   ├── vehicle-lifecycle/                # In-service date, warranty expiry
│   ├── service-network/                  # Service center locations, capabilities
│   ├── parts-catalog/                    # Replacement part numbers, pricing
│   └── campaigns-offers/                 # Manufacturer campaigns, promotions
│
├── reference-data/                       # Data product seeding
│   ├── nhtsa-poller/                     # NHTSA recall data ingestion
│   ├── signal-catalog/                   # Normalized automotive signals
│   └── event-catalog/                    # Event type definitions
│
└── scripts/                              # Data generation utilities
    ├── generate-vehicle-identity.py      # Synthetic vehicle records
    ├── generate-service-network.py       # Service center data
    ├── generate-parts-catalog.py         # Parts and pricing
    └── generate-*.py (others)            # Supporting data generators
```

## Usage

### Query the Knowledge Base (via Bedrock Agents)

```python
import boto3

bedrock_client = boto3.client('bedrock-agent-runtime')

response = bedrock_client.retrieve_and_generate(
    input={'text': 'What are the symptoms and causes of DTC P0301?'},
    retrieveAndGenerateConfiguration={
        'type': 'KNOWLEDGE_BASE',
        'knowledgeBaseConfiguration': {
            'knowledgeBaseId': 'YOUR_KB_ID',
            'modelArn': 'arn:aws:bedrock:region::foundation-model/anthropic.claude-3-haiku',
        }
    }
)

print(response['output']['text'])
```

### Upload custom documents

Add `.md`, `.pdf`, or `.txt` files to the appropriate `data-sources/` subfolder:

```bash
# Add a new TSB
echo "TSB-2026-NEW: Brake fluid leak procedure" > data-sources/tsb-recalls/tsb-2026-NEW.md

# Re-sync data
make sync-data STAGE=dev AWS_REGION=us-east-1
```

## Cleanup

Remove all resources (S3 bucket, Knowledge Base, OpenSearch collection):

```bash
make destroy STAGE=dev AWS_REGION=us-east-1
```

Or via CDK:

```bash
cdk destroy --require-approval never
```

Note: The S3 bucket is set to `RETAIN` on deletion — manually delete `s3://adp-{stage}-vehicle-knowledge-base` if needed.

## Related Guidance

- [Agentic Customer 360](../guidance-for-agentic-customer-360/) — Uses Vehicle KB for customer support AI agents
- [Telemetry Normalization](../guidance-for-telemetry-normalization/) — Feeds vehicle data to the KB's diagnostic reference
- [Predictive Maintenance](../guidance-for-predictive-maintenance/) — Integrates KB for maintenance procedure lookups
