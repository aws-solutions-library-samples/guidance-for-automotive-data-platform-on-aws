#!/bin/bash

# Interactive deployment script for Customer 360 Platform
# Guides users through configuration and deployment

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Banner
echo -e "${BLUE}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   🚗  Agentic Customer 360 Platform Deployment  🚗           ║
║                                                               ║
║   AWS Guidance for Automotive Customer Analytics             ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Check prerequisites
echo -e "${CYAN}Checking prerequisites...${NC}"

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo -e "${RED}✗ AWS CLI not found. Please install: https://aws.amazon.com/cli/${NC}"
    exit 1
fi
echo -e "${GREEN}✓ AWS CLI installed${NC}"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}✗ Node.js not found. Please install: https://nodejs.org/${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Node.js installed ($(node --version))${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 not found. Please install Python 3.8+${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python 3 installed ($(python3 --version))${NC}"

# Check CDK
if ! command -v cdk &> /dev/null; then
    echo -e "${YELLOW}⚠ AWS CDK not found. Installing...${NC}"
    npm install -g aws-cdk
fi
echo -e "${GREEN}✓ AWS CDK installed ($(cdk --version))${NC}"

echo ""

# Configuration
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}                    Configuration                              ${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# AWS Profile
echo -e "${YELLOW}AWS Configuration${NC}"
read -p "Enter AWS profile name (default: default): " AWS_PROFILE
AWS_PROFILE=${AWS_PROFILE:-default}
export AWS_PROFILE

# Verify AWS credentials
if ! aws sts get-caller-identity --profile $AWS_PROFILE &> /dev/null; then
    echo -e "${RED}✗ Cannot authenticate with AWS profile: $AWS_PROFILE${NC}"
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --profile $AWS_PROFILE --query Account --output text)
echo -e "${GREEN}✓ Authenticated as account: $ACCOUNT_ID${NC}"

# AWS Region
read -p "Enter AWS region (default: us-east-1): " AWS_REGION
AWS_REGION=${AWS_REGION:-us-east-1}
export AWS_REGION
echo -e "${GREEN}✓ Using region: $AWS_REGION${NC}"

echo ""

# Deployment Stage
echo -e "${YELLOW}Deployment Configuration${NC}"
read -p "Enter deployment stage (dev/test/prod, default: dev): " DEPLOYMENT_STAGE
DEPLOYMENT_STAGE=${DEPLOYMENT_STAGE:-dev}
export DEPLOYMENT_STAGE
echo -e "${GREEN}✓ Deployment stage: $DEPLOYMENT_STAGE${NC}"

echo ""

# Data Generation
echo -e "${YELLOW}Data Generation${NC}"
echo "The platform can generate synthetic customer data for testing."
read -p "Generate sample data? (y/n, default: y): " GENERATE_DATA
GENERATE_DATA=${GENERATE_DATA:-y}

if [[ "$GENERATE_DATA" =~ ^[Yy]$ ]]; then
    read -p "Number of customers to generate (default: 10000): " CUSTOMER_COUNT
    CUSTOMER_COUNT=${CUSTOMER_COUNT:-10000}
    export CUSTOMER_COUNT
    echo -e "${GREEN}✓ Will generate $CUSTOMER_COUNT customers${NC}"
else
    echo -e "${YELLOW}⚠ Skipping data generation - platform will deploy without data${NC}"
fi

echo ""

# Deployment Summary
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}                  Deployment Summary                           ${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  AWS Account:       ${GREEN}$ACCOUNT_ID${NC}"
echo -e "  AWS Region:        ${GREEN}$AWS_REGION${NC}"
echo -e "  AWS Profile:       ${GREEN}$AWS_PROFILE${NC}"
echo -e "  Deployment Stage:  ${GREEN}$DEPLOYMENT_STAGE${NC}"
echo -e "  Stack Prefix:      ${GREEN}cx360-$DEPLOYMENT_STAGE${NC}"
if [[ "$GENERATE_DATA" =~ ^[Yy]$ ]]; then
    echo -e "  Sample Data:       ${GREEN}$CUSTOMER_COUNT customers${NC}"
else
    echo -e "  Sample Data:       ${YELLOW}None (infrastructure only)${NC}"
fi
echo ""

# Components to deploy
echo -e "${CYAN}Components to deploy:${NC}"
echo -e "  ${GREEN}✓${NC} Phase 1: Data Lake (S3 + Glue + Athena)"
echo -e "  ${GREEN}✓${NC} Phase 2: ETL Jobs (Glue)"
if [[ "$GENERATE_DATA" =~ ^[Yy]$ ]]; then
    echo -e "  ${GREEN}✓${NC} Phase 3: Generate Sample Data"
else
    echo -e "  ${YELLOW}⊘${NC} Phase 3: Generate Sample Data (skipped)"
fi
echo -e "  ${GREEN}✓${NC} Phase 4: Amazon QuickSight Dashboards"
echo -e "  ${GREEN}✓${NC} Phase 5: Aurora PostgreSQL + Bedrock Agents"
echo ""

# Cost estimate
echo -e "${CYAN}Estimated Monthly Cost:${NC}"
echo -e "  • Data Lake (S3 + Glue + Athena):  ${GREEN}~\$50-100${NC}"
echo -e "  • Aurora Serverless v2:            ${GREEN}~\$100-200${NC}"
echo -e "  • Bedrock (pay per use):           ${GREEN}~\$20-50${NC}"
echo -e "  • QuickSight (per user):           ${GREEN}~\$24/user${NC}"
echo -e "  ${CYAN}Total:                             ~\$194-374/month${NC}"
echo ""

# Confirmation
read -p "$(echo -e ${YELLOW}Proceed with deployment? [y/N]:${NC} )" CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo -e "${RED}Deployment cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}                Starting Deployment                            ${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Install dependencies
echo -e "${BLUE}[1/6] Installing dependencies...${NC}"
make install
echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Bootstrap CDK (if needed)
echo -e "${BLUE}[2/6] Checking CDK bootstrap...${NC}"
if ! aws cloudformation describe-stacks --stack-name CDKToolkit --profile $AWS_PROFILE --region $AWS_REGION &> /dev/null; then
    echo -e "${YELLOW}CDK not bootstrapped. Bootstrapping...${NC}"
    make bootstrap
    echo -e "${GREEN}✓ CDK bootstrapped${NC}"
else
    echo -e "${GREEN}✓ CDK already bootstrapped${NC}"
fi
echo ""

# Phase 1: Data Lake
echo -e "${BLUE}[3/6] Deploying Data Lake (S3 + Glue + Athena)...${NC}"
make phase1
echo -e "${GREEN}✓ Phase 1 complete${NC}"
echo ""

# Phase 2: ETL
echo -e "${BLUE}[4/6] Deploying ETL Jobs...${NC}"
make phase2
echo -e "${GREEN}✓ Phase 2 complete${NC}"
echo ""

# Phase 3: Data Generation
if [[ "$GENERATE_DATA" =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}[5/6] Generating sample data ($CUSTOMER_COUNT customers)...${NC}"
    make phase3
    echo -e "${GREEN}✓ Phase 3 complete${NC}"
else
    echo -e "${YELLOW}[5/6] Skipping data generation${NC}"
fi
echo ""

# Phase 4: QuickSight
echo -e "${BLUE}[6/6] Deploying QuickSight dashboards...${NC}"
echo -e "${YELLOW}Note: QuickSight setup requires manual steps${NC}"
echo -e "${YELLOW}See docs/DEPLOYMENT.md for QuickSight configuration${NC}"
# make phase4  # Commented out - requires QuickSight subscription
echo -e "${YELLOW}⊘ Phase 4 skipped (manual setup required)${NC}"
echo ""

# Phase 5: Aurora + Bedrock
echo -e "${BLUE}[7/7] Deploying Aurora PostgreSQL + Bedrock Agents...${NC}"
make phase5
echo -e "${GREEN}✓ Phase 5 complete${NC}"
echo ""

# Deployment complete
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}                  ✓ Deployment Complete!                      ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Get outputs
DATA_LAKE_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name cx360-$DEPLOYMENT_STAGE-data-lake \
    --query 'Stacks[0].Outputs[?OutputKey==`DataLakeBucket`].OutputValue' \
    --output text \
    --profile $AWS_PROFILE \
    --region $AWS_REGION)

GLUE_DATABASE=$(aws cloudformation describe-stacks \
    --stack-name cx360-$DEPLOYMENT_STAGE-glue \
    --query 'Stacks[0].Outputs[?OutputKey==`GlueDatabase`].OutputValue' \
    --output text \
    --profile $AWS_PROFILE \
    --region $AWS_REGION)

AURORA_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name cx360-$DEPLOYMENT_STAGE-aurora \
    --query 'Stacks[0].Outputs[?OutputKey==`ClusterEndpoint`].OutputValue' \
    --output text \
    --profile $AWS_PROFILE \
    --region $AWS_REGION 2>/dev/null || echo "N/A")

echo -e "${CYAN}Deployed Resources:${NC}"
echo -e "  • S3 Data Lake:        ${GREEN}$DATA_LAKE_BUCKET${NC}"
echo -e "  • Glue Database:       ${GREEN}$GLUE_DATABASE${NC}"
echo -e "  • Aurora Endpoint:     ${GREEN}$AURORA_ENDPOINT${NC}"
echo ""

echo -e "${CYAN}Next Steps:${NC}"
echo ""
echo -e "  1. ${YELLOW}Query data with Athena:${NC}"
echo -e "     aws athena start-query-execution \\"
echo -e "       --query-string 'SELECT * FROM customer_health LIMIT 10' \\"
echo -e "       --query-execution-context Database=$GLUE_DATABASE \\"
echo -e "       --result-configuration OutputLocation=s3://$DATA_LAKE_BUCKET/athena-results/"
echo ""
echo -e "  2. ${YELLOW}Set up QuickSight:${NC}"
echo -e "     • Subscribe to QuickSight: https://quicksight.aws.amazon.com/"
echo -e "     • Run: make phase4"
echo -e "     • See: docs/DEPLOYMENT.md"
echo ""
echo -e "  3. ${YELLOW}Test Bedrock Agents:${NC}"
echo -e "     • Upload docs to Knowledge Base S3 bucket"
echo -e "     • Sync data sources"
echo -e "     • Test agent queries"
echo ""
echo -e "  4. ${YELLOW}View documentation:${NC}"
echo -e "     • Architecture: docs/ARCHITECTURE.md"
echo -e "     • Deployment: docs/DEPLOYMENT.md"
echo -e "     • Cost Analysis: docs/COST_ANALYSIS.md"
echo ""

echo -e "${GREEN}Thank you for deploying Agentic Customer 360!${NC}"
echo ""
