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
        });
        new cdk.CfnOutput(this, 'GlueRoleArn', {
            value: glueRole.roleArn,
        });
    }
}
exports.EtlStack = EtlStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiZXRsLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiZXRsLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7OztBQUFBLG1DQUFtQztBQUNuQyw2Q0FBNkM7QUFFN0MsMkNBQTJDO0FBUTNDLE1BQWEsUUFBUyxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBQ3JDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBb0I7UUFDNUQsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxRQUFRLEdBQUcsSUFBSSxHQUFHLENBQUMsSUFBSSxDQUFDLElBQUksRUFBRSxVQUFVLEVBQUU7WUFDOUMsU0FBUyxFQUFFLElBQUksR0FBRyxDQUFDLGdCQUFnQixDQUFDLG9CQUFvQixDQUFDO1lBQ3pELGVBQWUsRUFBRTtnQkFDZixHQUFHLENBQUMsYUFBYSxDQUFDLHdCQUF3QixDQUFDLGlDQUFpQyxDQUFDO2FBQzlFO1NBQ0YsQ0FBQyxDQUFDO1FBRUgsS0FBSyxDQUFDLGNBQWMsQ0FBQyxjQUFjLENBQUMsUUFBUSxDQUFDLENBQUM7UUFFOUMsNkJBQTZCO1FBQzdCLElBQUksSUFBSSxDQUFDLE1BQU0sQ0FBQyxJQUFJLEVBQUUsZ0JBQWdCLEVBQUU7WUFDdEMsSUFBSSxFQUFFLDJCQUEyQjtZQUNqQyxJQUFJLEVBQUUsUUFBUSxDQUFDLE9BQU87WUFDdEIsT0FBTyxFQUFFO2dCQUNQLElBQUksRUFBRSxTQUFTO2dCQUNmLGFBQWEsRUFBRSxHQUFHO2dCQUNsQixjQUFjLEVBQUUsUUFBUSxLQUFLLENBQUMsY0FBYyxDQUFDLFVBQVUsMEJBQTBCO2FBQ2xGO1lBQ0QsZ0JBQWdCLEVBQUU7Z0JBQ2hCLGFBQWEsRUFBRSxLQUFLLENBQUMsY0FBYyxDQUFDLFVBQVU7Z0JBQzlDLDJCQUEyQixFQUFFLE1BQU07YUFDcEM7WUFDRCxXQUFXLEVBQUUsS0FBSztZQUNsQixVQUFVLEVBQUUsQ0FBQztZQUNiLE9BQU8sRUFBRSxFQUFFO1lBQ1gsZUFBZSxFQUFFLENBQUM7WUFDbEIsVUFBVSxFQUFFLE1BQU07U0FDbkIsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxhQUFhLEVBQUU7WUFDckMsS0FBSyxFQUFFLFFBQVEsQ0FBQyxPQUFPO1NBQ3hCLENBQUMsQ0FBQztJQUNMLENBQUM7Q0FDRjtBQXJDRCw0QkFxQ0MiLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0ICogYXMgZ2x1ZSBmcm9tICdhd3MtY2RrLWxpYi9hd3MtZ2x1ZSc7XG5pbXBvcnQgKiBhcyBzMyBmcm9tICdhd3MtY2RrLWxpYi9hd3MtczMnO1xuaW1wb3J0ICogYXMgaWFtIGZyb20gJ2F3cy1jZGstbGliL2F3cy1pYW0nO1xuaW1wb3J0IHsgQ29uc3RydWN0IH0gZnJvbSAnY29uc3RydWN0cyc7XG5cbmV4cG9ydCBpbnRlcmZhY2UgRXRsU3RhY2tQcm9wcyBleHRlbmRzIGNkay5TdGFja1Byb3BzIHtcbiAgZGF0YUxha2VCdWNrZXQ6IHMzLklCdWNrZXQ7XG4gIGdsdWVEYXRhYmFzZTogZ2x1ZS5DZm5EYXRhYmFzZTtcbn1cblxuZXhwb3J0IGNsYXNzIEV0bFN0YWNrIGV4dGVuZHMgY2RrLlN0YWNrIHtcbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM6IEV0bFN0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIGNvbnN0IGdsdWVSb2xlID0gbmV3IGlhbS5Sb2xlKHRoaXMsICdHbHVlUm9sZScsIHtcbiAgICAgIGFzc3VtZWRCeTogbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKCdnbHVlLmFtYXpvbmF3cy5jb20nKSxcbiAgICAgIG1hbmFnZWRQb2xpY2llczogW1xuICAgICAgICBpYW0uTWFuYWdlZFBvbGljeS5mcm9tQXdzTWFuYWdlZFBvbGljeU5hbWUoJ3NlcnZpY2Utcm9sZS9BV1NHbHVlU2VydmljZVJvbGUnKSxcbiAgICAgIF0sXG4gICAgfSk7XG5cbiAgICBwcm9wcy5kYXRhTGFrZUJ1Y2tldC5ncmFudFJlYWRXcml0ZShnbHVlUm9sZSk7XG5cbiAgICAvLyBDdXN0b21lciAzNjAgVHJhbnNmb3JtIEpvYlxuICAgIG5ldyBnbHVlLkNmbkpvYih0aGlzLCAnQ3VzdG9tZXIzNjBKb2InLCB7XG4gICAgICBuYW1lOiAnY3gtY3VzdG9tZXItMzYwLXRyYW5zZm9ybScsXG4gICAgICByb2xlOiBnbHVlUm9sZS5yb2xlQXJuLFxuICAgICAgY29tbWFuZDoge1xuICAgICAgICBuYW1lOiAnZ2x1ZWV0bCcsXG4gICAgICAgIHB5dGhvblZlcnNpb246ICczJyxcbiAgICAgICAgc2NyaXB0TG9jYXRpb246IGBzMzovLyR7cHJvcHMuZGF0YUxha2VCdWNrZXQuYnVja2V0TmFtZX0vc2NyaXB0cy9jdXN0b21lcl8zNjAucHlgLFxuICAgICAgfSxcbiAgICAgIGRlZmF1bHRBcmd1bWVudHM6IHtcbiAgICAgICAgJy0tUzNfQlVDS0VUJzogcHJvcHMuZGF0YUxha2VCdWNrZXQuYnVja2V0TmFtZSxcbiAgICAgICAgJy0tZW5hYmxlLWdsdWUtZGF0YWNhdGFsb2cnOiAndHJ1ZScsXG4gICAgICB9LFxuICAgICAgZ2x1ZVZlcnNpb246ICc0LjAnLFxuICAgICAgbWF4UmV0cmllczogMCxcbiAgICAgIHRpbWVvdXQ6IDYwLFxuICAgICAgbnVtYmVyT2ZXb3JrZXJzOiA1LFxuICAgICAgd29ya2VyVHlwZTogJ0cuMVgnLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0dsdWVSb2xlQXJuJywge1xuICAgICAgdmFsdWU6IGdsdWVSb2xlLnJvbGVBcm4sXG4gICAgfSk7XG4gIH1cbn1cbiJdfQ==