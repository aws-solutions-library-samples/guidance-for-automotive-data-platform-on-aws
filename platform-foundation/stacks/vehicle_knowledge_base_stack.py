"""ADP Vehicle Knowledge Base stack — Bedrock KB + AOSS vector store.

Spec: `.kiro/specs/2026-06-16-adp-vehicle-knowledge-base/spec.md`

Creates the full IaC for the ADP staging vehicle knowledge base:
  - 2× AOSS security policies (encryption + network)
  - 1× AOSS vectorsearch collection (STANDBY_REPLICAS=DISABLED)
  - 1× AOSS data access policy (KB role + bootstrap Lambda + deploy role)
  - 1× Custom Resource (index bootstrap Lambda + cr.Provider)
  - 1× KB execution IAM role
  - 1× CfnKnowledgeBase (collection_arn = collection.attr_arn — no PLACEHOLDER)
  - 1× CfnDataSource
  - 0-1× CfnResourcePolicy (cross-account, when cvx_kb_principals provided)
  - 4× CfnOutput (KB id, KB ARN, bucket ARN, sources prefix)
"""
from __future__ import annotations

import json

from aws_cdk import (
    BundlingOptions,
    CfnOutput,
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_opensearchserverless as opensearchserverless,
    aws_s3 as s3,
    custom_resources as cr,
)
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks._naming import _stage_name, validate_stage


class VehicleKnowledgeBaseStack(Stack):
    """ADP Bedrock Knowledge Base (Group 5 of foundation rollout).

    Fixes the ``collection_arn="PLACEHOLDER"`` bug in the legacy
    ``guidance-for-vehicle-knowledge-base/`` stack by authoring the full
    AOSS collection + vector index IaC co-located with the foundation stacks.
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        stage: str,
        lake_bucket_name: str,
        lake_kms_key_arn: str,
        deploy_role_arn: str,
        cvx_kb_principals: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)
        validate_stage(stage)

        # ── 1. Names ──────────────────────────────────────────────────────
        collection_name = f"adp-{stage}-vehicle-knowledge"      # 29 / 26 chars ≤ 32
        index_name      = f"adp-{stage}-vehicle-knowledge-index"
        kb_display_name = f"adp-{stage}-vehicle-knowledge"

        enc_policy_name = f"adp-{stage}-vkb-encryption"
        net_policy_name = f"adp-{stage}-vkb-network"
        acc_policy_name = f"adp-{stage}-vkb-access"

        # ── 2. AOSS encryption policy ──────────────────────────────────────
        enc_policy = opensearchserverless.CfnSecurityPolicy(
            self, "EncPolicy",
            name=enc_policy_name,
            type="encryption",
            policy=json.dumps({
                "Rules": [{"ResourceType": "collection",
                            "Resource": [f"collection/{collection_name}"]}],
                "AWSOwnedKey": True,
            }),
        )
        enc_policy.apply_removal_policy(RemovalPolicy.DESTROY)

        # ── 3. AOSS network policy (public v1; Q3 LOCKED) ─────────────────
        net_policy = opensearchserverless.CfnSecurityPolicy(
            self, "NetPolicy",
            name=net_policy_name,
            type="network",
            policy=json.dumps([{
                "Rules": [
                    {"ResourceType": "collection",
                     "Resource": [f"collection/{collection_name}"]},
                    {"ResourceType": "dashboard",
                     "Resource": [f"collection/{collection_name}"]},
                ],
                "AllowFromPublic": True,
            }]),
        )
        net_policy.apply_removal_policy(RemovalPolicy.DESTROY)

        # ── 4. AOSS collection ────────────────────────────────────────────
        collection = opensearchserverless.CfnCollection(
            self, "Collection",
            name=collection_name,
            type="VECTORSEARCH",
            standby_replicas="DISABLED",
        )
        collection.add_dependency(enc_policy)
        collection.add_dependency(net_policy)
        collection.apply_removal_policy(RemovalPolicy.DESTROY)

        # ── 7. KB execution role (declared before access policy for arn ref) ──
        kb_role = iam.Role(
            self, "KBRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        )
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"],
            resources=[collection.attr_arn],
        ))
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"
            ],
        ))
        # spike-output #6: lake bucket is CMK-encrypted, so the KB role needs an
        # explicit KMS grant to decrypt source objects during ingestion.
        # Least-privilege per the AWS Bedrock KB service-role reference
        # (https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html
        # § "Permissions to decrypt your AWS KMS key for encrypted data sources
        # in Amazon S3", verified 2026-06-18): READ-ONLY ingestion needs only
        # kms:Decrypt, scoped via the kms:ViaService=s3 condition. GenerateDataKey
        # (write-path) and DescribeKey are NOT required — dropped per
        # security-review cycle-2 suggestion. Mirrors CVX's AdpLakeKmsDecrypt
        # statement (vsa-core-stack.ts).
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["kms:Decrypt"],
            resources=[lake_kms_key_arn],
            conditions={
                "StringEquals": {"kms:ViaService": f"s3.{self.region}.amazonaws.com"},
            },
        ))
        bucket = s3.Bucket.from_bucket_name(self, "Lake", lake_bucket_name)
        bucket.grant_read(kb_role, "knowledge/vehicle_knowledge_base/sources/*")

        # ── 6. Index-bootstrap Lambda role ───────────────────────────────
        bootstrap_lambda_role = iam.Role(
            self, "BootstrapLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        bootstrap_lambda_role.add_to_policy(iam.PolicyStatement(
            actions=["aoss:APIAccessAll"],
            resources=[collection.attr_arn],
        ))

        # ── 5. AOSS data access policy (roles known now) ─────────────────
        access_policy = opensearchserverless.CfnAccessPolicy(
            self, "AccessPolicy",
            name=acc_policy_name,
            type="data",
            policy=json.dumps([{
                "Rules": [
                    {
                        "ResourceType": "index",
                        "Resource": [f"index/{collection_name}/*"],
                        "Permission": ["aoss:*"],
                    },
                    {
                        "ResourceType": "collection",
                        "Resource": [f"collection/{collection_name}"],
                        "Permission": ["aoss:*"],
                    },
                ],
                "Principal": [
                    kb_role.role_arn,
                    bootstrap_lambda_role.role_arn,
                    deploy_role_arn,
                ],
            }]),
        )
        access_policy.apply_removal_policy(RemovalPolicy.DESTROY)

        # ── 6 (cont). Bootstrap Lambda + Provider + Custom Resource ───────
        bootstrap_fn = lambda_.Function(
            self, "IndexBootstrapFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_asset(
                "lambda/aoss_index_bootstrap",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            role=bootstrap_lambda_role,
            timeout=Duration.minutes(7),
            environment={
                "COLLECTION_ENDPOINT": collection.attr_collection_endpoint,
                "INDEX_NAME": index_name,
                "INDEX_DIMENSIONS": "1024",
                "INDEX_SPACE_TYPE": "l2",
                "INDEX_ENGINE": "faiss",
            },
        )

        provider = cr.Provider(
            self, "IndexBootstrapProvider",
            on_event_handler=bootstrap_fn,
        )

        index_cr = CustomResource(
            self, "IndexBootstrap",
            service_token=provider.service_token,
            properties={"IndexName": index_name},
        )
        index_cr.node.add_dependency(collection)
        index_cr.node.add_dependency(access_policy)

        # ── 8. Bedrock Knowledge Base ─────────────────────────────────────
        kb = bedrock.CfnKnowledgeBase(
            self, "KB",
            name=kb_display_name,
            role_arn=kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=(
                        f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"
                    ),
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="OPENSEARCH_SERVERLESS",
                opensearch_serverless_configuration=bedrock.CfnKnowledgeBase.OpenSearchServerlessConfigurationProperty(
                    collection_arn=collection.attr_arn,   # NEVER "PLACEHOLDER"
                    vector_index_name=index_name,
                    field_mapping=bedrock.CfnKnowledgeBase.OpenSearchServerlessFieldMappingProperty(
                        vector_field="vector",
                        text_field="text",
                        metadata_field="metadata",
                    ),
                ),
            ),
        )
        kb.add_dependency(index_cr.node.default_child)  # type: ignore[arg-type]
        kb.apply_removal_policy(RemovalPolicy.DESTROY)

        # ── 9. Data source ────────────────────────────────────────────────
        data_source = bedrock.CfnDataSource(
            self, "DataSource",
            knowledge_base_id=kb.attr_knowledge_base_id,
            name="vehicle-knowledge-base-sources",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=f"arn:aws:s3:::{lake_bucket_name}",
                    inclusion_prefixes=["knowledge/vehicle_knowledge_base/sources/"],
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=512,
                        overlap_percentage=10,
                    ),
                ),
            ),
        )
        data_source.add_dependency(kb)

        # ── 10. Cross-account resource policy (verbatim port) ─────────────
        self._attach_kb_resource_policy(kb.attr_knowledge_base_arn, cvx_kb_principals)

        # ── 11. Outputs ───────────────────────────────────────────────────
        CfnOutput(self, "KnowledgeBaseId",
                  value=kb.attr_knowledge_base_id,
                  export_name=_stage_name(stage, "vehicle-knowledge-id"))
        CfnOutput(self, "KnowledgeBaseArn",
                  value=kb.attr_knowledge_base_arn,
                  export_name=_stage_name(stage, "vehicle-knowledge-arn"))
        CfnOutput(self, "KnowledgeBaseBucketArn",
                  value=f"arn:aws:s3:::{lake_bucket_name}",
                  export_name=_stage_name(stage, "vehicle-knowledge-bucket-arn"))
        CfnOutput(self, "KnowledgeBaseSourcesPrefix",
                  value="knowledge/vehicle_knowledge_base/sources/",
                  export_name=_stage_name(stage, "vehicle-knowledge-sources-prefix"))

        # ── cdk-nag suppressions ──────────────────────────────────────────
        NagSuppressions.add_resource_suppressions(
            access_policy,
            [{"id": "AwsSolutions-IAM5",
              "reason": "AOSS APIAccessAll requires index-level wildcard; access is principal-gated."}],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            bootstrap_fn,
            [{"id": "AwsSolutions-L1",
              "reason": "Python 3.12 is the project-standard runtime per spec constraints; runtime bump is a separate dependency upgrade."}],
        )
        NagSuppressions.add_resource_suppressions(
            bootstrap_lambda_role,
            [
                {"id": "AwsSolutions-IAM4",
                 "reason": "AWSLambdaBasicExecutionRole managed policy scopes Logs to the function's own log group."},
                {"id": "AwsSolutions-IAM5",
                 "reason": "AWSLambdaBasicExecutionRole CW Logs * is the managed-policy template; function-scoped at deploy time."},
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            kb_role,
            [{"id": "AwsSolutions-IAM5",
              "reason": "S3 read scoped to prefix knowledge/vehicle_knowledge_base/sources/*; required by Bedrock KB ingestion."}],
            apply_to_children=True,
        )
        # cr.Provider generates a framework-onEvent Lambda with its own service role.
        # Suppress L1 (Python 3.12 is not latest per nag) and IAM findings on that
        # framework role — it is CDK-managed and scoped to this provider only.
        NagSuppressions.add_resource_suppressions(
            provider,
            [
                {"id": "AwsSolutions-L1",
                 "reason": "Python 3.12 is the project-standard runtime per spec constraints; updating to latest is a separate dependency bump."},
                {"id": "AwsSolutions-IAM4",
                 "reason": "AWSLambdaBasicExecutionRole on the cr.Provider framework Lambda is CDK-managed and scoped to this function's log group."},
                {"id": "AwsSolutions-IAM5",
                 "reason": "cr.Provider framework Lambda DefaultPolicy wildcard is CDK-generated and scoped to the bootstrap Lambda ARN."},
            ],
            apply_to_children=True,
        )

    def _attach_kb_resource_policy(
        self, kb_arn: str, principals: list[str] | None
    ) -> None:
        """Port verbatim from closed 2026-06-09-adp-kb-cross-account-grants spec."""
        if not principals:
            return
        bedrock.CfnResourcePolicy(
            self, "KBCrossAccountPolicy",
            resource_arn=kb_arn,
            policy_document={
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"AWS": principals},
                    "Action": [
                        "bedrock-agent-runtime:Retrieve",
                        "bedrock-agent-runtime:RetrieveAndGenerate",
                    ],
                    "Resource": kb_arn,
                }],
            },
        )
