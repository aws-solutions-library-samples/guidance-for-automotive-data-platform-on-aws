-- Table: customer_health
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://{{DATA_LAKE_BUCKET}}/customer_health_new/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.customer_health (
    customer_id bigint,
    user_id bigint,
    total_revenue double,
    avg_satisfaction_score double,
    total_cases double,
    open_cases double,
    total_vehicles double,
    total_service_spend double,
    total_service_appointments double,
    opportunity_count double,
    health_score double,
    health_segment varchar(15)
)
STORED AS PARQUET
LOCATION 's3://{{DATA_LAKE_BUCKET}}/customer_health_new/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
