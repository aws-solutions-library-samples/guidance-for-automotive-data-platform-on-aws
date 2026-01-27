#!/usr/bin/env python3
"""
Import QuickSight dashboard from local definition file with updated dataset ARNs
"""

import boto3
import json
import sys
import os

# Read dashboard definition from local file
DASHBOARD_DEFINITION_FILE = os.path.join(
    os.path.dirname(__file__), 
    '../quicksight/dashboard-definition.json'
)

# Get region first, then account
TARGET_REGION = os.environ.get('AWS_REGION', 'us-east-1')
AWS_PROFILE = os.environ.get('AWS_PROFILE')

# Create session with explicit profile if provided
if AWS_PROFILE:
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=TARGET_REGION)
else:
    session = boto3.Session(region_name=TARGET_REGION)

TARGET_ACCOUNT = os.environ.get('AWS_ACCOUNT_ID') or session.client('sts').get_caller_identity()['Account']
TARGET_ANALYSIS_ID = "customer-360-analysis"
TARGET_ANALYSIS_NAME = "Customer 360 Analytics (Analysis)"
TARGET_DASHBOARD_ID = "customer-360-dashboard"
TARGET_DASHBOARD_NAME = "Customer 360 Analytics"

# Dataset ARN mappings - map source identifiers to target ARNs
DATASET_ARNS = {
    "Issue Categories": f"arn:aws:quicksight:{TARGET_REGION}:{TARGET_ACCOUNT}:dataset/issue-categories",
    "At-Risk Revenue": f"arn:aws:quicksight:{TARGET_REGION}:{TARGET_ACCOUNT}:dataset/at-risk-revenue",
    "KPI Trends": f"arn:aws:quicksight:{TARGET_REGION}:{TARGET_ACCOUNT}:dataset/kpi-trends",
    "customer-health-scores": f"arn:aws:quicksight:{TARGET_REGION}:{TARGET_ACCOUNT}:dataset/customer-health-scores",
    "Revenue Breakdown": f"arn:aws:quicksight:{TARGET_REGION}:{TARGET_ACCOUNT}:dataset/revenue-breakdown",
    "Top Revenue Stream": f"arn:aws:quicksight:{TARGET_REGION}:{TARGET_ACCOUNT}:dataset/top-revenue-stream",
    "Customer 360": f"arn:aws:quicksight:{TARGET_REGION}:{TARGET_ACCOUNT}:dataset/customer-360",
    "Operational KPIs": f"arn:aws:quicksight:{TARGET_REGION}:{TARGET_ACCOUNT}:dataset/operational-kpis"
}

def main():
    # Load dashboard definition from local file
    print(f"Loading dashboard definition from {DASHBOARD_DEFINITION_FILE}...")
    
    try:
        with open(DASHBOARD_DEFINITION_FILE, 'r') as f:
            definition = json.load(f)
        print(f"  ✓ Loaded dashboard definition")
    except FileNotFoundError:
        print(f"  ✗ Dashboard definition file not found: {DASHBOARD_DEFINITION_FILE}")
        print(f"  Run this command to export it:")
        print(f"  aws quicksight describe-dashboard-definition --aws-account-id <SOURCE_ACCOUNT> --dashboard-id <DASHBOARD_ID> --region us-east-1 --profile <PROFILE> --query 'Definition' --output json > {DASHBOARD_DEFINITION_FILE}")
        sys.exit(1)
    except Exception as e:
        print(f"  ✗ Failed to load dashboard definition: {e}")
        sys.exit(1)
    
    # Replace all source account IDs with target account ID
    print("\nReplacing account IDs in definition...")
    definition_str = json.dumps(definition)
    # Find source account ID from the definition
    import re
    source_accounts = re.findall(r'arn:aws:quicksight:[^:]+:(\d{12}):', definition_str)
    if source_accounts:
        source_account = source_accounts[0]
        print(f"  Replacing {source_account} with {TARGET_ACCOUNT}")
        definition_str = definition_str.replace(source_account, TARGET_ACCOUNT)
        definition = json.loads(definition_str)
    
    # Update dataset ARNs in definition
    print("\nUpdating dataset ARNs...")
    if 'DataSetIdentifierDeclarations' in definition:
        for dataset_decl in definition['DataSetIdentifierDeclarations']:
            identifier = dataset_decl['Identifier']
            if identifier in DATASET_ARNS:
                old_arn = dataset_decl['DataSetArn']
                new_arn = DATASET_ARNS[identifier]
                dataset_decl['DataSetArn'] = new_arn
                print(f"  {identifier}: {old_arn} -> {new_arn}")
    
    # Get QuickSight user for permissions
    target_qs = session.client('quicksight')
    try:
        users_response = target_qs.list_users(
            AwsAccountId=TARGET_ACCOUNT,
            Namespace='default'
        )
        if users_response['UserList']:
            user_arn = users_response['UserList'][0]['Arn']
            print(f"\nFound QuickSight user: {user_arn}")
        else:
            user_arn = None
            print("\n⚠ No QuickSight users found")
    except Exception as e:
        user_arn = None
        print(f"\n⚠ Could not get QuickSight user: {e}")
    
    # Create analysis in target account
    print(f"\nCreating analysis in target account {TARGET_ACCOUNT}...")
    
    # Delete existing analysis if it exists
    try:
        target_qs.delete_analysis(
            AwsAccountId=TARGET_ACCOUNT,
            AnalysisId=TARGET_ANALYSIS_ID
        )
        print(f"  Deleted existing analysis {TARGET_ANALYSIS_ID}")
        import time
        time.sleep(3)
    except target_qs.exceptions.ResourceNotFoundException:
        print(f"  Analysis {TARGET_ANALYSIS_ID} doesn't exist, creating new")
    except Exception as e:
        print(f"  Warning: Could not delete analysis: {e}")
    
    # Create analysis
    try:
        response = target_qs.create_analysis(
            AwsAccountId=TARGET_ACCOUNT,
            AnalysisId=TARGET_ANALYSIS_ID,
            Name=TARGET_ANALYSIS_NAME,
            Definition=definition
        )
        
        print(f"  ✓ Analysis created successfully")
        print(f"  Analysis ID: {TARGET_ANALYSIS_ID}")
        print(f"  Analysis ARN: {response['Arn']}")
        
        # Grant analysis permissions
        print("\nGranting analysis permissions...")
        if user_arn:
            try:
                import time
                time.sleep(3)
                target_qs.update_analysis_permissions(
                    AwsAccountId=TARGET_ACCOUNT,
                    AnalysisId=TARGET_ANALYSIS_ID,
                    GrantPermissions=[
                        {
                            'Principal': user_arn,
                            'Actions': [
                                'quicksight:RestoreAnalysis',
                                'quicksight:UpdateAnalysisPermissions',
                                'quicksight:DeleteAnalysis',
                                'quicksight:DescribeAnalysisPermissions',
                                'quicksight:QueryAnalysis',
                                'quicksight:DescribeAnalysis',
                                'quicksight:UpdateAnalysis'
                            ]
                        }
                    ]
                )
                print(f"  ✓ Analysis permissions granted")
            except Exception as e:
                print(f"  ⚠ Analysis permissions warning: {e}")
            
            # Grant dataset permissions
            print("\nGranting dataset permissions...")
            dataset_ids = ['kpi-trends', 'operational-kpis', 'customer-health-scores', 
                          'at-risk-revenue', 'customer-360', 'issue-categories', 
                          'revenue-breakdown', 'top-revenue-stream']
            
            for dataset_id in dataset_ids:
                try:
                    target_qs.update_data_set_permissions(
                        AwsAccountId=TARGET_ACCOUNT,
                        DataSetId=dataset_id,
                        GrantPermissions=[
                            {
                                'Principal': user_arn,
                                'Actions': [
                                    'quicksight:DescribeDataSet',
                                    'quicksight:DescribeDataSetPermissions',
                                    'quicksight:PassDataSet',
                                    'quicksight:DescribeIngestion',
                                    'quicksight:ListIngestions',
                                    'quicksight:UpdateDataSet',
                                    'quicksight:DeleteDataSet',
                                    'quicksight:CreateIngestion',
                                    'quicksight:CancelIngestion',
                                    'quicksight:UpdateDataSetPermissions'
                                ]
                            }
                        ]
                    )
                    print(f"  ✓ {dataset_id}")
                except Exception as e:
                    print(f"  ⚠ {dataset_id}: {e}")
        
    except Exception as e:
        print(f"  ✗ Failed to create analysis: {e}")
        return 1
    
    print(f"\n{'='*60}")
    print("✓ Analysis creation complete!")
    print(f"{'='*60}")
    print(f"\nEdit analysis at:")
    print(f"https://{TARGET_REGION}.quicksight.aws.amazon.com/sn/analyses/{TARGET_ANALYSIS_ID}")
    
    # Create dashboard with same definition
    print(f"\nCreating dashboard with same definition...")
    try:
        # Delete existing dashboard
        try:
            target_qs.delete_dashboard(
                AwsAccountId=TARGET_ACCOUNT,
                DashboardId=TARGET_DASHBOARD_ID
            )
            print(f"  Deleted existing dashboard")
            import time
            time.sleep(3)
        except target_qs.exceptions.ResourceNotFoundException:
            print(f"  No existing dashboard to delete")
        
        # Create dashboard with definition
        dashboard_response = target_qs.create_dashboard(
            AwsAccountId=TARGET_ACCOUNT,
            DashboardId=TARGET_DASHBOARD_ID,
            Name=TARGET_DASHBOARD_NAME,
            Definition=definition
        )
        
        print(f"  ✓ Dashboard created")
        
        # Wait and publish
        import time
        time.sleep(5)
        version_response = target_qs.describe_dashboard(
            AwsAccountId=TARGET_ACCOUNT,
            DashboardId=TARGET_DASHBOARD_ID
        )
        version_number = version_response['Dashboard']['Version']['VersionNumber']
        
        target_qs.update_dashboard_published_version(
            AwsAccountId=TARGET_ACCOUNT,
            DashboardId=TARGET_DASHBOARD_ID,
            VersionNumber=version_number
        )
        print(f"  ✓ Dashboard published (version {version_number})")
        
        # Grant dashboard permissions
        if user_arn:
            try:
                target_qs.update_dashboard_permissions(
                    AwsAccountId=TARGET_ACCOUNT,
                    DashboardId=TARGET_DASHBOARD_ID,
                    GrantPermissions=[
                        {
                            'Principal': user_arn,
                            'Actions': [
                                'quicksight:DescribeDashboard',
                                'quicksight:ListDashboardVersions',
                                'quicksight:UpdateDashboardPermissions',
                                'quicksight:QueryDashboard',
                                'quicksight:UpdateDashboard',
                                'quicksight:DeleteDashboard',
                                'quicksight:DescribeDashboardPermissions',
                                'quicksight:UpdateDashboardPublishedVersion'
                            ]
                        }
                    ]
                )
                print(f"  ✓ Dashboard permissions granted")
            except Exception as e:
                print(f"  ⚠ Dashboard permissions warning: {e}")
        
        print(f"\nView dashboard at:")
        print(f"https://{TARGET_REGION}.quicksight.aws.amazon.com/sn/dashboards/{TARGET_DASHBOARD_ID}")
        
    except Exception as e:
        print(f"  ⚠ Could not create dashboard: {e}")
        print(f"  Analysis is available for manual publishing")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
