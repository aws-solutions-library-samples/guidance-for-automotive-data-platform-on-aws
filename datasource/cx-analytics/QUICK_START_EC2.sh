#!/bin/bash
# Copy and paste these commands into AWS Session Manager

set -e

# 1. Install dependencies
sudo yum install -y postgresql15 python3-pip jq
pip3 install psycopg2-binary faker boto3 --user

# 2. Resolve data lake bucket name from CloudFormation
BUCKET=$(aws cloudformation describe-stacks --stack-name CXDataLakeStack \
  --query 'Stacks[0].Outputs[?contains(OutputKey,`DataLake`)].OutputValue' --output text)
echo "Data lake bucket: $BUCKET"

# 3. Download files from S3
cd ~
aws s3 cp s3://${BUCKET}/scripts/init_cx_crm_schema.sql .
aws s3 cp s3://${BUCKET}/scripts/generate_cx_data.py .

# 4. Resolve DB credentials from Secrets Manager
SECRET_ARN=$(aws cloudformation describe-stacks --stack-name CXCRMStack \
  --query 'Stacks[0].Outputs[?contains(OutputKey,`SecretArn`)].OutputValue' --output text)
SECRET_JSON=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --query SecretString --output text)

export DB_HOST=$(echo "$SECRET_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['host'])")
export DB_USER=$(echo "$SECRET_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['username'])")
export DB_PASSWORD=$(echo "$SECRET_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['password'])")
export DB_NAME=cx_crm

echo "Connected to: $DB_HOST as $DB_USER"

# 5. Initialize schema
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f init_cx_crm_schema.sql

# 6. Generate data (30-60 minutes on c6i.4xlarge)
python3 generate_cx_data.py

# 7. Verify
PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT COUNT(*) FROM contacts;"
