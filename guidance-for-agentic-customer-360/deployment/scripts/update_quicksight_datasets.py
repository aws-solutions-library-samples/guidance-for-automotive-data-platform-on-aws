#!/usr/bin/env python3
"""
Update QuickSight datasets to use new Athena views with correct schemas
"""

import boto3
import time
import sys
import os

# Get region first, then account
REGION = os.environ.get('AWS_REGION', 'us-east-1')
AWS_PROFILE = os.environ.get('AWS_PROFILE')

# Create session with explicit profile if provided
if AWS_PROFILE:
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
else:
    session = boto3.Session(region_name=REGION)

ACCOUNT_ID = os.environ.get('AWS_ACCOUNT_ID') or session.client('sts').get_caller_identity()['Account']
DATA_SOURCE_ARN = f"arn:aws:quicksight:{REGION}:{ACCOUNT_ID}:datasource/cx-analytics-athena"

# Dataset mappings: dataset-id -> view-name
DATASETS = {
    "kpi-trends": "kpi_trends",
    "operational-kpis": "operational_kpis",
    "customer-health-scores": "customer_health_scores",
    "at-risk-revenue": "at_risk_revenue_view",
    "customer-360": "customer_360_view",
    "issue-categories": "issue_categories_view",
    "revenue-breakdown": "revenue_breakdown",
    "top-revenue-stream": "top_revenue_stream"
}

def main():
    quicksight = session.client('quicksight')
    glue = session.client('glue')
    
    print("Updating QuickSight datasets...")
    print("=" * 60)
    
    for dataset_id, view_name in DATASETS.items():
        print(f"\nUpdating dataset: {dataset_id} -> view: {view_name}")
        
        # Get table schema from Glue
        try:
            response = glue.get_table(DatabaseName='cx_analytics', Name=view_name)
            columns = response['Table']['StorageDescriptor']['Columns']
            
            # Map Glue types to QuickSight types
            type_mapping = {
                'bigint': 'INTEGER',
                'double': 'DECIMAL',
                'string': 'STRING',
                'int': 'INTEGER',
                'float': 'DECIMAL',
                'boolean': 'BOOLEAN',
                'timestamp': 'DATETIME',
                'date': 'DATETIME'
            }
            
            # Special column type overrides for QuickSight compatibility
            column_type_overrides = {
                'month_date': 'DATETIME',
                'snapshot_month': 'DATETIME',
                'customer_id': 'STRING',
                'user_id': 'STRING',
                'last_interaction_date': 'DATETIME',
                'first_purchase_date': 'DATETIME',
                'last_purchase_date': 'DATETIME'
            }
            
            input_columns = [
                {
                    'Name': col['Name'],
                    'Type': column_type_overrides.get(col['Name'], type_mapping.get(col['Type'].lower(), 'STRING'))
                }
                for col in columns
            ]
            
            print(f"  Found {len(input_columns)} columns in {view_name}")
            
        except Exception as e:
            print(f"  ✗ Failed to get schema for {view_name}: {e}")
            continue
        
        # Delete existing dataset
        try:
            quicksight.delete_data_set(
                AwsAccountId=ACCOUNT_ID,
                DataSetId=dataset_id
            )
            print(f"  Deleted existing dataset {dataset_id}")
            time.sleep(2)
        except quicksight.exceptions.ResourceNotFoundException:
            print(f"  Dataset {dataset_id} doesn't exist, creating new")
        except Exception as e:
            print(f"  Warning: Could not delete dataset: {e}")
        
        # Create new dataset
        try:
            quicksight.create_data_set(
                AwsAccountId=ACCOUNT_ID,
                DataSetId=dataset_id,
                Name=dataset_id,
                PhysicalTableMap={
                    dataset_id: {
                        'RelationalTable': {
                            'DataSourceArn': DATA_SOURCE_ARN,
                            'Catalog': 'AwsDataCatalog',
                            'Schema': 'cx_analytics',
                            'Name': view_name,
                            'InputColumns': input_columns
                        }
                    }
                },
                ImportMode='DIRECT_QUERY'
            )
            print(f"  ✓ Dataset {dataset_id} created successfully")
            
        except Exception as e:
            print(f"  ✗ Failed to create dataset {dataset_id}: {e}")
            continue
    
    print("\n" + "=" * 60)
    print("Dataset update complete!")
    print("\nNext step: Import dashboard definition")

if __name__ == '__main__':
    main()
