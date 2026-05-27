-- Table: issue_categories
-- Source: s3://BUCKET/raw/issue_categories/
CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.issue_categories (
    month_date string,
    month_label string,
    battery_cases int,
    software_cases int,
    hardware_cases int,
    service_cases int,
    other_cases int,
    total_cases int
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 's3://${BUCKET}/raw/issue_categories/'
TBLPROPERTIES ('skip.header.line.count'='1');
