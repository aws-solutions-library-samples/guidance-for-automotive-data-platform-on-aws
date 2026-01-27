#!/bin/bash
# Copy and paste these commands into AWS Session Manager

# 1. Install dependencies
sudo yum install -y postgresql15 python3-pip
pip3 install psycopg2-binary faker boto3 --user

# 2. Download files from S3
cd ~
aws s3 cp s3://automotive-cx-data-lake-022035076260/scripts/init_cx_crm_schema.sql .
aws s3 cp s3://automotive-cx-data-lake-022035076260/scripts/generate_cx_data.py .

# 3. Set environment
export DB_HOST=cxcrmstack-cxcrmcluster6c40befe-gzycdxj7qfiu.cluster-cnqi2n6fm8jq.us-east-1.rds.amazonaws.com
export DB_USER=cx_admin
export DB_NAME=cx_crm
export DB_PASSWORD='2on,7FtaYCH.SvW10,_bW5d5AJqIzE'

# 4. Initialize schema
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f init_cx_crm_schema.sql

# 5. Generate data (30-60 minutes on c6i.4xlarge)
python3 generate_cx_data.py

# 6. Verify
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT COUNT(*) FROM contacts;"
