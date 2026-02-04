"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.AuroraPgVectorStack = void 0;
const cdk = require("aws-cdk-lib");
const ec2 = require("aws-cdk-lib/aws-ec2");
const rds = require("aws-cdk-lib/aws-rds");
const kms = require("aws-cdk-lib/aws-kms");
const iam = require("aws-cdk-lib/aws-iam");
class AuroraPgVectorStack extends cdk.Stack {
    constructor(scope, id, props) {
        super(scope, id, props);
        // KMS key for encrypting secrets (CKV_AWS_149)
        const kmsKey = new kms.Key(this, 'SecretsKey', {
            enableKeyRotation: true,
            description: 'KMS key for Aurora secrets encryption',
            removalPolicy: cdk.RemovalPolicy.RETAIN,
        });
        // Use existing VPC or default VPC
        let vpc;
        let createdPrivateSubnets = [];
        if (props?.vpcId) {
            // Use specified VPC
            vpc = ec2.Vpc.fromLookup(this, 'Vpc', { vpcId: props.vpcId });
        }
        else if (props?.useDefaultVpc) {
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
        }
        else {
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
        dbSecurityGroup.addIngressRule(ec2.Peer.ipv4(vpc.vpcCidrBlock), ec2.Port.tcp(5432), 'Allow PostgreSQL access from VPC');
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
            storageEncryptionKey: kmsKey, // Use KMS CMK for storage encryption
            removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
            enableDataApi: true,
            iamAuthentication: true, // CKV_AWS_162: Enable IAM authentication
            monitoringInterval: cdk.Duration.seconds(60), // CKV_AWS_118: Enable enhanced monitoring
            monitoringRole: monitoringRole,
            credentials: rds.Credentials.fromGeneratedSecret('cx_admin', {
                encryptionKey: kmsKey, // CKV_AWS_149: Encrypt secret with KMS CMK
            }),
        });
        this.secret = this.cluster.secret;
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
exports.AuroraPgVectorStack = AuroraPgVectorStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXVyb3JhLXBndmVjdG9yLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXVyb3JhLXBndmVjdG9yLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7OztBQUFBLG1DQUFtQztBQUNuQywyQ0FBMkM7QUFDM0MsMkNBQTJDO0FBRTNDLDJDQUEyQztBQUMzQywyQ0FBMkM7QUFRM0MsTUFBYSxtQkFBb0IsU0FBUSxHQUFHLENBQUMsS0FBSztJQUloRCxZQUFZLEtBQWdCLEVBQUUsRUFBVSxFQUFFLEtBQWdDO1FBQ3hFLEtBQUssQ0FBQyxLQUFLLEVBQUUsRUFBRSxFQUFFLEtBQUssQ0FBQyxDQUFDO1FBRXhCLCtDQUErQztRQUMvQyxNQUFNLE1BQU0sR0FBRyxJQUFJLEdBQUcsQ0FBQyxHQUFHLENBQUMsSUFBSSxFQUFFLFlBQVksRUFBRTtZQUM3QyxpQkFBaUIsRUFBRSxJQUFJO1lBQ3ZCLFdBQVcsRUFBRSx1Q0FBdUM7WUFDcEQsYUFBYSxFQUFFLEdBQUcsQ0FBQyxhQUFhLENBQUMsTUFBTTtTQUN4QyxDQUFDLENBQUM7UUFFSCxrQ0FBa0M7UUFDbEMsSUFBSSxHQUFhLENBQUM7UUFDbEIsSUFBSSxxQkFBcUIsR0FBd0IsRUFBRSxDQUFDO1FBRXBELElBQUksS0FBSyxFQUFFLEtBQUssRUFBRSxDQUFDO1lBQ2pCLG9CQUFvQjtZQUNwQixHQUFHLEdBQUcsR0FBRyxDQUFDLEdBQUcsQ0FBQyxVQUFVLENBQUMsSUFBSSxFQUFFLEtBQUssRUFBRSxFQUFFLEtBQUssRUFBRSxLQUFLLENBQUMsS0FBSyxFQUFFLENBQUMsQ0FBQztRQUNoRSxDQUFDO2FBQU0sSUFBSSxLQUFLLEVBQUUsYUFBYSxFQUFFLENBQUM7WUFDaEMsMENBQTBDO1lBQzFDLE1BQU0sVUFBVSxHQUFHLEdBQUcsQ0FBQyxHQUFHLENBQUMsVUFBVSxDQUFDLElBQUksRUFBRSxLQUFLLEVBQUUsRUFBRSxTQUFTLEVBQUUsSUFBSSxFQUFFLENBQUMsQ0FBQztZQUN4RSxH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WUFDdEIsb0JBQW9CLEVBQUUsTUFBTSxFQUFHLHFDQUFxQztZQUNwRSxhQUFhLEVBQUUsR0FBRyxDQUFDLGFBQWEsQ0FBQyxRQUFRO1lBQ3pDLGFBQWEsRUFBRSxJQUFJO1lBQ25CLGlCQUFpQixFQUFFLElBQUksRUFBRyx5Q0FBeUM7WUFDbkUsa0JBQWtCLEVBQUUsR0FBRyxDQUFDLFFBQVEsQ0FBQyxPQUFPLENBQUMsRUFBRSxDQUFDLEVBQUcsMENBQTBDO1lBQ3pGLGNBQWMsRUFBRSxjQUFjO1lBQzlCLFdBQVcsRUFBRSxHQUFHLENBQUMsV0FBVyxDQUFDLG1CQUFtQixDQUFDLFVBQVUsRUFBRTtnQkFDM0QsYUFBYSxFQUFFLE1BQU0sRUFBRywyQ0FBMkM7YUFDcEUsQ0FBQztTQUNILENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyxNQUFNLEdBQUcsSUFBSSxDQUFDLE9BQU8sQ0FBQyxNQUFPLENBQUM7UUFFbkMsNEJBQTRCO1FBQzVCLElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsaUJBQWlCLEVBQUU7WUFDekMsS0FBSyxFQUFFLElBQUksQ0FBQyxPQUFPLENBQUMsZUFBZSxDQUFDLFFBQVE7WUFDNUMsV0FBVyxFQUFFLHlCQUF5QjtTQUN2QyxDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLFdBQVcsRUFBRTtZQUNuQyxLQUFLLEVBQUUsSUFBSSxDQUFDLE1BQU0sQ0FBQyxTQUFTO1lBQzVCLFdBQVcsRUFBRSxxQ0FBcUM7U0FDbkQsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxjQUFjLEVBQUU7WUFDdEMsS0FBSyxFQUFFLFVBQVU7WUFDakIsV0FBVyxFQUFFLGVBQWU7U0FDN0IsQ0FBQyxDQUFDO0lBQ0wsQ0FBQztDQUNGO0FBckhELGtEQXFIQyIsInNvdXJjZXNDb250ZW50IjpbImltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgKiBhcyBlYzIgZnJvbSAnYXdzLWNkay1saWIvYXdzLWVjMic7XG5pbXBvcnQgKiBhcyByZHMgZnJvbSAnYXdzLWNkay1saWIvYXdzLXJkcyc7XG5pbXBvcnQgKiBhcyBzZWNyZXRzbWFuYWdlciBmcm9tICdhd3MtY2RrLWxpYi9hd3Mtc2VjcmV0c21hbmFnZXInO1xuaW1wb3J0ICogYXMga21zIGZyb20gJ2F3cy1jZGstbGliL2F3cy1rbXMnO1xuaW1wb3J0ICogYXMgaWFtIGZyb20gJ2F3cy1jZGstbGliL2F3cy1pYW0nO1xuaW1wb3J0IHsgQ29uc3RydWN0IH0gZnJvbSAnY29uc3RydWN0cyc7XG5cbmV4cG9ydCBpbnRlcmZhY2UgQXVyb3JhUGdWZWN0b3JTdGFja1Byb3BzIGV4dGVuZHMgY2RrLlN0YWNrUHJvcHMge1xuICB2cGNJZD86IHN0cmluZztcbiAgdXNlRGVmYXVsdFZwYz86IGJvb2xlYW47XG59XG5cbmV4cG9ydCBjbGFzcyBBdXJvcmFQZ1ZlY3RvclN0YWNrIGV4dGVuZHMgY2RrLlN0YWNrIHtcbiAgcHVibGljIHJlYWRvbmx5IGNsdXN0ZXI6IHJkcy5EYXRhYmFzZUNsdXN0ZXI7XG4gIHB1YmxpYyByZWFkb25seSBzZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG5cbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM/OiBBdXJvcmFQZ1ZlY3RvclN0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIC8vIEtNUyBrZXkgZm9yIGVuY3J5cHRpbmcgc2VjcmV0cyAoQ0tWX0FXU18xNDkpXG4gICAgY29uc3Qga21zS2V5ID0gbmV3IGttcy5LZXkodGhpcywgJ1NlY3JldHNLZXknLCB7XG4gICAgICBlbmFibGVLZXlSb3RhdGlvbjogdHJ1ZSxcbiAgICAgIGRlc2NyaXB0aW9uOiAnS01TIGtleSBmb3IgQXVyb3JhIHNlY3JldHMgZW5jcnlwdGlvbicsXG4gICAgICByZW1vdmFsUG9saWN5OiBjZGsuUmVtb3ZhbFBvbGljeS5SRVRBSU4sXG4gICAgfSk7XG5cbiAgICAvLyBVc2UgZXhpc3RpbmcgVlBDIG9yIGRlZmF1bHQgVlBDXG4gICAgbGV0IHZwYzogZWMyLklWcGM7XG4gICAgbGV0IGNyZWF0ZWRQcml2YXRlU3VibmV0czogZWMyLlByaXZhdGVTdWJuZXRbXSA9IFtdO1xuICAgIFxuICAgIGlmIChwcm9wcz8udnBjSWQpIHtcbiAgICAgIC8vIFVzZSBzcGVjaWZpZWQgVlBDXG4gICAgICB2cGMgPSBlYzIuVnBjLmZyb21Mb29rdXAodGhpcywgJ1ZwYycsIHsgdnBjSWQ6IHByb3BzLnZwY0lkIH0pO1xuICAgIH0gZWxzZSBpZiAocHJvcHM/LnVzZURlZmF1bHRWcGMpIHtcbiAgICAgIC8vIFVzZSBkZWZhdWx0IFZQQyBhbmQgYWRkIHByaXZhdGUgc3VibmV0c1xuICAgICAgY29uc3QgZGVmYXVsdFZwYyA9IGVjMi5WcGMuZnJvbUxvb2t1cCh0aGlzLCAnVnBjJywgeyBpc0RlZmF1bHQ6IHRydWUgfSk7XG4gICAgICB2cGMgPSBkZWZhdWx0VnBjO1xuICAgICAgXG4gICAgICAvLyBDcmVhdGUgcHJpdmF0ZSBzdWJuZXRzIGluIGRlZmF1bHQgVlBDXG4gICAgICBjb25zdCBhenMgPSBjZGsuU3RhY2sub2YodGhpcykuYXZhaWxhYmlsaXR5Wm9uZXMuc2xpY2UoMCwgMik7XG4gICAgICBcbiAgICAgIGF6cy5mb3JFYWNoKChheiwgaW5kZXgpID0+IHtcbiAgICAgICAgY29uc3QgcHJpdmF0ZVN1Ym5ldCA9IG5ldyBlYzIuUHJpdmF0ZVN1Ym5ldCh0aGlzLCBgUHJpdmF0ZVN1Ym5ldCR7aW5kZXggKyAxfWAsIHtcbiAgICAgICAgICBhdmFpbGFiaWxpdHlab25lOiBheixcbiAgICAgICAgICB2cGNJZDogZGVmYXVsdFZwYy52cGNJZCxcbiAgICAgICAgICBjaWRyQmxvY2s6IGAxNzIuMzEuJHsxMDAgKyBpbmRleH0uMC8yNGAsIC8vIFVzZSB1bnVzZWQgQ0lEUiByYW5nZSBpbiBkZWZhdWx0IFZQQ1xuICAgICAgICB9KTtcbiAgICAgICAgY3JlYXRlZFByaXZhdGVTdWJuZXRzLnB1c2gocHJpdmF0ZVN1Ym5ldCk7XG4gICAgICB9KTtcbiAgICB9IGVsc2Uge1xuICAgICAgLy8gQ3JlYXRlIG5ldyBWUEMgKHdpbGwgZmFpbCBpZiBsaW1pdCByZWFjaGVkKVxuICAgICAgdnBjID0gbmV3IGVjMi5WcGModGhpcywgJ1ZwYycsIHtcbiAgICAgICAgbWF4QXpzOiAyLFxuICAgICAgICBuYXRHYXRld2F5czogMSxcbiAgICAgIH0pO1xuICAgIH1cblxuICAgIC8vIFNlY3VyaXR5IGdyb3VwIGZvciBBdXJvcmFcbiAgICBjb25zdCBkYlNlY3VyaXR5R3JvdXAgPSBuZXcgZWMyLlNlY3VyaXR5R3JvdXAodGhpcywgJ0RiU2VjdXJpdHlHcm91cCcsIHtcbiAgICAgIHZwYyxcbiAgICAgIGRlc2NyaXB0aW9uOiAnU2VjdXJpdHkgZ3JvdXAgZm9yIEF1cm9yYSBQb3N0Z3JlU1FMIHdpdGggcGd2ZWN0b3InLFxuICAgICAgYWxsb3dBbGxPdXRib3VuZDogdHJ1ZSxcbiAgICB9KTtcblxuICAgIC8vIEFsbG93IFBvc3RncmVTUUwgYWNjZXNzIGZyb20gVlBDXG4gICAgZGJTZWN1cml0eUdyb3VwLmFkZEluZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuaXB2NCh2cGMudnBjQ2lkckJsb2NrKSxcbiAgICAgIGVjMi5Qb3J0LnRjcCg1NDMyKSxcbiAgICAgICdBbGxvdyBQb3N0Z3JlU1FMIGFjY2VzcyBmcm9tIFZQQydcbiAgICApO1xuXG4gICAgLy8gRGV0ZXJtaW5lIHN1Ym5ldCBzZWxlY3Rpb25cbiAgICBjb25zdCBzdWJuZXRTZWxlY3Rpb24gPSBjcmVhdGVkUHJpdmF0ZVN1Ym5ldHMubGVuZ3RoID4gMFxuICAgICAgPyB7IHN1Ym5ldHM6IGNyZWF0ZWRQcml2YXRlU3VibmV0cyB9XG4gICAgICA6IHsgc3VibmV0VHlwZTogZWMyLlN1Ym5ldFR5cGUuUFJJVkFURV9XSVRIX0VHUkVTUyB9O1xuXG4gICAgLy8gSUFNIHJvbGUgZm9yIGVuaGFuY2VkIG1vbml0b3JpbmcgKENLVl9BV1NfMTE4KVxuICAgIGNvbnN0IG1vbml0b3JpbmdSb2xlID0gbmV3IGlhbS5Sb2xlKHRoaXMsICdNb25pdG9yaW5nUm9sZScsIHtcbiAgICAgIGFzc3VtZWRCeTogbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKCdtb25pdG9yaW5nLnJkcy5hbWF6b25hd3MuY29tJyksXG4gICAgICBtYW5hZ2VkUG9saWNpZXM6IFtcbiAgICAgICAgaWFtLk1hbmFnZWRQb2xpY3kuZnJvbUF3c01hbmFnZWRQb2xpY3lOYW1lKCdzZXJ2aWNlLXJvbGUvQW1hem9uUkRTRW5oYW5jZWRNb25pdG9yaW5nUm9sZScpLFxuICAgICAgXSxcbiAgICB9KTtcblxuICAgIC8vIENyZWF0ZSBBdXJvcmEgU2VydmVybGVzcyB2MiBjbHVzdGVyIHdpdGggUG9zdGdyZVNRTFxuICAgIHRoaXMuY2x1c3RlciA9IG5ldyByZHMuRGF0YWJhc2VDbHVzdGVyKHRoaXMsICdBdXJvcmFDbHVzdGVyJywge1xuICAgICAgZW5naW5lOiByZHMuRGF0YWJhc2VDbHVzdGVyRW5naW5lLmF1cm9yYVBvc3RncmVzKHtcbiAgICAgICAgdmVyc2lvbjogcmRzLkF1cm9yYVBvc3RncmVzRW5naW5lVmVyc2lvbi5WRVJfMTVfOCxcbiAgICAgIH0pLFxuICAgICAgd3JpdGVyOiByZHMuQ2x1c3Rlckluc3RhbmNlLnNlcnZlcmxlc3NWMignV3JpdGVyJywge1xuICAgICAgICBhdXRvTWlub3JWZXJzaW9uVXBncmFkZTogdHJ1ZSxcbiAgICAgICAgZW5hYmxlUGVyZm9ybWFuY2VJbnNpZ2h0czogdHJ1ZSxcbiAgICAgIH0pLFxuICAgICAgc2VydmVybGVzc1YyTWluQ2FwYWNpdHk6IDAuNSxcbiAgICAgIHNlcnZlcmxlc3NWMk1heENhcGFjaXR5OiAyLFxuICAgICAgdnBjLFxuICAgICAgdnBjU3VibmV0czogc3VibmV0U2VsZWN0aW9uLFxuICAgICAgc2VjdXJpdHlHcm91cHM6IFtkYlNlY3VyaXR5R3JvdXBdLFxuICAgICAgZGVmYXVsdERhdGFiYXNlTmFtZTogJ3ZlY3RvcmRiJyxcbiAgICAgIHN0b3JhZ2VFbmNyeXB0ZWQ6IHRydWUsXG4gICAgICBzdG9yYWdlRW5jcnlwdGlvbktleToga21zS2V5LCAgLy8gVXNlIEtNUyBDTUsgZm9yIHN0b3JhZ2UgZW5jcnlwdGlvblxuICAgICAgcmVtb3ZhbFBvbGljeTogY2RrLlJlbW92YWxQb2xpY3kuU05BUFNIT1QsXG4gICAgICBlbmFibGVEYXRhQXBpOiB0cnVlLFxuICAgICAgaWFtQXV0aGVudGljYXRpb246IHRydWUsICAvLyBDS1ZfQVdTXzE2MjogRW5hYmxlIElBTSBhdXRoZW50aWNhdGlvblxuICAgICAgbW9uaXRvcmluZ0ludGVydmFsOiBjZGsuRHVyYXRpb24uc2Vjb25kcyg2MCksICAvLyBDS1ZfQVdTXzExODogRW5hYmxlIGVuaGFuY2VkIG1vbml0b3JpbmdcbiAgICAgIG1vbml0b3JpbmdSb2xlOiBtb25pdG9yaW5nUm9sZSxcbiAgICAgIGNyZWRlbnRpYWxzOiByZHMuQ3JlZGVudGlhbHMuZnJvbUdlbmVyYXRlZFNlY3JldCgnY3hfYWRtaW4nLCB7XG4gICAgICAgIGVuY3J5cHRpb25LZXk6IGttc0tleSwgIC8vIENLVl9BV1NfMTQ5OiBFbmNyeXB0IHNlY3JldCB3aXRoIEtNUyBDTUtcbiAgICAgIH0pLFxuICAgIH0pO1xuXG4gICAgdGhpcy5zZWNyZXQgPSB0aGlzLmNsdXN0ZXIuc2VjcmV0ITtcblxuICAgIC8vIE91dHB1dCBjb25uZWN0aW9uIGRldGFpbHNcbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnQ2x1c3RlckVuZHBvaW50Jywge1xuICAgICAgdmFsdWU6IHRoaXMuY2x1c3Rlci5jbHVzdGVyRW5kcG9pbnQuaG9zdG5hbWUsXG4gICAgICBkZXNjcmlwdGlvbjogJ0F1cm9yYSBjbHVzdGVyIGVuZHBvaW50JyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdTZWNyZXRBcm4nLCB7XG4gICAgICB2YWx1ZTogdGhpcy5zZWNyZXQuc2VjcmV0QXJuLFxuICAgICAgZGVzY3JpcHRpb246ICdTZWNyZXQgQVJOIGZvciBkYXRhYmFzZSBjcmVkZW50aWFscycsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnRGF0YWJhc2VOYW1lJywge1xuICAgICAgdmFsdWU6ICd2ZWN0b3JkYicsXG4gICAgICBkZXNjcmlwdGlvbjogJ0RhdGFiYXNlIG5hbWUnLFxuICAgIH0pO1xuICB9XG59XG4iXX0=