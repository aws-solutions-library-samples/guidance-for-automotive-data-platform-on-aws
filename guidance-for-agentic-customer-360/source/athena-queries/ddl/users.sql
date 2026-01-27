-- Table: users
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-022035076260/raw/crm/users

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.users (
    id bigint,
    email string,
    first_name string,
    last_name string,
    phone string,
    created_date timestamp
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-022035076260/raw/crm/users'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
