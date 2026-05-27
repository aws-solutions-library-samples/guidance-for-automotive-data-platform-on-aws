-- Table: kpi_trends_new
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://{{DATA_LAKE_BUCKET}}/kpi_trends_new/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.kpi_trends_new (
    snapshot_month date,
    total_customers int,
    median_health_score double,
    total_clv double,
    revenue_at_risk double,
    avg_nps_score double,
    at_risk_customers int
)
STORED AS PARQUET
LOCATION 's3://{{DATA_LAKE_BUCKET}}/kpi_trends_new/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
