"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.GlueCatalogStack = void 0;
const cdk = require("aws-cdk-lib");
const glue = require("aws-cdk-lib/aws-glue");
class GlueCatalogStack extends cdk.Stack {
    constructor(scope, id, props) {
        super(scope, id, props);
        this.database = new glue.CfnDatabase(this, 'Database', {
            catalogId: this.account,
            databaseInput: {
                name: 'cx_analytics',
                description: 'Customer Experience Analytics Database',
            },
        });
        // Core tables
        this.createTable('customer_360', props.dataLakeBucket, 'processed/customer_360/');
        this.createTable('customer_health', props.dataLakeBucket, 'processed/customer_health/');
        this.createTable('cases', props.dataLakeBucket, 'raw/crm/cases/');
        this.createTable('vehicles', props.dataLakeBucket, 'raw/crm/vehicles/');
        this.createTable('service_appointments', props.dataLakeBucket, 'raw/crm/service_appointments/');
        this.createTable('nps_surveys', props.dataLakeBucket, 'raw/crm/surveys/');
        new cdk.CfnOutput(this, 'GlueDatabase', {
            value: this.database.ref,
            description: 'Glue Database Name',
        });
    }
    createTable(tableName, bucket, prefix) {
        new glue.CfnTable(this, `Table${tableName}`, {
            catalogId: this.account,
            databaseName: this.database.ref,
            tableInput: {
                name: tableName,
                storageDescriptor: {
                    location: `s3://${bucket.bucketName}/${prefix}`,
                    inputFormat: 'org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat',
                    outputFormat: 'org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat',
                    serdeInfo: {
                        serializationLibrary: 'org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe',
                    },
                },
                tableType: 'EXTERNAL_TABLE',
            },
        });
    }
}
exports.GlueCatalogStack = GlueCatalogStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiZ2x1ZS1jYXRhbG9nLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiZ2x1ZS1jYXRhbG9nLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7OztBQUFBLG1DQUFtQztBQUNuQyw2Q0FBNkM7QUFRN0MsTUFBYSxnQkFBaUIsU0FBUSxHQUFHLENBQUMsS0FBSztJQUc3QyxZQUFZLEtBQWdCLEVBQUUsRUFBVSxFQUFFLEtBQTRCO1FBQ3BFLEtBQUssQ0FBQyxLQUFLLEVBQUUsRUFBRSxFQUFFLEtBQUssQ0FBQyxDQUFDO1FBRXhCLElBQUksQ0FBQyxRQUFRLEdBQUcsSUFBSSxJQUFJLENBQUMsV0FBVyxDQUFDLElBQUksRUFBRSxVQUFVLEVBQUU7WUFDckQsU0FBUyxFQUFFLElBQUksQ0FBQyxPQUFPO1lBQ3ZCLGFBQWEsRUFBRTtnQkFDYixJQUFJLEVBQUUsY0FBYztnQkFDcEIsV0FBVyxFQUFFLHdDQUF3QzthQUN0RDtTQUNGLENBQUMsQ0FBQztRQUVILGNBQWM7UUFDZCxJQUFJLENBQUMsV0FBVyxDQUFDLGNBQWMsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLHlCQUF5QixDQUFDLENBQUM7UUFDbEYsSUFBSSxDQUFDLFdBQVcsQ0FBQyxpQkFBaUIsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLDRCQUE0QixDQUFDLENBQUM7UUFDeEYsSUFBSSxDQUFDLFdBQVcsQ0FBQyxPQUFPLEVBQUUsS0FBSyxDQUFDLGNBQWMsRUFBRSxnQkFBZ0IsQ0FBQyxDQUFDO1FBQ2xFLElBQUksQ0FBQyxXQUFXLENBQUMsVUFBVSxFQUFFLEtBQUssQ0FBQyxjQUFjLEVBQUUsbUJBQW1CLENBQUMsQ0FBQztRQUN4RSxJQUFJLENBQUMsV0FBVyxDQUFDLHNCQUFzQixFQUFFLEtBQUssQ0FBQyxjQUFjLEVBQUUsK0JBQStCLENBQUMsQ0FBQztRQUNoRyxJQUFJLENBQUMsV0FBVyxDQUFDLGFBQWEsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLGtCQUFrQixDQUFDLENBQUM7UUFFMUUsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxjQUFjLEVBQUU7WUFDdEMsS0FBSyxFQUFFLElBQUksQ0FBQyxRQUFRLENBQUMsR0FBRztZQUN4QixXQUFXLEVBQUUsb0JBQW9CO1NBQ2xDLENBQUMsQ0FBQztJQUNMLENBQUM7SUFFTyxXQUFXLENBQUMsU0FBaUIsRUFBRSxNQUFrQixFQUFFLE1BQWM7UUFDdkUsSUFBSSxJQUFJLENBQUMsUUFBUSxDQUFDLElBQUksRUFBRSxRQUFRLFNBQVMsRUFBRSxFQUFFO1lBQzNDLFNBQVMsRUFBRSxJQUFJLENBQUMsT0FBTztZQUN2QixZQUFZLEVBQUUsSUFBSSxDQUFDLFFBQVEsQ0FBQyxHQUFHO1lBQy9CLFVBQVUsRUFBRTtnQkFDVixJQUFJLEVBQUUsU0FBUztnQkFDZixpQkFBaUIsRUFBRTtvQkFDakIsUUFBUSxFQUFFLFFBQVEsTUFBTSxDQUFDLFVBQVUsSUFBSSxNQUFNLEVBQUU7b0JBQy9DLFdBQVcsRUFBRSwrREFBK0Q7b0JBQzVFLFlBQVksRUFBRSxnRUFBZ0U7b0JBQzlFLFNBQVMsRUFBRTt3QkFDVCxvQkFBb0IsRUFBRSw2REFBNkQ7cUJBQ3BGO2lCQUNGO2dCQUNELFNBQVMsRUFBRSxnQkFBZ0I7YUFDNUI7U0FDRixDQUFDLENBQUM7SUFDTCxDQUFDO0NBQ0Y7QUE5Q0QsNENBOENDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCAqIGFzIGdsdWUgZnJvbSAnYXdzLWNkay1saWIvYXdzLWdsdWUnO1xuaW1wb3J0ICogYXMgczMgZnJvbSAnYXdzLWNkay1saWIvYXdzLXMzJztcbmltcG9ydCB7IENvbnN0cnVjdCB9IGZyb20gJ2NvbnN0cnVjdHMnO1xuXG5leHBvcnQgaW50ZXJmYWNlIEdsdWVDYXRhbG9nU3RhY2tQcm9wcyBleHRlbmRzIGNkay5TdGFja1Byb3BzIHtcbiAgZGF0YUxha2VCdWNrZXQ6IHMzLklCdWNrZXQ7XG59XG5cbmV4cG9ydCBjbGFzcyBHbHVlQ2F0YWxvZ1N0YWNrIGV4dGVuZHMgY2RrLlN0YWNrIHtcbiAgcHVibGljIHJlYWRvbmx5IGRhdGFiYXNlOiBnbHVlLkNmbkRhdGFiYXNlO1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzOiBHbHVlQ2F0YWxvZ1N0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIHRoaXMuZGF0YWJhc2UgPSBuZXcgZ2x1ZS5DZm5EYXRhYmFzZSh0aGlzLCAnRGF0YWJhc2UnLCB7XG4gICAgICBjYXRhbG9nSWQ6IHRoaXMuYWNjb3VudCxcbiAgICAgIGRhdGFiYXNlSW5wdXQ6IHtcbiAgICAgICAgbmFtZTogJ2N4X2FuYWx5dGljcycsXG4gICAgICAgIGRlc2NyaXB0aW9uOiAnQ3VzdG9tZXIgRXhwZXJpZW5jZSBBbmFseXRpY3MgRGF0YWJhc2UnLFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIC8vIENvcmUgdGFibGVzXG4gICAgdGhpcy5jcmVhdGVUYWJsZSgnY3VzdG9tZXJfMzYwJywgcHJvcHMuZGF0YUxha2VCdWNrZXQsICdwcm9jZXNzZWQvY3VzdG9tZXJfMzYwLycpO1xuICAgIHRoaXMuY3JlYXRlVGFibGUoJ2N1c3RvbWVyX2hlYWx0aCcsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncHJvY2Vzc2VkL2N1c3RvbWVyX2hlYWx0aC8nKTtcbiAgICB0aGlzLmNyZWF0ZVRhYmxlKCdjYXNlcycsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L2NybS9jYXNlcy8nKTtcbiAgICB0aGlzLmNyZWF0ZVRhYmxlKCd2ZWhpY2xlcycsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L2NybS92ZWhpY2xlcy8nKTtcbiAgICB0aGlzLmNyZWF0ZVRhYmxlKCdzZXJ2aWNlX2FwcG9pbnRtZW50cycsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L2NybS9zZXJ2aWNlX2FwcG9pbnRtZW50cy8nKTtcbiAgICB0aGlzLmNyZWF0ZVRhYmxlKCducHNfc3VydmV5cycsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L2NybS9zdXJ2ZXlzLycpO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0dsdWVEYXRhYmFzZScsIHtcbiAgICAgIHZhbHVlOiB0aGlzLmRhdGFiYXNlLnJlZixcbiAgICAgIGRlc2NyaXB0aW9uOiAnR2x1ZSBEYXRhYmFzZSBOYW1lJyxcbiAgICB9KTtcbiAgfVxuXG4gIHByaXZhdGUgY3JlYXRlVGFibGUodGFibGVOYW1lOiBzdHJpbmcsIGJ1Y2tldDogczMuSUJ1Y2tldCwgcHJlZml4OiBzdHJpbmcpIHtcbiAgICBuZXcgZ2x1ZS5DZm5UYWJsZSh0aGlzLCBgVGFibGUke3RhYmxlTmFtZX1gLCB7XG4gICAgICBjYXRhbG9nSWQ6IHRoaXMuYWNjb3VudCxcbiAgICAgIGRhdGFiYXNlTmFtZTogdGhpcy5kYXRhYmFzZS5yZWYsXG4gICAgICB0YWJsZUlucHV0OiB7XG4gICAgICAgIG5hbWU6IHRhYmxlTmFtZSxcbiAgICAgICAgc3RvcmFnZURlc2NyaXB0b3I6IHtcbiAgICAgICAgICBsb2NhdGlvbjogYHMzOi8vJHtidWNrZXQuYnVja2V0TmFtZX0vJHtwcmVmaXh9YCxcbiAgICAgICAgICBpbnB1dEZvcm1hdDogJ29yZy5hcGFjaGUuaGFkb29wLmhpdmUucWwuaW8ucGFycXVldC5NYXByZWRQYXJxdWV0SW5wdXRGb3JtYXQnLFxuICAgICAgICAgIG91dHB1dEZvcm1hdDogJ29yZy5hcGFjaGUuaGFkb29wLmhpdmUucWwuaW8ucGFycXVldC5NYXByZWRQYXJxdWV0T3V0cHV0Rm9ybWF0JyxcbiAgICAgICAgICBzZXJkZUluZm86IHtcbiAgICAgICAgICAgIHNlcmlhbGl6YXRpb25MaWJyYXJ5OiAnb3JnLmFwYWNoZS5oYWRvb3AuaGl2ZS5xbC5pby5wYXJxdWV0LnNlcmRlLlBhcnF1ZXRIaXZlU2VyRGUnLFxuICAgICAgICAgIH0sXG4gICAgICAgIH0sXG4gICAgICAgIHRhYmxlVHlwZTogJ0VYVEVSTkFMX1RBQkxFJyxcbiAgICAgIH0sXG4gICAgfSk7XG4gIH1cbn1cbiJdfQ==