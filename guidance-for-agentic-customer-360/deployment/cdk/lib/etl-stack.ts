import * as cdk from 'aws-cdk-lib';
import * as glue from 'aws-cdk-lib/aws-glue';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface EtlStackProps extends cdk.StackProps {
  dataLakeBucket: s3.IBucket;
  glueDatabase: glue.CfnDatabase;
}

export class EtlStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: EtlStackProps) {
    super(scope, id, props);

    const glueRole = new iam.Role(this, 'GlueRole', {
      assumedBy: new iam.ServicePrincipal('glue.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSGlueServiceRole'),
      ],
    });

    props.dataLakeBucket.grantReadWrite(glueRole);

    // Glue Security Configuration (CKV_AWS_195)
    const securityConfig = new glue.CfnSecurityConfiguration(this, 'GlueSecurityConfig', {
      name: 'cx360-glue-security-config',
      encryptionConfiguration: {
        s3Encryptions: [{
          s3EncryptionMode: 'SSE-S3',
        }],
        cloudWatchEncryption: {
          cloudWatchEncryptionMode: 'SSE-KMS',
        },
        jobBookmarksEncryption: {
          jobBookmarksEncryptionMode: 'CSE-KMS',
        },
      },
    });

    // Customer 360 Transform Job
    new glue.CfnJob(this, 'Customer360Job', {
      name: 'cx-customer-360-transform',
      role: glueRole.roleArn,
      command: {
        name: 'glueetl',
        pythonVersion: '3',
        scriptLocation: `s3://${props.dataLakeBucket.bucketName}/scripts/customer_360.py`,
      },
      defaultArguments: {
        '--S3_BUCKET': props.dataLakeBucket.bucketName,
        '--enable-glue-datacatalog': 'true',
      },
      glueVersion: '4.0',
      maxRetries: 0,
      timeout: 60,
      numberOfWorkers: 5,
      workerType: 'G.1X',
      securityConfiguration: securityConfig.name,  // CKV_AWS_195: Associate security config
    });

    new cdk.CfnOutput(this, 'GlueRoleArn', {
      value: glueRole.roleArn,
    });
  }
}
