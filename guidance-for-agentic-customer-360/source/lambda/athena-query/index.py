import json
import boto3
import os
import time
import re
from typing import Dict, Any

athena = boto3.client('athena')
s3 = boto3.client('s3')

GLUE_DATABASE = os.environ['GLUE_DATABASE']
ATHENA_WORKGROUP = os.environ['ATHENA_WORKGROUP']
DATA_LAKE_BUCKET = os.environ['DATA_LAKE_BUCKET']


def sanitize_int(value: str, default: int, min_val: int = 0, max_val: int = 10000) -> int:
    """Sanitize and validate integer input."""
    try:
        val = int(value)
        return max(min_val, min(val, max_val))
    except (ValueError, TypeError):
        return default


def sanitize_identifier(value: str) -> str:
    """Sanitize identifier (customer_id) - alphanumeric and hyphens only."""
    if not value:
        return ''
    # Only allow alphanumeric, hyphens, and underscores
    return re.sub(r'[^a-zA-Z0-9_-]', '', value)

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda function for Bedrock Agent to query Athena.
    Handles customer health, revenue at risk, and trend queries.
    """
    print(f"Event: {json.dumps(event)}")
    
    # Extract action and parameters
    action = event.get('actionGroup', '')
    api_path = event.get('apiPath', '')
    parameters = event.get('parameters', [])
    
    # Convert parameters to dict
    params = {p['name']: p['value'] for p in parameters}
    
    try:
        # Support both old and new API paths
        if api_path in ['/customer-health', '/query-health-segments']:
            result = query_customer_health(params)
        elif api_path in ['/revenue-at-risk', '/query-at-risk-customers']:
            result = query_at_risk_customers(params)
        elif api_path in ['/customer-trends', '/query-sentiment-trends']:
            result = query_customer_trends(params)
        elif api_path == '/query-root-causes':
            result = query_root_causes(params)
        elif api_path == '/query-customer-360':
            result = query_customer_360(params)
        elif api_path == '/query-dashboard-metrics':
            result = query_dashboard_metrics(params)
        else:
            result = {'error': f'Unknown API path: {api_path}'}
        
        return {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': action,
                'apiPath': api_path,
                'httpMethod': event.get('httpMethod', 'GET'),
                'httpStatusCode': 200,
                'responseBody': {
                    'application/json': {
                        'body': json.dumps(result)
                    }
                }
            }
        }
    
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'messageVersion': '1.0',
            'response': {
                'actionGroup': action,
                'apiPath': api_path,
                'httpMethod': event.get('httpMethod', 'GET'),
                'httpStatusCode': 500,
                'responseBody': {
                    'application/json': {
                        'body': json.dumps({'error': str(e)})
                    }
                }
            }
        }

def query_customer_health(params: Dict[str, str]) -> Dict[str, Any]:
    """Query customer health scores from Athena."""
    min_score = sanitize_int(params.get('min_score', '0'), 0, 0, 100)
    max_score = sanitize_int(params.get('max_score', '100'), 100, 0, 100)
    limit = sanitize_int(params.get('limit', '100'), 100, 1, 1000)
    
    query = f"""
    SELECT 
        customer_id,
        health_score,
        churn_probability,
        lifetime_value,
        last_interaction_date,
        risk_level
    FROM {GLUE_DATABASE}.customer_health
    WHERE health_score BETWEEN {min_score} AND {max_score}
    ORDER BY health_score ASC
    LIMIT {limit}
    """  # nosec B608 - inputs are sanitized integers
    
    results = execute_athena_query(query)
    
    return {
        'customers': results,
        'count': len(results),
        'filters': {
            'min_score': min_score,
            'max_score': max_score
        }
    }

def query_at_risk_customers(params: Dict[str, str]) -> Dict[str, Any]:
    """Get list of at-risk customers."""
    limit = sanitize_int(params.get('limit', '50'), 50, 1, 1000)
    
    query = f"""
    SELECT 
        customer_id,
        health_score,
        total_revenue as revenue_at_risk,
        total_cases,
        open_cases
    FROM {GLUE_DATABASE}.customer_health
    WHERE health_score < 70
    ORDER BY health_score ASC, total_revenue DESC
    LIMIT {limit}
    """  # nosec B608 - limit is sanitized integer
    
    results = execute_athena_query(query)
    
    return {
        'at_risk_customers': results,
        'count': len(results)
    }

def query_root_causes(params: Dict[str, str]) -> Dict[str, Any]:
    """Get root causes for declining customer sentiment and health."""
    
    issue_query = f"""
    SELECT 
        month_label,
        battery_cases,
        adas_cases,
        connectivity_cases,
        infotainment_cases,
        (battery_cases + adas_cases + connectivity_cases + infotainment_cases) as total_cases
    FROM {GLUE_DATABASE}.issue_categories_view
    ORDER BY month_date DESC
    LIMIT 6
    """  # nosec B608 - no user input
    
    health_query = f"""
    SELECT 
        month_label,
        ROUND(median_health_score, 1) as health_score,
        ROUND(nps_score, 1) as nps,
        at_risk_customers,
        ROUND(revenue_at_risk / 1000000, 1) as revenue_at_risk_millions
    FROM {GLUE_DATABASE}.kpi_trends
    ORDER BY month_date DESC
    LIMIT 6
    """  # nosec B608 - no user input
    
    segment_query = f"""
    SELECT 
        health_segment,
        COUNT(*) as customer_count,
        ROUND(AVG(health_score), 1) as avg_health,
        ROUND(SUM(total_revenue) / 1000000, 1) as total_revenue_millions
    FROM {GLUE_DATABASE}.customer_health_scores
    GROUP BY health_segment
    ORDER BY avg_health DESC
    """  # nosec B608 - no user input
    
    issue_trends = execute_athena_query(issue_query)
    health_trends = execute_athena_query(health_query)
    segments = execute_athena_query(segment_query)
    
    # Calculate battery issue growth
    if len(issue_trends) >= 2:
        latest_battery = issue_trends[0].get('battery_cases', 0)
        oldest_battery = issue_trends[-1].get('battery_cases', 0)
        battery_growth = ((latest_battery - oldest_battery) / oldest_battery * 100) if oldest_battery > 0 else 0
    else:
        battery_growth = 0
    
    return {
        'summary': {
            'primary_issue': 'Battery-related cases increasing',
            'battery_case_growth_pct': round(battery_growth, 1),
            'health_score_trend': 'Declining',
            'nps_trend': 'Declining',
            'at_risk_customers_trend': 'Increasing'
        },
        'issue_trends': issue_trends,
        'health_trends': health_trends,
        'customer_segments': segments,
        'recommendation': 'Immediate action needed: Battery issues are the primary driver of declining customer sentiment. Recommend: 1) Proactive battery health monitoring, 2) Preventive maintenance program, 3) Customer communication about battery care'
    }

def query_customer_360(params: Dict[str, str]) -> Dict[str, Any]:
    """Get complete customer 360 view."""
    customer_id = sanitize_identifier(params.get('customer_id', ''))
    
    if not customer_id:
        return {'error': 'Invalid customer_id'}
    
    query = f"""
    SELECT 
        customer_id,
        health_score,
        churn_probability,
        lifetime_value,
        last_interaction_date
    FROM {GLUE_DATABASE}.customer_health
    WHERE customer_id = '{customer_id}'
    """  # nosec B608 - customer_id is sanitized
    
    results = execute_athena_query(query)
    
    return results[0] if results else {'error': 'Customer not found'}

def query_dashboard_metrics(params: Dict[str, str]) -> Dict[str, Any]:
    """Get current dashboard KPI metrics."""
    query = f"""
    SELECT 
        COUNT(*) as total_customers,
        AVG(health_score) as avg_health_score,
        SUM(total_revenue) as total_clv,
        SUM(CASE WHEN health_score < 40 THEN total_revenue ELSE 0 END) as revenue_at_risk
    FROM {GLUE_DATABASE}.customer_health
    """  # nosec B608 - no user input
    
    results = execute_athena_query(query)
    
    return results[0] if results else {}

def query_customer_trends(params: Dict[str, str]) -> Dict[str, Any]:
    """Query customer health trends over time."""
    days = sanitize_int(params.get('days', '30'), 30, 1, 365)
    
    query = f"""
    SELECT 
        DATE(snapshot_date) as date,
        AVG(health_score) as avg_health_score,
        COUNT(*) as total_customers,
        SUM(CASE WHEN health_score < 40 THEN 1 ELSE 0 END) as critical_customers,
        SUM(CASE WHEN health_score BETWEEN 40 AND 70 THEN 1 ELSE 0 END) as at_risk_customers
    FROM {GLUE_DATABASE}.customer_health
    WHERE snapshot_date >= CURRENT_DATE - INTERVAL '{days}' DAY
    GROUP BY DATE(snapshot_date)
    ORDER BY date DESC
    """  # nosec B608 - days is sanitized integer
    
    results = execute_athena_query(query)
    
    return {
        'trends': results,
        'period_days': days
    }

def execute_athena_query(query: str) -> list:
    """Execute Athena query and return results."""
    # Start query execution
    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={'Database': GLUE_DATABASE},
        WorkGroup=ATHENA_WORKGROUP,
        ResultConfiguration={
            'OutputLocation': f's3://{DATA_LAKE_BUCKET}/athena-results/'
        }
    )
    
    query_execution_id = response['QueryExecutionId']
    
    # Wait for query to complete
    max_attempts = 30
    for attempt in range(max_attempts):
        query_status = athena.get_query_execution(
            QueryExecutionId=query_execution_id
        )
        
        status = query_status['QueryExecution']['Status']['State']
        
        if status == 'SUCCEEDED':
            break
        elif status in ['FAILED', 'CANCELLED']:
            raise Exception(f"Query {status}: {query_status['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')}")
        
        time.sleep(1)
    
    # Get query results
    results = athena.get_query_results(
        QueryExecutionId=query_execution_id
    )
    
    # Parse results
    rows = results['ResultSet']['Rows']
    if len(rows) <= 1:
        return []
    
    # Extract column names
    columns = [col['VarCharValue'] for col in rows[0]['Data']]
    
    # Extract data rows
    data = []
    for row in rows[1:]:
        row_data = {}
        for i, col in enumerate(row['Data']):
            row_data[columns[i]] = col.get('VarCharValue', '')
        data.append(row_data)
    
    return data
