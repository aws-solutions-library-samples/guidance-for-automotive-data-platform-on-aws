# Guidance for Agentic Customer 360 on AWS

## Overview

This AWS Guidance helps automotive companies build an intelligent Customer 360 platform that combines traditional analytics with agentic AI capabilities. The solution provides real-time customer health scoring, churn prediction, and automated intervention recommendations powered by Amazon Bedrock agents.

### Key Features

- **Customer Health Scoring**: Multi-dimensional health scoring (0-100) based on satisfaction, engagement, support, and payment behavior
- **Churn Prediction**: ML-powered churn probability with revenue-at-risk calculations
- **Customer Lifetime Value (CLV)**: Predictive CLV modeling across multiple revenue streams
- **Agentic AI Integration**: Amazon Bedrock agents that proactively identify at-risk customers and recommend interventions
- **Revenue Stream Analysis**: Track revenue across vehicle sales, service, subscriptions, financing, and warranties
- **Real-time Analytics**: Athena-based queries for instant insights into customer behavior

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Data Sources                                                    │
│  - CRM (Aurora PostgreSQL)                                       │
│  - Service Records                                               │
│  - NPS Surveys                                                   │
│  - Customer Interactions                                         │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  Data Lake (Amazon S3)                                           │
│  ├── raw/          - Source data (Parquet)                       │
│  ├── processed/    - Transformed data                            │
│  └── analytics/    - Aggregated metrics                          │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  Analytics & Visualization Layer                                │
│  ├── AWS Glue      - ETL & Data Catalog                          │
│  ├── Amazon Athena - SQL Analytics (50+ views)                   │
│  └── Amazon Quick Suite    - Executive Dashboards                        │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│  Agentic AI Layer (Amazon Bedrock)                               │
│  ├── Customer Health Agent - Monitors health scores              │
│  ├── Churn Prevention Agent - Identifies at-risk customers       │
│  └── Intervention Agent - Recommends actions                     │
└─────────────────────────────────────────────────────────────────┘
```

## Use Cases

### 1. Proactive Churn Prevention
Automatically identify customers showing early warning signs of churn and trigger personalized retention campaigns.

### 2. Revenue Optimization
Analyze customer lifetime value across all revenue streams to prioritize high-value customer segments.

### 3. Service Quality Improvement
Track service appointment satisfaction and identify dealers/service centers needing improvement.

### 4. Product Adoption
Monitor adoption rates for connected services, extended warranties, and premium features.

### 5. Customer Journey Optimization
Understand drop-off points in the customer journey and optimize touchpoints.

## Prerequisites

- AWS Account with administrative access
- AWS CLI v2 installed and configured
- Node.js 18+ (for CDK deployment)
- Python 3.9+ (for data generation)
- Basic understanding of:
  - Amazon S3
  - AWS Glue
  - Amazon Athena
  - Amazon Bedrock (optional for agentic features)

## Quick Start

### Phased Deployment (Recommended)

```bash
# Clone and setup
git clone <repo-url>
cd guidance-for-agentic-customer-360

# Phase 1: Data Foundation
make install bootstrap phase1

# Phase 2: ETL Pipeline
make phase2

# Phase 3: Generate Data
make phase3

# Phase 4: Amazon Quick Suite Dashboards
make phase4  # Follow prompts for manual setup

# Phase 5: Bedrock Agents (Optional)
make phase5

# Verify everything
make verify
```

### Alternative: CDK Direct Deployment

```bash
cd deployment/cdk
npm install
cdk bootstrap
cdk deploy --all

# Then generate data
cd ../../source/synthetic-data
pip install -r requirements.txt
python generate_cx_data.py
```

See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for detailed instructions.
  --stack-name cx360-athena \
  --template-body file://deployment/cloudformation/03-athena-workgroup.yaml
```

## Data Model

### Core Entities

#### customer_360
Unified view of each customer combining all data sources.

**Key Fields:**
- `customer_id` - Unique identifier
- `health_score` - Overall health (0-100)
- `lifetime_value` - Total revenue generated
- `churn_probability` - Likelihood of churn (0-1)
- `lifecycle_stage` - Current journey stage

#### customer_health
Daily health score calculations with component breakdown.

**Components:**
- Satisfaction Score (25%) - Based on NPS/CSAT
- Support Score (20%) - Based on case volume
- Engagement Score (15%) - Based on app/web usage
- Recency Score (30%) - Based on last interaction
- Payment Score (10%) - Based on payment status

#### Revenue Streams
- `financing_revenue` - Interest income from loans
- `service_revenue` - Service appointment revenue
- `subscription_revenue` - Connected services subscriptions
- `warranty_revenue` - Extended warranty sales

See [DATA_MODEL.md](docs/DATA_MODEL_SPEC.md) for complete schema.

## Key Queries

### Customer Health Distribution
```sql
SELECT 
    CASE 
        WHEN health_score >= 70 THEN 'Healthy'
        WHEN health_score >= 40 THEN 'At-Risk'
        ELSE 'Critical'
    END as risk_level,
    COUNT(*) as customer_count,
    SUM(lifetime_value) as total_clv
FROM customer_health
GROUP BY 1;
```

### Revenue at Risk
```sql
SELECT 
    customer_type,
    COUNT(*) as at_risk_customers,
    SUM(lifetime_value) as revenue_at_risk
FROM customer_360
WHERE health_score < 40
GROUP BY customer_type
ORDER BY revenue_at_risk DESC;
```

See [athena-queries/](source/athena-queries/) for 50+ production-ready queries.

## Amazon Quick Suite Dashboards

### OEM Business Overview Dashboard

Fully automated deployment with complete formatting preservation:

**Executive Overview Sheet:**
- Total Subscriptions Sold
- Monthly Sales Trends
- Customer Base Metrics
- Median Health Score
- Total CLV & Revenue at Risk
- NPS Score Tracking
- At-Risk Customer Analysis
- Revenue Growth Rate
- Support Case Volume
- Retention Rate Trends

**Customer 360 Sheet:**
- Detailed customer segmentation
- Individual customer health tracking
- Revenue stream breakdown
- Churn risk analysis

### Automated Deployment

The dashboard is automatically deployed with `make phase4`:
1. Creates Athena data source
2. Creates all 8 datasets
3. **Deploys complete dashboard with all formatting**

All visual formatting, colors, fonts, and layouts are preserved from the template.

See [source/quick-suite/README.md](source/quick-suite/README.md) for details.

## Agentic AI Features (Optional)

### Enable Bedrock Agents

```bash
# Deploy Bedrock agent stack
cd deployment/cdk
cdk deploy BedrockAgentStack

# Configure agent with your data
python scripts/configure_bedrock_agent.py
```

### Agent Capabilities

1. **Customer Health Monitoring Agent**
   - Monitors health scores in real-time
   - Alerts when customers drop below thresholds
   - Provides context on why health declined

2. **Churn Prevention Agent**
   - Identifies customers likely to churn
   - Recommends personalized interventions
   - Tracks intervention effectiveness

3. **Revenue Optimization Agent**
   - Identifies upsell/cross-sell opportunities
   - Recommends product bundles
   - Optimizes pricing strategies

## Cost Estimate

### Base Platform
| Service | Monthly Cost | Notes |
|---------|-------------|-------|
| S3 Storage | $50 | 2TB data lake |
| Glue ETL | $100 | Daily jobs |
| Athena Queries | $25 | ~500 queries/month |
| Amazon Quick Suite | $9-180 | $9/user (first free) |
| **Total** | **~$184-355/month** | |

### With Agentic AI (Bedrock)
| Service | Monthly Cost | Notes |
|---------|-------------|-------|
| Base Platform | $184-355 | See above |
| Bedrock (Claude) | $200-500 | Depends on usage |
| Lambda (Agents) | $50 | Event processing |
| **Total** | **~$434-905/month** | |

## Customization

### Adding New Data Sources

1. Create Glue table definition
2. Add ETL job to process data
3. Update customer_360 view
4. Add relevant queries

See [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md) for details.

### Modifying Health Score

Edit `source/glue-jobs/health-score-calculation.py`:

```python
# Adjust component weights
WEIGHTS = {
    'satisfaction': 0.30,  # Increase satisfaction weight
    'support': 0.20,
    'engagement': 0.15,
    'recency': 0.25,       # Decrease recency weight
    'payment': 0.10
}
```

## Monitoring & Operations

### CloudWatch Dashboards

The solution includes pre-built dashboards for:
- ETL job success rates
- Query performance
- Data freshness
- Cost tracking

### Alerts

Configure SNS alerts for:
- ETL job failures
- Data quality issues
- Cost anomalies
- Agent errors

## Security

- All data encrypted at rest (S3-SSE)
- VPC endpoints for private connectivity
- IAM roles with least privilege
- Secrets Manager for credentials
- CloudTrail logging enabled

## Troubleshooting

### Common Issues

**ETL Job Fails**
```bash
# Check Glue job logs
aws logs tail /aws-glue/jobs/output --follow
```

**Athena Query Timeout**
- Increase workgroup timeout
- Partition your data
- Use CTAS for large aggregations

**High Costs**
- Enable S3 Intelligent-Tiering
- Use Glue job bookmarks
- Optimize Athena queries with partitions

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for more.

## Roadmap

- [ ] Real-time streaming with Kinesis
- [ ] ML model training with SageMaker
- [ ] Multi-region deployment
- [ ] Advanced Bedrock agent workflows
- [ ] Integration with Salesforce/Dynamics

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](../../CONTRIBUTING.md).

## License

This library is licensed under the MIT-0 License. See the [LICENSE](../../LICENSE) file.

## Support

- GitHub Issues: [Report bugs or request features](https://github.com/aws-samples/automotive-data-platform-on-aws/issues)
- AWS Support: For AWS service issues
- Documentation: [Full documentation](docs/)

## Authors

- AWS Automotive Industry Team
- AWS Solutions Architecture Team

---

**Ready to get started?** Follow the [Quick Start](#quick-start) guide above.
