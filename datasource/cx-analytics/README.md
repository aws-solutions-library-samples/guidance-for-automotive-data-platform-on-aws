# Customer Experience Analytics Platform

## Overview
Complete data platform to answer: **"Where should we invest to maximize customer satisfaction, loyalty, and revenue?"**

## Architecture

```
Aurora CRM (Operational) → S3 Data Lake (Analytics) → Athena (Queries)
                                ↓
                        Glue ETL (Processing)
                                ↓
                        Health Score Calculation
```

## Components

### 1. Aurora CRM Database
- **Purpose**: Operational CRM system
- **Scale**: 500K customers, 200 dealers
- **Tables**: dealers, users, accounts, contacts, vehicles, opportunities, cases, service_appointments, surveys

### 2. S3 Data Lake
- **Structure**: raw/ → processed/ → analytics/
- **Format**: Parquet (partitioned by date)
- **Catalog**: AWS Glue Data Catalog

### 3. Data Processing
- **Daily ETL**: Aurora → S3 export
- **Health Score**: Calculated daily (0-100 scale)
- **Investment Priorities**: Revenue-at-risk analysis

## Quick Deploy

### Prerequisites
```bash
# Ensure you have VPC
export VPC_ID=vpc-xxxxx
```

### 1. Deploy Aurora CRM
```bash
cd /Users/givenand/automotive-data-platform-on-aws
cdk deploy CXCRMStack
```

### 2. Deploy S3 Data Lake
```bash
cdk deploy CXDataLakeStack
```

### 3. Initialize Database Schema
```bash
# Get credentials
aws secretsmanager get-secret-value \
  --secret-id cx-crm-db-credentials \
  --query SecretString --output text | jq -r .password

# Connect and initialize
psql -h <cluster-endpoint> -U cx_admin -d cx_crm \
  -f datasource/cx-analytics/init_cx_crm_schema.sql
```

### 4. Generate Synthetic Data
```bash
# Install dependencies
pip install -r datasource/cx-analytics/requirements.txt

# Set database connection
export DB_HOST=<cluster-endpoint>
export DB_USER=cx_admin
export DB_PASSWORD=<from-secrets-manager>
export DB_NAME=cx_crm

# Generate data (takes ~30-60 minutes)
python datasource/cx-analytics/generate_cx_data.py
```

**What gets generated:**
- 200 dealers (40 Excellent, 70 Good, 60 Average, 30 Poor)
- 600 CRM users (3 per dealer)
- 500,000 customers (growth from 20K in 2015 to 500K in 2024)
- 750,000 vehicles (1.5 per customer avg)
- ~100,000 opportunities
- ~150,000 support cases
- ~375,000 service appointments
- ~125,000 surveys

## Data Model

### Core Entities
- **Contacts**: 500K customers with health scores
- **Vehicles**: 750K vehicles (1.5 per customer)
- **Dealers**: 200 dealers (varied performance)
- **Interactions**: 10M events over 10 years

### Health Score Components
1. **Recency** (30%): Last purchase/service date
2. **Satisfaction** (25%): NPS/CSAT scores
3. **Support** (20%): Ticket volume
4. **Engagement** (15%): App/web usage
5. **Payment** (10%): Payment status

### Risk Levels
- **Healthy**: 70-100 (Low churn risk)
- **At-Risk**: 40-69 (Medium churn risk)
- **Critical**: 0-39 (High churn risk)

## Data Sources

### Operational (Aurora)
- CRM data (contacts, accounts, opportunities)
- Service appointments
- Support tickets
- Surveys (NPS/CSAT)

### Analytics (S3)
- Dealer sales records
- Website analytics
- Mobile app analytics
- Contact center calls

## Query Examples

### Customer Health Distribution
```sql
SELECT 
    CASE 
        WHEN current_health_score >= 70 THEN 'Healthy'
        WHEN current_health_score >= 40 THEN 'At-Risk'
        ELSE 'Critical'
    END as risk_level,
    COUNT(*) as customer_count,
    AVG(lifetime_value) as avg_ltv
FROM contacts
GROUP BY risk_level;
```

### Investment Priorities
```sql
SELECT 
    dealer_id,
    COUNT(*) as at_risk_customers,
    SUM(lifetime_value) as revenue_at_risk
FROM contacts
WHERE current_health_score < 40
GROUP BY dealer_id
ORDER BY revenue_at_risk DESC
LIMIT 10;
```

## Cost Estimate

- **Aurora Serverless v2**: $50-200/month (0.5-8 ACU)
- **S3 Storage**: ~$50/month (2TB data)
- **Glue ETL**: ~$100/month (daily jobs)
- **Total**: ~$200-350/month

### 5. Deploy ETL Pipelines
```bash
# Upload Glue scripts and deploy jobs
cd datasource/cx-analytics
./deploy_glue_jobs.sh

# Run jobs manually (or wait for daily schedule at 2 AM)
aws glue start-job-run --job-name cx-aurora-to-s3-export
aws glue start-job-run --job-name cx-process-customer-360
aws glue start-job-run --job-name cx-calculate-health-scores
```

**ETL Pipeline:**
1. **Aurora Export** (2 AM): Exports all CRM tables to S3 raw layer
2. **Customer 360** (3 AM): Aggregates data into unified customer view
3. **Health Scores** (4 AM): Calculates daily health scores (0-100)

## Next Steps

1. ✅ Deploy Aurora CRM
2. ✅ Deploy S3 Data Lake
3. ✅ Initialize schema
4. ✅ Generate synthetic data (500K customers, 10 years)
5. ✅ Build ETL pipelines (Glue jobs)
6. Query and analyze with Athena

## No QuickSight
This implementation focuses on data infrastructure. Visualization can be done via:
- Athena queries
- Jupyter notebooks
- Custom dashboards
- Third-party BI tools
