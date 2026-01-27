-- Table: warranty_revenue
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-022035076260-us-east-1/tables/16e19db4-f5d1-4070-9bfd-ec42c97fb465

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.warranty_revenue (
    vehicle_id bigint,
    user_id bigint,
    sale_date date,
    warranty_type varchar(22),
    warranty_revenue int
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-022035076260-us-east-1/tables/16e19db4-f5d1-4070-9bfd-ec42c97fb465'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
