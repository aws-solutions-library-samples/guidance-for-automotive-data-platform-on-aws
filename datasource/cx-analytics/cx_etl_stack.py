from aws_cdk import (
    Stack,
    aws_glue as glue,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    RemovalPolicy,
)
from constructs import Construct
import os

class CXETLStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, data_lake_bucket: s3.IBucket, db_secret_arn: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Glue IAM Role
        glue_role = iam.Role(
            self, "GlueETLRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole")
            ]
        )
        
        data_lake_bucket.grant_read_write(glue_role)
        
        # Grant access to secrets
        glue_role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=[db_secret_arn]
        ))
        
        # VPC access for Glue
        glue_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "ec2:CreateNetworkInterface",
                "ec2:DescribeNetworkInterfaces",
                "ec2:DeleteNetworkInterface",
                "ec2:DescribeVpcEndpoints",
                "ec2:DescribeSubnets",
                "ec2:DescribeVpcAttribute",
                "ec2:DescribeRouteTables",
                "ec2:DescribeSecurityGroups"
            ],
            resources=["*"]
        ))

        # Create scripts directory using tempfile for secure temp directory
        import tempfile
        scripts_dir = tempfile.mkdtemp(prefix="cx_glue_scripts_")  # nosec B108

        # 1. Aurora to S3 Export Script
        export_script = """import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
import boto3
import json

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'SECRET_ARN', 'S3_BUCKET'])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Get DB credentials
secrets = boto3.client('secretsmanager')
secret = json.loads(secrets.get_secret_value(SecretId=args['SECRET_ARN'])['SecretString'])

jdbc_url = f"jdbc:postgresql://{secret['host']}:{secret['port']}/{secret['dbname']}"
connection_properties = {
    "user": secret['username'],
    "password": secret['password'],
    "driver": "org.postgresql.Driver"
}

tables = ['users', 'dealers', 'accounts', 'contacts', 'customer_vehicles', 
          'cases', 'service_appointments', 'surveys', 'opportunities']

for table in tables:
    print(f"Exporting {table}...")
    df = spark.read.jdbc(url=jdbc_url, table=table, properties=connection_properties)
    output_path = f"s3://{args['S3_BUCKET']}/raw/crm/{table}/"
    df.write.mode("overwrite").parquet(output_path)
    print(f"Exported {table}: {df.count()} records")

job.commit()
"""

        with open(f"{scripts_dir}/aurora_export.py", "w") as f:
            f.write(export_script)

        # 2. Customer 360 Transform Script
        customer_360_script = """import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql import functions as F

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'S3_BUCKET'])
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

bucket = args['S3_BUCKET']

# Load data
users = spark.read.parquet(f"s3://{bucket}/raw/crm/users/")
vehicles = spark.read.parquet(f"s3://{bucket}/raw/crm/customer_vehicles/")
cases = spark.read.parquet(f"s3://{bucket}/raw/crm/cases/")
appointments = spark.read.parquet(f"s3://{bucket}/raw/crm/service_appointments/")
surveys = spark.read.parquet(f"s3://{bucket}/raw/crm/surveys/")
opportunities = spark.read.parquet(f"s3://{bucket}/raw/crm/opportunities/")
contacts = spark.read.parquet(f"s3://{bucket}/raw/crm/contacts/")

# Vehicle metrics
vehicle_metrics = vehicles.groupBy("user_id").agg(
    F.count("*").alias("vehicle_count"),
    F.max("purchase_date").alias("last_purchase_date"),
    F.min("purchase_date").alias("first_purchase_date")
)

# Case metrics
case_metrics = cases.groupBy("user_id").agg(
    F.count("*").alias("total_cases"),
    F.sum(F.when(F.col("status").isin(["Open", "In Progress"]), 1).otherwise(0)).alias("open_cases"),
    F.max("created_date").alias("last_case_date"),
    F.sum(F.when(F.col("priority") == "Critical", 1).otherwise(0)).alias("critical_cases")
)

# Service metrics
service_metrics = appointments.join(vehicles, appointments.vehicle_id == vehicles.id).groupBy("user_id").agg(
    F.count("*").alias("total_appointments"),
    F.sum("cost").alias("total_service_spend"),
    F.avg("cost").alias("avg_service_cost"),
    F.max("appointment_date").alias("last_service_date"),
    F.sum(F.when(F.col("status") == "Completed", 1).otherwise(0)).alias("completed_appointments")
)

# Survey metrics
survey_metrics = surveys.groupBy("user_id").agg(
    F.avg("score").alias("avg_satisfaction_score"),
    F.count("*").alias("survey_count"),
    F.max("survey_date").alias("last_survey_date"),
    F.min("score").alias("min_satisfaction_score")
)

# Opportunity metrics
opp_metrics = contacts.join(opportunities, contacts.account_id == opportunities.account_id).groupBy("user_id").agg(
    F.sum(F.when(F.col("stage") == "Closed Won", F.col("amount")).otherwise(0)).alias("total_revenue"),
    F.count("*").alias("opportunity_count"),
    F.sum(F.when(F.col("stage").isin(["Prospecting", "Qualification", "Proposal", "Negotiation"]), 1).otherwise(0)).alias("active_opportunities")
)

# Build Customer 360
customer_360 = users.alias("u") \\
    .join(vehicle_metrics, users.id == vehicle_metrics.user_id, "left") \\
    .join(case_metrics, users.id == case_metrics.user_id, "left") \\
    .join(service_metrics, users.id == service_metrics.user_id, "left") \\
    .join(survey_metrics, users.id == survey_metrics.user_id, "left") \\
    .join(opp_metrics, users.id == opp_metrics.user_id, "left") \\
    .select(
        F.col("u.id").alias("customer_id"),
        F.col("u.email"),
        F.col("u.first_name"),
        F.col("u.last_name"),
        F.col("u.phone"),
        F.col("u.created_date").alias("customer_since"),
        F.coalesce("vehicle_count", F.lit(0)).alias("vehicle_count"),
        "last_purchase_date",
        "first_purchase_date",
        F.coalesce("total_cases", F.lit(0)).alias("total_cases"),
        F.coalesce("open_cases", F.lit(0)).alias("open_cases"),
        F.coalesce("critical_cases", F.lit(0)).alias("critical_cases"),
        "last_case_date",
        F.coalesce("total_appointments", F.lit(0)).alias("total_appointments"),
        F.coalesce("completed_appointments", F.lit(0)).alias("completed_appointments"),
        F.coalesce("total_service_spend", F.lit(0)).alias("total_service_spend"),
        F.coalesce("avg_service_cost", F.lit(0)).alias("avg_service_cost"),
        "last_service_date",
        F.coalesce("avg_satisfaction_score", F.lit(0)).alias("avg_satisfaction_score"),
        F.coalesce("min_satisfaction_score", F.lit(0)).alias("min_satisfaction_score"),
        F.coalesce("survey_count", F.lit(0)).alias("survey_count"),
        "last_survey_date",
        F.coalesce("total_revenue", F.lit(0)).alias("total_revenue"),
        F.coalesce("opportunity_count", F.lit(0)).alias("opportunity_count"),
        F.coalesce("active_opportunities", F.lit(0)).alias("active_opportunities")
    )

# Write Customer 360
output_path = f"s3://{bucket}/processed/customer_360/"
customer_360.write.mode("overwrite").parquet(output_path)
print(f"Customer 360 written: {customer_360.count()} customers")

job.commit()
"""

        with open(f"{scripts_dir}/customer_360.py", "w") as f:
            f.write(customer_360_script)

        # Deploy scripts to S3
        s3deploy.BucketDeployment(
            self, "DeployGlueScripts",
            sources=[s3deploy.Source.asset(scripts_dir)],
            destination_bucket=data_lake_bucket,
            destination_key_prefix="scripts",
            prune=False
        )

        # 1. Aurora to S3 Export Job
        glue.CfnJob(
            self, "AuroraToS3ExportJob",
            name="cx-aurora-to-s3-export",
            role=glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"s3://{data_lake_bucket.bucket_name}/scripts/aurora_export.py"
            ),
            default_arguments={
                "--SECRET_ARN": db_secret_arn,
                "--S3_BUCKET": data_lake_bucket.bucket_name,
                "--enable-glue-datacatalog": "true",
                "--extra-jars": f"s3://aws-glue-assets-{Stack.of(self).account}-{Stack.of(self).region}/postgresql-42.7.3.jar"
            },
            glue_version="4.0",
            max_retries=0,
            timeout=60,
            number_of_workers=5,
            worker_type="G.1X"
        )

        # 2. Customer 360 Transform Job
        glue.CfnJob(
            self, "Customer360Job",
            name="cx-customer-360-transform",
            role=glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"s3://{data_lake_bucket.bucket_name}/scripts/customer_360.py"
            ),
            default_arguments={
                "--S3_BUCKET": data_lake_bucket.bucket_name,
                "--enable-glue-datacatalog": "true"
            },
            glue_version="4.0",
            max_retries=0,
            timeout=60,
            number_of_workers=5,
            worker_type="G.1X"
        )
