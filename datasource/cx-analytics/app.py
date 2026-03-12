#!/usr/bin/env python3
import os
import aws_cdk as cdk
from cx_crm_stack import CXCRMStack
from cx_datalake_stack import CXDataLakeStack
from cx_etl_stack import CXETLStack
import aws_cdk.aws_ec2 as ec2

app = cdk.App()

# Configuration from environment variables
account = os.environ.get("CDK_DEFAULT_ACCOUNT", os.environ.get("AWS_ACCOUNT_ID"))
region = os.environ.get("CDK_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1"))
vpc_id = os.environ.get("VPC_ID", "")

env = cdk.Environment(account=account, region=region)

# Create a dummy stack to import VPC
class VpcStack(cdk.Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        self.vpc = ec2.Vpc.from_lookup(self, "SharedVpc", vpc_id=vpc_id)

vpc_stack = VpcStack(app, "VpcStack", env=env)

# Deploy stacks
crm_stack = CXCRMStack(app, "CXCRMStack", vpc=vpc_stack.vpc, env=env,
    description="Guidance for Automotive Data Platform on AWS (SO9676) - Customer 360 CRM")
datalake_stack = CXDataLakeStack(app, "CXDataLakeStack", env=env,
    description="Guidance for Automotive Data Platform on AWS (SO9676) - Customer 360 Data Lake")

# ETL stack depends on both
etl_stack = CXETLStack(
    app, "CXETLStack",
    data_lake_bucket=datalake_stack.data_lake_bucket,
    db_secret_arn=crm_stack.cluster.secret.secret_arn,
    env=env,
    description="Guidance for Automotive Data Platform on AWS (SO9676) - Customer 360 ETL"
)
etl_stack.add_dependency(crm_stack)
etl_stack.add_dependency(datalake_stack)

app.synth()
