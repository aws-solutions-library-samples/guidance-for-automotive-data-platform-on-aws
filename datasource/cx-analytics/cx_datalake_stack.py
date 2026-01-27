from aws_cdk import (
    Stack,
    aws_s3 as s3,
    aws_glue as glue,
    RemovalPolicy,
    CfnOutput,
)
from constructs import Construct

class CXDataLakeStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # S3 Data Lake Bucket
        self.data_lake_bucket = s3.Bucket(self, "CXDataLake",
            bucket_name=f"automotive-cx-data-lake-{self.account}",
            versioned=False,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN
        )

        # Glue Database
        self.glue_database = glue.CfnDatabase(self, "CXGlueDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name="cx_analytics",
                description="Customer Experience Analytics Database"
            )
        )

        # Glue Tables
        self._create_glue_tables()

        # Outputs
        CfnOutput(self, "DataLakeBucket",
            value=self.data_lake_bucket.bucket_name,
            description="CX Data Lake S3 bucket"
        )
        
        CfnOutput(self, "GlueDatabase",
            value=self.glue_database.database_input.name,
            description="Glue database name"
        )

    def _create_glue_tables(self):
        # Customer 360 Table
        glue.CfnTable(self, "Customer360Table",
            catalog_id=self.account,
            database_name=self.glue_database.database_input.name,
            table_input=glue.CfnTable.TableInputProperty(
                name="customer_360",
                storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                    columns=[
                        glue.CfnTable.ColumnProperty(name="customer_id", type="string"),
                        glue.CfnTable.ColumnProperty(name="first_name", type="string"),
                        glue.CfnTable.ColumnProperty(name="last_name", type="string"),
                        glue.CfnTable.ColumnProperty(name="email", type="string"),
                        glue.CfnTable.ColumnProperty(name="customer_since_date", type="date"),
                        glue.CfnTable.ColumnProperty(name="lifecycle_stage", type="string"),
                        glue.CfnTable.ColumnProperty(name="current_health_score", type="int"),
                        glue.CfnTable.ColumnProperty(name="lifetime_value", type="decimal(15,2)"),
                        glue.CfnTable.ColumnProperty(name="snapshot_date", type="date"),
                    ],
                    location=f"s3://{self.data_lake_bucket.bucket_name}/processed/customer-360/",
                    input_format="org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                    output_format="org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                    serde_info=glue.CfnTable.SerdeInfoProperty(
                        serialization_library="org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
                    )
                ),
                partition_keys=[
                    glue.CfnTable.ColumnProperty(name="year", type="string"),
                    glue.CfnTable.ColumnProperty(name="month", type="string"),
                    glue.CfnTable.ColumnProperty(name="day", type="string"),
                ]
            )
        )

        # Health Metrics Table
        glue.CfnTable(self, "HealthMetricsTable",
            catalog_id=self.account,
            database_name=self.glue_database.database_input.name,
            table_input=glue.CfnTable.TableInputProperty(
                name="customer_health_metrics",
                storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                    columns=[
                        glue.CfnTable.ColumnProperty(name="customer_id", type="string"),
                        glue.CfnTable.ColumnProperty(name="metric_date", type="date"),
                        glue.CfnTable.ColumnProperty(name="health_score", type="int"),
                        glue.CfnTable.ColumnProperty(name="churn_probability", type="decimal(5,2)"),
                        glue.CfnTable.ColumnProperty(name="recency_score", type="int"),
                        glue.CfnTable.ColumnProperty(name="satisfaction_score", type="int"),
                        glue.CfnTable.ColumnProperty(name="support_score", type="int"),
                        glue.CfnTable.ColumnProperty(name="engagement_score", type="int"),
                        glue.CfnTable.ColumnProperty(name="payment_score", type="int"),
                    ],
                    location=f"s3://{self.data_lake_bucket.bucket_name}/processed/health-metrics/",
                    input_format="org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                    output_format="org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                    serde_info=glue.CfnTable.SerdeInfoProperty(
                        serialization_library="org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
                    )
                ),
                partition_keys=[
                    glue.CfnTable.ColumnProperty(name="year", type="string"),
                    glue.CfnTable.ColumnProperty(name="month", type="string"),
                ]
            )
        )
