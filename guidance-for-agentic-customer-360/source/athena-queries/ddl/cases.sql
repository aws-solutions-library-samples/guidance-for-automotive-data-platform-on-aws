-- Table: cases
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-022035076260/raw/crm/cases

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.cases (
    id bigint,
    user_id bigint,
    subject string,
    status string,
    priority string,
    created_date timestamp,
    closed_date timestamp
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-022035076260/raw/crm/cases'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
