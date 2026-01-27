import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.dynamicframe import DynamicFrame
from datetime import datetime

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'DB_SECRET_ARN', 'S3_BUCKET'])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Get current date for partitioning
today = datetime.now()
year = today.strftime('%Y')
month = today.strftime('%m')
day = today.strftime('%d')

# JDBC connection options
jdbc_url = f"jdbc:postgresql://{args['DB_HOST']}:5432/{args['DB_NAME']}"
connection_options = {
    "url": jdbc_url,
    "user": args['DB_USER'],
    "password": args['DB_PASSWORD'],
    "driver": "org.postgresql.Driver"
}

# Tables to export
tables = [
    'contacts',
    'customer_vehicles',
    'opportunities',
    'cases',
    'service_appointments',
    'surveys',
    'dealers'
]

for table in tables:
    print(f"Exporting {table}...")
    
    # Read from Aurora
    df = spark.read.jdbc(
        url=jdbc_url,
        table=table,
        properties=connection_options
    )
    
    # Convert to DynamicFrame
    dynamic_frame = DynamicFrame.fromDF(df, glueContext, table)
    
    # Write to S3 as Parquet (partitioned by date)
    output_path = f"s3://{args['S3_BUCKET']}/raw/crm-export/year={year}/month={month}/day={day}/{table}/"
    
    glueContext.write_dynamic_frame.from_options(
        frame=dynamic_frame,
        connection_type="s3",
        connection_options={"path": output_path},
        format="parquet",
        format_options={"compression": "snappy"}
    )
    
    print(f"✓ Exported {table} to {output_path}")

job.commit()
