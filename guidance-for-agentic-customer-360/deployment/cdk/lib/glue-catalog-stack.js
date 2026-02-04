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
        // Core tables - customer_360 and customer_health are discovered by crawler from /raw/
        // Removed: this.createTable('customer_360', props.dataLakeBucket, 'processed/customer_360/');
        // Removed: this.createTable('customer_health', props.dataLakeBucket, 'processed/customer_health/');
        this.createTable('cases', props.dataLakeBucket, 'raw/crm/cases/');
        this.createTable('vehicles', props.dataLakeBucket, 'raw/crm/vehicles/');
        this.createTable('service_appointments', props.dataLakeBucket, 'raw/crm/service_appointments/');
        this.createTable('nps_surveys', props.dataLakeBucket, 'raw/crm/surveys/');
        // New CSV tables for QuickSight
        this.createCSVTable('monthly_kpis', props.dataLakeBucket, 'raw/monthly_kpis/');
        this.createCSVTable('operational_kpis', props.dataLakeBucket, 'raw/operational_kpis/');
        this.createCSVTable('issue_categories', props.dataLakeBucket, 'raw/issue_categories/');
        this.createCSVTable('revenue_streams', props.dataLakeBucket, 'raw/revenue_streams/');
        this.createCSVTable('revenue_trends', props.dataLakeBucket, 'raw/revenue_trends/');
        this.createCSVTable('at_risk_revenue', props.dataLakeBucket, 'raw/at_risk_revenue/');
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
    createCSVTable(tableName, bucket, prefix) {
        new glue.CfnTable(this, `Table${tableName}`, {
            catalogId: this.account,
            databaseName: this.database.ref,
            tableInput: {
                name: tableName,
                storageDescriptor: {
                    location: `s3://${bucket.bucketName}/${prefix}`,
                    inputFormat: 'org.apache.hadoop.mapred.TextInputFormat',
                    outputFormat: 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat',
                    serdeInfo: {
                        serializationLibrary: 'org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe',
                        parameters: {
                            'field.delim': ',',
                            'skip.header.line.count': '1',
                        },
                    },
                },
                tableType: 'EXTERNAL_TABLE',
            },
        });
    }
}
exports.GlueCatalogStack = GlueCatalogStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiZ2x1ZS1jYXRhbG9nLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiZ2x1ZS1jYXRhbG9nLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7OztBQUFBLG1DQUFtQztBQUNuQyw2Q0FBNkM7QUFRN0MsTUFBYSxnQkFBaUIsU0FBUSxHQUFHLENBQUMsS0FBSztJQUc3QyxZQUFZLEtBQWdCLEVBQUUsRUFBVSxFQUFFLEtBQTRCO1FBQ3BFLEtBQUssQ0FBQyxLQUFLLEVBQUUsRUFBRSxFQUFFLEtBQUssQ0FBQyxDQUFDO1FBRXhCLElBQUksQ0FBQyxRQUFRLEdBQUcsSUFBSSxJQUFJLENBQUMsV0FBVyxDQUFDLElBQUksRUFBRSxVQUFVLEVBQUU7WUFDckQsU0FBUyxFQUFFLElBQUksQ0FBQyxPQUFPO1lBQ3ZCLGFBQWEsRUFBRTtnQkFDYixJQUFJLEVBQUUsY0FBYztnQkFDcEIsV0FBVyxFQUFFLHdDQUF3QzthQUN0RDtTQUNGLENBQUMsQ0FBQztRQUVILHNGQUFzRjtRQUN0Riw4RkFBOEY7UUFDOUYsb0dBQW9HO1FBQ3BHLElBQUksQ0FBQyxXQUFXLENBQUMsT0FBTyxFQUFFLEtBQUssQ0FBQyxjQUFjLEVBQUUsZ0JBQWdCLENBQUMsQ0FBQztRQUNsRSxJQUFJLENBQUMsV0FBVyxDQUFDLFVBQVUsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLG1CQUFtQixDQUFDLENBQUM7UUFDeEUsSUFBSSxDQUFDLFdBQVcsQ0FBQyxzQkFBc0IsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLCtCQUErQixDQUFDLENBQUM7UUFDaEcsSUFBSSxDQUFDLFdBQVcsQ0FBQyxhQUFhLEVBQUUsS0FBSyxDQUFDLGNBQWMsRUFBRSxrQkFBa0IsQ0FBQyxDQUFDO1FBRTFFLGdDQUFnQztRQUNoQyxJQUFJLENBQUMsY0FBYyxDQUFDLGNBQWMsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLG1CQUFtQixDQUFDLENBQUM7UUFDL0UsSUFBSSxDQUFDLGNBQWMsQ0FBQyxrQkFBa0IsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLHVCQUF1QixDQUFDLENBQUM7UUFDdkYsSUFBSSxDQUFDLGNBQWMsQ0FBQyxrQkFBa0IsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLHVCQUF1QixDQUFDLENBQUM7UUFDdkYsSUFBSSxDQUFDLGNBQWMsQ0FBQyxpQkFBaUIsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLHNCQUFzQixDQUFDLENBQUM7UUFDckYsSUFBSSxDQUFDLGNBQWMsQ0FBQyxnQkFBZ0IsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLHFCQUFxQixDQUFDLENBQUM7UUFDbkYsSUFBSSxDQUFDLGNBQWMsQ0FBQyxpQkFBaUIsRUFBRSxLQUFLLENBQUMsY0FBYyxFQUFFLHNCQUFzQixDQUFDLENBQUM7UUFFckYsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxjQUFjLEVBQUU7WUFDdEMsS0FBSyxFQUFFLElBQUksQ0FBQyxRQUFRLENBQUMsR0FBRztZQUN4QixXQUFXLEVBQUUsb0JBQW9CO1NBQ2xDLENBQUMsQ0FBQztJQUNMLENBQUM7SUFFTyxXQUFXLENBQUMsU0FBaUIsRUFBRSxNQUFrQixFQUFFLE1BQWM7UUFDdkUsSUFBSSxJQUFJLENBQUMsUUFBUSxDQUFDLElBQUksRUFBRSxRQUFRLFNBQVMsRUFBRSxFQUFFO1lBQzNDLFNBQVMsRUFBRSxJQUFJLENBQUMsT0FBTztZQUN2QixZQUFZLEVBQUUsSUFBSSxDQUFDLFFBQVEsQ0FBQyxHQUFHO1lBQy9CLFVBQVUsRUFBRTtnQkFDVixJQUFJLEVBQUUsU0FBUztnQkFDZixpQkFBaUIsRUFBRTtvQkFDakIsUUFBUSxFQUFFLFFBQVEsTUFBTSxDQUFDLFVBQVUsSUFBSSxNQUFNLEVBQUU7b0JBQy9DLFdBQVcsRUFBRSwrREFBK0Q7b0JBQzVFLFlBQVksRUFBRSxnRUFBZ0U7b0JBQzlFLFNBQVMsRUFBRTt3QkFDVCxvQkFBb0IsRUFBRSw2REFBNkQ7cUJBQ3BGO2lCQUNGO2dCQUNELFNBQVMsRUFBRSxnQkFBZ0I7YUFDNUI7U0FDRixDQUFDLENBQUM7SUFDTCxDQUFDO0lBRU8sY0FBYyxDQUFDLFNBQWlCLEVBQUUsTUFBa0IsRUFBRSxNQUFjO1FBQzFFLElBQUksSUFBSSxDQUFDLFFBQVEsQ0FBQyxJQUFJLEVBQUUsUUFBUSxTQUFTLEVBQUUsRUFBRTtZQUMzQyxTQUFTLEVBQUUsSUFBSSxDQUFDLE9BQU87WUFDdkIsWUFBWSxFQUFFLElBQUksQ0FBQyxRQUFRLENBQUMsR0FBRztZQUMvQixVQUFVLEVBQUU7Z0JBQ1YsSUFBSSxFQUFFLFNBQVM7Z0JBQ2YsaUJBQWlCLEVBQUU7b0JBQ2pCLFFBQVEsRUFBRSxRQUFRLE1BQU0sQ0FBQyxVQUFVLElBQUksTUFBTSxFQUFFO29CQUMvQyxXQUFXLEVBQUUsMENBQTBDO29CQUN2RCxZQUFZLEVBQUUsNERBQTREO29CQUMxRSxTQUFTLEVBQUU7d0JBQ1Qsb0JBQW9CLEVBQUUsb0RBQW9EO3dCQUMxRSxVQUFVLEVBQUU7NEJBQ1YsYUFBYSxFQUFFLEdBQUc7NEJBQ2xCLHdCQUF3QixFQUFFLEdBQUc7eUJBQzlCO3FCQUNGO2lCQUNGO2dCQUNELFNBQVMsRUFBRSxnQkFBZ0I7YUFDNUI7U0FDRixDQUFDLENBQUM7SUFDTCxDQUFDO0NBQ0Y7QUE3RUQsNENBNkVDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCAqIGFzIGdsdWUgZnJvbSAnYXdzLWNkay1saWIvYXdzLWdsdWUnO1xuaW1wb3J0ICogYXMgczMgZnJvbSAnYXdzLWNkay1saWIvYXdzLXMzJztcbmltcG9ydCB7IENvbnN0cnVjdCB9IGZyb20gJ2NvbnN0cnVjdHMnO1xuXG5leHBvcnQgaW50ZXJmYWNlIEdsdWVDYXRhbG9nU3RhY2tQcm9wcyBleHRlbmRzIGNkay5TdGFja1Byb3BzIHtcbiAgZGF0YUxha2VCdWNrZXQ6IHMzLklCdWNrZXQ7XG59XG5cbmV4cG9ydCBjbGFzcyBHbHVlQ2F0YWxvZ1N0YWNrIGV4dGVuZHMgY2RrLlN0YWNrIHtcbiAgcHVibGljIHJlYWRvbmx5IGRhdGFiYXNlOiBnbHVlLkNmbkRhdGFiYXNlO1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzOiBHbHVlQ2F0YWxvZ1N0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIHRoaXMuZGF0YWJhc2UgPSBuZXcgZ2x1ZS5DZm5EYXRhYmFzZSh0aGlzLCAnRGF0YWJhc2UnLCB7XG4gICAgICBjYXRhbG9nSWQ6IHRoaXMuYWNjb3VudCxcbiAgICAgIGRhdGFiYXNlSW5wdXQ6IHtcbiAgICAgICAgbmFtZTogJ2N4X2FuYWx5dGljcycsXG4gICAgICAgIGRlc2NyaXB0aW9uOiAnQ3VzdG9tZXIgRXhwZXJpZW5jZSBBbmFseXRpY3MgRGF0YWJhc2UnLFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIC8vIENvcmUgdGFibGVzIC0gY3VzdG9tZXJfMzYwIGFuZCBjdXN0b21lcl9oZWFsdGggYXJlIGRpc2NvdmVyZWQgYnkgY3Jhd2xlciBmcm9tIC9yYXcvXG4gICAgLy8gUmVtb3ZlZDogdGhpcy5jcmVhdGVUYWJsZSgnY3VzdG9tZXJfMzYwJywgcHJvcHMuZGF0YUxha2VCdWNrZXQsICdwcm9jZXNzZWQvY3VzdG9tZXJfMzYwLycpO1xuICAgIC8vIFJlbW92ZWQ6IHRoaXMuY3JlYXRlVGFibGUoJ2N1c3RvbWVyX2hlYWx0aCcsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncHJvY2Vzc2VkL2N1c3RvbWVyX2hlYWx0aC8nKTtcbiAgICB0aGlzLmNyZWF0ZVRhYmxlKCdjYXNlcycsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L2NybS9jYXNlcy8nKTtcbiAgICB0aGlzLmNyZWF0ZVRhYmxlKCd2ZWhpY2xlcycsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L2NybS92ZWhpY2xlcy8nKTtcbiAgICB0aGlzLmNyZWF0ZVRhYmxlKCdzZXJ2aWNlX2FwcG9pbnRtZW50cycsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L2NybS9zZXJ2aWNlX2FwcG9pbnRtZW50cy8nKTtcbiAgICB0aGlzLmNyZWF0ZVRhYmxlKCducHNfc3VydmV5cycsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L2NybS9zdXJ2ZXlzLycpO1xuICAgIFxuICAgIC8vIE5ldyBDU1YgdGFibGVzIGZvciBRdWlja1NpZ2h0XG4gICAgdGhpcy5jcmVhdGVDU1ZUYWJsZSgnbW9udGhseV9rcGlzJywgcHJvcHMuZGF0YUxha2VCdWNrZXQsICdyYXcvbW9udGhseV9rcGlzLycpO1xuICAgIHRoaXMuY3JlYXRlQ1NWVGFibGUoJ29wZXJhdGlvbmFsX2twaXMnLCBwcm9wcy5kYXRhTGFrZUJ1Y2tldCwgJ3Jhdy9vcGVyYXRpb25hbF9rcGlzLycpO1xuICAgIHRoaXMuY3JlYXRlQ1NWVGFibGUoJ2lzc3VlX2NhdGVnb3JpZXMnLCBwcm9wcy5kYXRhTGFrZUJ1Y2tldCwgJ3Jhdy9pc3N1ZV9jYXRlZ29yaWVzLycpO1xuICAgIHRoaXMuY3JlYXRlQ1NWVGFibGUoJ3JldmVudWVfc3RyZWFtcycsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L3JldmVudWVfc3RyZWFtcy8nKTtcbiAgICB0aGlzLmNyZWF0ZUNTVlRhYmxlKCdyZXZlbnVlX3RyZW5kcycsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L3JldmVudWVfdHJlbmRzLycpO1xuICAgIHRoaXMuY3JlYXRlQ1NWVGFibGUoJ2F0X3Jpc2tfcmV2ZW51ZScsIHByb3BzLmRhdGFMYWtlQnVja2V0LCAncmF3L2F0X3Jpc2tfcmV2ZW51ZS8nKTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdHbHVlRGF0YWJhc2UnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5kYXRhYmFzZS5yZWYsXG4gICAgICBkZXNjcmlwdGlvbjogJ0dsdWUgRGF0YWJhc2UgTmFtZScsXG4gICAgfSk7XG4gIH1cblxuICBwcml2YXRlIGNyZWF0ZVRhYmxlKHRhYmxlTmFtZTogc3RyaW5nLCBidWNrZXQ6IHMzLklCdWNrZXQsIHByZWZpeDogc3RyaW5nKSB7XG4gICAgbmV3IGdsdWUuQ2ZuVGFibGUodGhpcywgYFRhYmxlJHt0YWJsZU5hbWV9YCwge1xuICAgICAgY2F0YWxvZ0lkOiB0aGlzLmFjY291bnQsXG4gICAgICBkYXRhYmFzZU5hbWU6IHRoaXMuZGF0YWJhc2UucmVmLFxuICAgICAgdGFibGVJbnB1dDoge1xuICAgICAgICBuYW1lOiB0YWJsZU5hbWUsXG4gICAgICAgIHN0b3JhZ2VEZXNjcmlwdG9yOiB7XG4gICAgICAgICAgbG9jYXRpb246IGBzMzovLyR7YnVja2V0LmJ1Y2tldE5hbWV9LyR7cHJlZml4fWAsXG4gICAgICAgICAgaW5wdXRGb3JtYXQ6ICdvcmcuYXBhY2hlLmhhZG9vcC5oaXZlLnFsLmlvLnBhcnF1ZXQuTWFwcmVkUGFycXVldElucHV0Rm9ybWF0JyxcbiAgICAgICAgICBvdXRwdXRGb3JtYXQ6ICdvcmcuYXBhY2hlLmhhZG9vcC5oaXZlLnFsLmlvLnBhcnF1ZXQuTWFwcmVkUGFycXVldE91dHB1dEZvcm1hdCcsXG4gICAgICAgICAgc2VyZGVJbmZvOiB7XG4gICAgICAgICAgICBzZXJpYWxpemF0aW9uTGlicmFyeTogJ29yZy5hcGFjaGUuaGFkb29wLmhpdmUucWwuaW8ucGFycXVldC5zZXJkZS5QYXJxdWV0SGl2ZVNlckRlJyxcbiAgICAgICAgICB9LFxuICAgICAgICB9LFxuICAgICAgICB0YWJsZVR5cGU6ICdFWFRFUk5BTF9UQUJMRScsXG4gICAgICB9LFxuICAgIH0pO1xuICB9XG5cbiAgcHJpdmF0ZSBjcmVhdGVDU1ZUYWJsZSh0YWJsZU5hbWU6IHN0cmluZywgYnVja2V0OiBzMy5JQnVja2V0LCBwcmVmaXg6IHN0cmluZykge1xuICAgIG5ldyBnbHVlLkNmblRhYmxlKHRoaXMsIGBUYWJsZSR7dGFibGVOYW1lfWAsIHtcbiAgICAgIGNhdGFsb2dJZDogdGhpcy5hY2NvdW50LFxuICAgICAgZGF0YWJhc2VOYW1lOiB0aGlzLmRhdGFiYXNlLnJlZixcbiAgICAgIHRhYmxlSW5wdXQ6IHtcbiAgICAgICAgbmFtZTogdGFibGVOYW1lLFxuICAgICAgICBzdG9yYWdlRGVzY3JpcHRvcjoge1xuICAgICAgICAgIGxvY2F0aW9uOiBgczM6Ly8ke2J1Y2tldC5idWNrZXROYW1lfS8ke3ByZWZpeH1gLFxuICAgICAgICAgIGlucHV0Rm9ybWF0OiAnb3JnLmFwYWNoZS5oYWRvb3AubWFwcmVkLlRleHRJbnB1dEZvcm1hdCcsXG4gICAgICAgICAgb3V0cHV0Rm9ybWF0OiAnb3JnLmFwYWNoZS5oYWRvb3AuaGl2ZS5xbC5pby5IaXZlSWdub3JlS2V5VGV4dE91dHB1dEZvcm1hdCcsXG4gICAgICAgICAgc2VyZGVJbmZvOiB7XG4gICAgICAgICAgICBzZXJpYWxpemF0aW9uTGlicmFyeTogJ29yZy5hcGFjaGUuaGFkb29wLmhpdmUuc2VyZGUyLmxhenkuTGF6eVNpbXBsZVNlckRlJyxcbiAgICAgICAgICAgIHBhcmFtZXRlcnM6IHtcbiAgICAgICAgICAgICAgJ2ZpZWxkLmRlbGltJzogJywnLFxuICAgICAgICAgICAgICAnc2tpcC5oZWFkZXIubGluZS5jb3VudCc6ICcxJyxcbiAgICAgICAgICAgIH0sXG4gICAgICAgICAgfSxcbiAgICAgICAgfSxcbiAgICAgICAgdGFibGVUeXBlOiAnRVhURVJOQUxfVEFCTEUnLFxuICAgICAgfSxcbiAgICB9KTtcbiAgfVxufVxuIl19