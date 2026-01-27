-- Table: customer_health_clean
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-givenand/customer_health_clean/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.customer_health_clean (
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
LOCATION 's3://cx-analytics-data-givenand/customer_health_clean/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
