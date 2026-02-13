-- Table: customer_360
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-{{ACCOUNT_ID}}/processed/customer_360

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.customer_360 (
    customer_id bigint,
    email string,
    first_name string,
    last_name string,
    phone string,
    customer_since string,
    vehicle_count double,
    last_purchase_date string,
    first_purchase_date string,
    total_cases double,
    open_cases double,
    critical_cases double,
    last_case_date string,
    total_appointments double,
    completed_appointments double,
    total_service_spend double,
    avg_service_cost double,
    last_service_date string,
    avg_satisfaction_score double,
    min_satisfaction_score double,
    survey_count double,
    last_survey_date string,
    total_revenue double,
    opportunity_count double,
    active_opportunities double
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-{{ACCOUNT_ID}}/processed/customer_360'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
