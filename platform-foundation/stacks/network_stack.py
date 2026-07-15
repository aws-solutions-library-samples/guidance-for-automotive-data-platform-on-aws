"""ADP foundation network stack — VPC + interface endpoints.

Provides a private network for SageMaker notebooks, Glue jobs, and
Athena queries to reach AWS services without traversing the public
internet. Deploys per-stage; staging and prod each get their own
VPC and endpoint suite (design §3 "Duplicated").

VPC topology
------------
- 1 VPC ``10.42.0.0/16``
- 3 private (isolated) subnets in 3 AZs (no NAT, no IGW — the lake
  is reached via gateway endpoint, control planes via interface
  endpoints)
- S3 + DynamoDB **gateway** endpoints (free)
- Glue, Athena, KMS, Logs, STS, SSM **interface** endpoints

Tradeoffs
---------
We deliberately avoid NAT gateways: this is an analytical workload,
not a public-facing service, so private+endpoints is sufficient. NAT
adds ~$32/month per AZ. cdk-nag may flag the lack of public subnets;
that's expected for an analytics-only foundation.
"""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Stack,
)
from aws_cdk import aws_ec2 as ec2
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks._naming import _stage_name, validate_stage


class NetworkStack(Stack):
    """VPC + endpoint suite for the ADP foundation (per-stage)."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        validate_stage(stage)
        self.stage = stage

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.42.0.0/16"),
            max_azs=3,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=22,
                )
            ],
            flow_logs={
                "to-cloudwatch": ec2.FlowLogOptions(
                    destination=ec2.FlowLogDestination.to_cloud_watch_logs(),
                    traffic_type=ec2.FlowLogTrafficType.REJECT,
                )
            },
            enable_dns_hostnames=True,
            enable_dns_support=True,
        )

        # Gateway endpoints (free)
        self.vpc.add_gateway_endpoint(
            "S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3
        )
        self.vpc.add_gateway_endpoint(
            "DynamoDbEndpoint", service=ec2.GatewayVpcEndpointAwsService.DYNAMODB
        )

        # Interface endpoints (paid, but required for private connectivity)
        for label, svc in [
            ("Glue", ec2.InterfaceVpcEndpointAwsService.GLUE),
            ("Athena", ec2.InterfaceVpcEndpointAwsService.ATHENA),
            ("Kms", ec2.InterfaceVpcEndpointAwsService.KMS),
            ("CwLogs", ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS),
            ("Sts", ec2.InterfaceVpcEndpointAwsService.STS),
            ("Ssm", ec2.InterfaceVpcEndpointAwsService.SSM),
        ]:
            self.vpc.add_interface_endpoint(
                f"{label}Endpoint",
                service=svc,
                private_dns_enabled=True,
            )

        # Outputs (stage-prefixed export names per design §2.11)
        CfnOutput(
            self,
            "VpcId",
            value=self.vpc.vpc_id,
            export_name=_stage_name(stage, "vpc-id"),
        )
        CfnOutput(
            self,
            "PrivateSubnetIds",
            value=",".join(s.subnet_id for s in self.vpc.isolated_subnets),
            export_name=_stage_name(stage, "private-subnet-ids"),
        )

        # cdk-nag suppressions
        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-VPC7",
                    "reason": (
                        "VPC flow logs ARE enabled (REJECT traffic to CloudWatch). "
                        "cdk-nag's default check looks for ALL traffic; we narrow to "
                        "REJECT to control cost — a documented trade-off for an "
                        "analytics foundation."
                    ),
                },
            ],
        )
