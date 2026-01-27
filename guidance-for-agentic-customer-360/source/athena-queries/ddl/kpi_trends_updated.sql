-- Table: kpi_trends_updated
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-givenand/kpi_trends_updated/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.kpi_trends_updated (
    snapshot_month date,
    total_customers int,
    median_health_score double,
    total_clv double,
    revenue_at_risk double,
    avg_nps_score double,
    at_risk_customers int
)
STORED AS PARQUET
LOCATION 's3://cx-analytics-data-givenand/kpi_trends_updated/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
