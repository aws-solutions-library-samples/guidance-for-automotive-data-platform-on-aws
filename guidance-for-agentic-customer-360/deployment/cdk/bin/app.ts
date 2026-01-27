#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { DataLakeStack } from '../lib/data-lake-stack';
import { GlueCatalogStack } from '../lib/glue-catalog-stack';
import { EtlStack } from '../lib/etl-stack';
import { AuroraPgVectorStack } from '../lib/aurora-pgvector-stack';

const app = new cdk.App();

const stage = process.env.DEPLOYMENT_STAGE || 'dev';
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.AWS_REGION || 'us-east-1',
};

// Phase 1: Data Lake
const dataLake = new DataLakeStack(app, `cx360-${stage}-data-lake`, { env });

// Phase 1: Glue Catalog
const glueCatalog = new GlueCatalogStack(app, `cx360-${stage}-glue`, {
  env,
  dataLakeBucket: dataLake.bucket,
});

// Phase 2: ETL
new EtlStack(app, `cx360-${stage}-etl`, {
  env,
  dataLakeBucket: dataLake.bucket,
  glueDatabase: glueCatalog.database,
});

// Phase 1: Athena Views
const { AthenaStack } = require('../lib/athena-stack');
const athena = new AthenaStack(app, `cx360-${stage}-athena`, {
  env,
  dataLakeBucket: dataLake.bucket,
  glueDatabase: glueCatalog.database,
});

// Phase 4: QuickSight Dashboard
const { QuickSightStack } = require('../lib/quicksight-stack');
new QuickSightStack(app, `cx360-${stage}-quicksight`, {
  env,
  athenaWorkgroup: athena.workgroup.name,
  glueDatabase: glueCatalog.database.databaseName,
});

// Phase 5: Aurora PostgreSQL with pgvector
const aurora = new AuroraPgVectorStack(app, `cx360-${stage}-aurora`, { 
  env,
  useDefaultVpc: true  // Use default VPC to avoid VPC limit
});

// Phase 5: Bedrock Agents
const { BedrockAgentStack } = require('../lib/bedrock-agent-stack');
new BedrockAgentStack(app, `cx360-${stage}-bedrock`, {
  env,
  dataLakeBucket: dataLake.bucket,
  glueDatabase: glueCatalog.database.databaseName,
  athenaWorkgroup: athena.workgroup.name,
  auroraCluster: aurora.cluster,
  auroraSecret: aurora.secret,
});

app.synth();
