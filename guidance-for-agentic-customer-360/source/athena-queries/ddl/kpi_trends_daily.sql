-- Table: kpi_trends_daily
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://{{DATA_LAKE_BUCKET}}/kpi_trends_daily

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.kpi_trends_daily (
    snapshot_date date,
    month_label varchar(50),
    total_customers bigint,
    median_health_score double,
    total_clv double,
    revenue_at_risk double,
    avg_nps_score double,
    at_risk_customers bigint,
    churned_customers bigint,
    churned_revenue double
)
STORED AS PARQUET
LOCATION 's3://{{DATA_LAKE_BUCKET}}/kpi_trends_daily'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
