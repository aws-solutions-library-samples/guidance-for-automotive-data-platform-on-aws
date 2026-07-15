# Amazon Quick Suite Security Model

## Recommended Approach

**Use AWS IAM Identity Center (SSO) + Quick Suite IAM Role**

### Security Architecture

```
AWS IAM Identity Center (SSO)
    ↓
Quick Suite Users (federated)
    ↓
Quick Suite IAM Role (for API access)
    ↓
Resources (dashboards, datasets, data sources)
```

### Benefits

1. **Centralized Identity**: Users authenticate via AWS SSO
2. **No Hardcoded Users**: Scripts use IAM role, not specific usernames
3. **Least Privilege**: Grant only necessary permissions
4. **Audit Trail**: CloudTrail logs all Quick Suite access
5. **Multi-Account**: Works across AWS Organizations

## Implementation

### 1. Quick Suite Setup

**Enable Quick Suite with IAM Identity Center**:
- Quick Suite automatically integrates with IAM Identity Center
- Users sign in via SSO portal
- No separate Quick Suite passwords

**Quick Suite Service Role**:
- Automatically created when enabling Quick Suite
- Grants Quick Suite access to Athena, S3, Glue
- Managed by AWS

### 2. Resource Ownership

**Deployment User/Role**:
- The IAM principal running `make phase4` becomes the owner
- Owns: data sources, datasets, dashboards
- Can grant permissions to other users

**Recommended**:
```bash
# Use a deployment role (not individual user)
aws sts assume-role --role-arn arn:aws:iam::ACCOUNT:role/QuickSuiteDeploymentRole
export AWS_PROFILE=quicksuite-deployment

# Deploy
make phase4
```

### 3. Sharing Dashboards

**After Deployment**:
1. Dashboard owner grants permissions to users/groups
2. Users access via SSO
3. Row-level security (optional) for data filtering

**Via Console**:
- Dashboard → Share → Add users/groups
- Set permissions: View, Edit, or Admin

**Via API**:
```bash
aws quicksight update-dashboard-permissions \
  --aws-account-id ACCOUNT_ID \
  --dashboard-id DASHBOARD_ID \
  --grant-permissions Principal=arn:aws:quicksight:REGION:ACCOUNT:group/default/Analysts,Actions=quicksight:DescribeDashboard,quicksight:QueryDashboard
```

## Security Best Practices

### 1. IAM Permissions

**Deployment Role** needs:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "quicksight:CreateDataSource",
        "quicksight:CreateDataSet",
        "quicksight:CreateDashboard",
        "quicksight:UpdateDataSource",
        "quicksight:UpdateDataSet",
        "quicksight:UpdateDashboard",
        "quicksight:DescribeDataSource",
        "quicksight:DescribeDataSet",
        "quicksight:DescribeDashboard",
        "quicksight:UpdateDashboardPermissions"
      ],
      "Resource": "*"
    }
  ]
}
```

**End Users** need:
- No IAM permissions required
- Access via Quick Suite permissions only
- Authenticate via SSO

### 2. Data Access Control

**Dataset Level**:
- Control which datasets users can access
- Set in dataset permissions

**Row-Level Security (RLS)**:
```sql
-- Example: Users only see their region's data
CREATE TABLE quicksight_rls AS
SELECT 
  username,
  region
FROM user_regions;

-- Apply to dataset
-- Users with region='US-EAST' only see US-EAST data
```

**Column-Level Security**:
- Hide sensitive columns (PII, revenue) from certain users
- Configure in dataset settings

### 3. Network Security

**VPC Connection** (optional):
- Connect Quick Suite to private VPC
- Access private data sources (RDS, Redshift in private subnets)
- Not needed for Athena (uses AWS PrivateLink)

**IP Allowlisting** (Enterprise only):
- Restrict Quick Suite access to corporate IPs
- Configure in Quick Suite account settings

### 4. Encryption

**At Rest**:
- SPICE data encrypted with AWS KMS
- We use DIRECT_QUERY (no SPICE), so data stays in S3
- S3 encryption handles at-rest

**In Transit**:
- TLS 1.2+ for all connections
- Automatic, no configuration needed

## Updated Deployment Scripts

### Remove Hardcoded Username

**Before**:
```bash
QS_USERNAME="${QUICKSIGHT_USERNAME:-admin}"
QS_USER_ARN="arn:aws:quicksight:${REGION}:${ACCOUNT_ID}:user/default/${QS_USERNAME}"
```

**After**:
```bash
# Get current IAM principal
CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)
CALLER_USER=$(echo $CALLER_ARN | cut -d'/' -f2)

# Use Quick Suite admin (deployment role)
QS_ADMIN_ARN="arn:aws:quicksight:${REGION}:${ACCOUNT_ID}:user/default/${CALLER_USER}"
```

### Permissions Strategy

**Resources created with**:
- Owner: Deployment IAM principal
- Permissions: Owner has full access
- Sharing: Done post-deployment via console or API

**No hardcoded users** in scripts - uses whoever runs the deployment.

## Recommended Setup

### For Production

1. **Create Deployment Role**:
```bash
# IAM role: QuickSuiteDeploymentRole
# Trust policy: Allows DevOps team to assume
# Permissions: Quick Suite create/update/describe
```

2. **Enable IAM Identity Center**:
```bash
# AWS Organizations → IAM Identity Center
# Add users/groups
# Quick Suite automatically integrates
```

3. **Deploy with Role**:
```bash
aws sts assume-role --role-arn arn:aws:iam::ACCOUNT:role/QuickSuiteDeploymentRole
make phase4
```

4. **Share Dashboards**:
```bash
# Via console or API
# Grant view permissions to analyst groups
```

### For Development/Testing

1. **Use Personal IAM User**:
```bash
# Your IAM user becomes owner
make phase4
```

2. **Access via SSO**:
```bash
# Sign in to Quick Suite via AWS console
# Your IAM user has access to resources you created
```

## Audit and Compliance

**CloudTrail Logging**:
- All Quick Suite API calls logged
- Who accessed what dashboard, when
- Data source queries logged

**Quick Suite Access Logs**:
- User login events
- Dashboard view events
- Query execution logs

**Monitoring**:
```bash
# CloudWatch metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/QuickSight \
  --metric-name DashboardViews \
  --dimensions Name=DashboardId,Value=DASHBOARD_ID
```

## Summary

**Recommended Security Model**:
1. ✅ Use AWS IAM Identity Center (SSO) for user authentication
2. ✅ Deployment role/user owns resources (whoever runs `make phase4`)
3. ✅ Share dashboards post-deployment via permissions
4. ✅ No hardcoded usernames in scripts
5. ✅ Row-level security for data filtering (optional)
6. ✅ CloudTrail for audit logging

**Scripts Updated**:
- Remove `QUICKSIGHT_USERNAME` environment variable
- Use current IAM principal as owner
- Document sharing process in README

This approach is secure, scalable, and follows AWS best practices.
