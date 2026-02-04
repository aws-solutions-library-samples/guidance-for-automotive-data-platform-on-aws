-- Table: revenue_breakdown
-- Source: s3://BUCKET/raw/revenue_streams/
CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.revenue_breakdown (
    revenue_stream string,
    current_revenue double,
    previous_revenue double,
    revenue_change double,
    growth_rate double
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION 's3://${BUCKET}/raw/revenue_streams/'
TBLPROPERTIES ('skip.header.line.count'='1');
