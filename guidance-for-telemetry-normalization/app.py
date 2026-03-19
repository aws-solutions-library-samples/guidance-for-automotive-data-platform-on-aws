#!/usr/bin/env python3
"""
Telemetry Normalization — ADP Data Product

Standalone CDK app that deploys:
  - WebSocket fanout service (Kafka → WebSocket bridge for FWE telemetry)
  - (Future) Glue ETL jobs for Iceberg table population

Requires the CMS pipeline (connected-mobility-guidance-on-aws) to be deployed first.
"""
import os
from aws_cdk import App, Environment
from stacks.ws_fanout_stack import WsFanoutStack

STAGE = os.environ.get('DEPLOYMENT_STAGE', 'prod')
REGION = os.environ.get('CDK_DEFAULT_REGION', os.environ.get('AWS_REGION', 'us-east-2'))
ACCOUNT = os.environ.get('CDK_DEFAULT_ACCOUNT')

app = App()
env = Environment(account=ACCOUNT, region=REGION)

ws_fanout = WsFanoutStack(
    app,
    f"adp-{STAGE}-telemetry-fanout",
    stage=STAGE,
    env=env,
    description="ADP Telemetry Normalization — WebSocket Fanout Service"
)

app.synth()
