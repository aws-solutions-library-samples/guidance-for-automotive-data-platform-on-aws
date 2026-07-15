#!/usr/bin/env python3
"""
Generate synthetic Customer 360 data and upload to S3 data lake.
Creates CSV files for customers, interactions, service records, and more.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import argparse
import boto3
from io import StringIO
import sys

# Seed for reproducibility
random.seed(42)
np.random.seed(42)

def generate_customers(num_customers=500000):
    """Generate customer profiles"""
    print(f"Generating {num_customers:,} customers...")
    
    customer_ids = list(range(1, num_customers + 1))
    
    # Realistic distributions
    segments = np.random.choice(
        ['Enterprise', 'Mid-Market', 'SMB', 'Consumer'],
        size=num_customers,
        p=[0.05, 0.15, 0.30, 0.50]
    )
    
    # Account creation dates (2015-2024 with growth)
    start_date = datetime(2015, 1, 1)
    end_date = datetime(2024, 12, 31)
    days_range = (end_date - start_date).days
    
    # Weighted towards recent years
    creation_dates = [
        start_date + timedelta(days=int(days_range * (i/num_customers)**0.5))
        for i in range(num_customers)
    ]
    
    # Revenue based on segment
    revenue_ranges = {
        'Enterprise': (10000, 50000),
        'Mid-Market': (4000, 10000),
        'SMB': (2000, 4000),
        'Consumer': (500, 2000)
    }
    
    revenues = [
        random.uniform(*revenue_ranges[seg]) for seg in segments
    ]
    
    df = pd.DataFrame({
        'customer_id': customer_ids,
        'customer_segment': segments,
        'account_created_date': creation_dates,
        'total_revenue': revenues,
        'status': 'active'
    })
    
    return df

def generate_customer_health(customers_df):
    """Generate customer health scores"""
    print("Generating customer health scores...")
    
    num_customers = len(customers_df)
    
    # Health score distribution (bell curve around 60)
    health_scores = np.random.normal(60, 20, num_customers)
    health_scores = np.clip(health_scores, 0, 100)
    
    # Health segments based on score
    def get_segment(score):
        if score >= 70: return 'Healthy'
        if score >= 50: return 'Needs Attention'
        if score >= 30: return 'At Risk'
        return 'Critical'
    
    health_segments = [get_segment(s) for s in health_scores]
    
    # Satisfaction scores (1-5)
    satisfaction = np.random.normal(4.0, 0.8, num_customers)
    satisfaction = np.clip(satisfaction, 1, 5)
    
    # Satisfaction buckets
    def get_satisfaction_bucket(score):
        if score >= 4.5: return 'Very Satisfied'
        if score >= 3.5: return 'Satisfied'
        if score >= 2.5: return 'Neutral'
        return 'Dissatisfied'
    
    satisfaction_buckets = [get_satisfaction_bucket(s) for s in satisfaction]
    
    # Cases and service appointments
    total_cases = np.random.poisson(3, num_customers)
    open_cases = np.random.binomial(total_cases, 0.2)
    service_appointments = np.random.poisson(4, num_customers)
    
    # Vehicles (1-5, weighted towards 1-2)
    vehicles = np.random.choice([1, 2, 3, 4, 5], num_customers, p=[0.5, 0.3, 0.15, 0.04, 0.01])
    
    # Battery related cases (subset of total cases)
    battery_cases = np.random.binomial(total_cases, 0.15)  # 15% of cases are battery related
    
    # Calculate is_at_risk and at_risk_revenue
    is_at_risk = health_scores < 60
    at_risk_revenue = np.where(is_at_risk, customers_df['total_revenue'], 0)
    
    df = pd.DataFrame({
        'customer_id': customers_df['customer_id'],
        'user_id': customers_df['customer_id'],  # Same as customer_id for simplicity
        'health_score': health_scores.round(2),
        'health_segment': health_segments,
        'total_revenue': customers_df['total_revenue'],
        'avg_satisfaction_score': satisfaction.round(2),
        'satisfaction_bucket': satisfaction_buckets,
        'total_cases': total_cases,
        'open_cases': open_cases,
        'total_vehicles': vehicles,
        'total_service_spend': (customers_df['total_revenue'] * 0.15).round(2),
        'total_service_appointments': service_appointments,
        'opportunity_count': np.random.poisson(2, num_customers),
        'customer_count': 1,  # For aggregations
        'is_at_risk': is_at_risk.astype(int),
        'at_risk_revenue': at_risk_revenue.round(2),
        'battery_related_cases': battery_cases,
        'clv': customers_df['total_revenue'].round(2),  # CLV same as total_revenue for now
        'avg_sentiment': np.random.uniform(-0.2, 0.8, num_customers).round(2),  # Mostly positive
        'last_interaction_date': customers_df['account_created_date'] + pd.to_timedelta(np.random.randint(0, 365, num_customers), unit='D'),
        'first_purchase_date': customers_df['account_created_date'],
        'last_purchase_date': customers_df['account_created_date'] + pd.to_timedelta(np.random.randint(0, 365, num_customers), unit='D')
    })
    
    return df

def generate_interactions(customers_df, num_interactions_per_customer=4):
    """Generate customer interactions"""
    print(f"Generating interactions ({num_interactions_per_customer} per customer avg)...")
    
    interaction_types = ['call', 'email', 'chat', 'service', 'app']
    sentiments = ['positive', 'neutral', 'negative']
    
    interactions = []
    interaction_id = 1
    
    # Sample customers for interactions (not all customers have interactions)
    sample_size = int(len(customers_df) * 0.7)  # 70% of customers
    sampled_customers = customers_df.sample(n=sample_size)
    
    for _, customer in sampled_customers.iterrows():
        num_interactions = np.random.poisson(num_interactions_per_customer)
        
        for _ in range(num_interactions):
            # Interaction date between account creation and now
            days_since_creation = (datetime.now() - customer['account_created_date']).days
            if days_since_creation > 0:
                interaction_date = customer['account_created_date'] + timedelta(
                    days=random.randint(0, days_since_creation)
                )
            else:
                interaction_date = customer['account_created_date']
            
            interactions.append({
                'interaction_id': interaction_id,
                'customer_id': customer['customer_id'],
                'interaction_date': interaction_date,
                'interaction_type': random.choice(interaction_types),
                'sentiment': random.choice(sentiments),
                'sentiment_score': round(random.uniform(-1, 1), 2)
            })
            interaction_id += 1
    
    return pd.DataFrame(interactions)

def generate_service_records(customers_df, num_records_per_customer=3):
    """Generate service appointment records"""
    print(f"Generating service records ({num_records_per_customer} per customer avg)...")
    
    service_types = ['Maintenance', 'Repair', 'Inspection', 'Warranty', 'Recall']
    
    records = []
    record_id = 1
    
    # Sample customers for service records
    sample_size = int(len(customers_df) * 0.6)  # 60% of customers
    sampled_customers = customers_df.sample(n=sample_size)
    
    for _, customer in sampled_customers.iterrows():
        num_records = np.random.poisson(num_records_per_customer)
        
        for _ in range(num_records):
            days_since_creation = (datetime.now() - customer['account_created_date']).days
            if days_since_creation > 0:
                service_date = customer['account_created_date'] + timedelta(
                    days=random.randint(0, days_since_creation)
                )
            else:
                service_date = customer['account_created_date']
            
            records.append({
                'service_id': record_id,
                'customer_id': customer['customer_id'],
                'service_date': service_date,
                'service_type': random.choice(service_types),
                'cost': round(random.uniform(100, 2000), 2),
                'satisfaction_rating': random.randint(1, 5)
            })
            record_id += 1
    
    return pd.DataFrame(records)

def generate_cases(customers_df, num_cases_per_customer=2):
    """Generate support cases"""
    print(f"Generating support cases ({num_cases_per_customer} per customer avg)...")
    
    case_types = ['Technical', 'Billing', 'Product', 'Service', 'General']
    priorities = ['Low', 'Medium', 'High', 'Critical']
    statuses = ['Open', 'In Progress', 'Resolved', 'Closed']
    
    cases = []
    case_id = 1
    
    # Sample customers for cases
    sample_size = int(len(customers_df) * 0.5)  # 50% of customers
    sampled_customers = customers_df.sample(n=sample_size)
    
    for _, customer in sampled_customers.iterrows():
        num_cases = np.random.poisson(num_cases_per_customer)
        
        for _ in range(num_cases):
            days_since_creation = (datetime.now() - customer['account_created_date']).days
            if days_since_creation > 0:
                case_date = customer['account_created_date'] + timedelta(
                    days=random.randint(0, days_since_creation)
                )
            else:
                case_date = customer['account_created_date']
            
            status = random.choice(statuses)
            resolution_days = random.randint(1, 30) if status in ['Resolved', 'Closed'] else None
            
            cases.append({
                'case_id': case_id,
                'customer_id': customer['customer_id'],
                'case_date': case_date,
                'case_type': random.choice(case_types),
                'priority': random.choice(priorities),
                'status': status,
                'resolution_days': resolution_days
            })
            case_id += 1
    
    return pd.DataFrame(cases)

def generate_monthly_kpis(customers_df, health_df):
    """Generate monthly KPI snapshots for time-series analysis"""
    print("Generating monthly KPI snapshots...")
    
    # Generate 12 months of data ending with current month
    from datetime import datetime
    current_date = datetime.now()
    months = []
    
    # Initialize baseline values for realistic declining trends (business problem scenario)
    base_nps = 52  # Start higher
    base_health = 65  # Start higher
    
    for month_offset in range(12):
        # Start from 11 months ago and go to current month
        month_date = datetime(current_date.year, current_date.month, 1) - timedelta(days=30 * (11 - month_offset))
        month_label = month_date.strftime('%b %Y')
        # Use ISO format for proper date parsing
        snapshot_month = month_date.strftime('%Y-%m-%d')
        month_date_str = month_date.strftime('%Y-%m-%d')
        
        # Simulate declining business health over time
        decline_factor = 1 - (month_offset * 0.015)  # 1.5% monthly decline
        
        total_customers = int(len(customers_df) * (0.8 + month_offset * 0.015))  # Slower growth
        monthly_sales = int(np.random.normal(5000, 500) * decline_factor)
        total_vehicles = int(total_customers * 1.3)  # 1.3 vehicles per customer avg
        
        # Health metrics with gradual decline (business problem)
        median_health = base_health - (month_offset * 0.9) + np.random.normal(0, 0.3)  # Consistent decline, low variance
        total_clv = customers_df['total_revenue'].sum() * decline_factor
        at_risk_pct = 0.25 + (month_offset * 0.015) + np.random.normal(0, 0.02)  # Increasing risk
        at_risk_customers = int(total_customers * min(0.45, at_risk_pct))
        revenue_at_risk = total_clv * at_risk_pct * 0.35
        
        # NPS with realistic declining trend (customer dissatisfaction growing)
        nps_score = base_nps - (month_offset * 0.8) + np.random.normal(0, 0.5)  # Stronger decline, less variance
        avg_nps = nps_score
        
        # Cases increasing (more problems)
        case_multiplier = 1 + (month_offset * 0.03)  # 3% more cases each month
        open_cases = int(np.random.normal(total_customers * 0.15, 100) * case_multiplier)
        cases_created = int(np.random.normal(total_customers * 0.25, 150) * case_multiplier)
        
        # Retention
        retention_rate = 0.92 + np.random.normal(0, 0.02)
        customers_retained = int(total_customers * retention_rate)
        retention_change = np.random.normal(0, 0.01)
        
        # Revenue metrics
        avg_revenue_per_customer = total_clv / total_customers
        revenue_growth_rate = (month_offset * 0.02) + np.random.normal(0, 0.01)
        
        # Subscriptions
        subscriptions_sold = int(np.random.normal(monthly_sales * 0.6, 200))
        
        months.append({
            'snapshot_month': snapshot_month,
            'month_date': month_date_str,
            'month_label': month_label,
            'total_customers': total_customers,
            'monthly_sales': monthly_sales,
            'total_vehicles': total_vehicles,
            'median_health_score': round(median_health, 2),
            'total_clv': round(total_clv, 2),
            'revenue_at_risk': round(revenue_at_risk, 2),
            'avg_nps_score': round(avg_nps, 2),
            'nps_score': round(nps_score, 2),
            'at_risk_customers': at_risk_customers,
            'pct_at_risk_customers': round(at_risk_pct, 4),
            'revenue_growth_rate': round(revenue_growth_rate, 4),
            'avg_revenue_per_customer': round(avg_revenue_per_customer, 2),
            'open_cases': open_cases,
            'cases_created': cases_created,
            'retention_rate': round(retention_rate, 4),
            'customers_retained': customers_retained,
            'retention_change': round(retention_change, 4),
            'subscriptions_sold': subscriptions_sold
        })
    
    return pd.DataFrame(months)

def generate_operational_kpis(monthly_kpis_df):
    """Generate operational KPIs by month"""
    print("Generating operational KPIs...")
    
    operational = []
    for _, month in monthly_kpis_df.iterrows():
        operational.append({
            'month_date': month['month_date'],
            'month_label': month['month_label'],
            'first_contact_resolution_rate': round(np.random.uniform(0.65, 0.85), 4),
            'avg_case_resolution_days': round(np.random.uniform(2, 8), 2),
            'service_wait_days': round(np.random.uniform(3, 12), 2),
            'warranty_claim_rate': round(np.random.uniform(0.05, 0.15), 4),
            'repeat_service_rate': round(np.random.uniform(0.25, 0.45), 4),
            'churn_risk_customers': int(month['at_risk_customers'] * 0.4),
            'churn_risk_revenue': round(month['revenue_at_risk'] * 0.5, 2),
            'operational_health_score': round(np.random.uniform(65, 85), 2)
        })
    
    return pd.DataFrame(operational)

def generate_issue_categories(monthly_kpis_df):
    """Generate issue categories by month with increasing battery issues"""
    print("Generating issue categories...")
    
    issues = []
    for idx, month in monthly_kpis_df.iterrows():
        total_cases = month['cases_created']
        
        # Battery issues increasing over time (the main problem)
        battery_pct = 0.15 + (idx * 0.02)  # Starting at 15%, increasing 2% each month
        
        issues.append({
            'month_date': month['month_date'],
            'month_label': month['month_label'],
            'battery_cases': int(total_cases * min(0.40, battery_pct)),  # Cap at 40%
            'adas_cases': int(total_cases * np.random.uniform(0.10, 0.15)),
            'connectivity_cases': int(total_cases * np.random.uniform(0.20, 0.25)),
            'infotainment_cases': int(total_cases * np.random.uniform(0.15, 0.20))
        })
    
    return pd.DataFrame(issues)

def generate_revenue_streams():
    """Generate revenue breakdown by stream"""
    print("Generating revenue streams...")
    
    streams = [
        {'revenue_stream': 'Vehicle Sales', 'revenue': round(np.random.uniform(800000, 1200000), 2)},
        {'revenue_stream': 'Service', 'revenue': round(np.random.uniform(300000, 500000), 2)},
        {'revenue_stream': 'Subscriptions', 'revenue': round(np.random.uniform(150000, 250000), 2)},
        {'revenue_stream': 'Financing', 'revenue': round(np.random.uniform(200000, 350000), 2)},
        {'revenue_stream': 'Warranty', 'revenue': round(np.random.uniform(100000, 180000), 2)}
    ]
    
    return pd.DataFrame(streams)

def generate_revenue_streams_with_trends():
    """Generate revenue streams with month-over-month trends"""
    print("Generating revenue stream trends...")
    
    streams = []
    for stream_name in ['Vehicle Sales', 'Service', 'Subscriptions', 'Financing', 'Warranty']:
        base_revenue = {
            'Vehicle Sales': 1000000,
            'Service': 400000,
            'Subscriptions': 200000,
            'Financing': 275000,
            'Warranty': 140000
        }[stream_name]
        
        current = base_revenue * np.random.uniform(0.95, 1.05)
        previous = current * np.random.uniform(0.90, 1.10)
        change = current - previous
        growth = (change / previous) if previous > 0 else 0
        
        streams.append({
            'revenue_stream': stream_name,
            'current_revenue': round(current, 2),
            'previous_revenue': round(previous, 2),
            'revenue_change': round(change, 2),
            'growth_rate': round(growth, 4)
        })
    
    return pd.DataFrame(streams)

def generate_at_risk_revenue_by_month(monthly_kpis_df):
    """Generate at-risk revenue breakdown by customer type and month"""
    print("Generating at-risk revenue by month...")
    
    at_risk = []
    customer_types = ['Enterprise', 'Mid-Market', 'SMB', 'Consumer']
    
    for _, month in monthly_kpis_df.iterrows():
        total_at_risk = month['revenue_at_risk']
        
        for cust_type in customer_types:
            # Distribution of at-risk revenue by customer type
            type_pct = {
                'Enterprise': 0.40,
                'Mid-Market': 0.30,
                'SMB': 0.20,
                'Consumer': 0.10
            }[cust_type]
            
            type_revenue = total_at_risk * type_pct
            type_customers = int(month['at_risk_customers'] * type_pct)
            
            at_risk.append({
                'month_date': month['month_date'],
                'month_label': month['month_label'],
                'customer_type': cust_type,
                'at_risk_customers': type_customers,
                'vehicle_sales_at_risk': round(type_revenue * 0.45, 2),
                'service_revenue_at_risk': round(type_revenue * 0.25, 2),
                'subscription_revenue_at_risk': round(type_revenue * 0.15, 2),
                'financing_revenue_at_risk': round(type_revenue * 0.10, 2),
                'warranty_revenue_at_risk': round(type_revenue * 0.05, 2),
                'total_revenue_at_risk': round(type_revenue, 2)
            })
    
    return pd.DataFrame(at_risk)

def upload_to_s3(df, bucket, key, profile=None):
    """Upload DataFrame to S3 as CSV"""
    print(f"Uploading to s3://{bucket}/{key}...")
    
    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)
    
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    s3 = session.client('s3')
    
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_buffer.getvalue(),
        ContentType='text/csv'
    )
    
    print(f"  ✓ Uploaded {len(df):,} rows")

def main():
    parser = argparse.ArgumentParser(description='Generate Customer 360 synthetic data')
    parser.add_argument('--customers', type=int, default=10000, help='Number of customers to generate')
    parser.add_argument('--bucket', required=True, help='S3 bucket name')
    parser.add_argument('--profile', help='AWS profile name')
    parser.add_argument('--prefix', default='raw', help='S3 prefix (default: raw)')
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"Customer 360 Data Generator")
    print(f"{'='*60}")
    print(f"Customers: {args.customers:,}")
    print(f"S3 Bucket: {args.bucket}")
    print(f"S3 Prefix: {args.prefix}")
    print(f"{'='*60}\n")
    
    # Generate data
    customers_df = generate_customers(args.customers)
    health_df = generate_customer_health(customers_df)
    interactions_df = generate_interactions(customers_df)
    service_df = generate_service_records(customers_df)
    cases_df = generate_cases(customers_df)
    
    # Generate time-series and aggregated data
    monthly_kpis_df = generate_monthly_kpis(customers_df, health_df)
    operational_kpis_df = generate_operational_kpis(monthly_kpis_df)
    issue_categories_df = generate_issue_categories(monthly_kpis_df)
    revenue_streams_df = generate_revenue_streams()
    revenue_trends_df = generate_revenue_streams_with_trends()
    at_risk_revenue_df = generate_at_risk_revenue_by_month(monthly_kpis_df)
    
    # Upload to S3
    print("\nUploading to S3...")
    upload_to_s3(customers_df, args.bucket, f'{args.prefix}/customers/customers.csv', args.profile)
    upload_to_s3(health_df, args.bucket, f'{args.prefix}/customer_health/customer_health.csv', args.profile)
    upload_to_s3(interactions_df, args.bucket, f'{args.prefix}/interactions/interactions.csv', args.profile)
    upload_to_s3(service_df, args.bucket, f'{args.prefix}/service_records/service_records.csv', args.profile)
    upload_to_s3(cases_df, args.bucket, f'{args.prefix}/cases/cases.csv', args.profile)
    upload_to_s3(monthly_kpis_df, args.bucket, f'{args.prefix}/monthly_kpis/monthly_kpis.csv', args.profile)
    upload_to_s3(operational_kpis_df, args.bucket, f'{args.prefix}/operational_kpis/operational_kpis.csv', args.profile)
    upload_to_s3(issue_categories_df, args.bucket, f'{args.prefix}/issue_categories/issue_categories.csv', args.profile)
    upload_to_s3(revenue_streams_df, args.bucket, f'{args.prefix}/revenue_streams/revenue_streams.csv', args.profile)
    upload_to_s3(revenue_trends_df, args.bucket, f'{args.prefix}/revenue_trends/revenue_trends.csv', args.profile)
    upload_to_s3(at_risk_revenue_df, args.bucket, f'{args.prefix}/at_risk_revenue/at_risk_revenue.csv', args.profile)
    
    print(f"\n{'='*60}")
    print("✓ Data generation complete!")
    print(f"{'='*60}")
    print(f"\nGenerated files:")
    print(f"  • customers.csv: {len(customers_df):,} rows")
    print(f"  • customer_health.csv: {len(health_df):,} rows")
    print(f"  • interactions.csv: {len(interactions_df):,} rows")
    print(f"  • service_records.csv: {len(service_df):,} rows")
    print(f"  • cases.csv: {len(cases_df):,} rows")
    print(f"  • monthly_kpis.csv: {len(monthly_kpis_df):,} rows")
    print(f"  • operational_kpis.csv: {len(operational_kpis_df):,} rows")
    print(f"  • issue_categories.csv: {len(issue_categories_df):,} rows")
    print(f"  • revenue_streams.csv: {len(revenue_streams_df):,} rows")
    print(f"  • revenue_trends.csv: {len(revenue_trends_df):,} rows")
    print(f"  • at_risk_revenue.csv: {len(at_risk_revenue_df):,} rows")
    print(f"\nNext steps:")
    print(f"  1. Run Glue crawler to populate table metadata")
    print(f"  2. Query data with Athena")
    print(f"  3. View dashboards in QuickSight")
    print()

if __name__ == '__main__':
    main()
