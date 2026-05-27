"""
Bedrock Knowledge Base stack — S3 bucket + 4 data sources + KB resource.

Exports KB_ID for consumers (CVX agent, CMS generate_kb_data.py).
"""

import os
import json
from aws_cdk import (
    Stack, RemovalPolicy, CfnOutput,
    aws_s3 as s3,
    aws_iam as iam,
    aws_bedrock as bedrock,
)
from constructs import Construct


DATA_SOURCE_PREFIXES = [
    ("technical-reference", "DTC interpretation guides and diagnostic procedures"),
    ("tsb-recalls", "Technical Service Bulletins and NHTSA recall notices"),
    ("owner-manuals", "Owner manual excerpts and maintenance schedules"),
    ("service-policy", "Warranty coverage, SLA definitions, escalation policies"),
]


class KnowledgeBaseStack(Stack):
    def __init__(self, scope: Construct, id: str, *, stage: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        prefix = f"adp-{stage}"

        # ─── S3 Bucket for KB documents ───────────────────────────────────
        bucket = s3.Bucket(self, "KBBucket",
            bucket_name=f"{prefix}-vehicle-knowledge-base",
            removal_policy=RemovalPolicy.RETAIN,
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
        )

        # ─── KB Execution Role ────────────────────────────────────────────
        kb_role = iam.Role(self, "KBRole",
            role_name=f"{prefix}-kb-execution-role",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        )
        bucket.grant_read(kb_role)
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"],
        ))
        # AOSS permissions for the managed vector store
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"],
            resources=["*"],  # Scoped by Bedrock's managed collection
        ))

        # ─── Bedrock Knowledge Base ───────────────────────────────────────
        kb = bedrock.CfnKnowledgeBase(self, "VehicleKB",
            name=f"{prefix}-vehicle-knowledge",
            description="Automotive technical reference — DTCs, TSBs, recalls, maintenance, warranty",
            role_arn=kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0",
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="OPENSEARCH_SERVERLESS",
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn="PLACEHOLDER",  # Bedrock creates managed collection
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        metadata_field="metadata",
                        text_field="text",
                        vector_field="vector",
                    ),
                    vector_index_name=f"{prefix}-kb-index",
                ),
            ),
        )

        # ─── Data Sources (one per content category) ──────────────────────
        for ds_prefix, description in DATA_SOURCE_PREFIXES:
            bedrock.CfnDataSource(self, f"DS-{ds_prefix}",
                knowledge_base_id=kb.attr_knowledge_base_id,
                name=ds_prefix,
                description=description,
                data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                    type="S3",
                    s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                        bucket_arn=bucket.bucket_arn,
                        inclusion_prefixes=[f"{ds_prefix}/"],
                    ),
                ),
            )

        # ─── Outputs ──────────────────────────────────────────────────────
        CfnOutput(self, "KnowledgeBaseId", value=kb.attr_knowledge_base_id,
                  description="Set as BEDROCK_KB_ID in CVX .env")
        CfnOutput(self, "KnowledgeBaseBucket", value=bucket.bucket_name,
                  description="Upload KB documents here")
        CfnOutput(self, "KnowledgeBaseRoleArn", value=kb_role.role_arn)
