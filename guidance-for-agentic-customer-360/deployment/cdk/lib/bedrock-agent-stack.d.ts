import * as cdk from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
export interface BedrockAgentStackProps extends cdk.StackProps {
    readonly dataLakeBucket: s3.IBucket;
    readonly glueDatabase: string;
    readonly athenaWorkgroup: string;
    readonly auroraCluster: rds.DatabaseCluster;
    readonly auroraSecret: secretsmanager.ISecret;
    readonly accessLogsBucket?: s3.IBucket;
}
export declare class BedrockAgentStack extends cdk.Stack {
    readonly knowledgeBase: bedrock.CfnKnowledgeBase;
    readonly customerHealthAgent: bedrock.CfnAgent;
    constructor(scope: Construct, id: string, props: BedrockAgentStackProps);
}
