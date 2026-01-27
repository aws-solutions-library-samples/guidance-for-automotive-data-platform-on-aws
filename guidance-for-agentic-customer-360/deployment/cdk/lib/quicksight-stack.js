"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.QuickSightStack = void 0;
const cdk = require("aws-cdk-lib");
const quicksight = require("aws-cdk-lib/aws-quicksight");
class QuickSightStack extends cdk.Stack {
    constructor(scope, id, props) {
        super(scope, id, props);
        // Data Source
        const dataSource = new quicksight.CfnDataSource(this, 'AthenaDataSource', {
            awsAccountId: this.account,
            dataSourceId: 'cx-analytics-athena',
            name: 'CX Analytics Athena',
            type: 'ATHENA',
            dataSourceParameters: {
                athenaParameters: {
                    workGroup: props.athenaWorkgroup,
                },
            },
        });
        // Datasets
        const customerHealthDataSet = new quicksight.CfnDataSet(this, 'CustomerHealthDataSet', {
            awsAccountId: this.account,
            dataSetId: 'customer-health-scores',
            name: 'Customer Health Scores',
            importMode: 'DIRECT_QUERY',
            physicalTableMap: {
                table1: {
                    relationalTable: {
                        dataSourceArn: dataSource.attrArn,
                        catalog: 'AwsDataCatalog',
                        schema: props.glueDatabase,
                        name: 'customer_health',
                        inputColumns: [
                            { name: 'customer_id', type: 'INTEGER' },
                            { name: 'health_score', type: 'DECIMAL' },
                            { name: 'health_segment', type: 'STRING' },
                            { name: 'total_revenue', type: 'DECIMAL' },
                            { name: 'total_cases', type: 'INTEGER' },
                            { name: 'open_cases', type: 'INTEGER' },
                        ],
                    },
                },
            },
        });
        const kpiTrendsDataSet = new quicksight.CfnDataSet(this, 'KPITrendsDataSet', {
            awsAccountId: this.account,
            dataSetId: 'kpi-trends',
            name: 'KPI Trends',
            importMode: 'DIRECT_QUERY',
            physicalTableMap: {
                table1: {
                    relationalTable: {
                        dataSourceArn: dataSource.attrArn,
                        catalog: 'AwsDataCatalog',
                        schema: props.glueDatabase,
                        name: 'kpi_trends_from_vehicles',
                        inputColumns: [
                            { name: 'total_vehicles', type: 'INTEGER' },
                            { name: 'avg_health_score', type: 'DECIMAL' },
                            { name: 'total_revenue', type: 'DECIMAL' },
                        ],
                    },
                },
            },
        });
        const operationalKPIsDataSet = new quicksight.CfnDataSet(this, 'OperationalKPIsDataSet', {
            awsAccountId: this.account,
            dataSetId: 'operational-kpis',
            name: 'Operational KPIs',
            importMode: 'DIRECT_QUERY',
            physicalTableMap: {
                table1: {
                    relationalTable: {
                        dataSourceArn: dataSource.attrArn,
                        catalog: 'AwsDataCatalog',
                        schema: props.glueDatabase,
                        name: 'operational_kpis',
                        inputColumns: [
                            { name: 'total_customers', type: 'INTEGER' },
                            { name: 'critical_customers', type: 'INTEGER' },
                            { name: 'customers_with_open_cases', type: 'INTEGER' },
                        ],
                    },
                },
            },
        });
        // Dashboard
        const dashboard = new quicksight.CfnDashboard(this, 'CustomerDashboard', {
            awsAccountId: this.account,
            dashboardId: 'customer-360-dashboard',
            name: 'Customer 360 Dashboard',
            definition: {
                dataSetIdentifierDeclarations: [
                    {
                        identifier: 'customer-health',
                        dataSetArn: customerHealthDataSet.attrArn,
                    },
                    {
                        identifier: 'kpi-trends',
                        dataSetArn: kpiTrendsDataSet.attrArn,
                    },
                    {
                        identifier: 'operational-kpis',
                        dataSetArn: operationalKPIsDataSet.attrArn,
                    },
                ],
                sheets: [
                    {
                        sheetId: 'overview-sheet',
                        name: 'Overview',
                        visuals: [
                            {
                                kpiVisual: {
                                    visualId: 'total-customers-kpi',
                                    title: {
                                        visibility: 'VISIBLE',
                                        formatText: {
                                            plainText: 'Total Customers',
                                        },
                                    },
                                    chartConfiguration: {
                                        fieldWells: {
                                            values: [
                                                {
                                                    numericalMeasureField: {
                                                        fieldId: 'total_customers',
                                                        column: {
                                                            dataSetIdentifier: 'operational-kpis',
                                                            columnName: 'total_customers',
                                                        },
                                                        aggregationFunction: {
                                                            simpleNumericalAggregation: 'SUM',
                                                        },
                                                    },
                                                },
                                            ],
                                        },
                                    },
                                },
                            },
                            {
                                kpiVisual: {
                                    visualId: 'avg-health-score-kpi',
                                    title: {
                                        visibility: 'VISIBLE',
                                        formatText: {
                                            plainText: 'Average Health Score',
                                        },
                                    },
                                    chartConfiguration: {
                                        fieldWells: {
                                            values: [
                                                {
                                                    numericalMeasureField: {
                                                        fieldId: 'avg_health_score',
                                                        column: {
                                                            dataSetIdentifier: 'kpi-trends',
                                                            columnName: 'avg_health_score',
                                                        },
                                                        aggregationFunction: {
                                                            simpleNumericalAggregation: 'AVERAGE',
                                                        },
                                                    },
                                                },
                                            ],
                                        },
                                    },
                                },
                            },
                            {
                                kpiVisual: {
                                    visualId: 'total-revenue-kpi',
                                    title: {
                                        visibility: 'VISIBLE',
                                        formatText: {
                                            plainText: 'Total Revenue',
                                        },
                                    },
                                    chartConfiguration: {
                                        fieldWells: {
                                            values: [
                                                {
                                                    numericalMeasureField: {
                                                        fieldId: 'total_revenue',
                                                        column: {
                                                            dataSetIdentifier: 'kpi-trends',
                                                            columnName: 'total_revenue',
                                                        },
                                                        aggregationFunction: {
                                                            simpleNumericalAggregation: 'SUM',
                                                        },
                                                    },
                                                },
                                            ],
                                        },
                                    },
                                },
                            },
                        ],
                    },
                ],
            },
        });
        dashboard.node.addDependency(customerHealthDataSet);
        dashboard.node.addDependency(kpiTrendsDataSet);
        dashboard.node.addDependency(operationalKPIsDataSet);
        // Outputs
        new cdk.CfnOutput(this, 'DashboardURL', {
            value: `https://${this.region}.quicksight.aws.amazon.com/sn/dashboards/${dashboard.dashboardId}`,
            description: 'QuickSight Dashboard URL',
        });
        new cdk.CfnOutput(this, 'DataSourceId', {
            value: dataSource.dataSourceId,
            description: 'QuickSight Data Source ID',
        });
    }
}
exports.QuickSightStack = QuickSightStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoicXVpY2tzaWdodC1zdGFjay5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbInF1aWNrc2lnaHQtc3RhY2sudHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7O0FBQUEsbUNBQW1DO0FBQ25DLHlEQUF5RDtBQVF6RCxNQUFhLGVBQWdCLFNBQVEsR0FBRyxDQUFDLEtBQUs7SUFDNUMsWUFBWSxLQUFnQixFQUFFLEVBQVUsRUFBRSxLQUEyQjtRQUNuRSxLQUFLLENBQUMsS0FBSyxFQUFFLEVBQUUsRUFBRSxLQUFLLENBQUMsQ0FBQztRQUV4QixjQUFjO1FBQ2QsTUFBTSxVQUFVLEdBQUcsSUFBSSxVQUFVLENBQUMsYUFBYSxDQUFDLElBQUksRUFBRSxrQkFBa0IsRUFBRTtZQUN4RSxZQUFZLEVBQUUsSUFBSSxDQUFDLE9BQU87WUFDMUIsWUFBWSxFQUFFLHFCQUFxQjtZQUNuQyxJQUFJLEVBQUUscUJBQXFCO1lBQzNCLElBQUksRUFBRSxRQUFRO1lBQ2Qsb0JBQW9CLEVBQUU7Z0JBQ3BCLGdCQUFnQixFQUFFO29CQUNoQixTQUFTLEVBQUUsS0FBSyxDQUFDLGVBQWU7aUJBQ2pDO2FBQ0Y7U0FDRixDQUFDLENBQUM7UUFFSCxXQUFXO1FBQ1gsTUFBTSxxQkFBcUIsR0FBRyxJQUFJLFVBQVUsQ0FBQyxVQUFVLENBQUMsSUFBSSxFQUFFLHVCQUF1QixFQUFFO1lBQ3JGLFlBQVksRUFBRSxJQUFJLENBQUMsT0FBTztZQUMxQixTQUFTLEVBQUUsd0JBQXdCO1lBQ25DLElBQUksRUFBRSx3QkFBd0I7WUFDOUIsVUFBVSxFQUFFLGNBQWM7WUFDMUIsZ0JBQWdCLEVBQUU7Z0JBQ2hCLE1BQU0sRUFBRTtvQkFDTixlQUFlLEVBQUU7d0JBQ2YsYUFBYSxFQUFFLFVBQVUsQ0FBQyxPQUFPO3dCQUNqQyxPQUFPLEVBQUUsZ0JBQWdCO3dCQUN6QixNQUFNLEVBQUUsS0FBSyxDQUFDLFlBQVk7d0JBQzFCLElBQUksRUFBRSxpQkFBaUI7d0JBQ3ZCLFlBQVksRUFBRTs0QkFD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RjtBQTVORCwwQ0E0TkMiLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0ICogYXMgcXVpY2tzaWdodCBmcm9tICdhd3MtY2RrLWxpYi9hd3MtcXVpY2tzaWdodCc7XG5pbXBvcnQgeyBDb25zdHJ1Y3QgfSBmcm9tICdjb25zdHJ1Y3RzJztcblxuZXhwb3J0IGludGVyZmFjZSBRdWlja1NpZ2h0U3RhY2tQcm9wcyBleHRlbmRzIGNkay5TdGFja1Byb3BzIHtcbiAgcmVhZG9ubHkgYXRoZW5hV29ya2dyb3VwOiBzdHJpbmc7XG4gIHJlYWRvbmx5IGdsdWVEYXRhYmFzZTogc3RyaW5nO1xufVxuXG5leHBvcnQgY2xhc3MgUXVpY2tTaWdodFN0YWNrIGV4dGVuZHMgY2RrLlN0YWNrIHtcbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM6IFF1aWNrU2lnaHRTdGFja1Byb3BzKSB7XG4gICAgc3VwZXIoc2NvcGUsIGlkLCBwcm9wcyk7XG5cbiAgICAvLyBEYXRhIFNvdXJjZVxuICAgIGNvbnN0IGRhdGFTb3VyY2UgPSBuZXcgcXVpY2tzaWdodC5DZm5EYXRhU291cmNlKHRoaXMsICdBdGhlbmFEYXRhU291cmNlJywge1xuICAgICAgYXdzQWNjb3VudElkOiB0aGlzLmFjY291bnQsXG4gICAgICBkYXRhU291cmNlSWQ6ICdjeC1hbmFseXRpY3MtYXRoZW5hJyxcbiAgICAgIG5hbWU6ICdDWCBBbmFseXRpY3MgQXRoZW5hJyxcbiAgICAgIHR5cGU6ICdBVEhFTkEnLFxuICAgICAgZGF0YVNvdXJjZVBhcmFtZXRlcnM6IHtcbiAgICAgICAgYXRoZW5hUGFyYW1ldGVyczoge1xuICAgICAgICAgIHdvcmtHcm91cDogcHJvcHMuYXRoZW5hV29ya2dyb3VwLFxuICAgICAgICB9LFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIC8vIERhdGFzZXRzXG4gICAgY29uc3QgY3VzdG9tZXJIZWFsdGhEYXRhU2V0ID0gbmV3IHF1aWNrc2lnaHQuQ2ZuRGF0YVNldCh0aGlzLCAnQ3VzdG9tZXJIZWFsdGhEYXRhU2V0Jywge1xuICAgICAgYXdzQWNjb3VudElkOiB0aGlzLmFjY291bnQsXG4gICAgICBkYXRhU2V0SWQ6ICdjdXN0b21lci1oZWFsdGgtc2NvcmVzJyxcbiAgICAgIG5hbWU6ICdDdXN0b21lciBIZWFsdGggU2NvcmVzJyxcbiAgICAgIGltcG9ydE1vZGU6ICdESVJFQ1RfUVVFUlknLFxuICAgICAgcGh5c2ljYWxUYWJsZU1hcDoge1xuICAgICAgICB0YWJsZTE6IHtcbiAgICAgICAgICByZWxhdGlvbmFsVGFibGU6IHtcbiAgICAgICAgICAgIGRhdGFTb3VyY2VBcm46IGRhdGFTb3VyY2UuYXR0ckFybixcbiAgICAgICAgICAgIGNhdGFsb2c6ICdBd3NEYXRhQ2F0YWxvZycsXG4gICAgICAgICAgICBzY2hlbWE6IHByb3BzLmdsdWVEYXRhYmFzZSxcbiAgICAgICAgICAgIG5hbWU6ICdjdXN0b21lcl9oZWFsdGgnLFxuICAgICAgICAgICAgaW5wdXRDb2x1bW5zOiBbXG4gICAgICAgICAgICAgIHsgbmFtZTogJ2N1c3RvbWVyX2lkJywgdHlwZTogJ0lOVEVHRVInIH0sXG4gICAgICAgICAgICAgIHsgbmFtZTogJ2hlYWx0aF9zY29yZScsIHR5cGU6ICdERUNJTUFMJyB9LFxuICAgICAgICAgICAgICB7IG5hbWU6ICdoZWFsdGhfc2VnbWVudCcsIHR5cGU6ICdTVFJJTkcnIH0sXG4gICAgICAgICAgICAgIHsgbmFtZTogJ3RvdGFsX3JldmVudWUnLCB0eXBlOiAnREVDSU1BTCcgfSxcbiAgICAgICAgICAgICAgeyBuYW1lOiAndG90YWxfY2FzZXMnLCB0eXBlOiAnSU5URUdFUicgfSxcbiAgICAgICAgICAgICAgeyBuYW1lOiAnb3Blbl9jYXNlcycsIHR5cGU6ICdJTlRFR0VSJyB9LFxuICAgICAgICAgICAgXSxcbiAgICAgICAgICB9LFxuICAgICAgICB9LFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIGNvbnN0IGtwaVRyZW5kc0RhdGFTZXQgPSBuZXcgcXVpY2tzaWdodC5DZm5EYXRhU2V0KHRoaXMsICdLUElUcmVuZHNEYXRhU2V0Jywge1xuICAgICAgYXdzQWNjb3VudElkOiB0aGlzLmFjY291bnQsXG4gICAgICBkYXRhU2V0SWQ6ICdrcGktdHJlbmRzJyxcbiAgICAgIG5hbWU6ICdLUEkgVHJlbmRzJyxcbiAgICAgIGltcG9ydE1vZGU6ICdESVJFQ1RfUVVFUlknLFxuICAgICAgcGh5c2ljYWxUYWJsZU1hcDoge1xuICAgICAgICB0YWJsZTE6IHtcbiAgICAgICAgICByZWxhdGlvbmFsVGFibGU6IHtcbiAgICAgICAgICAgIGRhdGFTb3VyY2VBcm46IGRhdGFTb3VyY2UuYXR0ckFybixcbiAgICAgICAgICAgIGNhdGFsb2c6ICdBd3NEYXRhQ2F0YWxvZycsXG4gICAgICAgICAgICBzY2hlbWE6IHByb3BzLmdsdWVEYXRhYmFzZSxcbiAgICAgICAgICAgIG5hbWU6ICdrcGlfdHJlbmRzX2Zyb21fdmVoaWNsZXMnLFxuICAgICAgICAgICAgaW5wdXRDb2x1bW5zOiBbXG4gICAgICAgICAgICAgIHsgbmFtZTogJ3RvdGFsX3ZlaGljbGVzJywgdHlwZTogJ0lOVEVHRVInIH0sXG4gICAgICAgICAgICAgIHsgbmFtZTogJ2F2Z19oZWFsdGhfc2NvcmUnLCB0eXBlOiAnREVDSU1BTCcgfSxcbiAgICAgICAgICAgICAgeyBuYW1lOiAndG90YWxfcmV2ZW51ZScsIHR5cGU6ICdERUNJTUFMJyB9LFxuICAgICAgICAgICAgXSxcbiAgICAgICAgICB9LFxuICAgICAgICB9LFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIGNvbnN0IG9wZXJhdGlvbmFsS1BJc0RhdGFTZXQgPSBuZXcgcXVpY2tzaWdodC5DZm5EYXRhU2V0KHRoaXMsICdPcGVyYXRpb25hbEtQSXNEYXRhU2V0Jywge1xuICAgICAgYXdzQWNjb3VudElkOiB0aGlzLmFjY291bnQsXG4gICAgICBkYXRhU2V0SWQ6ICdvcGVyYXRpb25hbC1rcGlzJyxcbiAgICAgIG5hbWU6ICdPcGVyYXRpb25hbCBLUElzJyxcbiAgICAgIGltcG9ydE1vZGU6ICdESVJFQ1RfUVVFUlknLFxuICAgICAgcGh5c2ljYWxUYWJsZU1hcDoge1xuICAgICAgICB0YWJsZTE6IHtcbiAgICAgICAgICByZWxhdGlvbmFsVGFibGU6IHtcbiAgICAgICAgICAgIGRhdGFTb3VyY2VBcm46IGRhdGFTb3VyY2UuYXR0ckFybixcbiAgICAgICAgICAgIGNhdGFsb2c6ICdBd3NEYXRhQ2F0YWxvZycsXG4gICAgICAgICAgICBzY2hlbWE6IHByb3BzLmdsdWVEYXRhYmFzZSxcbiAgICAgICAgICAgIG5hbWU6ICdvcGVyYXRpb25hbF9rcGlzJyxcbiAgICAgICAgICAgIGlucHV0Q29sdW1uczogW1xuICAgICAgICAgICAgICB7IG5hbWU6ICd0b3RhbF9jdXN0b21lcnMnLCB0eXBlOiAnSU5URUdFUicgfSxcbiAgICAgICAgICAgICAgeyBuYW1lOiAnY3JpdGljYWxfY3VzdG9tZXJzJywgdHlwZTogJ0lOVEVHRVInIH0sXG4gICAgICAgICAgICAgIHsgbmFtZTogJ2N1c3RvbWVyc193aXRoX29wZW5fY2FzZXMnLCB0eXBlOiAnSU5URUdFUicgfSxcbiAgICAgICAgICAgIF0sXG4gICAgICAgICAgfSxcbiAgICAgICAgfSxcbiAgICAgIH0sXG4gICAgfSk7XG5cbiAgICAvLyBEYXNoYm9hcmRcbiAgICBjb25zdCBkYXNoYm9hcmQgPSBuZXcgcXVpY2tzaWdodC5DZm5EYXNoYm9hcmQodGhpcywgJ0N1c3RvbWVyRGFzaGJvYXJkJywge1xuICAgICAgYXdzQWNjb3VudElkOiB0aGlzLmFjY291bnQsXG4gICAgICBkYXNoYm9hcmRJZDogJ2N1c3RvbWVyLTM2MC1kYXNoYm9hcmQnLFxuICAgICAgbmFtZTogJ0N1c3RvbWVyIDM2MCBEYXNoYm9hcmQnLFxuICAgICAgZGVmaW5pdGlvbjoge1xuICAgICAgICBkYXRhU2V0SWRlbnRpZmllckRlY2xhcmF0aW9uczogW1xuICAgICAgICAgIHtcbiAgICAgICAgICAgIGlkZW50aWZpZXI6ICdjdXN0b21lci1oZWFsdGgnLFxuICAgICAgICAgICAgZGF0YVNldEFybjogY3VzdG9tZXJIZWFsdGhEYXRhU2V0LmF0dHJBcm4sXG4gICAgICAgICAgfSxcbiAgICAgICAgICB7XG4gICAgICAgICAgICBpZGVudGlmaWVyOiAna3BpLXRyZW5kcycsXG4gICAgICAgICAgICBkYXRhU2V0QXJuOiBrcGlUcmVuZHNEYXRhU2V0LmF0dHJBcm4sXG4gICAgICAgICAgfSxcbiAgICAgICAgICB7XG4gICAgICAgICAgICBpZGVudGlmaWVyOiAnb3BlcmF0aW9uYWwta3BpcycsXG4gICAgICAgICAgICBkYXRhU2V0QXJuOiBvcGVyYXRpb25hbEtQSXNEYXRhU2V0LmF0dHJBcm4sXG4gICAgICAgICAgfSxcbiAgICAgICAgXSxcbiAgICAgICAgc2hlZXRzOiBbXG4gICAgICAgICAge1xuICAgICAgICAgICAgc2hlZXRJZDogJ292ZXJ2aWV3LXNoZWV0JyxcbiAgICAgICAgICAgIG5hbWU6ICdPdmVydmlldycsXG4gICAgICAgICAgICB2aXN1YWxzOiBbXG4gICAgICAgICAgICAgIHtcbiAgICAgICAgICAgICAgICBrcGlWaXN1YWw6IHtcbiAgICAgICAgICAgICAgICAgIHZpc3VhbElkOiAndG90YWwtY3VzdG9tZXJzLWtwaScsXG4gICAgICAgICAgICAgICAgICB0aXRsZToge1xuICAgICAgICAgICAgICAgICAgICB2aXNpYmlsaXR5OiAnVklTSUJMRScsXG4gICAgICAgICAgICAgICAgICAgIGZvcm1hdFRleHQ6IHtcbiAgICAgICAgICAgICAgICAgICAgICBwbGFpblRleHQ6ICdUb3RhbCBDdXN0b21lcnMnLFxuICAgICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgICAgfSxcbiAgICAgICAgICAgICAgICAgIGNoYXJ0Q29uZmlndXJhdGlvbjoge1xuICAgICAgICAgICAgICAgICAgICBmaWVsZFdlbGxzOiB7XG4gICAgICAgICAgICAgICAgICAgICAgdmFsdWVzOiBbXG4gICAgICAgICAgICAgICAgICAgICAgICB7XG4gICAgICAgICAgICAgICAgICAgICAgICAgIG51bWVyaWNhbE1lYXN1cmVGaWVsZDoge1xuICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZpZWxkSWQ6ICd0b3RhbF9jdXN0b21lcnMnLFxuICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNvbHVtbjoge1xuICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZGF0YVNldElkZW50aWZpZXI6ICdvcGVyYXRpb25hbC1rcGlzJyxcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNvbHVtbk5hbWU6ICd0b3RhbF9jdXN0b21lcnMnLFxuICAgICAgICAgICAgICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgICAgICAgICAgICAgICAgYWdncmVnYXRpb25GdW5jdGlvbjoge1xuICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgc2ltcGxlTnVtZXJpY2FsQWdncmVnYXRpb246ICdTVU0nLFxuICAgICAgICAgICAgICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgICAgICAgIF0sXG4gICAgICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgIHtcbiAgICAgICAgICAgICAgICBrcGlWaXN1YWw6IHtcbiAgICAgICAgICAgICAgICAgIHZpc3VhbElkOiAnYXZnLWhlYWx0aC1zY29yZS1rcGknLFxuICAgICAgICAgICAgICAgICAgdGl0bGU6IHtcbiAgICAgICAgICAgICAgICAgICAgdmlzaWJpbGl0eTogJ1ZJU0lCTEUnLFxuICAgICAgICAgICAgICAgICAgICBmb3JtYXRUZXh0OiB7XG4gICAgICAgICAgICAgICAgICAgICAgcGxhaW5UZXh0OiAnQXZlcmFnZSBIZWFsdGggU2NvcmUnLFxuICAgICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgICAgfSxcbiAgICAgICAgICAgICAgICAgIGNoYXJ0Q29uZmlndXJhdGlvbjoge1xuICAgICAgICAgICAgICAgICAgICBmaWVsZFdlbGxzOiB7XG4gICAgICAgICAgICAgICAgICAgICAgdmFsdWVzOiBbXG4gICAgICAgICAgICAgICAgICAgICAgICB7XG4gICAgICAgICAgICAgICAgICAgICAgICAgIG51bWVyaWNhbE1lYXN1cmVGaWVsZDoge1xuICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZpZWxkSWQ6ICdhdmdfaGVhbHRoX3Njb3JlJyxcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICBjb2x1bW46IHtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFTZXRJZGVudGlmaWVyOiAna3BpLXRyZW5kcycsXG4gICAgICAgICAgICAgICAgICAgICAgICAgICAgICBjb2x1bW5OYW1lOiAnYXZnX2hlYWx0aF9zY29yZScsXG4gICAgICAgICAgICAgICAgICAgICAgICAgICAgfSxcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICBhZ2dyZWdhdGlvbkZ1bmN0aW9uOiB7XG4gICAgICAgICAgICAgICAgICAgICAgICAgICAgICBzaW1wbGVOdW1lcmljYWxBZ2dyZWdhdGlvbjogJ0FWRVJBR0UnLFxuICAgICAgICAgICAgICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgICAgICAgIF0sXG4gICAgICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgIHtcbiAgICAgICAgICAgICAgICBrcGlWaXN1YWw6IHtcbiAgICAgICAgICAgICAgICAgIHZpc3VhbElkOiAndG90YWwtcmV2ZW51ZS1rcGknLFxuICAgICAgICAgICAgICAgICAgdGl0bGU6IHtcbiAgICAgICAgICAgICAgICAgICAgdmlzaWJpbGl0eTogJ1ZJU0lCTEUnLFxuICAgICAgICAgICAgICAgICAgICBmb3JtYXRUZXh0OiB7XG4gICAgICAgICAgICAgICAgICAgICAgcGxhaW5UZXh0OiAnVG90YWwgUmV2ZW51ZScsXG4gICAgICAgICAgICAgICAgICAgIH0sXG4gICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgICAgY2hhcnRDb25maWd1cmF0aW9uOiB7XG4gICAgICAgICAgICAgICAgICAgIGZpZWxkV2VsbHM6IHtcbiAgICAgICAgICAgICAgICAgICAgICB2YWx1ZXM6IFtcbiAgICAgICAgICAgICAgICAgICAgICAgIHtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgbnVtZXJpY2FsTWVhc3VyZUZpZWxkOiB7XG4gICAgICAgICAgICAgICAgICAgICAgICAgICAgZmllbGRJZDogJ3RvdGFsX3JldmVudWUnLFxuICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNvbHVtbjoge1xuICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZGF0YVNldElkZW50aWZpZXI6ICdrcGktdHJlbmRzJyxcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNvbHVtbk5hbWU6ICd0b3RhbF9yZXZlbnVlJyxcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgICAgICAgICAgICAgIGFnZ3JlZ2F0aW9uRnVuY3Rpb246IHtcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHNpbXBsZU51bWVyaWNhbEFnZ3JlZ2F0aW9uOiAnU1VNJyxcbiAgICAgICAgICAgICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgICAgICAgICAgfSxcbiAgICAgICAgICAgICAgICAgICAgICBdLFxuICAgICAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICAgICAgfSxcbiAgICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgICB9LFxuICAgICAgICAgICAgXSxcbiAgICAgICAgICB9LFxuICAgICAgICBdLFxuICAgICAgfSxcbiAgICB9KTtcblxuICAgIGRhc2hib2FyZC5ub2RlLmFkZERlcGVuZGVuY3koY3VzdG9tZXJIZWFsdGhEYXRhU2V0KTtcbiAgICBkYXNoYm9hcmQubm9kZS5hZGREZXBlbmRlbmN5KGtwaVRyZW5kc0RhdGFTZXQpO1xuICAgIGRhc2hib2FyZC5ub2RlLmFkZERlcGVuZGVuY3kob3BlcmF0aW9uYWxLUElzRGF0YVNldCk7XG5cbiAgICAvLyBPdXRwdXRzXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0Rhc2hib2FyZFVSTCcsIHtcbiAgICAgIHZhbHVlOiBgaHR0cHM6Ly8ke3RoaXMucmVnaW9ufS5xdWlja3NpZ2h0LmF3cy5hbWF6b24uY29tL3NuL2Rhc2hib2FyZHMvJHtkYXNoYm9hcmQuZGFzaGJvYXJkSWR9YCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnUXVpY2tTaWdodCBEYXNoYm9hcmQgVVJMJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdEYXRhU291cmNlSWQnLCB7XG4gICAgICB2YWx1ZTogZGF0YVNvdXJjZS5kYXRhU291cmNlSWQhLFxuICAgICAgZGVzY3JpcHRpb246ICdRdWlja1NpZ2h0IERhdGEgU291cmNlIElEJyxcbiAgICB9KTtcbiAgfVxufVxuIl19