-- Table: health_snapshots
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://cx-analytics-data-lake-022035076260/health-snapshots

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.health_snapshots (
    snapshot_date date,
    avg_health_score decimal(5,2),
    total_customers int,
    at_risk_customers int,
    total_revenue decimal(15,2)
)
STORED AS PARQUET
LOCATION 's3://cx-analytics-data-lake-022035076260/health-snapshots'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
