-- Table: service_trends_real
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-lake-022035076260/service-trends

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.service_trends_real (
    quarter_label string,
    total_cases int,
    open_cases int
)
STORED AS PARQUET
LOCATION 's3://cx-analytics-data-lake-022035076260/service-trends'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
