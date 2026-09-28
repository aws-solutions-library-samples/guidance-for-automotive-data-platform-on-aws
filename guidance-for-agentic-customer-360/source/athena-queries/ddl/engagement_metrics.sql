-- Table: engagement_metrics
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-lake-{{ACCOUNT_ID}}/engagement-metrics

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.engagement_metrics (
    vehicle_segment string,
    customer_count bigint,
    revenue double,
    avg_health double
)
STORED AS PARQUET
LOCATION 's3://cx-analytics-data-lake-{{ACCOUNT_ID}}/engagement-metrics'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
