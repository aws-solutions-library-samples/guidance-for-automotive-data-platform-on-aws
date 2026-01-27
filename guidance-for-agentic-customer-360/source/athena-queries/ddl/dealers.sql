-- Table: dealers
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://automotive-cx-data-lake-022035076260/raw/crm/dealers

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.dealers (
    dealer_id bigint,
    dealer_name string,
    location string,
    region string,
    performance_rating double
)
STORED AS PARQUET
LOCATION 's3://automotive-cx-data-lake-022035076260/raw/crm/dealers'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
