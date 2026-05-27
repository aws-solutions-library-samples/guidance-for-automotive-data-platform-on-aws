-- Table: customer_health_scores
-- Source: s3://BUCKET/raw/customer_health/
CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.customer_health_scores (
    customer_id bigint,
    health_score double,
    health_segment string,
    satisfaction_score double,
    satisfaction_bucket string,
    total_cases int,
    open_cases int,
    total_service_appointments int,
    total_service_spend double,
    clv double
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 's3://${BUCKET}/raw/customer_health/'
TBLPROPERTIES ('skip.header.line.count'='1');
