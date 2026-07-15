-- Table: cases_realistic
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-{{ACCOUNT_ID}}/athena-results/tables/504310a4-4409-48a8-a2ad-7135fb91f51f

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.cases_realistic (
    id bigint,
    user_id bigint,
    subject string,
    status varchar(6),
    priority string,
    created_date timestamp,
    closed_date timestamp
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-{{ACCOUNT_ID}}/athena-results/tables/504310a4-4409-48a8-a2ad-7135fb91f51f'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
