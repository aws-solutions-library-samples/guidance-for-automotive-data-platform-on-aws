-- Table: surveys
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-{{ACCOUNT_ID}}/raw/crm/surveys

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.surveys (
    id bigint,
    user_id bigint,
    survey_type string,
    score int,
    feedback string,
    survey_date timestamp
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-{{ACCOUNT_ID}}/raw/crm/surveys'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
