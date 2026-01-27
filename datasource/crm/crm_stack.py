from aws_cdk import (
    Stack,
    aws_rds as rds,
    aws_ec2 as ec2,
    aws_secretsmanager as secretsmanager,
    RemovalPolicy,
    CfnOutput,
)
from constructs import Construct

class AutomotiveCRMStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, vpc: ec2.Vpc, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Database credentials
        db_credentials = rds.DatabaseSecret(self, "CRMDBCredentials",
            username="crm_admin",
            secret_name="automotive-crm-db-credentials"
        )

        # Security group for Aurora
        db_security_group = ec2.SecurityGroup(self, "CRMDBSecurityGroup",
            vpc=vpc,
            description="Security group for Automotive CRM Aurora cluster",
            allow_all_outbound=True
        )

        # Aurora PostgreSQL Serverless v2 cluster
        self.cluster = rds.DatabaseCluster(self, "CRMCluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_15_4
            ),
            credentials=rds.Credentials.from_secret(db_credentials),
            default_database_name="automotive_crm",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[db_security_group],
            serverless_v2_min_capacity=0.5,
            serverless_v2_max_capacity=4,
            writer=rds.ClusterInstance.serverless_v2("writer"),
            readers=[
                rds.ClusterInstance.serverless_v2("reader", scale_with_writer=True)
            ],
            backup=rds.BackupProps(
                retention=Duration.days(7)
            ),
            removal_policy=RemovalPolicy.SNAPSHOT
        )

        # Outputs
        CfnOutput(self, "ClusterEndpoint",
            value=self.cluster.cluster_endpoint.hostname,
            description="Aurora cluster endpoint"
        )
        
        CfnOutput(self, "ReaderEndpoint",
            value=self.cluster.cluster_read_endpoint.hostname,
            description="Aurora reader endpoint"
        )
        
        CfnOutput(self, "SecretArn",
            value=db_credentials.secret_arn,
            description="Database credentials secret ARN"
        )
