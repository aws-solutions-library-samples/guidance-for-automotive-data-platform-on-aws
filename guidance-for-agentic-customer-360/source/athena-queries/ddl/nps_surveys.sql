-- Table: nps_surveys
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/66609e8e-38ed-4661-b2b3-354f55612aec

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.nps_surveys (
    customer_id bigint,
    vehicle_id bigint,
    survey_date date,
    nps_score int,
    response_type varchar(9)
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/66609e8e-38ed-4661-b2b3-354f55612aec'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
