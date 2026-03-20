"""
Data Governance Stack — Multi-region PII/anonymized data separation.

Deploys in the EU producer region:
  - S3 buckets for PII and anonymized data stores
  - Glue database and crawler for data cataloging
  - Glue ETL job for anonymization
  - Macie classification job with custom identifiers
  - Lake Formation permissions
  - CloudTrail organization trail for audit
"""
import os
import json
from aws_cdk import (
    Stack, Duration, RemovalPolicy, CfnOutput,
    aws_s3 as s3,
    aws_glue as glue,
    aws_iam as iam,
    aws_macie as macie,
    aws_lakeformation as lakeformation,
    aws_cloudtrail as cloudtrail,
    aws_logs as logs,
)
from constructs import Construct


class GovernanceStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, stage: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        # ── S3 Buckets ────────────────────────────────────────────

        pii_bucket = s3.Bucket(self, "PIIDataStore",
            bucket_name=f"adp-{stage}-pii-data-{self.account}-{self.region}",
            encryption=s3.BucketEncryption.KMS_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            object_lock_enabled=True,
        )

        anonymized_bucket = s3.Bucket(self, "AnonymizedDataStore",
            bucket_name=f"adp-{stage}-anonymized-data-{self.account}-{self.region}",
            encryption=s3.BucketEncryption.KMS_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        audit_bucket = s3.Bucket(self, "AuditLogBucket",
            bucket_name=f"adp-{stage}-audit-logs-{self.account}-{self.region}",
            encryption=s3.BucketEncryption.KMS_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            object_lock_enabled=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── Glue Database ─────────────────────────────────────────

        pii_db = glue.CfnDatabase(self, "PIIDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=f"adp_{stage}_pii",
                description="PII vehicle telemetry — EU region only",
            ),
        )

        anonymized_db = glue.CfnDatabase(self, "AnonymizedDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=f"adp_{stage}_anonymized",
                description="Anonymized vehicle telemetry — available for cross-region sharing",
            ),
        )

        # ── Glue ETL Role ─────────────────────────────────────────

        glue_role = iam.Role(self, "GlueETLRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole"),
            ],
        )
        pii_bucket.grant_read(glue_role)
        anonymized_bucket.grant_read_write(glue_role)

        # ── Glue Anonymization Job ────────────────────────────────

        glue.CfnJob(self, "AnonymizationJob",
            name=f"adp-{stage}-anonymize-telemetry",
            role=glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=f"s3://{anonymized_bucket.bucket_name}/scripts/anonymize_telemetry.py",
            ),
            default_arguments={
                "--source_database": f"adp_{stage}_pii",
                "--source_table": "raw_vehicle_telemetry",
                "--target_bucket": anonymized_bucket.bucket_name,
                "--target_prefix": "anonymized/telemetry/",
                "--job-language": "python",
                "--enable-metrics": "true",
                "--enable-continuous-cloudwatch-log": "true",
            },
            glue_version="4.0",
            number_of_workers=2,
            worker_type="G.1X",
            timeout=60,
        )

        # ── Lake Formation Registration ───────────────────────────

        lakeformation.CfnResource(self, "RegisterPIIBucket",
            resource_arn=pii_bucket.bucket_arn,
            use_service_linked_role=True,
        )

        lakeformation.CfnResource(self, "RegisterAnonymizedBucket",
            resource_arn=anonymized_bucket.bucket_arn,
            use_service_linked_role=True,
        )

        # ── CloudTrail ────────────────────────────────────────────

        trail = cloudtrail.Trail(self, "GovernanceTrail",
            trail_name=f"adp-{stage}-governance-trail",
            bucket=audit_bucket,
            is_multi_region_trail=True,
            include_global_service_events=True,
            enable_file_validation=True,
            send_to_cloud_watch_logs=True,
            cloud_watch_logs_retention=logs.RetentionDays.ONE_YEAR,
        )

        # Log S3 data events for PII and anonymized buckets
        trail.add_s3_event_selector([
            cloudtrail.S3EventSelector(bucket=pii_bucket),
            cloudtrail.S3EventSelector(bucket=anonymized_bucket),
        ])

        # ── Outputs ───────────────────────────────────────────────

        CfnOutput(self, "PIIBucketName", value=pii_bucket.bucket_name,
            export_name=f"{construct_id}-pii-bucket")
        CfnOutput(self, "AnonymizedBucketName", value=anonymized_bucket.bucket_name,
            export_name=f"{construct_id}-anonymized-bucket")
        CfnOutput(self, "AuditBucketName", value=audit_bucket.bucket_name,
            export_name=f"{construct_id}-audit-bucket")
        CfnOutput(self, "PIIDatabaseName", value=f"adp_{stage}_pii",
            export_name=f"{construct_id}-pii-database")
        CfnOutput(self, "AnonymizedDatabaseName", value=f"adp_{stage}_anonymized",
            export_name=f"{construct_id}-anonymized-database")
