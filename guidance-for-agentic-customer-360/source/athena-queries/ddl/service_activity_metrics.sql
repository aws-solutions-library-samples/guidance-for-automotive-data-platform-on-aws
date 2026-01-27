-- Table: service_activity_metrics
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-lake-022035076260/service-activity-metrics/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.service_activity_metrics (
    service_segment varchar(22),
    customer_count bigint,
    revenue double,
    avg_health double
)
STORED AS PARQUET
LOCATION 's3://cx-analytics-data-lake-022035076260/service-activity-metrics/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
