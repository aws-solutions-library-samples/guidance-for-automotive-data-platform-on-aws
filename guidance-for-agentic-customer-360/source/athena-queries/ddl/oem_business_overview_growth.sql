-- Table: oem_business_overview_growth
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/32c21194-0893-411a-9092-8404d519744c

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.oem_business_overview_growth (
    created_date date,
    customer_id bigint,
    customer_name string,
    dealer_id bigint,
    dealer_name string,
    vehicle_id bigint,
    model string
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/32c21194-0893-411a-9092-8404d519744c'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
