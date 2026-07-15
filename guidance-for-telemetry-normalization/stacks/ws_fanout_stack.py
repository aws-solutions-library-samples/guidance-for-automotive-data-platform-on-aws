"""
WebSocket Fanout Stack

ECS Fargate task that consumes from per-fleet Kafka topics (CMS pipeline)
and pushes FWE telemetry to connected WebSocket clients.

Prerequisites (from connected-mobility-guidance-on-aws):
  - MSK cluster with per-fleet topics (cms-fleet-{fleetId}-telemetry)
  - WebSocket API Gateway + handler Lambda
  - WS connections DynamoDB table with fleetId-index GSI
"""
from aws_cdk import (
    Stack, Fn, CfnOutput,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct


class WsFanoutStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, stage: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        cms_prefix = f"cms-{stage}"
        msk_stack = f"{cms_prefix}-msk"
        storage_prefix = f"{cms_prefix}-storage"

        # Import networking from CMS MSK stack
        vpc_id = Fn.import_value(f"{msk_stack}-vpc-id")
        subnet_ids_joined = Fn.import_value(f"{msk_stack}-private-subnet-ids")
        msk_sg_id = Fn.import_value(f"{msk_stack}-security-group-id")

        vpc = ec2.Vpc.from_vpc_attributes(self, "Vpc",
            vpc_id=vpc_id,
            availability_zones=[f"{self.region}a", f"{self.region}b"],
            private_subnet_ids=[
                Fn.select(0, Fn.split(",", subnet_ids_joined)),
                Fn.select(1, Fn.split(",", subnet_ids_joined)),
            ],
        )
        msk_sg = ec2.SecurityGroup.from_security_group_id(self, "MskSg", msk_sg_id)

        # Import WebSocket endpoint from CMS UI stack
        ws_endpoint = Fn.import_value(f"{cms_prefix}-ui-ws-endpoint")

        # ECS Cluster
        cluster = ecs.Cluster(self, "FanoutCluster",
            vpc=vpc,
            cluster_name=f"adp-{stage}-telemetry-fanout",
        )

        # Task definition
        task_def = ecs.FargateTaskDefinition(self, "FanoutTask",
            cpu=256,
            memory_limit_mib=512,
        )

        # IAM: Kafka read, DDB query, WebSocket push
        task_def.task_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "kafka-cluster:Connect", "kafka-cluster:DescribeGroup",
                "kafka-cluster:AlterGroup", "kafka-cluster:DescribeTopic",
                "kafka-cluster:ReadData", "kafka-cluster:DescribeClusterDynamicConfiguration",
            ],
            resources=["*"],
        ))
        task_def.task_role.add_to_policy(iam.PolicyStatement(
            actions=["dynamodb:Query", "dynamodb:DeleteItem"],
            resources=[
                f"arn:aws:dynamodb:{self.region}:{self.account}:table/{storage_prefix}-ws-connections",
                f"arn:aws:dynamodb:{self.region}:{self.account}:table/{storage_prefix}-ws-connections/index/*",
            ],
        ))
        task_def.task_role.add_to_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:*/@connections/*"],
        ))

        # Container
        task_def.add_container("FanoutContainer",
            image=ecs.ContainerImage.from_asset("source/ws-fanout"),
            environment={
                "BOOTSTRAP_SERVERS": "PLACEHOLDER",  # Set after deploy via update-service
                "WS_CONNECTIONS_TABLE": f"{storage_prefix}-ws-connections",
                "WS_API_ENDPOINT": ws_endpoint,
                "AWS_REGION": self.region,
                "GROUP_ID": f"adp-{stage}-ws-fanout-consumer",
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="ws-fanout",
                log_retention=logs.RetentionDays.ONE_WEEK,
            ),
        )

        # Fargate service — single task
        service = ecs.FargateService(self, "FanoutService",
            cluster=cluster,
            task_definition=task_def,
            desired_count=1,
            security_groups=[msk_sg],
            assign_public_ip=False,
        )

        CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        CfnOutput(self, "ServiceName", value=service.service_name)
