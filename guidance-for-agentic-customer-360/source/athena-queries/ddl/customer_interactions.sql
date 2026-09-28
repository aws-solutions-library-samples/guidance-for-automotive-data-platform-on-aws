-- Table: customer_interactions
-- Database: cx_analytics
-- Type: External Table
-- Location: s3://{{DATA_LAKE_BUCKET}}/customer_interactions

CREATE EXTERNAL TABLE IF NOT EXISTS cx_analytics.customer_interactions (
    customer_id bigint,
    interaction_id varchar(100),
    interaction_date date,
    interaction_type varchar(50),
    channel varchar(20),
    duration_minutes int,
    sentiment_score double,
    sentiment_label varchar(20),
    agent_id varchar(20),
    resolution_status varchar(20),
    topic varchar(50),
    notes varchar(500),
    created_at timestamp
)
STORED AS PARQUET
LOCATION 's3://{{DATA_LAKE_BUCKET}}/customer_interactions'
TBLPROPERTIES ('parquet.compression'='SNAPPY');
