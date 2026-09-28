-- Table: kpi_trends_with_arpc
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://{{DATA_LAKE_BUCKET}}/kpi_trends_with_arpc/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.kpi_trends_with_arpc (
    snapshot_month date,
    total_customers int,
    median_health_score double,
    total_clv double,
    revenue_at_risk double,
    avg_nps_score double,
    at_risk_customers int,
    revenue_growth_rate double,
    avg_revenue_per_customer double
)
STORED AS PARQUET
LOCATION 's3://{{DATA_LAKE_BUCKET}}/kpi_trends_with_arpc/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
