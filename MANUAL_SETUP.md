# Manual SageMaker Unified Studio Setup

The automated domain creation is complex. Here's the simple manual approach:

## Step 1: Verify Infrastructure

```bash
source deployment/stack-outputs.env
echo "VPC ID: $VPC_ID"
echo "Subnets: $SUBNET_IDS"
```

**Expected Output:**
- VPC ID: `vpc-043a20cee59083f17`
- Subnets: `subnet-0adee6e65a30f185f,subnet-02ad14636b605b600,subnet-06018d06d0a10a93f`

## Step 2: Create SageMaker Domain via Console

1. **Open SageMaker Console**:
   https://console.aws.amazon.com/sagemaker/home?region=us-east-1#/dashboard

2. **Navigate to Domains**:
   - Click "Domains" in the left sidebar
   - Click "Create domain"

3. **Domain Settings**:
   - **Domain name**: `automotive-data-platform`
   - **Authentication**: IAM

4. **Network Configuration**:
   - **VPC**: Select `vpc-043a20cee59083f17`
   - **Subnets**: Select these 3 subnets:
     - `subnet-0adee6e65a30f185f`
     - `subnet-02ad14636b605b600`
     - `subnet-06018d06d0a10a93f`
   - **Security groups**: Use default

5. **Execution Role**:
   - Select existing role: `SageMakerUnifiedStudioExecutionRole`
   - Or create new role with SageMaker permissions

6. **Create Domain**:
   - Click "Submit"
   - Wait 10-15 minutes for domain creation

## Step 3: Configure IAM Identity Center (Optional)

If you want to use IAM Identity Center for user management:

1. **Open IAM Identity Center**:
   https://console.aws.amazon.com/singlesignon

2. **Create Groups**:
   - `automotive-data-engineers`
   - `automotive-ml-engineers`
   - `automotive-admins`

3. **Add Users** to groups

4. **Assign to SageMaker Domain**:
   - Go back to SageMaker console
   - Select your domain
   - Add groups with appropriate permissions

## Step 4: Get Domain URL

```bash
# Get domain ID
DOMAIN_ID=$(aws sagemaker list-domains \
    --region us-east-1 \
    --query 'Domains[0].DomainId' \
    --output text)

# Get domain URL
aws sagemaker describe-domain \
    --domain-id $DOMAIN_ID \
    --region us-east-1 \
    --query 'Url' \
    --output text
```

## Step 5: Save Domain Info

```bash
# Add to stack outputs
echo "" >> deployment/stack-outputs.env
echo "# SageMaker Domain" >> deployment/stack-outputs.env
echo "export DOMAIN_ID=\"$DOMAIN_ID\"" >> deployment/stack-outputs.env
echo "export DOMAIN_URL=\"$(aws sagemaker describe-domain --domain-id $DOMAIN_ID --region us-east-1 --query 'Url' --output text)\"" >> deployment/stack-outputs.env
```

## Verification

```bash
# Check domain status
aws sagemaker describe-domain \
    --domain-id $DOMAIN_ID \
    --region us-east-1 \
    --query '[DomainId,Status,Url]' \
    --output table
```

**Expected Status**: `InService`

## Next Steps

Once domain is ready:

1. **Access Studio**: Open the domain URL in browser
2. **Create Project**: Create "tire-prediction" project
3. **Add Users**: Invite data engineers and ML engineers
4. **Deploy Tire Prediction**: Follow tire prediction repo instructions

## Troubleshooting

**Issue**: Domain creation fails
- Check VPC has internet connectivity (NAT Gateway)
- Verify subnets are in different AZs
- Check IAM role has correct permissions

**Issue**: Can't access domain URL
- Verify IAM Identity Center is configured
- Check user has been added to domain
- Try incognito/private browser window

**Issue**: Subnets not found
- Run: `aws ec2 describe-subnets --filters "Name=vpc-id,Values=$VPC_ID" --region us-east-1`
- Verify CloudFormation stack created subnets

## Cost Reminder

- SageMaker Domain: No charge (only for compute resources used)
- NAT Gateway: ~$32/month
- VPC Endpoints: ~$36/month
- **Total Base Cost**: ~$84/month

Stop compute resources when not in use to minimize costs.
