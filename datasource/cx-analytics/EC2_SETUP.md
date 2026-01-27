# EC2 Data Generation Setup

## Instance Details
- **Instance ID**: i-02e8b0043997916e4
- **Type**: c6i.4xlarge (16 vCPU, 32 GB RAM)
- **Private IP**: 10.0.2.167
- **Public IP**: 18.209.32.214

## Connect via AWS Console

1. Go to EC2 Console: https://console.aws.amazon.com/ec2
2. Select instance `i-02e8b0043997916e4`
3. Click **Connect** → **Session Manager** → **Connect**

## Setup Commands (Run in Session Manager)

```bash
# 1. Install dependencies
sudo yum install -y postgresql15 python3-pip git

# 2. Install Python packages
pip3 install psycopg2-binary faker boto3 --user

# 3. Set environment variables
export DB_HOST=cxcrmstack-cxcrmcluster6c40befe-gzycdxj7qfiu.cluster-cnqi2n6fm8jq.us-east-1.rds.amazonaws.com
export DB_USER=cx_admin
export DB_NAME=cx_crm
export DB_PASSWORD='2on,7FtaYCH.SvW10,_bW5d5AJqIzE'

# 4. Create working directory
mkdir -p ~/cx-analytics && cd ~/cx-analytics

# 5. Download schema file
curl -o init_cx_crm_schema.sql https://raw.githubusercontent.com/YOUR_REPO/init_cx_crm_schema.sql

# OR create it inline (copy/paste the SQL from init_cx_crm_schema.sql)

# 6. Initialize schema
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f init_cx_crm_schema.sql

# 7. Download data generator
curl -o generate_cx_data.py https://raw.githubusercontent.com/YOUR_REPO/generate_cx_data.py

# OR create it inline (copy/paste from generate_cx_data.py)

# 8. Run data generation (30-60 minutes)
python3 generate_cx_data.py
```

## Alternative: Use AWS CLI to Send Commands

```bash
# From your local machine
AWS_PROFILE=givenand-CMS aws ssm send-command \
  --instance-ids i-02e8b0043997916e4 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "sudo yum install -y postgresql15 python3-pip",
    "pip3 install psycopg2-binary faker boto3 --user"
  ]'
```

## Files to Copy

You need to get these files onto the EC2 instance:
1. `init_cx_crm_schema.sql` - Database schema
2. `generate_cx_data.py` - Data generator

**Option 1**: Use S3 as intermediary
```bash
# From local machine
AWS_PROFILE=givenand-CMS aws s3 cp init_cx_crm_schema.sql s3://automotive-cx-data-lake-022035076260/scripts/
AWS_PROFILE=givenand-CMS aws s3 cp generate_cx_data.py s3://automotive-cx-data-lake-022035076260/scripts/

# From EC2
aws s3 cp s3://automotive-cx-data-lake-022035076260/scripts/init_cx_crm_schema.sql .
aws s3 cp s3://automotive-cx-data-lake-022035076260/scripts/generate_cx_data.py .
```

**Option 2**: Copy/paste file contents directly in Session Manager

## Expected Timeline

- Schema initialization: 1 minute
- Data generation: 30-60 minutes
  - 200 dealers: instant
  - 600 users: instant
  - 500K customers: ~20 minutes
  - 750K vehicles: ~15 minutes
  - Interactions: ~20 minutes

## Monitoring Progress

The script prints progress every 1000 records:
```
✓ Generated 200 dealers
✓ Generated 600 users
=== Year 2015 (Target: 20000 total customers) ===
  2015: 1000/20000 customers
  2015: 2000/20000 customers
  ...
```

## After Completion

1. Verify data:
```bash
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT COUNT(*) FROM contacts;"
```

2. Terminate instance:
```bash
AWS_PROFILE=givenand-CMS aws ec2 terminate-instances --instance-ids i-02e8b0043997916e4
```

3. Deploy ETL jobs and run pipeline

## Need Help?

If you get stuck, I can:
1. Create a Lambda function to do this automatically
2. Help troubleshoot connection issues
3. Provide alternative approaches
