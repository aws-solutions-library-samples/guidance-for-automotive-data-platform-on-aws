import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface AuroraPgVectorStackProps extends cdk.StackProps {
  vpcId?: string;
  useDefaultVpc?: boolean;
}

export class AuroraPgVectorStack extends cdk.Stack {
  public readonly cluster: rds.DatabaseCluster;
  public readonly secret: secretsmanager.ISecret;

  constructor(scope: Construct, id: string, props?: AuroraPgVectorStackProps) {
    super(scope, id, props);

    // KMS key for encrypting secrets (CKV_AWS_149)
    const kmsKey = new kms.Key(this, 'SecretsKey', {
      enableKeyRotation: true,
      description: 'KMS key for Aurora secrets encryption',
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // Use existing VPC or default VPC
    let vpc: ec2.IVpc;
    let createdPrivateSubnets: ec2.PrivateSubnet[] = [];
    
    if (props?.vpcId) {
      // Use specified VPC
      vpc = ec2.Vpc.fromLookup(this, 'Vpc', { vpcId: props.vpcId });
    } else if (props?.useDefaultVpc) {
      // Use default VPC and add private subnets
      const defaultVpc = ec2.Vpc.fromLookup(this, 'Vpc', { isDefault: true });
      vpc = defaultVpc;
      
      // Create private subnets in default VPC
      const azs = cdk.Stack.of(this).availabilityZones.slice(0, 2);
      
      azs.forEach((az, index) => {
        const privateSubnet = new ec2.PrivateSubnet(this, `PrivateSubnet${index + 1}`, {
          availabilityZone: az,
          vpcId: defaultVpc.vpcId,
          cidrBlock: `172.31.${100 + index}.0/24`, // Use unused CIDR range in default VPC
        });
        createdPrivateSubnets.push(privateSubnet);
      });
    } else {
      // Create new VPC (will fail if limit reached)
      vpc = new ec2.Vpc(this, 'Vpc', {
        maxAzs: 2,
        natGateways: 1,
      });
    }

    // Security group for Aurora
    const dbSecurityGroup = new ec2.SecurityGroup(this, 'DbSecurityGroup', {
      vpc,
      description: 'Security group for Aurora PostgreSQL with pgvector',
      allowAllOutbound: true,
    });

    // Allow PostgreSQL access from VPC
    dbSecurityGroup.addIngressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(5432),
      'Allow PostgreSQL access from VPC'
    );

    // Determine subnet selection
    const subnetSelection = createdPrivateSubnets.length > 0
      ? { subnets: createdPrivateSubnets }
      : { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS };

    // IAM role for enhanced monitoring (CKV_AWS_118)
    const monitoringRole = new iam.Role(this, 'MonitoringRole', {
      assumedBy: new iam.ServicePrincipal('monitoring.rds.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonRDSEnhancedMonitoringRole'),
      ],
    });

    // Create Aurora Serverless v2 cluster with PostgreSQL
    this.cluster = new rds.DatabaseCluster(this, 'AuroraCluster', {
      engine: rds.DatabaseClusterEngine.auroraPostgres({
        version: rds.AuroraPostgresEngineVersion.VER_15_8,
      }),
      writer: rds.ClusterInstance.serverlessV2('Writer', {
        autoMinorVersionUpgrade: true,
        enablePerformanceInsights: true,
      }),
      serverlessV2MinCapacity: 0.5,
      serverlessV2MaxCapacity: 2,
      vpc,
      vpcSubnets: subnetSelection,
      securityGroups: [dbSecurityGroup],
      defaultDatabaseName: 'vectordb',
      storageEncrypted: true,
      storageEncryptionKey: kmsKey,  // Use KMS CMK for storage encryption
      removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
      enableDataApi: true,
      iamAuthentication: true,  // CKV_AWS_162: Enable IAM authentication
      monitoringInterval: cdk.Duration.seconds(60),  // CKV_AWS_118: Enable enhanced monitoring
      monitoringRole: monitoringRole,
      credentials: rds.Credentials.fromGeneratedSecret('cx_admin', {
        encryptionKey: kmsKey,  // CKV_AWS_149: Encrypt secret with KMS CMK
      }),
    });

    this.secret = this.cluster.secret!;

    // Output connection details
    new cdk.CfnOutput(this, 'ClusterEndpoint', {
      value: this.cluster.clusterEndpoint.hostname,
      description: 'Aurora cluster endpoint',
    });

    new cdk.CfnOutput(this, 'SecretArn', {
      value: this.secret.secretArn,
      description: 'Secret ARN for database credentials',
    });

    new cdk.CfnOutput(this, 'DatabaseName', {
      value: 'vectordb',
      description: 'Database name',
    });
  }
}
