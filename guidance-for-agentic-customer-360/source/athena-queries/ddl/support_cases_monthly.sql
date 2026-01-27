-- Table: support_cases_monthly
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-022035076260-us-east-1/tables/support_cases_monthly_v2/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.support_cases_monthly (
    month_date date,
    month_label varchar(8),
    total_cases int,
    battery_cases int,
    charging_cases int,
    other_cases int,
    open_cases int,
    resolved_cases int,
    escalated_cases int
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-022035076260-us-east-1/tables/support_cases_monthly_v2/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
