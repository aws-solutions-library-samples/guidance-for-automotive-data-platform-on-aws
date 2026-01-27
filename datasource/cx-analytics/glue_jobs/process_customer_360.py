import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql.functions import *
from datetime import datetime

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'S3_BUCKET', 'DATABASE'])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

today = datetime.now()
year = today.strftime('%Y')
month = today.strftime('%m')
day = today.strftime('%d')

# Read raw data from S3
base_path = f"s3://{args['S3_BUCKET']}/raw/crm-export/year={year}/month={month}/day={day}/"

contacts = spark.read.parquet(f"{base_path}contacts/")
vehicles = spark.read.parquet(f"{base_path}customer_vehicles/")
opportunities = spark.read.parquet(f"{base_path}opportunities/")
cases = spark.read.parquet(f"{base_path}cases/")
appointments = spark.read.parquet(f"{base_path}service_appointments/")
surveys = spark.read.parquet(f"{base_path}surveys/")

# Calculate aggregates per customer
vehicle_stats = vehicles.groupBy("contact_id").agg(
    count("vehicle_id").alias("total_vehicles_owned"),
    sum("purchase_price").alias("total_purchases")
)

service_stats = appointments.groupBy("contact_id").agg(
    sum("actual_cost").alias("total_service_spend"),
    max("appointment_date").alias("last_service_date")
)

purchase_stats = vehicles.groupBy("contact_id").agg(
    max("purchase_date").alias("last_purchase_date")
)

ticket_stats = cases.groupBy("contact_id").agg(
    max("opened_date").alias("last_support_ticket_date")
)

survey_stats = surveys.groupBy("contact_id").agg(
    max("survey_date").alias("last_survey_date")
)

# Build Customer 360
customer_360 = contacts.select(
    col("contact_id").alias("customer_id"),
    "account_id",
    "first_name",
    "last_name",
    "email",
    "phone",
    col("customer_since").alias("customer_since_date"),
    "lifecycle_stage",
    "current_health_score",
    "lifetime_value"
)

# Join aggregates
customer_360 = customer_360 \
    .join(vehicle_stats, customer_360.customer_id == vehicle_stats.contact_id, "left") \
    .join(service_stats, customer_360.customer_id == service_stats.contact_id, "left") \
    .join(purchase_stats, customer_360.customer_id == purchase_stats.contact_id, "left") \
    .join(ticket_stats, customer_360.customer_id == ticket_stats.contact_id, "left") \
    .join(survey_stats, customer_360.customer_id == survey_stats.contact_id, "left")

# Calculate days since last interaction
customer_360 = customer_360.withColumn(
    "last_interaction_date",
    greatest(
        coalesce("last_purchase_date", lit("1900-01-01")),
        coalesce("last_service_date", lit("1900-01-01")),
        coalesce("last_support_ticket_date", lit("1900-01-01"))
    )
).withColumn(
    "days_since_last_interaction",
    datediff(current_date(), col("last_interaction_date"))
)

# Add snapshot date
customer_360 = customer_360.withColumn("snapshot_date", lit(today.date()))

# Fill nulls
customer_360 = customer_360.fillna({
    "total_vehicles_owned": 0,
    "total_purchases": 0,
    "total_service_spend": 0,
    "days_since_last_interaction": 9999
})

# Select final columns
customer_360 = customer_360.select(
    "customer_id", "account_id", "first_name", "last_name", "email", "phone",
    "customer_since_date", "lifecycle_stage", "current_health_score", "lifetime_value",
    "total_vehicles_owned", "total_purchases", "total_service_spend",
    "last_purchase_date", "last_service_date", "last_support_ticket_date",
    "last_survey_date", "days_since_last_interaction", "snapshot_date"
)

# Write to processed layer
output_path = f"s3://{args['S3_BUCKET']}/processed/customer-360/year={year}/month={month}/day={day}/"

customer_360.write.mode("overwrite").parquet(output_path)

print(f"✓ Processed {customer_360.count()} customer records to {output_path}")

job.commit()
