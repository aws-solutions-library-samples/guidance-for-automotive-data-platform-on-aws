#!/bin/bash

# Deploy Glue ETL Jobs for CX Analytics

set -e

# Get S3 bucket from stack outputs
BUCKET=$(aws cloudformation describe-stacks \
  --stack-name CXDataLakeStack \
  --query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' \
  --output text)

echo "Uploading Glue scripts to s3://${BUCKET}/glue-scripts/"

# Upload Glue job scripts
aws s3 cp glue_jobs/aurora_to_s3_export.py s3://${BUCKET}/glue-scripts/
aws s3 cp glue_jobs/process_customer_360.py s3://${BUCKET}/glue-scripts/
aws s3 cp glue_jobs/calculate_health_scores.py s3://${BUCKET}/glue-scripts/

echo "✓ Glue scripts uploaded"

# Deploy Glue jobs stack
echo "Deploying Glue ETL jobs..."
cdk deploy CXETLStack

echo "✓ Glue ETL jobs deployed"
echo ""
echo "To run jobs manually:"
echo "  aws glue start-job-run --job-name cx-aurora-to-s3-export"
echo "  aws glue start-job-run --job-name cx-process-customer-360"
echo "  aws glue start-job-run --job-name cx-calculate-health-scores"
