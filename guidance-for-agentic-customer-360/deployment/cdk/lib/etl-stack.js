"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.EtlStack = void 0;
const cdk = require("aws-cdk-lib");
const glue = require("aws-cdk-lib/aws-glue");
const iam = require("aws-cdk-lib/aws-iam");
class EtlStack extends cdk.Stack {
    constructor(scope, id, props) {
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
            securityConfiguration: securityConfig.name, // CKV_AWS_195: Associate security config
        });
        new cdk.CfnOutput(this, 'GlueRoleArn', {
            value: glueRole.roleArn,
        });
    }
}
exports.EtlStack = EtlStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiZXRsLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiZXRsLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7OztBQUFBLG1DQUFtQztBQUNuQyw2Q0FBNkM7QUFFN0MsMkNBQTJDO0FBUTNDLE1BQWEsUUFBUyxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBQ3JDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBb0I7UUFDNUQsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxRQUFRLEdBQUcsSUFBSSxHQUFHLENBQUMsSUFBSSxDQUFDLElBQUksRUFBRSxVQUFVLEVBQUU7WUFDOUMsU0FBUyxFQUFFLElBQUksR0FBRyxDQUFDLGdCQUFnQixDQUFDLG9CQUFvQixDQUFDO1lBQ3pELGVBQWUsRUFBRTtnQkFDZixHQUFHLENBQUMsYUFBYSxDQUFDLHdCQUF3QixDQUFDLGlDQUFpQyxDQUFDO2FBQzlFO1NBQ0YsQ0FBQyxDQUFDO1FBRUgsS0FBSyxDQUFDLGNBQWMsQ0FBQyxjQUFjLENBQUMsUUFBUSxDQUFDLENBQUM7UUFFOUMsNENBQTRDO1FBQzVDLE1BQU0sY0FBYyxHQUFHLElBQUksSUFBSSxDQUFDLHdCQUF3QixDQUFDLElBQUksRUFBRSxvQkFBb0IsRUFBRTtZQUNuRixJQUFJLEVBQUUsNEJBQTRCO1lBQ2xDLHVCQUF1QixFQUFFO2dCQUN2QixhQUFhLEVBQUUsQ0FBQzt3QkFDZCxnQkFBZ0IsRUFBRSxRQUFRO3FCQUMzQixDQUFDO2dCQUNGLG9CQUFvQixFQUFFO29CQUNwQix3QkFBd0IsRUFBRSxTQUFTO2lCQUNwQztnQkFDRCxzQkFBc0IsRUFBRTtvQkFDdEIsMEJBQTBCLEVBQUUsU0FBUztpQkFDdEM7YUFDRjtTQUNGLENBQUMsQ0FBQztRQUVILDZCQUE2QjtRQUM3QixJQUFJLElBQUksQ0FBQyxNQUFNLENBQUMsSUFBSSxFQUFFLGdCQUFnQixFQUFFO1lBQ3RDLElBQUksRUFBRSwyQkFBMkI7WUFDakMsSUFBSSxFQUFFLFFBQVEsQ0FBQyxPQUFPO1lBQ3RCLE9BQU8sRUFBRTtnQkFDUCxJQUFJLEVBQUUsU0FBUztnQkFDZixhQUFhLEVBQUUsR0FBRztnQkFDbEIsY0FBYyxFQUFFLFFBQVEsS0FBSyxDQUFDLGNBQWMsQ0FBQyxVQUFVLDBCQUEwQjthQUNsRjtZQUNELGdCQUFnQixFQUFFO2dCQUNoQixhQUFhLEVBQUUsS0FBSyxDQUFDLGNBQWMsQ0FBQyxVQUFVO2dCQUM5QywyQkFBMkIsRUFBRSxNQUFNO2FBQ3BDO1lBQ0QsV0FBVyxFQUFFLEtBQUs7WUFDbEIsVUFBVSxFQUFFLENBQUM7WUFDYixPQUFPLEVBQUUsRUFBRTtZQUNYLGVBQWUsRUFBRSxDQUFDO1lBQ2xCLFVBQVUsRUFBRSxNQUFNO1lBQ2xCLHFCQUFxQixFQUFFLGNBQWMsQ0FBQyxJQUFJLEVBQUcseUNBQXlDO1NBQ3ZGLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsYUFBYSxFQUFFO1lBQ3JDLEtBQUssRUFBRSxRQUFRLENBQUMsT0FBTztTQUN4QixDQUFDLENBQUM7SUFDTCxDQUFDO0NBQ0Y7QUF0REQsNEJBc0RDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCAqIGFzIGdsdWUgZnJvbSAnYXdzLWNkay1saWIvYXdzLWdsdWUnO1xuaW1wb3J0ICogYXMgczMgZnJvbSAnYXdzLWNkay1saWIvYXdzLXMzJztcbmltcG9ydCAqIGFzIGlhbSBmcm9tICdhd3MtY2RrLWxpYi9hd3MtaWFtJztcbmltcG9ydCB7IENvbnN0cnVjdCB9IGZyb20gJ2NvbnN0cnVjdHMnO1xuXG5leHBvcnQgaW50ZXJmYWNlIEV0bFN0YWNrUHJvcHMgZXh0ZW5kcyBjZGsuU3RhY2tQcm9wcyB7XG4gIGRhdGFMYWtlQnVja2V0OiBzMy5JQnVja2V0O1xuICBnbHVlRGF0YWJhc2U6IGdsdWUuQ2ZuRGF0YWJhc2U7XG59XG5cbmV4cG9ydCBjbGFzcyBFdGxTdGFjayBleHRlbmRzIGNkay5TdGFjayB7XG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzOiBFdGxTdGFja1Byb3BzKSB7XG4gICAgc3VwZXIoc2NvcGUsIGlkLCBwcm9wcyk7XG5cbiAgICBjb25zdCBnbHVlUm9sZSA9IG5ldyBpYW0uUm9sZSh0aGlzLCAnR2x1ZVJvbGUnLCB7XG4gICAgICBhc3N1bWVkQnk6IG5ldyBpYW0uU2VydmljZVByaW5jaXBhbCgnZ2x1ZS5hbWF6b25hd3MuY29tJyksXG4gICAgICBtYW5hZ2VkUG9saWNpZXM6IFtcbiAgICAgICAgaWFtLk1hbmFnZWRQb2xpY3kuZnJvbUF3c01hbmFnZWRQb2xpY3lOYW1lKCdzZXJ2aWNlLXJvbGUvQVdTR2x1ZVNlcnZpY2VSb2xlJyksXG4gICAgICBdLFxuICAgIH0pO1xuXG4gICAgcHJvcHMuZGF0YUxha2VCdWNrZXQuZ3JhbnRSZWFkV3JpdGUoZ2x1ZVJvbGUpO1xuXG4gICAgLy8gR2x1ZSBTZWN1cml0eSBDb25maWd1cmF0aW9uIChDS1ZfQVdTXzE5NSlcbiAgICBjb25zdCBzZWN1cml0eUNvbmZpZyA9IG5ldyBnbHVlLkNmblNlY3VyaXR5Q29uZmlndXJhdGlvbih0aGlzLCAnR2x1ZVNlY3VyaXR5Q29uZmlnJywge1xuICAgICAgbmFtZTogJ2N4MzYwLWdsdWUtc2VjdXJpdHktY29uZmlnJyxcbiAgICAgIGVuY3J5cHRpb25Db25maWd1cmF0aW9uOiB7XG4gICAgICAgIHMzRW5jcnlwdGlvbnM6IFt7XG4gICAgICAgICAgczNFbmNyeXB0aW9uTW9kZTogJ1NTRS1TMycsXG4gICAgICAgIH1dLFxuICAgICAgICBjbG91ZFdhdGNoRW5jcnlwdGlvbjoge1xuICAgICAgICAgIGNsb3VkV2F0Y2hFbmNyeXB0aW9uTW9kZTogJ1NTRS1LTVMnLFxuICAgICAgICB9LFxuICAgICAgICBqb2JCb29rbWFya3NFbmNyeXB0aW9uOiB7XG4gICAgICAgICAgam9iQm9va21hcmtzRW5jcnlwdGlvbk1vZGU6ICdDU0UtS01TJyxcbiAgICAgICAgfSxcbiAgICAgIH0sXG4gICAgfSk7XG5cbiAgICAvLyBDdXN0b21lciAzNjAgVHJhbnNmb3JtIEpvYlxuICAgIG5ldyBnbHVlLkNmbkpvYih0aGlzLCAnQ3VzdG9tZXIzNjBKb2InLCB7XG4gICAgICBuYW1lOiAnY3gtY3VzdG9tZXItMzYwLXRyYW5zZm9ybScsXG4gICAgICByb2xlOiBnbHVlUm9sZS5yb2xlQXJuLFxuICAgICAgY29tbWFuZDoge1xuICAgICAgICBuYW1lOiAnZ2x1ZWV0bCcsXG4gICAgICAgIHB5dGhvblZlcnNpb246ICczJyxcbiAgICAgICAgc2NyaXB0TG9jYXRpb246IGBzMzovLyR7cHJvcHMuZGF0YUxha2VCdWNrZXQuYnVja2V0TmFtZX0vc2NyaXB0cy9jdXN0b21lcl8zNjAucHlgLFxuICAgICAgfSxcbiAgICAgIGRlZmF1bHRBcmd1bWVudHM6IHtcbiAgICAgICAgJy0tUzNfQlVDS0VUJzogcHJvcHMuZGF0YUxha2VCdWNrZXQuYnVja2V0TmFtZSxcbiAgICAgICAgJy0tZW5hYmxlLWdsdWUtZGF0YWNhdGFsb2cnOiAndHJ1ZScsXG4gICAgICB9LFxuICAgICAgZ2x1ZVZlcnNpb246ICc0LjAnLFxuICAgICAgbWF4UmV0cmllczogMCxcbiAgICAgIHRpbWVvdXQ6IDYwLFxuICAgICAgbnVtYmVyT2ZXb3JrZXJzOiA1LFxuICAgICAgd29ya2VyVHlwZTogJ0cuMVgnLFxuICAgICAgc2VjdXJpdHlDb25maWd1cmF0aW9uOiBzZWN1cml0eUNvbmZpZy5uYW1lLCAgLy8gQ0tWX0FXU18xOTU6IEFzc29jaWF0ZSBzZWN1cml0eSBjb25maWdcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdHbHVlUm9sZUFybicsIHtcbiAgICAgIHZhbHVlOiBnbHVlUm9sZS5yb2xlQXJuLFxuICAgIH0pO1xuICB9XG59XG4iXX0=