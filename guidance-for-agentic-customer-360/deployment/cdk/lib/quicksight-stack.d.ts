import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
export interface QuickSightStackProps extends cdk.StackProps {
    readonly athenaWorkgroup: string;
    readonly glueDatabase: string;
}
export declare class QuickSightStack extends cdk.Stack {
    constructor(scope: Construct, id: string, props: QuickSightStackProps);
}
