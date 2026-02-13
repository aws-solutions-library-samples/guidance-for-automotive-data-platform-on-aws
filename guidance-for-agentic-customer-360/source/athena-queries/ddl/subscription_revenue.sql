-- Table: subscription_revenue
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/fc70698f-347e-40bd-8f34-dbe272cb2b82

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.subscription_revenue (
    vehicle_id bigint,
    user_id bigint,
    billing_date date,
    subscription_type varchar(22),
    monthly_revenue int
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/fc70698f-347e-40bd-8f34-dbe272cb2b82'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
