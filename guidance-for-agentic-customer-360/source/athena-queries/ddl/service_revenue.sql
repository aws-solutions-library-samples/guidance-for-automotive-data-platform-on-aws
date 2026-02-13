-- Table: service_revenue
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/13d1f16c-b9a1-4674-acce-4bce4618daad

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.service_revenue (
    vehicle_id bigint,
    user_id bigint,
    purchase_date date,
    service_date date,
    service_type varchar(13),
    revenue int
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/13d1f16c-b9a1-4674-acce-4bce4618daad'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
