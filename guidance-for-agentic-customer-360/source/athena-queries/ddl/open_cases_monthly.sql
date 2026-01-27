-- Table: open_cases_monthly
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-givenand/open_cases_monthly/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.open_cases_monthly (
    month_date date,
    month_label varchar(8),
    open_cases int
)
STORED AS PARQUET
LOCATION 's3://cx-analytics-data-givenand/open_cases_monthly/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
