import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql.functions import *
from pyspark.sql.window import Window
from datetime import datetime

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'S3_BUCKET'])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

today = datetime.now()
year = today.strftime('%Y')
month = today.strftime('%m')
day = today.strftime('%d')

# Read processed customer 360
customer_360_path = f"s3://{args['S3_BUCKET']}/processed/customer-360/year={year}/month={month}/day={day}/"
customers = spark.read.parquet(customer_360_path)

# Read raw data for calculations
base_path = f"s3://{args['S3_BUCKET']}/raw/crm-export/year={year}/month={month}/day={day}/"
cases = spark.read.parquet(f"{base_path}cases/")
surveys = spark.read.parquet(f"{base_path}surveys/")

# 1. Recency Score (30%)
customers = customers.withColumn(
    "recency_score",
    when(col("days_since_last_interaction") <= 180, 100)
    .when(col("days_since_last_interaction") <= 365, 80)
    .when(col("days_since_last_interaction") <= 730, 60)
    .when(col("days_since_last_interaction") <= 1095, 40)
    .otherwise(20)
)

# 2. Satisfaction Score (25%) - Get latest NPS
latest_surveys = surveys.withColumn(
    "row_num",
    row_number().over(Window.partitionBy("contact_id").orderBy(desc("survey_date")))
).filter(col("row_num") == 1).select(
    col("contact_id").alias("customer_id"),
    "nps_score"
)

customers = customers.join(latest_surveys, "customer_id", "left")

customers = customers.withColumn(
    "satisfaction_score",
    when(col("nps_score") >= 9, 100)
    .when(col("nps_score") >= 7, 70)
    .when(col("nps_score") >= 0, 30)
    .otherwise(50)  # No survey
)

# 3. Support Score (20%) - Count tickets in last 90 days
recent_cases = cases.filter(
    datediff(current_date(), col("opened_date")) <= 90
).groupBy("contact_id").agg(
    count("case_id").alias("tickets_90d")
)

customers = customers.join(
    recent_cases.withColumnRenamed("contact_id", "customer_id"),
    "customer_id",
    "left"
).fillna({"tickets_90d": 0})

customers = customers.withColumn(
    "support_score",
    when(col("tickets_90d") == 0, 100)
    .when(col("tickets_90d") <= 2, 80)
    .when(col("tickets_90d") <= 5, 60)
    .otherwise(30)
)

# 4. Engagement Score (15%) - Placeholder (would use app/web analytics)
customers = customers.withColumn("engagement_score", lit(70))

# 5. Payment Score (10%) - Placeholder (would use payment data)
customers = customers.withColumn("payment_score", lit(100))

# Calculate weighted health score
customers = customers.withColumn(
    "health_score",
    (
        col("recency_score") * 0.30 +
        col("satisfaction_score") * 0.25 +
        col("support_score") * 0.20 +
        col("engagement_score") * 0.15 +
        col("payment_score") * 0.10
    ).cast("int")
)

# Calculate churn probability
customers = customers.withColumn(
    "churn_probability",
    when(col("health_score") < 40, 0.75)
    .when(col("health_score") < 60, 0.50)
    .otherwise(0.15)
)

# Prepare health metrics output
health_metrics = customers.select(
    "customer_id",
    lit(today.date()).alias("metric_date"),
    "health_score",
    "churn_probability",
    "recency_score",
    "satisfaction_score",
    "support_score",
    "engagement_score",
    "payment_score"
)

# Write to processed layer
output_path = f"s3://{args['S3_BUCKET']}/processed/health-metrics/year={year}/month={month}/"

health_metrics.write.mode("overwrite").parquet(output_path)

print(f"✓ Calculated health scores for {health_metrics.count()} customers")

# Update contacts table with new health scores (write back to Aurora would go here)

job.commit()
