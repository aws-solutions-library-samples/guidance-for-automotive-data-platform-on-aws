import * as cdk from 'aws-cdk-lib';
import * as glue from 'aws-cdk-lib/aws-glue';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
export interface EtlStackProps extends cdk.StackProps {
    dataLakeBucket: s3.IBucket;
    glueDatabase: glue.CfnDatabase;
}
export declare class EtlStack extends cdk.Stack {
    constructor(scope: Construct, id: string, props: EtlStackProps);
}
