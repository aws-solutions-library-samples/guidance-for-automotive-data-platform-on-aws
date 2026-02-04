-- Table: kpi_trends
-- Source: s3://BUCKET/raw/monthly_kpis/
CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.kpi_trends (
    snapshot_month string,
    month_date string,
    month_label string,
    total_customers int,
    monthly_sales int,
    total_vehicles int,
    median_health_score double,
    total_clv double,
    revenue_at_risk double,
    avg_nps_score double,
    nps_score double,
    at_risk_customers int,
    pct_at_risk_customers double,
    revenue_growth_rate double,
    avg_revenue_per_customer double,
    open_cases int,
    cases_created int,
    retention_rate double,
    customers_retained int,
    retention_change double,
    subscriptions_sold int
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 's3://${BUCKET}/raw/monthly_kpis/'
TBLPROPERTIES ('skip.header.line.count'='1');
