-- Table: nps_monthly_with_history
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-givenand/nps_monthly_v2/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.nps_monthly_with_history (
    month_date date,
    month_label varchar(8),
    total_responses int,
    promoters int,
    passives int,
    detractors int,
    nps_score double,
    avg_score double
)
STORED AS PARQUET
LOCATION 's3://cx-analytics-data-givenand/nps_monthly_v2/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
