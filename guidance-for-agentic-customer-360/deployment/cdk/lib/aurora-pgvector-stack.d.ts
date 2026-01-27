import * as cdk from 'aws-cdk-lib';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
export interface AuroraPgVectorStackProps extends cdk.StackProps {
    vpcId?: string;
    useDefaultVpc?: boolean;
}
export declare class AuroraPgVectorStack extends cdk.Stack {
    readonly cluster: rds.DatabaseCluster;
    readonly secret: secretsmanager.ISecret;
    constructor(scope: Construct, id: string, props?: AuroraPgVectorStackProps);
}
