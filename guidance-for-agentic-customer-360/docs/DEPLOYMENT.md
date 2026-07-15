# Deployment Guide - Agentic Customer 360

## Prerequisites

### AWS Account Setup
- [ ] AWS Account with administrative access
- [ ] AWS CLI v2 installed and configured
- [ ] **Amazon Quick Suite enabled** (visit https://quicksight.aws.amazon.com/)
- [ ] **AWS IAM Identity Center (SSO) recommended** for user access
- [ ] IAM user/role with permissions for:
  - S3, Glue, Athena, Lambda, Bedrock, Quick Suite
  - CloudFormation/CDK deployment
  - IAM role creation

### Development Environment
- [ ] Node.js 18+ (for CDK)
- [ ] Python 3.9+ (for data generation)
- [ ] Git
- [ ] 10GB free disk space

### Cost Considerations
- Estimated monthly cost: $184-905 (base: $184-355, with Bedrock: $434-905)
- One-time setup: ~$50 (data generation)
- Amazon Quick Suite: $9/user/month (first user free)
- See [Cost Estimate](#cost-estimate) for details

## Deployment Options

### Option 1: CDK Deployment (Recommended)

**Best for**: Customers familiar with infrastructure as code, need customization

```bash
# 1. Clone repository
git clone <repo-url>
cd guidance-for-agentic-customer-360/deployment/cdk

# 2. Install dependencies
npm install

# 3. Configure AWS credentials
aws configure
# Enter your AWS Access Key ID, Secret Access Key, and region

# 4. Bootstrap CDK (first time only)
cdk bootstrap

# 5. Review what will be deployed
cdk diff

# 6. Deploy all stacks
cdk deploy --all --require-approval never

# Expected output:
# ✅ CXDataLakeStack
# ✅ CXGlueCatalogStack
# ✅ CXETLStack
# ✅ CXAthenaStack
# (Optional) ✅ BedrockAgentStack

# 7. Note the outputs
# DataLakeBucket = automotive-cx-data-lake-<account-id>
# GlueDatabase = cx_analytics
# AthenaWorkgroup = cx-analytics-workgroup
```

**Deployment Time**: ~15-20 minutes

### Option 2: CloudFormation Deployment

**Best for**: Customers preferring AWS native tools, simpler deployment

```bash
# 1. Clone repository
git clone <repo-url>
cd guidance-for-agentic-customer-360/deployment/cloudformation

# 2. Deploy data lake
aws cloudformation create-stack \
  --stack-name cx360-data-lake \
  --template-body file://01-data-lake.yaml \
  --capabilities CAPABILITY_IAM \
  --parameters \
    ParameterKey=ProjectName,ParameterValue=cx360

# Wait for completion
aws cloudformation wait stack-create-complete \
  --stack-name cx360-data-lake

# 3. Deploy Glue catalog
aws cloudformation create-stack \
  --stack-name cx360-glue-catalog \
  --template-body file://02-glue-catalog.yaml \
  --capabilities CAPABILITY_IAM \
  --parameters \
    ParameterKey=DataLakeBucket,ParameterValue=$(aws cloudformation describe-stacks --stack-name cx360-data-lake --query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' --output text)

# Wait for completion
aws cloudformation wait stack-create-complete \
  --stack-name cx360-glue-catalog

# 4. Deploy Athena workgroup
aws cloudformation create-stack \
  --stack-name cx360-athena \
  --template-body file://03-athena-workgroup.yaml \
  --parameters \
    ParameterKey=DataLakeBucket,ParameterValue=$(aws cloudformation describe-stacks --stack-name cx360-data-lake --query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' --output text)

# Wait for completion
aws cloudformation wait stack-create-complete \
  --stack-name cx360-athena
```

**Deployment Time**: ~20-25 minutes

## Post-Deployment Steps

### 1. Generate Synthetic Data

```bash
cd ../../source/synthetic-data

# Install Python dependencies
pip install -r requirements.txt

# Generate 500K customers (takes ~30-60 minutes)
python generate_cx_data.py \
  --customers 500000 \
  --output-bucket $(aws cloudformation describe-stacks --stack-name cx360-data-lake --query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' --output text)

# Expected output:
# ✓ Generated 500,000 customers
# ✓ Generated 750,000 vehicles
# ✓ Generated 150,000 cases
# ✓ Generated 375,000 service appointments
# ✓ Generated 125,000 surveys
# ✓ Uploaded to S3: s3://automotive-cx-data-lake-<account>/raw/
```

### 2. Run Initial ETL Jobs

```bash
# Trigger Glue jobs to process data
aws glue start-job-run --job-name cx-customer-360-transform

# Monitor job progress
aws glue get-job-run \
  --job-name cx-customer-360-transform \
  --run-id <run-id-from-above>

# Wait for completion (5-10 minutes)
```

### 3. Deploy Amazon Quick Suite

**Fully Automated** - Creates data source, datasets, and complete dashboard:

```bash
make phase4
```

This automatically:
1. ✅ Checks if Amazon Quick Suite is enabled
2. ✅ Creates Athena data source (`cx-analytics-athena`)
3. ✅ Creates 8 datasets from Athena views
4. ✅ **Deploys OEM Business Overview dashboard with all formatting**

**Security**:
- Resources owned by the IAM principal running the deployment
- Use AWS IAM Identity Center (SSO) for user access
- Share dashboards post-deployment via Quick Suite permissions
- See [QUICK_SUITE_SECURITY.md](../docs/QUICK_SUITE_SECURITY.md) for details

**Dashboard Features:**
- Executive KPI overview (20+ metrics)
- Customer 360 deep dive
- Revenue at risk analysis
- Churn prediction trends
- Support case analytics
- **All visual formatting preserved** (colors, fonts, layouts)

**Time to Complete**: 5-10 minutes

**Dashboard URL**: 
```
https://${REGION}.quicksight.aws.amazon.com/sn/dashboards/oem-business-overview-${ACCOUNT_ID}
```

**Sharing Dashboards**:
After deployment, share with your team:
1. Sign in to Quick Suite via AWS console (SSO)
2. Navigate to dashboard
3. Click Share → Add users/groups
4. Grant view permissions

See [source/quick-suite/README.md](../source/quick-suite/README.md) for details.


### 3. Verify Data in Athena

```bash
# Open Athena console
# Or use AWS CLI:

aws athena start-query-execution \
  --query-string "SELECT COUNT(*) as customer_count FROM cx_analytics.customer_360" \
  --result-configuration OutputLocation=s3://$(aws cloudformation describe-stacks --stack-name cx360-data-lake --query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' --output text)/athena-results/ \
  --work-group cx-analytics-workgroup

# Get results
aws athena get-query-results --query-execution-id <execution-id>
```

Expected result: `customer_count = 500000`

### 4. (Optional) Deploy Bedrock Agents

```bash
# Only if you want agentic AI features

cd ../../deployment/cdk
cdk deploy BedrockAgentStack

# Configure agent
python ../scripts/configure_bedrock_agent.py
```

## Validation Checklist

### Infrastructure
- [ ] S3 bucket created with proper structure (raw/, processed/, analytics/)
- [ ] Glue database `cx_analytics` exists
- [ ] All Glue tables created (50+ tables)
- [ ] Athena workgroup configured
- [ ] IAM roles have correct permissions

### Data
- [ ] Synthetic data generated successfully
- [ ] Data uploaded to S3 raw/ folder
- [ ] ETL jobs completed without errors
- [ ] customer_360 table has 500K records
- [ ] All queries return results

### Queries
- [ ] Customer health query works
- [ ] Churn prediction query works
- [ ] CLV analysis query works
- [ ] Revenue at risk query works
- [ ] Amazon Quick Suite dashboard is accessible and displays data

## Troubleshooting

### Issue: CDK Bootstrap Fails

**Error**: `Unable to resolve AWS account to use`

**Solution**:
```bash
# Ensure AWS credentials are configured
aws sts get-caller-identity

# If not configured:
aws configure
```

### Issue: Glue Job Fails

**Error**: `Table not found: cx_analytics.customer_360`

**Solution**:
```bash
# Verify Glue catalog
aws glue get-table --database-name cx_analytics --name customer_360

# If missing, redeploy Glue catalog stack
cdk deploy CXGlueCatalogStack
```

### Issue: Athena Query Timeout

**Error**: `Query exhausted resources at this scale factor`

**Solution**:
```sql
-- Use partitions
SELECT * FROM customer_360
WHERE year = '2024' AND month = '12'

-- Or use CTAS for large aggregations
CREATE TABLE customer_health_summary AS
SELECT health_segment, COUNT(*) as count
FROM customer_360
GROUP BY health_segment
```

### Issue: High Costs

**Problem**: Monthly bill higher than expected

**Solution**:
1. Enable S3 Intelligent-Tiering
   ```bash
   aws s3api put-bucket-intelligent-tiering-configuration \
     --bucket <bucket-name> \
     --id EntireDataLake \
     --intelligent-tiering-configuration file://intelligent-tiering.json
   ```

2. Use Glue job bookmarks to avoid reprocessing
   ```python
   # In Glue job
   job.init(args['JOB_NAME'], args)
   job.commit()  # Saves bookmark
   ```

3. Optimize Athena queries
   - Use partitions
   - Limit SELECT * queries
   - Use columnar formats (Parquet)

## Cost Estimate

### Base Platform (No Bedrock)

| Service | Usage | Monthly Cost |
|---------|-------|-------------|
| **S3 Storage** | 2TB data lake | $46 |
| **Glue ETL** | 5 jobs/day, 10 min each | $100 |
| **Athena** | 500 queries, 1TB scanned | $25 |
| **CloudWatch** | Logs + metrics | $10 |
| **Total** | | **~$181/month** |

### With Agentic AI (Bedrock)

| Service | Usage | Monthly Cost |
|---------|-------|-------------|
| Base Platform | See above | $181 |
| **Bedrock (Claude 3.5)** | 1M input tokens, 500K output | $300 |
| **Lambda** | 1M invocations | $20 |
| **EventBridge** | 1M events | $10 |
| **Total** | | **~$511/month** |

### One-Time Costs

| Item | Cost |
|------|------|
| Data generation (EC2) | $20 |
| Initial ETL runs | $30 |
| **Total** | **~$50** |

## Cleanup

### Delete All Resources

```bash
# Option 1: CDK
cd deployment/cdk
cdk destroy --all

# Option 2: CloudFormation
aws cloudformation delete-stack --stack-name cx360-athena
aws cloudformation delete-stack --stack-name cx360-glue-catalog
aws cloudformation delete-stack --stack-name cx360-data-lake

# Wait for deletion
aws cloudformation wait stack-delete-complete --stack-name cx360-data-lake
```

### Manual Cleanup

Some resources may need manual deletion:

1. **S3 Bucket** (if not empty)
   ```bash
   aws s3 rm s3://<bucket-name> --recursive
   aws s3 rb s3://<bucket-name>
   ```

2. **CloudWatch Logs**
   ```bash
   aws logs delete-log-group --log-group-name /aws-glue/jobs/output
   ```

3. **Athena Query Results**
   ```bash
   aws s3 rm s3://<bucket-name>/athena-results/ --recursive
   ```

## Next Steps

1. **Explore Queries**: Try the sample queries in `source/athena-queries/`
2. **Customize Health Score**: Modify weights in `source/glue-jobs/health-score-calculation.py`
3. **Add Data Sources**: Integrate your own CRM or service data
4. **Enable Bedrock**: Deploy agentic AI features
5. **Create Dashboards**: Build Amazon Quick Suite visualizations

## Support

- **Documentation**: See `docs/` folder
- **Issues**: GitHub Issues
- **AWS Support**: For service-specific questions

---

**Deployment complete!** 🎉

Your Customer 360 platform is ready. Start exploring with:
```bash
# Open Athena console
aws athena start-query-execution \
  --query-string "SELECT * FROM cx_analytics.customer_health LIMIT 10" \
  --work-group cx-analytics-workgroup
```
