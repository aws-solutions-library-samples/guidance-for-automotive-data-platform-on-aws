-- Table: kpi_trends_final
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-givenand/kpi_trends_final/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.kpi_trends_final (
    snapshot_month date,
    total_customers int,
    median_health_score double,
    total_clv double,
    revenue_at_risk double,
    avg_nps_score double,
    at_risk_customers int,
    revenue_growth_rate double
)
STORED AS PARQUET
LOCATION 's3://cx-analytics-data-givenand/kpi_trends_final/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
