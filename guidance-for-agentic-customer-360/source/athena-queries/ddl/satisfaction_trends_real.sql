-- Table: satisfaction_trends_real
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-lake-022035076260/satisfaction-trends

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.satisfaction_trends_real (
    quarter_label string,
    survey_type string,
    avg_score double
)
STORED AS PARQUET
LOCATION 's3://cx-analytics-data-lake-022035076260/satisfaction-trends'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
