#!/usr/bin/env python3
"""
Automotive Data Governance — CDK App

Deploys the data governance framework in the EU producer region.
"""
import os
from aws_cdk import App, Environment
from stacks.governance_stack import GovernanceStack

STAGE = os.environ.get('DEPLOYMENT_STAGE', 'dev')
REGION = os.environ.get('CDK_DEFAULT_REGION', os.environ.get('AWS_REGION', 'us-west-2'))
ACCOUNT = os.environ.get('CDK_DEFAULT_ACCOUNT')

app = App()
env = Environment(account=ACCOUNT, region=REGION)

GovernanceStack(
    app,
    f"adp-{STAGE}-governance",
    stage=STAGE,
    env=env,
    description="ADP Data Governance — Multi-region PII/anonymized data separation",
)

app.synth()
