-- Table: health_score_monthly
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://{{DATA_LAKE_BUCKET}}/health_score_monthly_v2/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.health_score_monthly (
    month_date date,
    month_label varchar(8),
    median_health_score double
)
STORED AS PARQUET
LOCATION 's3://{{DATA_LAKE_BUCKET}}/health_score_monthly_v2/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
