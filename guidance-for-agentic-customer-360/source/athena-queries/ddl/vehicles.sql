-- Table: vehicles
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-{{ACCOUNT_ID}}/raw/crm/customer_vehicles

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.vehicles (
    id bigint,
    user_id bigint,
    vin string,
    make string,
    model string,
    year int,
    purchase_date date,
    dealer_id bigint
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-{{ACCOUNT_ID}}/raw/crm/customer_vehicles'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
