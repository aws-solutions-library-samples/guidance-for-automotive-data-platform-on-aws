"""ADP Vehicle Knowledge Base stack — Bedrock KB backed by Amazon S3 Vectors.

Spec: `.kiro/specs/2026-08-03-adp-vkb-s3-vectors/spec.md`

Replaces the OpenSearch Serverless-based storage layer with Amazon S3 Vectors (GA in us-east-1).
Net delta vs. the prior stack:
  - REMOVED: 2× AOSS security policies, 1× AOSS collection, 1× AOSS access policy,
    1× index-bootstrap Lambda + role + Custom Resource provider
  - ADDED: 1× s3vectors.CfnVectorBucket, 1× s3vectors.CfnIndex
  - KEPT: KB execution IAM role (policies swapped: collection-access →
    s3vectors:{GetIndex,QueryVectors,PutVectors,GetVectors,ListVectors,DeleteVectors}),
    CfnKnowledgeBase (REPLACED — new physical ID on deploy),
    CfnDataSource (byte-identical config), cross-account resource policy helper
  - OUTPUTS: 4 existing kept + 1 new VectorBucketArn

Constructor change: `deploy_role_arn` parameter removed (was vector-store-specific).
"""
from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_bedrock as bedrock,
    aws_iam as iam,
    aws_s3 as s3,
    aws_s3vectors as s3vectors,
)
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks._naming import _stage_name, validate_stage


class VehicleKnowledgeBaseStack(Stack):
    """ADP Bedrock Knowledge Base backed by Amazon S3 Vectors.

    Swaps the AOSS vectorsearch collection + FAISS-index bootstrap Custom Resource
    for first-class AWS::S3Vectors::VectorBucket + AWS::S3Vectors::Index resources.
    StorageConfiguration.Type changes from OPENSEARCH_SERVERLESS to S3_VECTORS.
    The KB physical ID changes on this deploy (StorageConfiguration is
    Update requires: Replacement per the CFN spec).

    Spec: 2026-08-03-adp-vkb-s3-vectors
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        stage: str,
        lake_bucket_name: str,
        lake_kms_key_arn: str,
        cvx_kb_principals: list[str] | None = None,
        dms_kb_principals: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)
        validate_stage(stage)

        # ── 1. Names ──────────────────────────────────────────────────────
        kb_display_name = f"adp-{stage}-vehicle-knowledge"

        # ── 2. S3 Vectors bucket + index ───────────────────────────────────
        # VectorBucket naming: adp-{stage}-vehicle-knowledge-vectors-{region}
        # Length check: adp-staging-vehicle-knowledge-vectors-us-east-1 = 47 chars ≤ 63
        # Region-suffixed per ~/.kiro/steering/cross-region-namespace.md even though
        # S3 Vectors bucket names are regional, for future multi-region safety.
        vector_bucket = s3vectors.CfnVectorBucket(
            self, "VectorBucket",
            vector_bucket_name=f"adp-{stage}-vehicle-knowledge-vectors-{self.region}",
        )
        vector_bucket.apply_removal_policy(RemovalPolicy.DESTROY)

        # Index config per spec § Design (F):
        #   - dimension=1024: Titan-embed-v2 default; within S3 Vectors [1,4096] range
        #   - data_type="float32": sole supported value on S3 Vectors
        #   - distance_metric="cosine": AWS-blog pairing for Titan-embed-v2 (unit-length)
        #   - non_filterable_metadata_keys=["AMAZON_BEDROCK_TEXT"]: REQUIRED — without
        #     this, ingestion fails because 512-token chunks overflow the 2 KB
        #     filterable-per-vector cap when stored as filterable metadata.
        #     The Bedrock console sets this automatically; IaC must be explicit.
        vector_index = s3vectors.CfnIndex(
            self, "VectorIndex",
            index_name=f"adp-{stage}-vehicle-knowledge-index",
            vector_bucket_arn=vector_bucket.attr_vector_bucket_arn,
            dimension=1024,
            data_type="float32",
            distance_metric="cosine",
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                # BOTH auto-populated Bedrock KB metadata fields must be
                # non-filterable to fit within the 2 KB filterable-metadata
                # cap per vector:
                #   - AMAZON_BEDROCK_TEXT     : the chunk text (~512 tokens)
                #   - AMAZON_BEDROCK_METADATA : JSON blob with source S3 URI,
                #                               timestamps, sourceDocumentId
                # Missing the second key produced 23/92 ingestion failures
                # during the staging cutover (spec 2026-08-03, T4B.3 empirical
                # finding 2026-08-30); the spec's original SDK research (Q3)
                # named only AMAZON_BEDROCK_TEXT. Corrected here per the AWS
                # cost-effective-RAG blog which names both.
                non_filterable_metadata_keys=[
                    "AMAZON_BEDROCK_TEXT",
                    "AMAZON_BEDROCK_METADATA",
                ],
            ),
        )
        vector_index.add_dependency(vector_bucket)
        vector_index.apply_removal_policy(RemovalPolicy.DESTROY)

        # ── 3. KB execution role ──────────────────────────────────────────
        kb_role = iam.Role(
            self, "KBRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        )

        # NEW: s3vectors least-privilege — GetIndex (schema fetch), QueryVectors +
        # GetVectors (retrieve), PutVectors (ingestion write), ListVectors (sync),
        # DeleteVectors (re-sync deletes). Scoped to the specific bucket + /index/*.
        # Resource wildcard ${vectorBucketArn}/index/* is the least-privilege scoping
        # Bedrock KB requires per the S3 Vectors service-role docs.
        # Ref: spec 2026-08-03-adp-vkb-s3-vectors § Design "KB execution role"
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=[
                "s3vectors:GetIndex",
                "s3vectors:QueryVectors",
                "s3vectors:PutVectors",
                "s3vectors:GetVectors",
                "s3vectors:ListVectors",
                "s3vectors:DeleteVectors",
            ],
            resources=[
                vector_bucket.attr_vector_bucket_arn,
                f"{vector_bucket.attr_vector_bucket_arn}/index/*",
            ],
        ))

        # KEPT byte-identical: Bedrock embedding model invocation
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:aws:bedrock:{self.region}::foundation-model/amazon.titan-embed-text-v2:0"
            ],
        ))

        # KEPT byte-identical: lake KMS Decrypt (ingestion read path)
        # Least-privilege per the AWS Bedrock KB service-role reference
        # (https://docs.aws.amazon.com/bedrock/latest/userguide/kb-permissions.html
        # § "Permissions to decrypt your AWS KMS key for encrypted data sources
        # in Amazon S3", verified 2026-06-18): READ-ONLY ingestion needs only
        # kms:Decrypt, scoped via the kms:ViaService=s3 condition. GenerateDataKey
        # (write-path) and DescribeKey are NOT required.
        kb_role.add_to_policy(iam.PolicyStatement(
            actions=["kms:Decrypt"],
            resources=[lake_kms_key_arn],
            conditions={
                "StringEquals": {"kms:ViaService": f"s3.{self.region}.amazonaws.com"},
            },
        ))

        # KEPT byte-identical: S3 lake prefix read grant
        bucket = s3.Bucket.from_bucket_name(self, "Lake", lake_bucket_name)
        bucket.grant_read(kb_role, "knowledge/vehicle_knowledge_base/sources/*")

        # ── 4. Bedrock Knowledge Base ─────────────────────────────────────
        # StorageConfiguration.Type = "S3_VECTORS" (was "OPENSEARCH_SERVERLESS").
        # StorageConfiguration is Update requires: Replacement per CFN spec → new KB ID.
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
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    index_arn=vector_index.attr_index_arn,
                ),
            ),
        )
        kb.add_dependency(vector_index)
        kb.apply_removal_policy(RemovalPolicy.DESTROY)

        # Force KB creation to wait until the KBRole's inline DefaultPolicy
        # (populated by all `add_to_policy` + `bucket.grant_read` calls above)
        # is attached. Bedrock validates that role.arn can call
        # `s3vectors:QueryVectors` on the target index at KB-create time; if
        # the DefaultPolicy hasn't attached yet, CFN parallelizes and the KB
        # create races the policy attach, producing:
        #   "User: <role>/... is not authorized to perform: s3vectors:QueryVectors
        #    ... because no identity-based policy allows the s3vectors:QueryVectors
        #    action" (Service: S3Vectors, Status Code: 403)
        # CDK does not add this dependency automatically because the KB
        # references the role via `role_arn` (a Ref to KBRole L1 resource),
        # not to KBRoleDefaultPolicy which is a sibling L1 resource created
        # by the `add_to_policy` calls.
        _kb_role_default_policy = kb_role.node.try_find_child("DefaultPolicy")
        if _kb_role_default_policy is not None:
            kb.node.add_dependency(_kb_role_default_policy)

        # ── 5. Data source (byte-identical to prior AOSS stack) ───────────
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

        # ── 6. Cross-account resource policy (byte-identical helper) ───────
        self._attach_kb_resource_policy(
            kb.attr_knowledge_base_arn, cvx_kb_principals, dms_kb_principals
        )

        # ── 7. Outputs ────────────────────────────────────────────────────
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
        # NEW: expose vector bucket ARN for operator debugging + future prod dual-KB spec
        CfnOutput(self, "VectorBucketArn",
                  value=vector_bucket.attr_vector_bucket_arn,
                  export_name=_stage_name(stage, "vehicle-knowledge-vector-bucket-arn"))

        # ── cdk-nag suppressions ──────────────────────────────────────────
        # KEPT: S3 read prefix wildcard on kb_role (required by Bedrock KB ingestion)
        # Reason updated to reference spec 2026-08-03-adp-vkb-s3-vectors.
        NagSuppressions.add_resource_suppressions(
            kb_role,
            [
                {"id": "AwsSolutions-IAM5",
                 "reason": (
                     "S3 read scoped to prefix knowledge/vehicle_knowledge_base/sources/*; "
                     "required by Bedrock KB ingestion. "
                     "Ref: spec 2026-08-03-adp-vkb-s3-vectors § Design 'KB execution role'."
                 )},
                {"id": "AwsSolutions-IAM5",
                 "reason": (
                     "s3vectors:* actions scoped to the specific vector bucket ARN + "
                     "${vectorBucketArn}/index/* — least-privilege per the S3 Vectors "
                     "service-role docs. The /index/* wildcard is the minimum required "
                     "scope for Bedrock KB to perform ingestion PutVectors + retrieve "
                     "QueryVectors across index partitions. "
                     "Ref: spec 2026-08-03-adp-vkb-s3-vectors § Design 'KB execution role'."
                 )},
            ],
            apply_to_children=True,
        )

    def _attach_kb_resource_policy(
        self,
        kb_arn: str,
        cvx_principals: list[str] | None,
        dms_principals: list[str] | None = None,
    ) -> None:
        """Attach a single-Statement Bedrock KB resource policy covering CVX + DMS.

        Extends the port from closed spec ``2026-06-09-adp-kb-cross-account-grants``
        (which handled the CVX list only) to also cover the DMS-side principal(s)
        per spec ``2026-08-26-adp-dealer-domain`` T3.4 / Group 6. Both lists are
        concatenated into a single ``Principal.AWS`` array in one ``Statement``
        rather than two separate statements — one combined statement keeps the
        policy under ``AWS::Bedrock::CfnResourcePolicy``'s size limits and
        matches the shape verified in G1.T1 finding 2.

        Backward-compatible: with both lists ``None``/empty, no policy resource
        is attached (matches the pre-Group-6 zero-principal behaviour).
        """
        combined: list[str] = []
        if cvx_principals:
            combined.extend(cvx_principals)
        if dms_principals:
            combined.extend(dms_principals)
        if not combined:
            return
        bedrock.CfnResourcePolicy(
            self, "KBCrossAccountPolicy",
            resource_arn=kb_arn,
            policy_document={
                "Version": "2012-10-17",
                "Statement": [{
                    "Effect": "Allow",
                    "Principal": {"AWS": combined},
                    "Action": [
                        "bedrock-agent-runtime:Retrieve",
                        "bedrock-agent-runtime:RetrieveAndGenerate",
                    ],
                    "Resource": kb_arn,
                }],
            },
        )
