#!/bin/bash
# Deploy the Telemetry Normalization ADP data product
#
# Usage:
#   ./deploy.sh                          # defaults: stage=prod, region=us-east-2
#   ./deploy.sh --stage dev --region us-west-2
#
set -e

STAGE="${DEPLOYMENT_STAGE:-prod}"
REGION="${AWS_REGION:-us-east-2}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --stage) STAGE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

echo "🚀 Deploying ADP Telemetry Normalization (stage=$STAGE, region=$REGION)"

# Setup venv if needed
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
else
  source .venv/bin/activate
fi

# Deploy
CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text) \
CDK_DEFAULT_REGION=$REGION \
AWS_DEFAULT_REGION=$REGION \
DEPLOYMENT_STAGE=$STAGE \
cdk deploy --all --require-approval never

# Get bootstrap servers for the fanout service
echo ""
echo "📋 Post-deploy: Set BOOTSTRAP_SERVERS on the Fargate task"
MSK_ARN=$(aws cloudformation describe-stacks \
  --stack-name "cms-${STAGE}-msk" \
  --query "Stacks[0].Outputs[?OutputKey=='MSKClusterArn'].OutputValue" \
  --output text --region "$REGION")
BOOTSTRAP=$(aws kafka get-bootstrap-brokers \
  --cluster-arn "$MSK_ARN" \
  --query 'BootstrapBrokerStringSaslIam' \
  --output text --region "$REGION")
echo "   BOOTSTRAP_SERVERS=$BOOTSTRAP"
echo ""
echo "✅ Done"
