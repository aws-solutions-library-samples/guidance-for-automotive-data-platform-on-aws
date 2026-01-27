from aws_cdk import (
    Stack,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_secretsmanager as secretsmanager,
    RemovalPolicy,
    Duration,
    CfnOutput,
)
from constructs import Construct

class CXCRMStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Database credentials
        db_credentials = rds.DatabaseSecret(self, "CXCRMCredentials",
            username="cx_admin",
            secret_name="cx-crm-db-credentials"
        )

        # Security group
        db_sg = ec2.SecurityGroup(self, "CXCRMSecurityGroup",
            vpc=vpc,
            description="Security group for CX CRM Aurora cluster",
            allow_all_outbound=True
        )

        # Aurora PostgreSQL Serverless v2
        self.cluster = rds.DatabaseCluster(self, "CXCRMCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_15_8
            ),
            credentials=rds.Credentials.from_secret(db_credentials),
            default_database_name="cx_crm",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[db_sg],
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=8,
            writer=rds.ClusterInstance.serverless_v2("writer"),
            readers=[
                rds.ClusterInstance.serverless_v2("reader", scale_with_writer=True)
            ],
            backup=rds.BackupProps(retention=Duration.days(7)),
            removal_policy=RemovalPolicy.SNAPSHOT
        )

        # Outputs
        CfnOutput(self, "ClusterEndpoint",
            value=self.cluster.cluster_endpoint.hostname,
            description="CX CRM Aurora cluster endpoint"
        )
        
        CfnOutput(self, "ReaderEndpoint",
            value=self.cluster.cluster_read_endpoint.hostname,
            description="CX CRM Aurora reader endpoint"
        )
        
        CfnOutput(self, "SecretArn",
            value=db_credentials.secret_arn,
            description="Database credentials secret ARN"
        )
        
        CfnOutput(self, "DatabaseName",
            value="cx_crm",
            description="Database name"
        )
