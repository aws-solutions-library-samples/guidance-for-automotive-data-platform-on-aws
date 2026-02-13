-- Table: oem_business_trends_realistic
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/123e51f2-9619-4680-a814-35b43435362f

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.oem_business_trends_realistic (
    month_date date,
    month_label string,
    monthly_sales bigint,
    total_vehicles bigint,
    active_dealers bigint,
    cases_created bigint,
    open_cases bigint,
    avg_health_score double,
    avg_revenue_per_customer double,
    at_risk_customers bigint,
    avg_sales_per_dealer double
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/123e51f2-9619-4680-a814-35b43435362f'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
