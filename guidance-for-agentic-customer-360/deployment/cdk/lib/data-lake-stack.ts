import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export class DataLakeStack extends cdk.Stack {
  public readonly bucket: s3.Bucket;
  public readonly accessLogsBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Access logs bucket for S3 server access logging
    // Note: This bucket cannot log to itself (would be circular)
    // checkov:skip=CKV_AWS_18: Access logs bucket cannot log to itself
    this.accessLogsBucket = new s3.Bucket(this, 'AccessLogsBucket', {
      bucketName: `automotive-cx-access-logs-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      enforceSSL: true,
      versioned: true,  // CKV_AWS_21: Enable versioning
    });

    this.bucket = new s3.Bucket(this, 'DataLake', {
      bucketName: `automotive-cx-data-lake-${this.account}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      versioned: true,  // CKV_AWS_21: Enable versioning
      serverAccessLogsBucket: this.accessLogsBucket,  // CKV_AWS_18: Enable access logging
      serverAccessLogsPrefix: 'data-lake-logs/',
      enforceSSL: true,
      lifecycleRules: [
        {
          transitions: [
            {
              storageClass: s3.StorageClass.INTELLIGENT_TIERING,
              transitionAfter: cdk.Duration.days(0),
            },
          ],
        },
      ],
    });

    new cdk.CfnOutput(this, 'DataLakeBucket', {
      value: this.bucket.bucketName,
      description: 'S3 Data Lake Bucket',
    });
  }
}
