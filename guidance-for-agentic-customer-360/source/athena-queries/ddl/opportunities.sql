-- Table: opportunities
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-{{ACCOUNT_ID}}/raw/crm/opportunities

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.opportunities (
    opportunity_id string,
    account_id string,
    opportunity_type string,
    value decimal(10,2),
    stage string,
    created_at timestamp
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-{{ACCOUNT_ID}}/raw/crm/opportunities'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
