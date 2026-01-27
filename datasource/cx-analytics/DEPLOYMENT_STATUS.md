# CX Analytics Deployment Status

## ✅ Completed

### Infrastructure Deployed to Account: 022035076260

**1. CXDataLakeStack**
- S3 Bucket: `automotive-cx-data-lake-022035076260`
- Glue Database: `cx_analytics`
- Status: ✅ DEPLOYED

**2. CXCRMStack**
- Aurora Cluster: `cxcrmstack-cxcrmcluster6c40befe-gzycdxj7qfiu.cluster-cnqi2n6fm8jq.us-east-1.rds.amazonaws.com`
- Database: `cx_crm`
- Version: PostgreSQL 15.8 Serverless v2
- Secret: `arn:aws:secretsmanager:us-east-1:022035076260:secret:cx-crm-db-credentials-sHsXy9`
- Status: ✅ DEPLOYED

---

## 🔄 Next Steps

### Option 1: Initialize Schema & Generate Data from EC2

Since Aurora is in a private subnet, you need to run from within the VPC:

```bash
# 1. Launch EC2 instance in the VPC (or use existing bastion)
# 2. SSH into instance
# 3. Install dependencies
sudo yum install -y postgresql15 python3-pip git
pip3 install psycopg2-binary faker boto3

# 4. Clone repo or copy files
# 5. Get database password
export DB_PASSWORD=$(aws secretsmanager get-secret-value \
  --secret-id cx-crm-db-credentials \
  --query SecretString --output text | jq -r '.password')

# 6. Initialize schema
export DB_HOST=cxcrmstack-cxcrmcluster6c40befe-gzycdxj7qfiu.cluster-cnqi2n6fm8jq.us-east-1.rds.amazonaws.com
export DB_USER=cx_admin
export DB_NAME=cx_crm

psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f init_cx_crm_schema.sql

# 7. Generate data (30-60 minutes)
python3 generate_cx_data.py
```

### Option 2: Use AWS Systems Manager Session Manager

```bash
# Connect to an EC2 instance via SSM (no SSH key needed)
aws ssm start-session --target <instance-id> --profile givenand-CMS

# Then run same commands as Option 1
```

### Option 3: Deploy Lambda Function (Automated)

I can create a Lambda function that:
- Runs in the VPC
- Initializes the schema
- Generates the data in batches

Would take ~2 hours to generate all 500K customers via Lambda.

---

## 📊 What You'll Have After Data Generation

- **200 dealers** (varied performance tiers)
- **600 CRM users** (sales reps, service advisors)
- **500,000 customers** (10-year growth pattern)
- **750,000 vehicles**
- **~100,000 opportunities**
- **~150,000 support cases**
- **~375,000 service appointments**
- **~125,000 surveys**

---

## 🚀 After Data Generation

1. Deploy ETL jobs:
```bash
cd datasource/cx-analytics
./deploy_glue_jobs.sh
```

2. Run ETL pipeline:
```bash
aws glue start-job-run --job-name cx-aurora-to-s3-export
aws glue start-job-run --job-name cx-process-customer-360
aws glue start-job-run --job-name cx-calculate-health-scores
```

3. Query with Athena:
```sql
USE cx_analytics;
SELECT * FROM customer_360 LIMIT 10;
SELECT * FROM customer_health_metrics LIMIT 10;
```

---

## 💰 Current Costs

- **Aurora Serverless v2**: ~$50-100/month (0.5-8 ACU, currently idle)
- **S3**: ~$1/month (minimal data so far)
- **Total**: ~$51-101/month

---

## Which Option Do You Prefer?

1. **EC2/Bastion** - Traditional, full control
2. **SSM Session Manager** - No SSH keys needed
3. **Lambda** - Fully automated, I can build it

Let me know and I'll help you proceed!
