-- Table: accounts
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-{{ACCOUNT_ID}}/raw/crm/accounts

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.accounts (
    account_id string,
    user_id string,
    account_type string,
    status string,
    total_revenue decimal(10,2),
    created_at timestamp
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-{{ACCOUNT_ID}}/raw/crm/accounts'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
