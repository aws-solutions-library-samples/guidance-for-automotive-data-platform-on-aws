-- Table: battery_service_records
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/battery_service_records/

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.battery_service_records (
    service_id varchar(12),
    vehicle_id int,
    user_id varchar(7),
    service_date date,
    service_type varchar(22),
    service_category varchar(8),
    issue_description varchar(105),
    parts_replaced varchar(13),
    labor_hours double,
    total_cost double,
    resolution_status varchar(11)
)
STORED AS PARQUET
LOCATION 's3://aws-athena-query-results-{{ACCOUNT_ID}}-{{REGION}}/tables/battery_service_records/'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
