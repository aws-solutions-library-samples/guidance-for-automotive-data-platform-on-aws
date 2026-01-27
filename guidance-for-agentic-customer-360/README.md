# Customer 360 Analytics Platform with Agentic AI

An end-to-end customer analytics platform demonstrating declining business metrics and AI-powered root cause analysis using AWS services.

## Overview

This platform showcases a complete Customer 360 solution with:
- **Synthetic data** with realistic declining trends (NPS, health scores, revenue)
- **Increasing battery issues** (15% → 40% over 12 months) for root cause analysis
- **QuickSight dashboards** for visual analytics
- **Bedrock Agent** for AI-powered insights and natural language queries

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Layer                                │
├─────────────────────────────────────────────────────────────────┤
│  S3 Data Lake  →  Glue Catalog  →  Athena Views                │
│  (Raw CSV)        (Tables)         (Analytics)                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Analytics Layer                               │
├─────────────────────────────────────────────────────────────────┤
│  QuickSight Datasets  →  Dashboard  →  Demo User                │
│  (8 datasets)            (Analysis)     (Viewer)                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      AI Layer                                    │
├─────────────────────────────────────────────────────────────────┤
│  Aurora pgvector  →  Knowledge Base  →  Bedrock Agent           │
│  (Vector DB)         (Documentation)    (Q&A)                    │
└─────────────────────────────────────────────────────────────────┘
```

### Components

#### Data Lake (Phase 1)
- **S3 Bucket**: Raw data storage with 11 datasets
- **Glue Catalog**: Metadata and table definitions
- **Glue Crawler**: Automatic schema discovery
- **Athena**: SQL queries on S3 data

#### Analytics (Phases 3-4)
- **Synthetic Data Generator**: Creates 500K customers with declining metrics
  - NPS: 52 → 42 (declining 1.5% monthly)
  - Health Scores: 65 → 56 (declining 1.5% monthly)
  - Battery Issues: 15% → 40% (increasing 2% monthly)
- **8 Athena Views**: Pre-built analytics queries
- **QuickSight**: 8 datasets, analysis, and dashboard
- **Demo User**: QuickSight-only authentication

#### AI Layer (Phase 5)
- **Aurora PostgreSQL**: Vector database with pgvector extension
- **Bedrock Knowledge Base**: Documentation and playbooks
- **Bedrock Agent**: Natural language query interface with Athena integration

### Data Model

**Core Datasets:**
1. `customers` (500K records) - Customer master data
2. `customer_health` (500K records) - Health scores and metrics
3. `interactions` (1.4M records) - Customer touchpoints
4. `service_records` (900K records) - Service history
5. `cases` (500K records) - Support cases with battery issues
6. `monthly_kpis` (12 records) - Aggregated KPIs by month
7. `operational_kpis` (12 records) - Service quality metrics
8. `issue_categories` (12 records) - Issue breakdown by type
9. `revenue_streams` (5 records) - Revenue by stream
10. `revenue_trends` (5 records) - Revenue changes
11. `at_risk_revenue` (48 records) - At-risk revenue by segment

**Key Metrics:**
- Net Promoter Score (NPS)
- Customer Health Score
- Customer Lifetime Value (CLV)
- Churn Risk
- Service Quality Metrics
- Revenue by Stream

## Prerequisites

- **AWS Account** with admin access
- **AWS CLI** configured with credentials
- **Node.js** 18+ installed
- **Python** 3.9+ installed
- **CDK CLI**: `npm install -g aws-cdk`
- **QuickSight** subscription (Enterprise edition)

## Quick Start

### 1. Clone and Install

```bash
cd guidance-for-agentic-customer-360
make install
```

### 2. Deploy

```bash
make deploy
```

**Interactive Menu:**
1. Select AWS profile (from `~/.aws/credentials`)
2. Select region (us-east-1 recommended for QuickSight)
3. Choose deployment option:
   - Option 1: Bootstrap CDK (first time only)
   - Option 2: Deploy All (recommended)
   - Options 3-7: Individual phases

### 3. Access Dashboard

After deployment completes:

**QuickSight Dashboard:**
1. Go to: https://us-east-1.quicksight.aws.amazon.com/
2. Account name: (shown in deployment output)
3. Sign in with IAM or demo user credentials

**Demo User Setup:**
- Username: `demo-viewer`
- Setup URL: (shown in deployment output)
- Visit URL to set password

## Deployment Phases

### Phase 1: Data Lake Infrastructure
```bash
make phase1
```
- Creates S3 bucket for data lake
- Sets up Glue catalog database
- Deploys Athena workgroup

**Duration:** ~2 minutes

### Phase 2: ETL & Prerequisites
```bash
make phase2
```
- Deploys Glue ETL jobs
- Creates Glue crawler
- Grants Lake Formation permissions
- Creates QuickSight data source

**Duration:** ~3 minutes

### Phase 3: Data Generation
```bash
make phase3
```
- Generates 500K customers with declining metrics
- Uploads 11 datasets to S3 (~2GB total)
- Runs Glue crawler to discover tables
- Creates 8 Athena views

**Duration:** ~10 minutes (data generation + crawler)

**What's Generated:**
- 500,000 customers
- 1.4M interactions
- 900K service records
- 500K support cases
- 12 months of declining trends

### Phase 4: QuickSight Dashboard
```bash
make phase4
```
- Creates 8 QuickSight datasets from Athena views
- Imports dashboard definition
- Creates analysis and dashboard
- Creates demo user with invitation URL
- Grants permissions

**Duration:** ~5 minutes

**Outputs:**
- Dashboard URL
- Analysis URL
- Demo user invitation URL
- QuickSight account name

### Phase 5: Bedrock Agent
```bash
make phase5
```
- Deploys Aurora PostgreSQL with pgvector
- Initializes vector database
- Creates Bedrock Knowledge Base
- Uploads documentation
- Creates Bedrock Agent with Athena integration

**Duration:** ~15 minutes (Aurora creation + ingestion)

**Outputs:**
- Agent ID
- Knowledge Base ID
- Agent console URL

## Configuration

### Environment Variables

```bash
# Required for deployment
AWS_PROFILE=default          # AWS profile to use
AWS_REGION=us-east-1        # AWS region

# Optional for QuickSight users
QS_VIEWER_EMAIL=user@example.com   # Email for demo viewer
QS_AUTHOR_EMAIL=user@example.com   # Email for author user
```

### Customization

**Change customer count:**
```bash
# Edit Makefile
CUSTOMER_COUNT ?= 500000  # Change to desired count
```

**Modify declining trends:**
```python
# Edit source/synthetic-data/generate_s3_data.py
base_nps = 52              # Starting NPS
base_health = 65           # Starting health score
decline_factor = 0.015     # 1.5% monthly decline
battery_pct = 0.15         # Starting battery issue %
```

## Usage

### Query with Athena

```sql
-- View declining NPS trend
SELECT month_date, nps_score, health_score, at_risk_customers
FROM kpi_trends
ORDER BY month_date;

-- Analyze battery issues
SELECT month_label, battery_cases, 
       ROUND(100.0 * battery_cases / total_cases, 2) as battery_pct
FROM issue_categories_view
ORDER BY month_date;

-- At-risk revenue analysis
SELECT customer_type, at_risk_revenue, at_risk_customers
FROM at_risk_revenue_view
WHERE month_date = (SELECT MAX(month_date) FROM at_risk_revenue_view);
```

### Test Bedrock Agent

**Via AWS Console:**
1. Go to: https://console.aws.amazon.com/bedrock/home?region=us-east-1#/agents
2. Select: `customer-360-agent`
3. Click: **Test**
4. Ask: "What's causing declining customer sentiment?"

**Sample Questions:**
- "What are the main customer issues this month?"
- "Show me the trend in battery-related cases"
- "Which customer segments are at highest risk?"
- "What's the correlation between NPS and health scores?"

## Verification

### Check Data

```bash
# List S3 data
aws s3 ls s3://automotive-cx-data-lake-<ACCOUNT-ID>/raw/ --recursive

# Query Athena
aws athena start-query-execution \
  --query-string "SELECT COUNT(*) FROM customers" \
  --query-execution-context Database=cx_analytics \
  --result-configuration OutputLocation=s3://automotive-cx-data-lake-<ACCOUNT-ID>/athena-results/ \
  --work-group cx-analytics-workgroup
```

### Check QuickSight

```bash
# List datasets
aws quicksight list-data-sets \
  --aws-account-id <ACCOUNT-ID> \
  --region us-east-1

# List dashboards
aws quicksight list-dashboards \
  --aws-account-id <ACCOUNT-ID> \
  --region us-east-1
```

### Check Bedrock

```bash
# List knowledge bases
aws bedrock-agent list-knowledge-bases --region us-east-1

# List agents
aws bedrock-agent list-agents --region us-east-1
```

## Cleanup

### Remove All Resources

```bash
make clean
```

**What gets deleted:**
- All CloudFormation stacks
- S3 buckets and data
- Glue database and tables
- Athena workgroup
- QuickSight dashboards and datasets
- Bedrock agents and knowledge bases
- Aurora cluster

**Note:** Some resources may require manual deletion:
- QuickSight users
- IAM roles (if created outside CDK)

### Selective Cleanup

```bash
# Delete specific phase
AWS_REGION=us-east-1 make phase1  # Then delete stack manually

# Delete QuickSight only
aws quicksight delete-dashboard --dashboard-id customer-360-dashboard --aws-account-id <ACCOUNT-ID>
aws quicksight delete-analysis --analysis-id customer-360-analysis --aws-account-id <ACCOUNT-ID>
```

## Troubleshooting

### Common Issues

**1. Bucket already exists**
```bash
# Delete existing bucket
aws s3 rb s3://automotive-cx-data-lake-<ACCOUNT-ID> --force
```

**2. QuickSight data source failed**
- Ensure QuickSight has permissions to S3 and Athena
- Check Lake Formation permissions
- Verify Athena workgroup exists

**3. Views not found**
- Wait for Glue crawler to complete
- Check if tables exist: `aws glue get-tables --database-name cx_analytics`
- Manually create views: `make phase3` (re-run)

**4. Bedrock agent errors**
- Ensure Aurora cluster is running
- Check knowledge base ingestion status
- Verify IAM roles have correct permissions

**5. Dataset creation fails**
```bash
# Recreate datasets
cd deployment/scripts
AWS_REGION=us-east-1 python3 update_quicksight_datasets.py
```

### Debug Commands

```bash
# Check stack status
aws cloudformation describe-stacks --stack-name cx360-dev-data-lake

# Check Glue crawler
aws glue get-crawler --name cx-analytics-crawler

# Check Athena query
aws athena get-query-execution --query-execution-id <ID>

# Check QuickSight dataset
aws quicksight describe-data-set --data-set-id <ID> --aws-account-id <ACCOUNT-ID>
```

## Architecture Decisions

### Why Aurora pgvector?
- Native PostgreSQL vector support
- Serverless scaling
- Integrated with Bedrock Knowledge Base
- Better performance than OpenSearch for this use case

### Why QuickSight?
- Native AWS integration
- No infrastructure management
- Built-in ML insights
- Embedded analytics capabilities

### Why Synthetic Data?
- Demonstrates declining trends without real customer data
- Reproducible for demos and testing
- Configurable metrics and volumes
- No PII concerns

## Cost Estimate

**Monthly costs (us-east-1, 500K customers):**
- S3: ~$5 (2GB storage + requests)
- Glue: ~$10 (crawler runs)
- Athena: ~$5 (query costs)
- QuickSight: $24/user (Enterprise)
- Aurora Serverless: ~$50 (minimal usage)
- Bedrock: ~$20 (agent + embeddings)

**Total: ~$114/month** (excluding QuickSight users)

**Cost optimization:**
- Use Aurora Serverless v2 auto-pause
- Limit QuickSight users
- Use S3 Intelligent-Tiering
- Set Athena query limits

## Security

### IAM Roles
- Glue crawler role: Read S3, write Glue catalog
- Lambda execution role: Query Athena, read S3
- Bedrock agent role: Query Athena, access Aurora
- QuickSight role: Read Athena, access S3

### Data Access
- Lake Formation: Fine-grained access control
- S3 bucket policies: Restrict to specific roles
- Aurora: Secrets Manager for credentials
- QuickSight: Row-level security (optional)

### Best Practices
- Enable CloudTrail logging
- Use VPC endpoints for private access
- Encrypt data at rest (S3, Aurora)
- Rotate credentials regularly
- Use least privilege IAM policies

## Contributing

### Development Setup

```bash
# Install dependencies
make install

# Run tests (if available)
npm test

# Build CDK
cd deployment/cdk && npm run build
```

### Code Structure

```
guidance-for-agentic-customer-360/
├── deployment/
│   ├── cdk/                    # CDK infrastructure
│   ├── scripts/                # Deployment scripts
│   └── quicksight/             # Dashboard definitions
├── source/
│   ├── synthetic-data/         # Data generators
│   ├── athena-queries/         # SQL views
│   ├── lambda/                 # Lambda functions
│   └── knowledge-base/         # Bedrock KB docs
└── Makefile                    # Deployment automation
```

## References

- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/)
- [Amazon QuickSight](https://docs.aws.amazon.com/quicksight/)
- [Amazon Bedrock](https://docs.aws.amazon.com/bedrock/)
- [AWS Glue](https://docs.aws.amazon.com/glue/)
- [Amazon Athena](https://docs.aws.amazon.com/athena/)

## License

This library is licensed under the MIT-0 License. See the LICENSE file.

## Support

For issues and questions:
1. Check [Troubleshooting](#troubleshooting) section
2. Review [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)
3. Open an issue in the repository
