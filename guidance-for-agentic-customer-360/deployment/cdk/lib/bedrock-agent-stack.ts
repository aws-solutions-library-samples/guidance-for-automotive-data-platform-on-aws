import * as cdk from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export interface BedrockAgentStackProps extends cdk.StackProps {
  readonly dataLakeBucket: s3.IBucket;
  readonly glueDatabase: string;
  readonly athenaWorkgroup: string;
  readonly auroraCluster: rds.DatabaseCluster;
  readonly auroraSecret: secretsmanager.ISecret;
}

export class BedrockAgentStack extends cdk.Stack {
  public readonly knowledgeBase: bedrock.CfnKnowledgeBase;
  public readonly customerHealthAgent: bedrock.CfnAgent;

  constructor(scope: Construct, id: string, props: BedrockAgentStackProps) {
    super(scope, id, props);

    // Knowledge Base S3 bucket for documentation
    const kbBucket = new s3.Bucket(this, 'KnowledgeBaseBucket', {
      bucketName: `cx360-knowledge-base-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      autoDeleteObjects: false,
    });

    // Bedrock service role for Knowledge Base
    const kbRole = new iam.Role(this, 'KnowledgeBaseRole', {
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
      description: 'Role for Bedrock Knowledge Base to access S3',
    });

    kbBucket.grantRead(kbRole);

    // Knowledge Base and Agent are created via CLI scripts
    // See deployment/scripts/create-bedrock-kb-cli.sh and create-bedrock-agent-cli.sh
    // CDK deployment is commented out due to CloudFormation validation issues

    // Outputs
    new cdk.CfnOutput(this, 'KnowledgeBaseBucketName', {
      value: kbBucket.bucketName,
      description: 'S3 bucket for knowledge base documents',
    });
  }
}
