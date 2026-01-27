import * as cdk from 'aws-cdk-lib';
import * as glue from 'aws-cdk-lib/aws-glue';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface GlueCatalogStackProps extends cdk.StackProps {
  dataLakeBucket: s3.IBucket;
}

export class GlueCatalogStack extends cdk.Stack {
  public readonly database: glue.CfnDatabase;

  constructor(scope: Construct, id: string, props: GlueCatalogStackProps) {
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

  private createTable(tableName: string, bucket: s3.IBucket, prefix: string) {
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

  private createCSVTable(tableName: string, bucket: s3.IBucket, prefix: string) {
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
