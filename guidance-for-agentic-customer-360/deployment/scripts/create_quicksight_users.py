#!/usr/bin/env python3
"""
Create QuickSight-only users with separate passwords
"""

import boto3
import json
import os
import sys

# Get region and account
REGION = os.environ.get('AWS_REGION', 'us-east-1')
AWS_PROFILE = os.environ.get('AWS_PROFILE')

# Create session with explicit profile if provided
if AWS_PROFILE:
    session = boto3.Session(profile_name=AWS_PROFILE, region_name=REGION)
else:
    session = boto3.Session(region_name=REGION)

ACCOUNT_ID = os.environ.get('AWS_ACCOUNT_ID') or session.client('sts').get_caller_identity()['Account']

# Default user to create automatically
DEFAULT_USER = {
    'username': 'demo-viewer',
    'email': 'demo-viewer@example.com',
    'role': 'READER'
}

def create_quicksight_user(quicksight, username, email, role='READER'):
    """Create a QuickSight-only user"""
    try:
        response = quicksight.register_user(
            AwsAccountId=ACCOUNT_ID,
            Namespace='default',
            IdentityType='QUICKSIGHT',
            Email=email,
            UserRole=role,
            UserName=username
        )
        
        return {
            'success': True,
            'username': username,
            'email': email,
            'role': role,
            'user_arn': response['User']['Arn'],
            'invitation_url': response.get('UserInvitationUrl', 'N/A'),
            'status': response['User']['Active']
        }
    except quicksight.exceptions.ResourceExistsException:
        return {
            'success': False,
            'username': username,
            'error': 'User already exists'
        }
    except Exception as e:
        return {
            'success': False,
            'username': username,
            'error': str(e)
        }

def grant_dashboard_permissions(quicksight, user_arn, dashboard_id='customer-360-dashboard'):
    """Grant dashboard access to user"""
    try:
        quicksight.update_dashboard_permissions(
            AwsAccountId=ACCOUNT_ID,
            DashboardId=dashboard_id,
            GrantPermissions=[
                {
                    'Principal': user_arn,
                    'Actions': [
                        'quicksight:DescribeDashboard',
                        'quicksight:ListDashboardVersions',
                        'quicksight:QueryDashboard'
                    ]
                }
            ]
        )
        return True
    except Exception as e:
        print(f"  ⚠ Could not grant dashboard permissions: {e}")
        return False

def main():
    quicksight = session.client('quicksight')
    
    # Get QuickSight account name
    try:
        account_settings = quicksight.describe_account_settings(AwsAccountId=ACCOUNT_ID)
        account_name = account_settings['AccountSettings']['AccountName']
        print(f"QuickSight Account: {account_name}")
        print(f"AWS Account ID: {ACCOUNT_ID}")
        print(f"Region: {REGION}")
        print()
    except Exception as e:
        print(f"✗ Could not get QuickSight account settings: {e}")
        sys.exit(1)
    
    # Create default user
    print("Creating QuickSight demo user...")
    print("=" * 80)
    
    print(f"\nCreating user: {DEFAULT_USER['username']}")
    print(f"  Email: {DEFAULT_USER['email']}")
    print(f"  Role: {DEFAULT_USER['role']}")
    
    result = create_quicksight_user(
        quicksight,
        DEFAULT_USER['username'],
        DEFAULT_USER['email'],
        DEFAULT_USER['role']
    )
    
    created_users = []
    
    if result['success']:
        print(f"  ✓ User created successfully")
        print(f"  User ARN: {result['user_arn']}")
        
        # Grant dashboard permissions
        if grant_dashboard_permissions(quicksight, result['user_arn']):
            print(f"  ✓ Dashboard permissions granted")
        
        created_users.append(result)
    else:
        print(f"  ✗ Failed: {result['error']}")
        print(f"\nCreating user: {user_config['username']}")
        print(f"  Email: {user_config['email']}")
        print(f"  Role: {user_config['role']}")
        
        result = create_quicksight_user(
            quicksight,
            user_config['username'],
            user_config['email'],
            user_config['role']
        )
        
        if result['success']:
            print(f"  ✓ User created successfully")
            print(f"  User ARN: {result['user_arn']}")
            print(f"  Invitation URL: {result['invitation_url']}")
            
            # Grant dashboard permissions
            if grant_dashboard_permissions(quicksight, result['user_arn']):
                print(f"  ✓ Dashboard permissions granted")
            
            created_users.append(result)
        else:
            print(f"  ✗ Failed: {result['error']}")
    
    # Output summary
    print()
    print("=" * 80)
    print("✓ User creation complete!")
    print("=" * 80)
    print()
    
    print("QuickSight Login Information:")
    print(f"  QuickSight Account Name: {account_name}")
    print(f"  AWS Account ID: {ACCOUNT_ID}")
    print(f"  Sign-in URL: https://{REGION}.quicksight.aws.amazon.com/")
    print()
    
    if created_users:
        user = created_users[0]
        print("Demo User Created:")
        print(f"  Username: {user['username']}")
        print(f"  Role: {user['role']}")
        print()
        print("IMPORTANT: To set password for this user:")
        print(f"  1. Visit: {user['invitation_url']}")
        print(f"  2. Set a password")
        print(f"  3. Sign in at: https://{REGION}.quicksight.aws.amazon.com/")
        print(f"     - Account name: {account_name}")
        print(f"     - Username: {user['username']}")
        print(f"     - Password: (the one you just set)")
        
        # Save to file
        output_file = 'quicksight_users.json'
        with open(output_file, 'w') as f:
            json.dump({
                'quicksight_account_name': account_name,
                'aws_account_id': ACCOUNT_ID,
                'region': REGION,
                'signin_url': f"https://{REGION}.quicksight.aws.amazon.com/",
                'users': created_users
            }, f, indent=2)
        print(f"\n✓ User details saved to: {output_file}")
    else:
        print("User already exists or could not be created.")
        print(f"\nTo sign in with existing users:")
        print(f"  1. Go to: https://{REGION}.quicksight.aws.amazon.com/")
        print(f"  2. Enter QuickSight account name: {account_name}")
        print(f"  3. Sign in with your username and password")

if __name__ == '__main__':
    main()
