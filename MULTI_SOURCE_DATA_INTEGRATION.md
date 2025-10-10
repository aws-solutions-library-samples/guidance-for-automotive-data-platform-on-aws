# Multi-Source Data Integration for Tire Prediction ML

## Overview

This document describes the multi-source data integration architecture implemented for the tire prediction ML model. The platform now supports three data sources that can be combined for comprehensive tire wear prediction:

1. **Tire Telemetry** - Real-time sensor data from vehicles (tire pressure, temperature, tread depth)
2. **Weather Data** - Environmental conditions affecting tire wear (temperature, precipitation, road conditions)
3. **Service History** - Maintenance records and tire service events (optional)

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Data Sources                              │
├─────────────────────────────────────────────────────────────┤
│  Tire Telemetry    │   Weather Data   │  Service History    │
│  (CM or Synthetic) │   (Synthetic)    │  (CM or Synthetic)  │
│        ↓           │        ↓         │         ↓           │
│    S3 Bucket       │    S3 Bucket     │    DynamoDB         │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  AWS Glue Crawlers                           │
├─────────────────────────────────────────────────────────────┤
│  • tire-telemetry-crawler                                    │
│  • weather-data-crawler                                      │
│  • service-history-crawler (optional)                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  AWS Glue Databases                          │
├─────────────────────────────────────────────────────────────┤
│  • tire_telemetry                                            │
│  • weather_data                                              │
│  • vehicle_service_history (optional)                        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│            DataZone Data Catalog Project                     │
├─────────────────────────────────────────────────────────────┤
│  • Publishes Glue tables as DataZone assets                  │
│  • Manages data source runs                                  │
│  • Centralized data governance                               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│          Tire Prediction ML Project                          │
├─────────────────────────────────────────────────────────────┤
│  • Subscribes to published data assets                       │
│  • Accesses data via Athena/SageMaker                        │
│  • Trains multi-source ML models                             │
└─────────────────────────────────────────────────────────────┘
```

## Data Sources

### 1. Tire Telemetry Data

**Source**: Connected Mobility platform or synthetic generator

**Schema**:
- `vin` (string) - Vehicle identification number
- `timestamp` (bigint) - Unix timestamp
- `tire_position` (string) - FL, FR, RL, RR
- `pressure_psi` (double) - Tire pressure
- `temperature_f` (double) - Tire temperature
- `tread_depth_32nds` (int) - Tread depth in 32nds of an inch
- `rotation_count` (bigint) - Wheel rotations
- Partitions: `year`, `month`, `day`, `hour`

**Location**: `s3://{bucket}/raw-telemetry/`

### 2. Weather Data

**Source**: Synthetic generator (5 US regions)

**Schema**:
- `location_id` (string) - Location identifier (LOC-001 to LOC-005)
- `region` (string) - northeast, southeast, midwest, southwest, west
- `date` (string) - ISO date
- `timestamp` (bigint) - Unix timestamp
- `temperature_f` (double) - Temperature in Fahrenheit
- `precipitation_inches` (double) - Precipitation amount
- `humidity_pct` (double) - Humidity percentage
- `wind_mph` (double) - Wind speed
- `road_condition` (string) - DRY, WET, ICY, SNOWY
- `uv_index` (int) - UV index (0-11)
- Partitions: `year`, `month`, `day`

**Location**: `s3://weather-data-{account}/weather-data/`

**Regional Characteristics**:
- **Northeast**: Cold winters with snow, moderate summers
- **Southeast**: Hot humid summers, mild winters
- **Midwest**: Extreme temperature variations, snow in winter
- **Southwest**: Hot dry climate, minimal precipitation
- **West**: Moderate temperatures, seasonal rain

### 3. Service History (Optional)

**Source**: Connected Mobility platform or synthetic DynamoDB table

**Schema**:
- `vehicleId` (string) - Partition key
- `serviceDate` (string) - Sort key (ISO timestamp)
- `serviceType` (string) - TIRE_ROTATION, TIRE_REPLACEMENT, etc.
- `dealerId` (string) - Service provider
- `mileage` (number) - Vehicle mileage at service
- `serviceDetails` (map) - Service-specific details
- `cost` (map) - Labor, parts, total costs
- `invoiceUrl` (string) - S3 URL to PDF invoice

**Location**: DynamoDB table `{prefix}-service-history`

## Deployment Workflow

### Platform Deployment

```bash
cd ~/automotive-data-platform-on-aws
make deploy
```

**Steps executed**:
1. Create/verify Unified Studio domain
2. Configure S3 bucket and VPC
3. Enable Tooling and MLExperiments blueprints
4. Create project profile
5. Setup telemetry data source (auto-detect CM or create synthetic)
6. Generate and upload weather data
7. Create Glue databases and crawlers
8. Configure Lake Formation permissions
9. Run Glue crawlers to catalog data
10. Create Data Catalog project
11. Create DataZone data sources with IAM connection
12. Run data source jobs to publish assets

**Wait time**: ~10 minutes for Data Catalog project environments to become ACTIVE

### Publish Data Sources (if not auto-published)

```bash
cd ~/automotive-data-platform-on-aws
make publish-data
```

This step is only needed if the platform deployment couldn't auto-publish because environments weren't ready.

### Tire Prediction Deployment

```bash
cd ~/automotive-tire-prediction-model-on-aws
make deploy
```

**Steps executed**:
1. Create tire prediction project
2. Deploy project resources
3. Upload notebooks to S3

**Wait time**: ~10 minutes for tire prediction project environments to become ACTIVE

### Subscribe to Data Sources

```bash
cd ~/automotive-tire-prediction-model-on-aws
make subscribe-data
```

**Steps executed**:
1. Search for published data listings
2. Create subscription requests for telemetry and weather data
3. Auto-approve subscriptions (same domain owner)
4. Grant access to tire prediction project

## Key Technical Details

### DataZone V2 IAM Connection

DataZone V2 domains require using the DataZone IAM connection instead of environment IDs:

```bash
# Get IAM connection ID
CONNECTION_ID=$(aws datazone list-connections \
  --domain-identifier $DOMAIN_ID \
  --project-identifier $PROJECT_ID \
  --query 'items[?name==`project.iam`].connectionId|[0]' \
  --output text)

# Create data source with connection
aws datazone create-data-source \
  --domain-identifier $DOMAIN_ID \
  --project-identifier $PROJECT_ID \
  --connection-identifier $CONNECTION_ID \
  --name "Data Source Name" \
  --type GLUE \
  --enable-setting ENABLED \
  --publish-on-import \
  --configuration '{"glueRunConfiguration":{"relationalFilterConfigurations":[{"databaseName":"db_name"}]}}'
```

### Lake Formation Permissions

Critical for Glue crawlers and DataZone data sources:

```bash
# Database permissions for crawler
aws lakeformation grant-permissions \
  --principal DataLakePrincipalIdentifier="$CRAWLER_ROLE_ARN" \
  --resource '{"Database":{"Name":"database_name"}}' \
  --permissions "DESCRIBE" "ALTER" "CREATE_TABLE" "DROP"

# Table permissions for DataZone
aws lakeformation grant-permissions \
  --principal DataLakePrincipalIdentifier="$DATAZONE_ROLE_ARN" \
  --resource '{"Table":{"DatabaseName":"database_name","TableWildcard":{}}}' \
  --permissions "SELECT" "DESCRIBE"
```

### Blueprint S3 Configuration

Blueprints require full S3 URI format:

```bash
# Correct format
"S3Location": "s3://bucket-name/domain-id/datazone"

# Incorrect (causes "Invalid S3 path" errors)
"S3Location": "bucket-name"
```

### Automated Subscription Workflow

The subscription script handles:
1. Loading platform configuration from `/tmp/automotive-platform/config.env`
2. Finding the tire prediction project
3. Searching for published listings by name
4. Checking for existing subscriptions
5. Creating subscription requests
6. Auto-approving (since same domain owner)

## Data Access Patterns

### Athena Queries

Access data through Athena in the Tooling environment:

```sql
-- Query tire telemetry
SELECT * FROM tire_telemetry.raw_telemetry
WHERE year='2025' AND month='10'
LIMIT 10;

-- Query weather data
SELECT * FROM weather_data.weather_data
WHERE region='northeast' AND year='2025'
LIMIT 10;

-- Join telemetry and weather
SELECT t.vin, t.tire_position, t.pressure_psi, w.temperature_f, w.road_condition
FROM tire_telemetry.raw_telemetry t
JOIN weather_data.weather_data w
  ON DATE_FORMAT(FROM_UNIXTIME(t.timestamp), '%Y-%m-%d') = w.date
WHERE t.year='2025' AND t.month='10'
LIMIT 100;
```

### SageMaker Notebooks

Access data through AWS Data Wrangler in MLExperiments environment:

```python
import awswrangler as wr

# Read tire telemetry
telemetry_df = wr.athena.read_sql_query(
    sql="SELECT * FROM tire_telemetry.raw_telemetry WHERE year='2025'",
    database="tire_telemetry"
)

# Read weather data
weather_df = wr.athena.read_sql_query(
    sql="SELECT * FROM weather_data.weather_data WHERE year='2025'",
    database="weather_data"
)

# Join datasets
merged_df = telemetry_df.merge(
    weather_df,
    left_on='date',
    right_on='date',
    how='inner'
)
```

## Troubleshooting

### Data Sources Not Publishing

**Symptom**: Data source runs succeed but add 0 assets

**Cause**: Glue crawlers haven't run or failed

**Solution**:
```bash
# Check crawler status
aws glue get-crawler --name tire-telemetry-crawler

# Run crawler manually
aws glue start-crawler --name tire-telemetry-crawler

# Check for Lake Formation permission errors in logs
```

### Subscription Requests Fail

**Symptom**: "listing entity not found" error

**Cause**: Assets not published as listings yet

**Solution**: Wait for data source runs to complete, then retry subscription

### Environment Creation Fails

**Symptom**: "Invalid S3 path provided" error

**Cause**: Blueprint S3Location parameter not in correct format

**Solution**: Ensure S3Location uses full URI: `s3://bucket/domain/datazone`

### Glue Crawler Fails

**Symptom**: "Insufficient Lake Formation permission(s)" error

**Cause**: Missing Lake Formation permissions

**Solution**: Grant database and table permissions to crawler role

## Configuration Files

### Platform Configuration

Saved to `/tmp/automotive-platform/config.env`:
```bash
export DOMAIN_ID=dzd-xxxxx
export PROFILE_ID=xxxxx
export ROOT_DOMAIN_UNIT=xxxxx
export REGION=us-east-1
export ACCOUNT_ID=123456789012
export TELEMETRY_BUCKET=bucket-name
export TELEMETRY_PREFIX=raw-telemetry
export DATA_SOURCE=cm|synthetic
export WEATHER_BUCKET=weather-data-123456789012
export CATALOG_PROJECT=xxxxx
export SERVICE_HISTORY_TABLE=table-name (optional)
```

## Future Enhancements

1. **Real-time Weather Integration**: Replace synthetic weather with actual weather API
2. **Additional Data Sources**: Road quality, traffic patterns, driver behavior
3. **Data Quality Monitoring**: Automated data quality checks and alerts
4. **Feature Store**: Centralized feature engineering and storage
5. **Automated Retraining**: Trigger model retraining on new data availability
6. **Cross-Region Support**: Multi-region data sources and model deployment

## References

- [AWS DataZone Documentation](https://docs.aws.amazon.com/datazone/)
- [AWS Glue Crawlers](https://docs.aws.amazon.com/glue/latest/dg/add-crawler.html)
- [AWS Lake Formation](https://docs.aws.amazon.com/lake-formation/)
- [SageMaker Unified Studio](https://docs.aws.amazon.com/sagemaker/latest/dg/unified-studio.html)
