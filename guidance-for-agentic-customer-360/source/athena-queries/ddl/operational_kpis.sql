-- Table: operational_kpis
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-022035076260-us-east-1/tables/operational_kpis/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.operational_kpis (
    month_date date,
    month_label varchar(8),
    first_contact_resolution_rate double,
    avg_case_resolution_days double,
    service_wait_days double,
    warranty_claim_rate double,
    repeat_service_rate double,
    churn_risk_customers int,
    churn_risk_revenue int
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-022035076260-us-east-1/tables/operational_kpis/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
