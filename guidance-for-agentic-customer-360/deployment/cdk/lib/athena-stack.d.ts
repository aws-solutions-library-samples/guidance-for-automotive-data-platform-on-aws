import * as cdk from 'aws-cdk-lib';
import * as athena from 'aws-cdk-lib/aws-athena';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as glue from 'aws-cdk-lib/aws-glue';
import { Construct } from 'constructs';
export interface AthenaStackProps extends cdk.StackProps {
    dataLakeBucket: s3.IBucket;
    glueDatabase: glue.CfnDatabase;
}
export declare class AthenaStack extends cdk.Stack {
    readonly workgroup: athena.CfnWorkGroup;
    constructor(scope: Construct, id: string, props: AthenaStackProps);
}
