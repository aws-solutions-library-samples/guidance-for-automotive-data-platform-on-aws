# Clean Account Deployment Checklist

## Prerequisites

- [ ] AWS Account with admin access
- [ ] AWS CLI configured with credentials
- [ ] Node.js 18+ installed
- [ ] Python 3.9+ installed
- [ ] CDK CLI installed (`npm install -g aws-cdk`)
- [ ] QuickSight subscription (Enterprise or Enterprise + Q)

## Deployment Steps

### 1. Install Dependencies
```bash
make install
```

**What it does:**
- Installs CDK dependencies
- Installs Python dependencies for data generator

### 2. Bootstrap CDK
```bash
make bootstrap
```

**What it does:**
- Creates CDK toolkit stack
- Sets up S3 bucket for CDK assets

### 3. Deploy Data Lake (Phase 1)
```bash
make phase1
```

**What it does:**
- Creates S3 data lake bucket
- Creates Glue database (`cx_analytics`)
- Creates Athena workgroup
- **Time**: ~3-5 minutes

**Outputs:**
- S3 Bucket: `automotive-cx-data-lake-{account-id}`
- Glue Database: `cx_analytics`
- Athena Workgroup: `cx-analytics-workgroup`

### 4. Deploy ETL & Setup Prerequisites (Phase 2)
```bash
make phase2
```

**What it does:**
- Deploys Glue ETL jobs
- Creates Glue crawler
- Grants Lake Formation permissions
- Creates QuickSight data source
- **Time**: ~2-3 minutes

**Prerequisites created:**
- Glue Crawler: `cx-analytics-crawler`
- QuickSight Data Source: `cx-analytics-athena`
- Lake Formation permissions granted

### 5. Generate Data (Phase 3)
```bash
make phase3
```

**What it does:**
- Generates 500K customers with synthetic data
- Uploads 11 datasets to S3
- Runs Glue crawler to discover schemas
- Creates 8 Athena views
- **Time**: ~5-10 minutes

**Data generated:**
- 500,000 customers
- 1.4M interactions
- 900K service records
- 500K cases
- 12 months of KPI trends (declining)
- Issue categories (battery issues increasing)

### 6. Deploy QuickSight Dashboard (Phase 4)
```bash
make phase4
```

**What it does:**
- Creates 8 QuickSight datasets
- Creates analysis (editable)
- Creates dashboard (published)
- Grants permissions
- **Time**: ~2-3 minutes

**Outputs:**
- Analysis: `customer-360-analysis`
- Dashboard: `customer-360-dashboard`
- 8 datasets with DIRECT_QUERY mode

### 7. Deploy Bedrock Agent (Phase 5)
```bash
make phase5
```

**What it does:**
- Deploys Lambda function for Athena queries
- Creates Bedrock Agent
- Configures action groups
- **Time**: ~5-7 minutes

**Outputs:**
- Lambda: `cx360-athena-query`
- Bedrock Agent: `customer-360-analyzer`

## Verification

### Check Data
```bash
aws athena start-query-execution \
  --query-string "SELECT COUNT(*) FROM cx_analytics.customer_health" \
  --query-execution-context Database=cx_analytics \
  --result-configuration OutputLocation=s3://automotive-cx-data-lake-{account-id}/athena-results/ \
  --work-group cx-analytics-workgroup \
  --region us-east-1
```

Expected: 500,000 rows

### Check Dashboard
```bash
aws quicksight list-dashboards \
  --aws-account-id {account-id} \
  --region us-east-1
```

Expected: `customer-360-dashboard` with status PUBLISHED

### Check Bedrock Agent
```bash
aws bedrock-agent list-agents --region us-east-1
```

Expected: `customer-360-analyzer` with status PREPARED

## Access URLs

### QuickSight
- **Analysis**: https://us-east-1.quicksight.aws.amazon.com/sn/analyses/customer-360-analysis
- **Dashboard**: https://us-east-1.quicksight.aws.amazon.com/sn/dashboards/customer-360-dashboard

### AWS Console
- **Athena**: https://console.aws.amazon.com/athena/home?region=us-east-1
- **Glue**: https://console.aws.amazon.com/glue/home?region=us-east-1
- **Bedrock**: https://console.aws.amazon.com/bedrock/home?region=us-east-1

## Troubleshooting

### QuickSight Not Set Up
If phase4 fails with "QuickSight not set up":
1. Go to https://quicksight.aws.amazon.com/
2. Sign up for QuickSight (Enterprise edition)
3. Re-run `make phase2` to create data source
4. Continue with `make phase4`

### Glue Crawler Fails
If crawler fails with Lake Formation errors:
```bash
cd deployment/scripts && ./setup-prerequisites.sh
```

### Dashboard Shows No Data
1. Check if Glue crawler completed:
   ```bash
   aws glue get-crawler --name cx-analytics-crawler --region us-east-1
   ```
2. Verify Athena views exist:
   ```bash
   aws glue get-tables --database-name cx_analytics --region us-east-1
   ```
3. Re-run phase3 to recreate views

## Clean Up

To delete all resources:
```bash
make clean
```

**Warning**: This will delete:
- All S3 data
- All Glue tables and databases
- All QuickSight dashboards and datasets
- All CDK stacks
- Bedrock Agent

## Total Deployment Time

- **Full deployment**: ~20-30 minutes
- **Data generation**: ~10 minutes (largest component)
- **QuickSight setup**: ~3 minutes
- **Infrastructure**: ~10 minutes

## What You Get

### Dashboard Features
- 30+ KPIs tracking customer health
- Declining trends showing business problems
- Battery issue root cause analysis
- Revenue at risk tracking
- Customer segmentation

### Bedrock Agent Capabilities
- Root cause analysis
- Customer health queries
- Trend analysis
- Actionable recommendations

### Data Characteristics
- **Realistic declining trends**: NPS, health scores, revenue
- **Increasing problems**: Battery cases growing 15% → 40%
- **Business problem scenario**: Demonstrates need for intervention
- **12 months of data**: Feb 2025 - Jan 2026

## Success Criteria

✅ All 5 phases complete without errors
✅ Dashboard shows declining trends
✅ Battery issues increasing over time
✅ Bedrock Agent responds to queries
✅ All permissions granted correctly
