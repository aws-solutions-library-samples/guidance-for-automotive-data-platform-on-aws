-- Table: operational_kpis
-- Source: s3://BUCKET/raw/operational_kpis/
CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.operational_kpis (
    month_date string,
    month_label string,
    first_contact_resolution_rate double,
    avg_case_resolution_days double,
    service_wait_days double,
    warranty_claim_rate double,
    repeat_service_rate double,
    churn_risk_customers int,
    churn_risk_revenue bigint
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 's3://${BUCKET}/raw/operational_kpis/'
TBLPROPERTIES ('skip.header.line.count'='1');
