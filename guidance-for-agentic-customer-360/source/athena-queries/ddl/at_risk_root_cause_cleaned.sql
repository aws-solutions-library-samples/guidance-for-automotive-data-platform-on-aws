-- Table: at_risk_root_cause_cleaned
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-022035076260-us-east-1/tables/ed6a6539-b592-47d7-89db-9810ff0b7ddf

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.at_risk_root_cause_cleaned (
    customer_id bigint,
    health_score double,
    health_segment varchar(15),
    total_revenue double,
    avg_satisfaction_score double,
    total_cases double,
    open_cases double,
    total_service_appointments double,
    primary_root_cause varchar(25),
    contributing_factor varchar(16),
    severity varchar(8),
    days_at_risk double,
    revenue_at_risk double
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-022035076260-us-east-1/tables/ed6a6539-b592-47d7-89db-9810ff0b7ddf'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
