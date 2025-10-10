# SageMaker Unified Studio Domain Setup

## Important Note

SageMaker Unified Studio domains with proper SSO integration must be created through the AWS Console. The AWS CLI does not currently support all required configuration options for DataZone/Unified Studio domains.

## Setup Steps

### 1. Deploy Base Infrastructure

```bash
make deploy-network
```

This creates:
- VPC and subnets
- IAM execution role
- S3 buckets

### 2. Create Domain via Console

1. Go to: https://console.aws.amazon.com/datazone
2. Click **"Create domain"**
3. Configure domain:
   - **Name:** automotive-data-platform
   - **Authentication:** IAM Identity Center
   - **User assignment:** "Do not require assignments" (recommended for testing)
   - **VPC:** Select the VPC created in step 1
   - **Subnets:** Select subnets from step 1
   - **Execution role:** SageMakerUnifiedStudioExecutionRole

4. Click **"Create domain"**
5. Wait 10-15 minutes for domain creation

### 3. Configure SSO User Access

1. In the domain details page, go to **"User management"** tab
2. Click **"Configure SSO user access"**
3. Choose **"IAM Identity Center"**
4. Select assignment method:
   - **"Do not require assignments"** - All IAM Identity Center users can access
   - **"Require assignments"** - Manually add specific users
5. Click **"Save"**

### 4. Create SSO User

```bash
# Set your email
export DEFAULT_EMAIL=your-email@company.com

# Create user
./deployment/create-sso-user.sh
```

This will:
- Create SSO user in IAM Identity Center
- Provide link to reset password
- User can then login to Studio

### 5. Access Studio

1. User receives password reset email
2. Sets password
3. Logs in at the Studio URL provided

## Why Console is Required

- DataZone CLI commands are not available in all AWS CLI versions
- SSO user assignment configuration requires console interaction
- Domain creation with proper SSO integration needs DataZone console

## Automation Limitations

Currently automated:
- ✅ VPC and network infrastructure
- ✅ IAM roles and policies
- ✅ SSO user creation
- ✅ User profile creation (after domain exists)

Requires manual console steps:
- ❌ Domain creation with DataZone
- ❌ SSO user access configuration
- ❌ User assignment to domain

## Future Improvements

When DataZone CLI becomes fully available or CloudFormation supports these resources, the entire process can be automated.
