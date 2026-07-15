-- Table: at_risk_revenue
-- Source: s3://BUCKET/raw/at_risk_revenue/
CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.at_risk_revenue (
    month_date string,
    month_label string,
    customer_type string,
    at_risk_customers int,
    vehicle_sales_at_risk bigint,
    service_revenue_at_risk bigint,
    subscription_revenue_at_risk bigint,
    financing_revenue_at_risk bigint,
    warranty_revenue_at_risk bigint,
    total_revenue_at_risk bigint
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 's3://${BUCKET}/raw/at_risk_revenue/'
TBLPROPERTIES ('skip.header.line.count'='1');
