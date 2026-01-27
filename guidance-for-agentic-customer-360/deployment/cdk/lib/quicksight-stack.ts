import * as cdk from 'aws-cdk-lib';
import * as quicksight from 'aws-cdk-lib/aws-quicksight';
import { Construct } from 'constructs';

export interface QuickSightStackProps extends cdk.StackProps {
  readonly athenaWorkgroup: string;
  readonly glueDatabase: string;
}

export class QuickSightStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: QuickSightStackProps) {
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
      value: dataSource.dataSourceId!,
      description: 'QuickSight Data Source ID',
    });
  }
}
