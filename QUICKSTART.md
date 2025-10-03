# Quick Start: Automotive Data Platform

Deploy the base platform in under 30 minutes.

## Prerequisites Checklist

- [ ] AWS Account with admin permissions
- [ ] AWS CLI v2 installed and configured
- [ ] IAM Identity Center set up in your region
- [ ] Connected Mobility Solution deployed (for data source)

## Step 1: Deploy Base Infrastructure (5 minutes)

```bash
# Clone repository
cd /Users/givenand/automotive-data-platform-on-aws

# Set your AWS profile and region
export AWS_PROFILE=default
export AWS_REGION=us-east-1

# Deploy the base platform
./deployment/deploy-base-platform.sh
```

**Expected Output:**
```
✅ Stack creation complete
VPC ID: vpc-xxxxx
Private Subnet IDs: subnet-xxxxx,subnet-yyyyy,subnet-zzzzz
```

## Step 2: Load Stack Outputs (1 minute)

```bash
# Load the VPC and subnet IDs
source deployment/stack-outputs.env

# Verify
echo $VPC_ID
echo $SUBNET_IDS
```

## Step 3: Create SageMaker Unified Studio Domain (15 minutes)

### Automated Setup (Recommended)

```bash
# Run automated domain creation
./deployment/create-sagemaker-domain.sh
```

**What it does:**
- ✅ Creates IAM execution role
- ✅ Creates SageMaker domain with proper VPC/subnet configuration
- ✅ Waits for domain to be ready
- ✅ Saves domain ID and URL to stack-outputs.env

**Note**: If the script fails due to SageMaker Unified Studio API limitations, follow the manual steps below.

### Manual Setup (If Automated Fails)

1. **Open SageMaker Console**
   - Navigate to: https://console.aws.amazon.com/sagemaker

2. **Create Domain**
   - Click "Create domain"
   - Domain name: `automotive-data-platform`
   - Auth mode: IAM

3. **Network Configuration**
   - VPC: Use `$VPC_ID` from Step 2
   - Subnets: Select 3 private subnets
   - Security group: Use default

4. **Create Domain**
   - Click "Create domain"
   - Wait 10-15 minutes

## Step 4: Configure Users (5 minutes)

### Create IAM Identity Center Groups

1. **Open IAM Identity Center Console**
   - Navigate to: https://console.aws.amazon.com/singlesignon

2. **Create Groups**
   ```
   Group Name: automotive-data-engineers
   Description: Data engineers for automotive platform
   
   Group Name: automotive-ml-engineers
   Description: ML engineers for automotive platform
   
   Group Name: automotive-admins
   Description: Platform administrators
   ```

3. **Add Users to Groups**
   - Create or assign existing users
   - Add to appropriate groups

### Assign Groups to Domain

1. **Return to SageMaker Unified Studio Console**
2. **Select your domain** → "User management"
3. **Add groups**:
   - `automotive-data-engineers` → Data Engineer role
   - `automotive-ml-engineers` → ML Engineer role
   - `automotive-admins` → Admin role

## Step 5: Get Portal URL (1 minute)

```bash
# Get domain ID
DOMAIN_ID=$(aws sagemaker list-domains \
  --query 'Domains[?DomainName==`automotive-data-platform`].DomainId' \
  --output text \
  --region $AWS_REGION \
  --profile $AWS_PROFILE)

# Get portal URL
PORTAL_URL=$(aws sagemaker describe-domain \
  --domain-id $DOMAIN_ID \
  --query 'Url' \
  --output text \
  --region $AWS_REGION \
  --profile $AWS_PROFILE)

echo "Portal URL: $PORTAL_URL"

# Save for later
echo "export PORTAL_URL=\"$PORTAL_URL\"" >> deployment/stack-outputs.env
```

## Step 6: Verify Deployment (2 minutes)

### Test Portal Access

1. **Open Portal URL** in browser
2. **Sign in** with IAM Identity Center credentials
3. **Verify** you can access the portal

### Verify Network Connectivity

```bash
# Check VPC
aws ec2 describe-vpcs \
  --vpc-ids $VPC_ID \
  --query 'Vpcs[0].State' \
  --output text

# Check subnets
aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=$VPC_ID" \
  --query 'Subnets[*].[SubnetId,AvailabilityZone,State]' \
  --output table
```

### Verify Data Source Access

```bash
# List Connected Mobility telemetry data
# Replace with your actual CMS bucket name
CMS_BUCKET="your-cms-bucket-name"

aws s3 ls s3://$CMS_BUCKET/telemetry/ --recursive | head -10
```

## Step 7: Deploy First Project (Next)

Now that the base platform is ready, deploy the tire prediction project:

```bash
# Clone tire prediction project
cd ..
git clone <tire-prediction-repo-url>
cd automotive-tire-prediction-model-on-aws

# Follow project deployment guide
cat README.md
```

## Troubleshooting

### Stack Creation Failed

```bash
# Check stack events
aws cloudformation describe-stack-events \
  --stack-name automotive-data-platform-network \
  --max-items 20 \
  --region $AWS_REGION \
  --profile $AWS_PROFILE
```

### Domain Creation Failed

1. Check IAM Identity Center is configured
2. Verify VPC and subnets are in same region
3. Check service quotas for SageMaker

### Cannot Access Portal

1. Verify user is in IAM Identity Center group
2. Check group is assigned to domain
3. Verify user has correct permissions

### No Data in S3

1. Verify Connected Mobility Solution is deployed
2. Check simulator is running and generating data
3. Verify S3 bucket permissions

## Cost Estimate

**Base Platform**: ~$84/month
- VPC NAT Gateway: $32/month
- VPC Endpoints: $36/month
- CloudWatch Logs: $2.50/month
- Other: $13.50/month

**Note**: Project-specific costs are additional.

## Next Steps

1. ✅ Base platform deployed
2. ✅ Users configured
3. ✅ Portal accessible
4. → Deploy tire prediction project
5. → Create additional projects
6. → Set up monitoring and alerts

## Support

- **Documentation**: See main README.md
- **AWS Support**: Contact your AWS account team
- **Issues**: Check CloudFormation events and logs
