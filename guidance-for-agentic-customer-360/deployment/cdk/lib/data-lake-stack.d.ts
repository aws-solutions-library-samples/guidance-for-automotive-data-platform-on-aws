import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
export declare class DataLakeStack extends cdk.Stack {
    readonly bucket: s3.Bucket;
    readonly accessLogsBucket: s3.Bucket;
    constructor(scope: Construct, id: string, props?: cdk.StackProps);
}
