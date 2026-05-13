#!/usr/bin/env python3
"""
Vehicle Knowledge Base — CDK App

Deploys a Bedrock Knowledge Base backed by S3 with 4 data sources:
- technical-reference (DTC guides, diagnostic procedures)
- tsb-recalls (Technical Service Bulletins, NHTSA recalls)
- owner-manuals (maintenance schedules, fluid specs, warning lights)
- service-policy (warranty coverage, SLA definitions, escalation rules)
"""
import os
from aws_cdk import App, Environment
from stacks.knowledge_base_stack import KnowledgeBaseStack

STAGE = os.environ.get("DEPLOYMENT_STAGE", "dev")
REGION = os.environ.get("CDK_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1"))
ACCOUNT = os.environ.get("CDK_DEFAULT_ACCOUNT")

app = App()
env = Environment(account=ACCOUNT, region=REGION)

KnowledgeBaseStack(
    app,
    f"adp-{STAGE}-vehicle-knowledge-base",
    stage=STAGE,
    env=env,
    description="ADP Vehicle Knowledge Base — Bedrock KB with 4 automotive data sources",
)

app.synth()
