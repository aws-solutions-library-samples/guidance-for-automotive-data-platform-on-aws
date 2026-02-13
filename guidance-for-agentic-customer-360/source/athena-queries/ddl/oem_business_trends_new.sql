-- Table: oem_business_trends_new
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-{{ACCOUNT_ID}}/athena-results/tables/fa1f3041-92e5-423a-aa22-af4f989eebd8

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.oem_business_trends_new (
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
LOCATION 's3://automotive-cx-data-lake-{{ACCOUNT_ID}}/athena-results/tables/fa1f3041-92e5-423a-aa22-af4f989eebd8'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
