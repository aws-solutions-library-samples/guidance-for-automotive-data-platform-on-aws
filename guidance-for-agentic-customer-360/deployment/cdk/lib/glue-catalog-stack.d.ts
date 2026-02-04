import * as cdk from 'aws-cdk-lib';
import * as glue from 'aws-cdk-lib/aws-glue';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';
export interface GlueCatalogStackProps extends cdk.StackProps {
    dataLakeBucket: s3.IBucket;
}
export declare class GlueCatalogStack extends cdk.Stack {
    readonly database: glue.CfnDatabase;
    constructor(scope: Construct, id: string, props: GlueCatalogStackProps);
    private createTable;
    private createCSVTable;
}
