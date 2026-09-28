-- Table: service_appointments
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-{{ACCOUNT_ID}}/raw/crm/service_appointments

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.service_appointments (
    appointment_id string,
    vehicle_id string,
    service_type string,
    appointment_date timestamp,
    cost decimal(10,2),
    status string
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-{{ACCOUNT_ID}}/raw/crm/service_appointments'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
