-- Table: oem_business_overview
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/870e3384-e09e-48fe-b88a-42554820cf18

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.oem_business_overview (
    created_date date,
    customer_id bigint,
    customer_name string,
    dealer_id bigint,
    dealer_name string,
    vehicle_id bigint,
    model string
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/870e3384-e09e-48fe-b88a-42554820cf18'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
