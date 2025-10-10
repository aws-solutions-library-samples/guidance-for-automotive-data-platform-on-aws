# DataZone Blueprint Setup

DataZone blueprints must be enabled by a DataZone domain administrator. You can do this via the AWS Console or CloudFormation.

## Option 1: AWS Console (Recommended - 2 minutes)

1. **Open DataZone Console**
   ```
   https://us-east-1.console.aws.amazon.com/datazone/home?region=us-east-1#/domains/dzd-b0wxxskkm6s5wn/blueprints
   ```

2. **Enable Required Blueprints**
   
   For each blueprint below, click "Enable" and configure:

   ### MLExperiments
   - ManageAccessRole: `arn:aws:iam::195026230833:role/datazone-dzd-b0wxxskkm6s5wn-manage-access`
   - ProvisioningRole: `arn:aws:iam::195026230833:role/datazone-dzd-b0wxxskkm6s5wn-provisioning`
   - S3Location: `datazone-environments-195026230833`
   - VpcId: `vpc-06729499efe7e7acb`
   - Subnets: `subnet-0419cf90e2841211e,subnet-0a5e2468f2062582d`

   ### Tooling
   - Same configuration as MLExperiments

   ### LakehouseCatalog
   - ManageAccessRole: `arn:aws:iam::195026230833:role/datazone-dzd-b0wxxskkm6s5wn-manage-access`
   - ProvisioningRole: `arn:aws:iam::195026230833:role/datazone-dzd-b0wxxskkm6s5wn-provisioning`
   - No regional parameters needed

## Option 2: CloudFormation (For automation)

**Prerequisites:** You must be authenticated as a DataZone domain user (via AWS SSO/IAM Identity Center).

1. **Login with SSO**
   ```bash
   aws sso login --profile datazone-admin
   export AWS_PROFILE=datazone-admin
   ```

2. **Deploy CloudFormation**
   ```bash
   cd deployment
   aws cloudformation create-stack \
       --region us-east-1 \
       --stack-name datazone-blueprints \
       --template-body file://enable-blueprints.yaml \
       --parameters \
           ParameterKey=DomainId,ParameterValue=dzd-b0wxxskkm6s5wn \
           ParameterKey=ManageAccessRoleArn,ParameterValue=arn:aws:iam::195026230833:role/datazone-dzd-b0wxxskkm6s5wn-manage-access \
           ParameterKey=ProvisioningRoleArn,ParameterValue=arn:aws:iam::195026230833:role/datazone-dzd-b0wxxskkm6s5wn-provisioning \
           ParameterKey=S3Bucket,ParameterValue=datazone-environments-195026230833 \
           ParameterKey=VpcId,ParameterValue=vpc-06729499efe7e7acb \
           ParameterKey=SubnetIds,ParameterValue=subnet-0419cf90e2841211e,subnet-0a5e2468f2062582d
   ```

3. **Wait for completion**
   ```bash
   aws cloudformation wait stack-create-complete \
       --region us-east-1 \
       --stack-name datazone-blueprints
   ```

## Verify

- All 3 blueprints should show status "Enabled"
- You can now create environments in your DataZone projects

## Why Domain User Authentication?

DataZone blueprint configuration requires domain-level permissions that can only be obtained by authenticating as a DataZone domain user through IAM Identity Center (SSO). Standard IAM user credentials with AdministratorAccess will return `UnauthorizedException` when calling DataZone blueprint APIs.

This is a DataZone platform requirement, not a limitation of CloudFormation or other tools.
