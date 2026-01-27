-- Table: customer_health_metrics
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-022035076260/processed/health-metrics/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.customer_health_metrics (
    customer_id string,
    metric_date date,
    health_score int,
    churn_probability decimal(5,2),
    recency_score int,
    satisfaction_score int,
    support_score int,
    engagement_score int,
    payment_score int
)
PARTITIONED BY (
    year string,
    month string
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-022035076260/processed/health-metrics/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
