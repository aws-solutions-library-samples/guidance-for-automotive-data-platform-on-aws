-- Table: financing_revenue
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/add08d34-2c3a-41dd-840a-cccad6a9385b

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.financing_revenue (
    vehicle_id bigint,
    user_id bigint,
    purchase_date date,
    payment_date date,
    financing_type varchar(5),
    interest_revenue int
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/add08d34-2c3a-41dd-840a-cccad6a9385b'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
