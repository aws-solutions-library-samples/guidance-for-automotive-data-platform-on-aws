# Multi-Repository Integration Architecture

## Overview

This document describes how three repositories work together to create an end-to-end automotive data and ML platform.

## Repository Structure

### 1. automotive-data-platform-on-aws (This Repo)
**Purpose**: Infrastructure and platform foundation

**Responsibilities**:
- DataZone V2 domain management
- SageMaker Unified Studio setup
- IAM roles and permissions
- Shared resources (S3 buckets, VPC, etc.)
- Project creation templates

**Outputs**:
- Domain ID
- Project IDs
- S3 bucket names
- IAM role ARNs

### 2. connected-mobility-workspace
**Purpose**: Data generation and ingestion

**Responsibilities**:
- Vehicle simulator (generates synthetic tire telemetry)
- Flink processor (transforms data)
- Kafka streaming
- Iceberg table management
- Publishes tire data to S3/Iceberg

**Data Output**:
- Tire telemetry (pressure, temperature, tread depth, condition)
- Format: Long format (one record per tire)
- Storage: Iceberg tables in S3
- Partitioning: year/month/day/hour

### 3. automotive-tire-prediction-model-on-aws
**Purpose**: ML model development and deployment

**Responsibilities**:
- Tire wear prediction model
- Training pipelines
- Model inference
- SageMaker notebooks
- Consumes data from connected-mobility-workspace

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ connected-mobility-workspace                                │
│                                                             │
│  Vehicle Simulator                                          │
│       ↓                                                     │
│  Kafka (cms-telemetry-processed)                           │
│       ↓                                                     │
│  Flink TireTelemetryTransformer                            │
│       ↓                                                     │
│  Iceberg Tables (S3)                                       │
│    - tire_telemetry                                        │
│    - Partitioned by timestamp                              │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ (S3 bucket shared)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ automotive-data-platform-on-aws                             │
│                                                             │
│  DataZone Domain                                            │
│       ↓                                                     │
│  Unified Studio Project: tire-prediction-ml                │
│    - Data catalog (registers Iceberg tables)               │
│    - S3 access permissions                                 │
│    - SageMaker execution roles                             │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ (project environment)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ automotive-tire-prediction-model-on-aws                     │
│                                                             │
│  SageMaker Notebooks (in Unified Studio)                   │
│       ↓                                                     │
│  Read tire_telemetry from Iceberg                          │
│       ↓                                                     │
│  Train ML Model                                             │
│       ↓                                                     │
│  Deploy Model Endpoint                                      │
│       ↓                                                     │
│  Predict tire wear/maintenance needs                        │
└─────────────────────────────────────────────────────────────┘
```

## Integration Points

### Shared S3 Bucket
**Created by**: automotive-data-platform-on-aws  
**Written to by**: connected-mobility-workspace  
**Read by**: automotive-tire-prediction-model-on-aws

```yaml
# In automotive-data-platform-on-aws
Resources:
  TireDataBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: automotive-tire-data-${AWS::AccountId}
```

### Data Catalog Registration
**Iceberg tables** created by connected-mobility-workspace are registered in DataZone catalog:

```bash
# In automotive-data-platform-on-aws
aws datazone create-data-source \
  --domain-identifier $DOMAIN_ID \
  --project-identifier $PROJECT_ID \
  --name tire-telemetry-iceberg \
  --type GLUE \
  --configuration '{"glueRunConfiguration":{"dataAccessRole":"..."}}'
```

### IAM Permissions
**Cross-repo access** via IAM roles:

```yaml
# In automotive-data-platform-on-aws
TireMLExecutionRole:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument:
      Statement:
        - Effect: Allow
          Principal:
            Service: sagemaker.amazonaws.com
          Action: sts:AssumeRole
    Policies:
      - PolicyName: TireDataAccess
        PolicyDocument:
          Statement:
            - Effect: Allow
              Action:
                - s3:GetObject
                - s3:ListBucket
              Resource:
                - !GetAtt TireDataBucket.Arn
                - !Sub '${TireDataBucket.Arn}/*'
            - Effect: Allow
              Action:
                - glue:GetTable
                - glue:GetDatabase
              Resource: '*'
```

## Deployment Workflow

### 1. Platform Setup (One-time)
```bash
cd automotive-data-platform-on-aws
make deploy                    # Deploy DataZone domain
make deploy-tire-project       # Create tire-prediction-ml project
```

### 2. Data Pipeline Setup (One-time)
```bash
cd connected-mobility-workspace
# Deploy simulator and Flink processor
# Configure to write to platform S3 bucket
```

### 3. ML Development (Iterative)
```bash
cd automotive-tire-prediction-model-on-aws
# Access Unified Studio portal
# Open tire-prediction-ml project
# Develop notebooks, train models
```

## Environment Variables

### automotive-data-platform-on-aws
```bash
export DOMAIN_ID=dzd-xxxxx
export PROJECT_ID=xxxxx
export TIRE_DATA_BUCKET=automotive-tire-data-123456789
export EXECUTION_ROLE_ARN=arn:aws:iam::123456789:role/tire-ml-execution
```

### connected-mobility-workspace
```bash
export TIRE_DATA_BUCKET=automotive-tire-data-123456789
export ICEBERG_CATALOG=glue
export ICEBERG_DATABASE=tire_telemetry
```

### automotive-tire-prediction-model-on-aws
```bash
export PROJECT_ID=xxxxx
export TIRE_DATA_BUCKET=automotive-tire-data-123456789
export EXECUTION_ROLE_ARN=arn:aws:iam::123456789:role/tire-ml-execution
```

## Data Schema

### Tire Telemetry (from connected-mobility-workspace)
```json
{
  "vin": "string",
  "timestamp": "ISO 8601",
  "tire_position": "FL|FR|RL|RR",
  "pressure_mbar": "float",
  "temperature_celsius": "float",
  "tread_depth_mm": "float",
  "condition": "NORMAL|WARNING|CRITICAL",
  "year": "int",
  "month": "int",
  "day": "int",
  "hour": "int"
}
```

## Next Steps

1. **Create shared S3 bucket** in automotive-data-platform-on-aws
2. **Configure connected-mobility-workspace** to write to that bucket
3. **Register Iceberg tables** in DataZone catalog
4. **Set up SageMaker notebook** in tire-prediction-ml project
5. **Develop ML model** in automotive-tire-prediction-model-on-aws

## Maintenance

- **Platform updates**: automotive-data-platform-on-aws team
- **Data pipeline**: connected-mobility-workspace team
- **ML models**: automotive-tire-prediction-model-on-aws team

Each team can work independently while sharing infrastructure and data.
