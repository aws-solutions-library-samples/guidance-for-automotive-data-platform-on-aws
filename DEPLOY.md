# DataZone V2 (SageMaker Unified Studio) Deployment Guide

## Prerequisites

1. **AWS Account** with admin access
2. **AWS CLI** v2.27+ configured
   ```bash
   aws --version
   aws configure
   ```
3. **IAM Permissions**: Your user/role needs:
   - `iam:CreateRole`, `iam:AttachRolePolicy`
   - `datazone:*`
   - `sso-admin:*`

## Quick Start

### 1. Enable IAM Identity Center (One-Time Setup)

**This is required once per AWS account:**

```bash
make deploy
```

If IAM Identity Center is not enabled, you'll see:

```
❌ IAM Identity Center is not enabled in this account

1. Open: https://console.aws.amazon.com/singlesignon/home?region=us-east-1
2. Click 'Enable'
3. Wait 30 seconds
4. Run 'make deploy' again
```

Follow the instructions, then run `make deploy` again.

### 2. Deploy DataZone Domain

Once IAM Identity Center is enabled:

```bash
make deploy
```

That's it! The script will:
- ✓ Verify IAM Identity Center is enabled
- ✓ Create execution and service IAM roles
- ✓ Create DataZone V2 domain with SSO
- ✓ Create default project profile
- ✓ Output portal URL

### 3. Access the Portal

**Option 1: AWS Console (Recommended)**
```bash
# Opens DataZone console
open https://console.aws.amazon.com/datazone
```
Click your domain → "Open data portal"

**Option 2: Direct IAM Login**
```bash
make datazone-login
```
Copy the URL and paste in your browser (valid for 5 minutes).

## Commands

```bash
make deploy          # Deploy DataZone domain
make datazone-status # Check domain status
make datazone-login  # Get portal access URL
make datazone-clean  # Delete domain
```

## Configuration

Set environment variables before deploying:

```bash
export AWS_REGION=us-west-2
export DOMAIN_NAME=my-data-platform
make deploy
```

## What Gets Created

- **IAM Roles**:
  - `{domain-name}-execution-role` - Used by DataZone for operations
  - `{domain-name}-service-role` - Used by DataZone service

- **DataZone Domain**:
  - Version: V2 (SageMaker Unified Studio)
  - SSO: Integrated with IAM Identity Center
  - User Assignment: AUTOMATIC
  - Project Profile: `default-profile` (enabled)

## Troubleshooting

### "IAM Identity Center not enabled"
- Enable it at: https://console.aws.amazon.com/singlesignon
- This is a one-time manual step (AWS security requirement)
- Cannot be automated via CLI/CloudFormation for management accounts

### "Unable to assume role" in portal
- This indicates an account-level IAM Identity Center issue
- Try in a different AWS account
- Older IAM Identity Center instances (pre-2023) may have compatibility issues

### Domain creation fails
- Wait 15 seconds and try again (IAM propagation)
- Verify you have required permissions
- Check IAM Identity Center is in the same region

### Portal shows "Something went wrong"
- Clear browser cache and cookies
- Try incognito/private browsing
- Use console access instead: https://console.aws.amazon.com/datazone

## Cost

- **DataZone domain**: No charge for the domain itself
- **Usage-based charges**:
  - Data catalog operations
  - Compute resources (when you create projects)
  - Storage (S3, Glue catalog)

Estimated: $0-50/month depending on usage

## Architecture

```
┌─────────────────────────────────────────┐
│ IAM Identity Center (Required)          │
│ - One-time manual setup                 │
│ - Provides SSO authentication           │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ DataZone V2 Domain                      │
│ - Execution Role                        │
│ - Service Role                          │
│ - Project Profiles                      │
└─────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ SageMaker Unified Studio Portal         │
│ - Data analytics                        │
│ - Machine learning                      │
│ - Generative AI                         │
└─────────────────────────────────────────┘
```

## Next Steps

After deployment:
1. Access portal: `make datazone-login` or via console
2. Create a project
3. Add data sources (S3, Glue, Redshift)
4. Invite team members via IAM Identity Center
5. Start analyzing data

## Support

If you encounter issues:
1. Check CloudTrail for detailed error messages
2. Verify IAM Identity Center is properly configured
3. Review the troubleshooting section above
4. Open an AWS Support case if issues persist

## Manual Setup (Alternative)

For full control, use the AWS Console:
1. Go to: https://console.aws.amazon.com/datazone
2. Click "Create a Unified Studio domain"
3. Choose "Manual setup" for customization
4. Follow the wizard

The console provides more options for:
- VPC configuration
- Encryption settings
- Bedrock model access
- Data onboarding
