-- Table: sentiment_reports
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-givenand/sentiment-reports

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.sentiment_reports (
    report_date date,
    sentiment_status string,
    decline_pct double,
    total_customers_affected int,
    total_revenue_at_risk double,
    expected_recovery double,
    root_causes array<struct<name:string,customers:int,revenue:double,action:string,success_rate:int>>
)
STORED AS PARQUET
LOCATION 's3://cx-analytics-data-givenand/sentiment-reports'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
