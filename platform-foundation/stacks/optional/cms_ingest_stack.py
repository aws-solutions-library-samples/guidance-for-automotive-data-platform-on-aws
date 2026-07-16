"""Optional CMS→ADP ingest stack — DDB Streams → Firehose → S3 → Glue Iceberg.

Default: this stack is NOT instantiated. It is created only when
``cdk deploy -c stage=staging|prod -c enable_cms_ingest=true`` is
passed AND ``cms_vehicle_state_table_arn`` is supplied.

Deploys (when enabled):

* Stage-prefixed Glue database ``adp_{stage}_cms_ingest`` for the
  raw replica tables.
* Glue *staging* table whose schema is consumed by the Firehose
  ``DataFormatConversionConfiguration`` to drive JSON → parquet
  conversion. Schema columns come from
  :mod:`platform_foundation.source.optional.cms_ingest.firehose_schema`.
* Glue *Iceberg* target table per CMS source table (one per logical
  source registered in
  :mod:`~platform_foundation.source.optional.cms_ingest.glue_merge_job.TABLE_PROJECTIONS`).
  v1 covers ``vehicle_state``.
* Kinesis Firehose delivery stream with parquet conversion enabled,
  buffered at 60 s / 64 MiB (micro-batch — matches spec Constraint
  #9 "no streaming integration in v1").
* IAM role for Firehose (S3 PutObject + KMS encrypt + Glue GetTable).
* Asset-deployed Glue 4.0 PySpark job (the MERGE job) and an
  EventBridge schedule that fires it every 15 minutes.

Per ``staging-prod-design.md`` §2.9–§2.10, all resource names are
stage-prefixed so staging and prod can each deploy their own copy
without colliding.

This stack does NOT run by default. Synth-time check in
``tests/test_optional_cms_ingest_disabled.py`` asserts that with
``enable_cms_ingest=false`` the synthesized templates contain zero
``AWS::KinesisFirehose::DeliveryStream``, zero ``AWS::DynamoDB::Stream``,
and zero ``adp_{stage}_cms_ingest`` Glue databases.

See ``docs/cms-ingest-optional-module.md`` for the operator-facing
runbook (prereqs, enable/disable commands, single-account vs
cross-account, tear-down).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_events as events
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kinesisfirehose as firehose
from aws_cdk import aws_s3 as s3  # noqa: F401  # imported for completeness; constructs use string ARNs
from aws_cdk import aws_s3_assets as s3_assets
from cdk_nag import NagSuppressions
from constructs import Construct

from stacks._naming import _stage_db_name, _stage_name, validate_stage

# Source-side runtime helpers. Imported here so the stack and the
# runtime always agree on the schema, the table list, and the prefix
# template — single source of truth.
from source.optional.cms_ingest import firehose_schema as _fs
from source.optional.cms_ingest.glue_merge_job import TABLE_PROJECTIONS


#: Path to the PySpark Glue MERGE job script (asset-uploaded at synth).
_GLUE_JOB_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "source"
    / "optional"
    / "cms_ingest"
    / "glue_merge_job.py"
)

#: Glue version pinned for the MERGE job. Matches the spike + Group 3
#: PySpark generators (Glue 4.0 = Spark 3.3 + Python 3.10).
_GLUE_VERSION = "4.0"

#: 15-minute MERGE cadence per spec.
_MERGE_SCHEDULE_RATE = "rate(15 minutes)"


class CmsIngestStack(Stack):
    """Stage-prefixed CMS→ADP ingest. Only instantiated when ``enable_cms_ingest=true``."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        lake_bucket_name: str,
        cms_vehicle_state_table_arn: Optional[str],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        validate_stage(stage)
        self.stage = stage

        if not cms_vehicle_state_table_arn:
            raise ValueError(
                "CmsIngestStack requires -c cms_vehicle_state_table_arn=<arn> "
                "when enable_cms_ingest=true. See docs/cms-ingest-optional-module.md."
            )
        self._cms_table_arn = cms_vehicle_state_table_arn

        # 1. Glue database for ingested CMS tables (raw replica, NOT a
        #    published product). Stage-prefixed so staging and prod can
        #    ingest into separate catalogs without colliding.
        cms_db_name = _stage_db_name(stage, "cms_ingest")
        self.cms_db = glue.CfnDatabase(
            self,
            "CmsIngestDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=cms_db_name,
                description=(
                    f"Raw replica of CMS DDB tables (stage={stage}). "
                    "NOT a published data product — opt-in only."
                ),
                location_uri=f"s3://{lake_bucket_name}/cms-ingest/",
            ),
        )

        # 2. Firehose schema-target Glue table. Firehose's parquet
        #    conversion needs to read columns + serde from a Glue table
        #    matching the JSON shape it sees on the wire. We declare a
        #    single staging table (``stream_records``) that mirrors
        #    every DDB-Stream record envelope; the per-table typed
        #    projection happens inside the MERGE job.
        firehose_staging_table_name = "_firehose_staging_records"
        firehose_s3_root = f"s3://{lake_bucket_name}/cms-ingest/"
        self.firehose_staging_table = glue.CfnTable(
            self,
            "FirehoseStagingTable",
            catalog_id=self.account,
            database_name=cms_db_name,
            table_input=glue.CfnTable.TableInputProperty(
                name=firehose_staging_table_name,
                description=(
                    "Schema target consumed by the Firehose "
                    "DataFormatConversionConfiguration. Mirrors the "
                    "DDB-Stream record envelope. Per-CMS-table typed "
                    "projection lives in the MERGE job."
                ),
                table_type="EXTERNAL_TABLE",
                parameters={
                    "classification": "parquet",
                    "compressionType": "zstd",
                    "EXTERNAL": "TRUE",
                },
                partition_keys=[
                    glue.CfnTable.ColumnProperty(**c)
                    for c in _fs.partition_keys_cfn()
                ],
                storage_descriptor=_storage_descriptor_property(
                    _fs.storage_descriptor_cfn(firehose_s3_root)
                ),
            ),
        )
        self.firehose_staging_table.add_dependency(self.cms_db)

        # 3. Per-CMS-table Iceberg targets (one per logical source).
        #    The MERGE job creates the underlying snapshot lineage on
        #    first run; here we just register the Glue catalog entry
        #    so the table is queryable even before the first MERGE.
        self.iceberg_targets: dict[str, glue.CfnTable] = {}
        for logical_name, projection in TABLE_PROJECTIONS.items():
            table_loc = (
                f"s3://{lake_bucket_name}/curated/cms-ingest/{logical_name}/"
            )
            target = glue.CfnTable(
                self,
                f"IcebergTarget{_pascal(logical_name)}",
                catalog_id=self.account,
                database_name=cms_db_name,
                table_input=glue.CfnTable.TableInputProperty(
                    name=projection.iceberg_table,
                    description=(
                        f"Iceberg replica of CMS '{logical_name}' "
                        f"(stage={stage}). Maintained by the MERGE "
                        f"job every 15 minutes. PK={projection.primary_keys}."
                    ),
                    table_type="EXTERNAL_TABLE",
                    parameters={
                        "table_type": "ICEBERG",
                        "EXTERNAL": "TRUE",
                        "format": "parquet",
                        "write_compression": "zstd",
                        "classification": "parquet",
                    },
                    storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                        location=table_loc,
                        # Iceberg manages its own InputFormat /
                        # OutputFormat / SerDe — Glue table
                        # registration just needs the columns and the
                        # ``table_type=ICEBERG`` parameter so Athena
                        # Engine V3 dispatches via the Iceberg adapter.
                        columns=[
                            # The MERGE job's projection is the
                            # authoritative shape. We declare a
                            # minimal schema here so DataZone +
                            # Lake Formation can grant on the table
                            # immediately; the MERGE job will evolve
                            # the schema additively as needed.
                            glue.CfnTable.ColumnProperty(
                                name=pk, type="string", comment="PK column"
                            )
                            for pk in projection.primary_keys
                        ],
                    ),
                ),
            )
            target.add_dependency(self.cms_db)
            self.iceberg_targets[logical_name] = target

        # 4. Firehose delivery role (stage-prefixed name per design §2.9).
        firehose_role = iam.Role(
            self,
            "FirehoseDeliveryRole",
            role_name=_stage_name(stage, "cms-ingest-firehose-role"),
            assumed_by=iam.ServicePrincipal("firehose.amazonaws.com"),
        )
        firehose_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:AbortMultipartUpload",
                    "s3:GetBucketLocation",
                    "s3:GetObject",
                    "s3:ListBucket",
                    "s3:ListBucketMultipartUploads",
                    "s3:PutObject",
                ],
                resources=[
                    f"arn:aws:s3:::{lake_bucket_name}",
                    f"arn:aws:s3:::{lake_bucket_name}/cms-ingest/*",
                ],
            )
        )
        firehose_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetTable",
                    "glue:GetTableVersion",
                    "glue:GetTableVersions",
                ],
                resources=[
                    f"arn:aws:glue:{self.region}:{self.account}:catalog",
                    f"arn:aws:glue:{self.region}:{self.account}:database/{cms_db_name}",
                    f"arn:aws:glue:{self.region}:{self.account}:table/{cms_db_name}/*",
                ],
            )
        )
        # Lake bucket KMS decrypt (the lake bucket is SSE-KMS).
        # The lake sets ``bucket_key_enabled=True`` (per
        # foundation_stack.py:127), so S3 Bucket Keys send the
        # **bucket** ARN as ``kms:EncryptionContext:aws:s3:arn`` —
        # not the object ARN. The first list entry below is the
        # bucket-key path; the second is the legacy/object-context
        # fallback for the unlikely future case where bucket keys
        # are disabled. See AWS Firehose IAM docs and the S3 user
        # guide ("Reducing the cost of SSE-KMS with Amazon S3
        # Bucket Keys").
        firehose_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=["*"],  # KMS key ARN is cross-stack; scoped via condition
                conditions={
                    "StringLike": {
                        "kms:ViaService": f"s3.{self.region}.amazonaws.com",
                        "kms:EncryptionContext:aws:s3:arn": [
                            f"arn:aws:s3:::{lake_bucket_name}",
                            f"arn:aws:s3:::{lake_bucket_name}/cms-ingest/*",
                        ],
                    }
                },
            )
        )

        # 5. Firehose delivery stream with parquet conversion +
        #    dynamic partitioning by tableName. Stream name is
        #    stage-prefixed per design §2.10.
        firehose_stream_name = _stage_name(stage, "cms-vehicle-state")
        self.firehose_stream = firehose.CfnDeliveryStream(
            self,
            "VehicleStateFirehose",
            delivery_stream_name=firehose_stream_name,
            delivery_stream_type="DirectPut",  # DDB Stream → Lambda transformer → Firehose putRecord
            delivery_stream_encryption_configuration_input=(
                firehose.CfnDeliveryStream.DeliveryStreamEncryptionConfigurationInputProperty(
                    key_type="AWS_OWNED_CMK",
                )
            ),
            extended_s3_destination_configuration=firehose.CfnDeliveryStream.ExtendedS3DestinationConfigurationProperty(
                bucket_arn=f"arn:aws:s3:::{lake_bucket_name}",
                # Per-table dynamic prefix:
                # ``cms-ingest/!{partitionKeyFromQuery:tablename}/dt=YYYY-MM-DD/``.
                prefix=(
                    "cms-ingest/!{partitionKeyFromQuery:tablename}/"
                    "dt=!{timestamp:yyyy-MM-dd}/"
                ),
                error_output_prefix=(
                    "cms-ingest/_errors/!{firehose:error-output-type}/"
                    "dt=!{timestamp:yyyy-MM-dd}/"
                ),
                role_arn=firehose_role.role_arn,
                buffering_hints=firehose.CfnDeliveryStream.BufferingHintsProperty(
                    interval_in_seconds=_fs.BUFFERING_INTERVAL_SECONDS,
                    size_in_m_bs=_fs.BUFFERING_SIZE_MB,
                ),
                # ``UNCOMPRESSED`` is mandatory when DataFormatConversion
                # is enabled — the parquet writer compresses internally.
                compression_format="UNCOMPRESSED",
                # 5a. Dynamic partitioning + metadata extraction so the
                #     ``tableName`` field on the wire becomes the
                #     ``!{partitionKeyFromQuery:tablename}`` placeholder.
                dynamic_partitioning_configuration=(
                    firehose.CfnDeliveryStream.DynamicPartitioningConfigurationProperty(
                        enabled=True,
                        retry_options=firehose.CfnDeliveryStream.RetryOptionsProperty(
                            duration_in_seconds=300,
                        ),
                    )
                ),
                processing_configuration=firehose.CfnDeliveryStream.ProcessingConfigurationProperty(
                    enabled=True,
                    processors=[
                        firehose.CfnDeliveryStream.ProcessorProperty(
                            type="MetadataExtraction",
                            parameters=[
                                firehose.CfnDeliveryStream.ProcessorParameterProperty(
                                    parameter_name="MetadataExtractionQuery",
                                    parameter_value="{tablename: .table_name}",
                                ),
                                firehose.CfnDeliveryStream.ProcessorParameterProperty(
                                    parameter_name="JsonParsingEngine",
                                    parameter_value="JQ-1.6",
                                ),
                            ],
                        ),
                    ],
                ),
                # 5b. JSON → parquet conversion driven by the
                #     ``_firehose_staging_records`` Glue table.
                data_format_conversion_configuration=(
                    firehose.CfnDeliveryStream.DataFormatConversionConfigurationProperty(
                        enabled=True,
                        input_format_configuration=(
                            firehose.CfnDeliveryStream.InputFormatConfigurationProperty(
                                deserializer=firehose.CfnDeliveryStream.DeserializerProperty(
                                    open_x_json_ser_de=firehose.CfnDeliveryStream.OpenXJsonSerDeProperty(
                                        case_insensitive=False,
                                        convert_dots_in_json_keys_to_underscores=False,
                                    )
                                )
                            )
                        ),
                        output_format_configuration=(
                            firehose.CfnDeliveryStream.OutputFormatConfigurationProperty(
                                serializer=firehose.CfnDeliveryStream.SerializerProperty(
                                    parquet_ser_de=firehose.CfnDeliveryStream.ParquetSerDeProperty(
                                        compression="ZSTD",
                                    )
                                )
                            )
                        ),
                        schema_configuration=(
                            firehose.CfnDeliveryStream.SchemaConfigurationProperty(
                                catalog_id=self.account,
                                database_name=cms_db_name,
                                table_name=firehose_staging_table_name,
                                region=self.region,
                                role_arn=firehose_role.role_arn,
                                version_id="LATEST",
                            )
                        ),
                    )
                ),
            ),
        )
        self.firehose_stream.add_dependency(self.firehose_staging_table)

        # 6. Glue MERGE job — asset-uploaded Python script + IAM role
        #    + EventBridge 15-min schedule.
        glue_role = iam.Role(
            self,
            "GlueMergeJobRole",
            role_name=_stage_name(stage, "cms-ingest-glue-role"),
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
        )
        glue_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "service-role/AWSGlueServiceRole"
            )
        )
        glue_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                    "s3:GetBucketLocation",
                    "s3:AbortMultipartUpload",
                ],
                resources=[
                    f"arn:aws:s3:::{lake_bucket_name}",
                    f"arn:aws:s3:::{lake_bucket_name}/cms-ingest/*",
                    f"arn:aws:s3:::{lake_bucket_name}/curated/cms-ingest/*",
                ],
            )
        )
        glue_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetTable",
                    "glue:GetTables",
                    "glue:GetDatabase",
                    "glue:GetDatabases",
                    "glue:CreateTable",
                    "glue:UpdateTable",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                    "glue:CreatePartition",
                    "glue:UpdatePartition",
                    "glue:BatchCreatePartition",
                ],
                resources=[
                    f"arn:aws:glue:{self.region}:{self.account}:catalog",
                    f"arn:aws:glue:{self.region}:{self.account}:database/{cms_db_name}",
                    f"arn:aws:glue:{self.region}:{self.account}:table/{cms_db_name}/*",
                ],
            )
        )
        glue_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=["*"],
                conditions={
                    "StringLike": {
                        "kms:ViaService": f"s3.{self.region}.amazonaws.com",
                        # Bucket-key path: S3 sends the bare bucket
                        # ARN when ``bucket_key_enabled=True``
                        # (foundation_stack.py:127). The two prefixed
                        # entries are the legacy/object-context
                        # fallbacks if bucket keys are ever disabled.
                        "kms:EncryptionContext:aws:s3:arn": [
                            f"arn:aws:s3:::{lake_bucket_name}",
                            f"arn:aws:s3:::{lake_bucket_name}/cms-ingest/*",
                            f"arn:aws:s3:::{lake_bucket_name}/curated/cms-ingest/*",
                        ],
                    }
                },
            )
        )

        # The Glue script file is uploaded as a CDK asset on each synth
        # so deploys ship the latest version. (At synth time the file
        # need not exist — the assertion below is the safety net.)
        if not _GLUE_JOB_SCRIPT.exists():
            raise FileNotFoundError(
                f"Glue MERGE job script not found at {_GLUE_JOB_SCRIPT}. "
                "Did the source/optional/cms_ingest/glue_merge_job.py "
                "land? See spec.md Group 5 task."
            )
        merge_script_asset = s3_assets.Asset(
            self,
            "MergeJobScriptAsset",
            path=str(_GLUE_JOB_SCRIPT),
        )
        merge_script_asset.grant_read(glue_role)

        merge_job_name = _stage_name(stage, "cms-ingest-merge")
        self.merge_job = glue.CfnJob(
            self,
            "MergeJob",
            name=merge_job_name,
            role=glue_role.role_arn,
            glue_version=_GLUE_VERSION,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=merge_script_asset.s3_object_url,
            ),
            default_arguments={
                "--stage": stage,
                "--lake-bucket": lake_bucket_name,
                "--source-tables": ",".join(TABLE_PROJECTIONS.keys()),
                "--enable-metrics": "true",
                "--enable-continuous-cloudwatch-log": "true",
                "--job-language": "python",
                # Iceberg + the Glue Iceberg connector — both are GA on
                # Glue 4.0 but must be requested explicitly so the
                # Spark session boots with the catalog extensions.
                "--datalake-formats": "iceberg",
                "--conf": (
                    "spark.sql.extensions="
                    "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions "
                    "--conf spark.sql.catalog.glue_catalog="
                    "org.apache.iceberg.spark.SparkCatalog "
                    "--conf spark.sql.catalog.glue_catalog.warehouse="
                    f"s3://{lake_bucket_name}/curated/ "
                    "--conf spark.sql.catalog.glue_catalog.catalog-impl="
                    "org.apache.iceberg.aws.glue.GlueCatalog "
                    "--conf spark.sql.catalog.glue_catalog.io-impl="
                    "org.apache.iceberg.aws.s3.S3FileIO"
                ),
            },
            number_of_workers=2,
            worker_type="G.1X",
            timeout=10,  # minutes — well under the 15-min schedule
            execution_property=glue.CfnJob.ExecutionPropertyProperty(
                max_concurrent_runs=1,  # never overlap a 15-min slot
            ),
            description=(
                f"15-min cadence Iceberg MERGE for CMS ingest (stage={stage}). "
                f"Sources: {','.join(TABLE_PROJECTIONS.keys())}."
            ),
        )

        # 7. EventBridge rule firing the MERGE job every 15 minutes.
        events_role = iam.Role(
            self,
            "MergeScheduleRole",
            role_name=_stage_name(stage, "cms-ingest-schedule-role"),
            assumed_by=iam.ServicePrincipal("events.amazonaws.com"),
        )
        events_role.add_to_policy(
            iam.PolicyStatement(
                actions=["glue:StartJobRun"],
                resources=[
                    f"arn:aws:glue:{self.region}:{self.account}:job/{merge_job_name}",
                ],
            )
        )
        self.merge_schedule = events.CfnRule(
            self,
            "MergeSchedule",
            name=_stage_name(stage, "cms-ingest-merge-schedule"),
            description=(
                f"Trigger {merge_job_name} every 15 minutes "
                f"(stage={stage})."
            ),
            schedule_expression="rate(15 minutes)",
            state="ENABLED",
            targets=[
                events.CfnRule.TargetProperty(
                    arn=f"arn:aws:glue:{self.region}:{self.account}:job/{merge_job_name}",
                    id="GlueMergeJobTarget",
                    role_arn=events_role.role_arn,
                ),
            ],
        )
        self.merge_schedule.add_dependency(self.merge_job)

        # 8. Outputs — useful for the smoke-test runbook.
        CfnOutput(
            self,
            "CmsIngestDatabaseName",
            value=self.cms_db.ref,
            export_name=_stage_name(stage, "cms-ingest-db"),
        )
        CfnOutput(
            self,
            "FirehoseStreamName",
            value=self.firehose_stream.delivery_stream_name or "",
            export_name=_stage_name(stage, "cms-ingest-firehose-name"),
        )
        CfnOutput(
            self,
            "MergeJobName",
            value=merge_job_name,
            export_name=_stage_name(stage, "cms-ingest-merge-job"),
        )
        CfnOutput(
            self,
            "CmsSourceTableArn",
            value=cms_vehicle_state_table_arn,
            description=(
                "Operator-provided CMS source table ARN (read-only — "
                "ADP never writes to this table)."
            ),
        )

        NagSuppressions.add_resource_suppressions(
            firehose_role,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Firehose role needs prefix:* on the cms-ingest/ S3 path "
                        "(per-day partition keys are dynamic). Glue table:*/* "
                        "is required to read schema for parquet conversion. "
                        f"Both wildcards are scoped to {cms_db_name} only."
                    ),
                    "applies_to": [
                        f"Resource::arn:aws:s3:::{lake_bucket_name}/cms-ingest/*",
                        f"Resource::arn:aws:glue:<AWS::Region>:<AWS::AccountId>:table/{cms_db_name}/*",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "KMS:Decrypt / GenerateDataKey on Resource::* is scoped via "
                        "the kms:ViaService = s3 condition + the "
                        "kms:EncryptionContext:aws:s3:arn restriction to the "
                        "cms-ingest/ prefix. The lake bucket uses SSE-KMS with "
                        "bucket keys (enabled post-ADP Foundation; reduces per-object "
                        "KMS calls). The lake KMS key ARN is owned by the foundation "
                        "lake stack and cross-stack imported via the bucket policy; "
                        "this stack cannot reference it directly without tight coupling."
                    ),
                    "applies_to": ["Resource::*"],
                },
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            self.merge_job,
            [
                {
                    "id": "AwsSolutions-GL1",
                    "reason": (
                        "Glue security-configuration for CloudWatch Log "
                        "encryption is account-level shared infrastructure "
                        "and lives in the foundation governance stack (not "
                        "the optional cms-ingest stack). Adding a "
                        "per-stack security configuration here would "
                        "duplicate the KMS CMK + IAM glue policy already "
                        "owned by the foundation. Suppression is scoped to "
                        "this single Glue job; revisit when the foundation "
                        "ships a shared Glue SecurityConfiguration."
                    ),
                },
                {
                    "id": "AwsSolutions-GL3",
                    "reason": (
                        "Job bookmark encryption is N/A — this MERGE job "
                        "does NOT use Glue job bookmarks. The MERGE job's "
                        "own ``_seq_no`` predicate (DDB-Stream sequence "
                        "number) provides idempotency without bookmarks; "
                        "see source/optional/cms_ingest/glue_merge_job.py "
                        "merge_sql() — UPDATE branch is gated on "
                        "``s._seq_no > t._seq_no``."
                    ),
                },
            ],
            apply_to_children=True,
        )
        NagSuppressions.add_resource_suppressions(
            glue_role,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": (
                        "AWSGlueServiceRole is the AWS-managed policy AWS "
                        "documents for Glue Spark jobs (CloudWatch Logs, S3 "
                        "asset read, ENI). Replacing it requires enumerating "
                        "every Glue runtime IAM action (CW Logs, X-Ray, Glue "
                        "schema registry) — a known cdk-nag tradeoff captured "
                        "in the foundation suppression policy."
                    ),
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": (
                        "Glue role needs S3 prefix:* on cms-ingest/ + "
                        "curated/cms-ingest/ for source reads + Iceberg "
                        "metadata writes. Glue table:*/* is required because "
                        "Iceberg creates per-snapshot table versions in the "
                        "Glue catalog. Both wildcards are scoped to "
                        f"{cms_db_name} only."
                    ),
                    "applies_to": [
                        f"Resource::arn:aws:s3:::{lake_bucket_name}/cms-ingest/*",
                        f"Resource::arn:aws:s3:::{lake_bucket_name}/curated/cms-ingest/*",
                        f"Resource::arn:aws:glue:<AWS::Region>:<AWS::AccountId>:table/{cms_db_name}/*",
                        "Resource::*",
                    ],
                },
            ],
            apply_to_children=True,
        )


def _pascal(snake: str) -> str:
    """``snake_case`` → ``PascalCase`` for CDK construct ids."""
    return "".join(part.capitalize() for part in snake.split("_"))


def _storage_descriptor_property(d: dict) -> glue.CfnTable.StorageDescriptorProperty:
    """Convert :func:`_fs.storage_descriptor_cfn` dict to the typed CFN property.

    Keeping this conversion local to the stack means the
    :mod:`firehose_schema` module stays free of CDK imports (so it
    can be unit-tested without instantiating a CDK App).
    """
    return glue.CfnTable.StorageDescriptorProperty(
        columns=[glue.CfnTable.ColumnProperty(**c) for c in d["columns"]],
        location=d["location"],
        input_format=d["input_format"],
        output_format=d["output_format"],
        serde_info=glue.CfnTable.SerdeInfoProperty(
            serialization_library=d["serde_info"]["serialization_library"],
            parameters=d["serde_info"]["parameters"],
        ),
        stored_as_sub_directories=d["stored_as_sub_directories"],
        compressed=d["compressed"],
        parameters=d["parameters"],
    )


# Silence unused-import warning when the module is imported but the
# `os` module is not used (kept available for any future env-var
# lookups in this stack).
_ = os
