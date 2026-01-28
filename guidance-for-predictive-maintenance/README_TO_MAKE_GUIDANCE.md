# Tire Predictive Maintenance System

A comprehensive AWS-based solution for predictive maintenance of vehicle tires using machine learning to detect slow leaks and anomalies before they become critical failures.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              TIRE PREDICTIVE MAINTENANCE SYSTEM                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │   Raw Data  │───▶│  ETL Pipeline │───▶│  ML Training    │───▶│  Model Storage  │  │
│  │   Sources   │    │   (Glue)     │    │ (SageMaker)     │    │    (S3)        │  │
│  └─────────────┘    └──────────────┘    └─────────────────┘    └─────────────────┘  │
│         │                   │                      │                      │         │
│         │                   │                      │                      │         │
│         ▼                   ▼                      ▼                      ▼         │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │  S3 Buckets │    │ Normalization│    │   Endpoint      │    │  Batch Inference│  │
│  │ (Partitioned│    │  Statistics  │    │  Management     │    │  (Step Functions│  │
│  │  by Date)   │    │    (SSM)     │    │ (Step Functions)│    │   + SageMaker)  │  │
│  └─────────────┘    └──────────────┘    └─────────────────┘    └─────────────────┘  │
│                                                  │                      │           │
│                                                  │                      │           │
│                                                  ▼                      ▼           │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │ Real-time   │◀───│  API Gateway │    │  Anomaly Score  │───▶│ Alert Processing│  │
│  │ Inference   │    │   + Lambda   │    │   Threshold     │    │   (SQS + Lambda)│  │
│  │  (Lambda)   │    │              │    │    (SSM)       │    │                 │  │
│  └─────────────┘    └──────────────┘    └─────────────────┘    └─────────────────┘  │
│                                                                         │           │
│                                                                         ▼           │
│                                                                ┌─────────────────┐  │
│                                                                │ Alert Storage   │  │
│                                                                │   (DynamoDB)    │  │
│                                                                └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## System Components

### 1. ETL Pipeline (Extract, Transform, Load)

**Purpose**: Processes raw tire sensor data into machine learning-ready format

**Architecture**: 
- **AWS Glue Jobs** for distributed data processing
- **S3 buckets** for data storage with date partitioning
- **SSM Parameter Store** for normalization statistics

**Data Flow**:
1. Raw CSV data arrives in source S3 bucket (partitioned by date: `yyyy/mm/dd/`)
2. Glue job processes previous day's data
3. Applies data cleaning, feature engineering, and normalization
4. Outputs training and inference datasets to separate S3 buckets
5. Updates normalization statistics in SSM for consistency

**Key Features**:
- **Incremental normalization**: Uses Welford's algorithm to maintain running statistics
- **Feature engineering**: Calculates pressure/temperature deltas between readings
- **Data validation**: Handles missing values and timestamp parsing
- **Partitioned storage**: Organizes data by date for efficient processing

### 2. ML Training Pipeline

**Purpose**: Trains Random Cut Forest models for anomaly detection

**Architecture**:
- **Step Functions** orchestrate the training workflow
- **SageMaker Training Jobs** using AWS's Random Cut Forest algorithm
- **SageMaker Endpoints** for model deployment
- **S3** for model artifact storage

**Training Workflow**:
1. **Data Preparation**: Cleans training data bucket
2. **Model Training**: Uses Random Cut Forest for unsupervised anomaly detection
3. **Model Creation**: Creates SageMaker model from training artifacts
4. **Endpoint Management**: Creates or updates SageMaker endpoint for inference
5. **Parameter Updates**: Stores model name in SSM for reference

**Model Configuration**:
- **Algorithm**: Random Cut Forest (unsupervised anomaly detection)
- **Features**: 4 dimensions (pressure, temperature, delta_pressure, delta_temp)
- **Hyperparameters**: 100 trees, 256 samples per tree
- **Instance**: m5.xlarge for endpoint hosting

### 3. Batch Inference Pipeline

**Purpose**: Processes daily data to detect anomalies and establish thresholds

**Architecture**:
- **Step Functions** coordinate batch processing
- **SageMaker Batch Transform** for scalable inference
- **Lambda functions** for data preparation and post-processing

**Inference Workflow**:
1. **Data Preparation**: Formats inference data for SageMaker
2. **Batch Transform**: Processes entire dataset through trained model
3. **Threshold Calculation**: Determines anomaly threshold (95th percentile)
4. **Alert Generation**: Identifies anomalies above threshold
5. **Alert Processing**: Sends alerts to processing queue

### 4. Real-time Inference API

**Purpose**: Provides immediate anomaly detection for live tire data

**Architecture**:
- **API Gateway** with API key authentication
- **Lambda function** for real-time processing
- **SageMaker Endpoint** for model inference

**API Features**:
- **Authentication**: API key-based access control
- **Rate Limiting**: 100 requests/second, 10K daily quota
- **CORS Support**: Enables web browser access
- **Input Validation**: Ensures required fields are present
- **Error Handling**: Comprehensive error responses

**Request Format**:
```json
{
  "vehicle_id": "VEHICLE_001",
  "tire_id": "FL",
  "pressure": 32.5,
  "temperature": 75.0,
  "delta_pressure": -0.5,
  "delta_temp": 2.0
}
```

**Response Format**:
```json
{
  "anomaly_score": 0.7542,
  "prediction": true,
  "vehicle_id": "VEHICLE_001",
  "tire_id": "FL"
}
```

### 5. Alert System

**Purpose**: Manages and processes anomaly alerts

**Architecture**:
- **SQS Queues** for reliable message processing
- **DynamoDB** for alert storage and tracking
- **Lambda functions** for alert processing
- **Dead Letter Queue** for failed message handling

**Alert Processing Flow**:
1. **Alert Generation**: Batch inference creates alerts for anomalies
2. **Queue Processing**: SQS ensures reliable delivery
3. **Alert Storage**: DynamoDB stores alert details with status tracking
4. **Error Handling**: Failed alerts go to DLQ for manual review
5. **Alert Cleanup**: Processes failed alerts and updates status

## Why This Architecture?

### ETL Design Decisions

**Why AWS Glue?**
- **Serverless**: No infrastructure management required
- **Scalable**: Automatically scales based on data volume
- **Cost-effective**: Pay only for processing time
- **PySpark Integration**: Powerful data transformation capabilities

**Why Date Partitioning?**
- **Performance**: Enables efficient data querying and processing
- **Cost Optimization**: Reduces data scanning costs
- **Parallel Processing**: Allows concurrent processing of different date ranges
- **Data Lifecycle**: Simplifies data retention and archival policies

**Why Incremental Normalization?**
- **Consistency**: Ensures all data uses same normalization parameters
- **Efficiency**: Avoids reprocessing entire dataset for statistics
- **Accuracy**: Maintains statistical accuracy as data grows
- **Real-time Compatibility**: Enables consistent real-time inference

### ML Pipeline Design Decisions

**Why Random Cut Forest?**
- **Unsupervised**: No need for labeled anomaly data
- **Scalable**: Handles high-dimensional data efficiently
- **Real-time**: Fast inference suitable for real-time applications
- **Robust**: Handles varying data distributions well

**Why Step Functions?**
- **Orchestration**: Manages complex multi-step workflows
- **Error Handling**: Built-in retry and error handling
- **Monitoring**: Visual workflow monitoring and debugging
- **Integration**: Native integration with AWS services

**Why In-place Endpoint Updates?**
- **Zero Downtime**: Seamless model updates without service interruption
- **Cost Efficiency**: Single endpoint reduces infrastructure costs
- **Simplicity**: Consistent endpoint name simplifies client integration
- **Version Control**: Model versioning through SageMaker model registry

### Real-time API Design Decisions

**Why API Gateway + Lambda?**
- **Serverless**: No server management overhead
- **Scalable**: Automatic scaling based on demand
- **Security**: Built-in authentication and authorization
- **Monitoring**: Comprehensive logging and metrics

**Why API Key Authentication?**
- **Simplicity**: Easy to implement and manage
- **Control**: Fine-grained access control and rate limiting
- **Monitoring**: Track usage per API key
- **Flexibility**: Easy to revoke or rotate keys

### Alert System Design Decisions

**Why SQS + DynamoDB?**
- **Reliability**: SQS ensures message delivery
- **Scalability**: Both services scale automatically
- **Durability**: Messages and alerts are persisted
- **Query Flexibility**: DynamoDB supports complex queries

**Why Dead Letter Queue?**
- **Error Recovery**: Captures failed messages for analysis
- **System Resilience**: Prevents message loss
- **Debugging**: Enables investigation of processing failures
- **Manual Intervention**: Allows manual processing of edge cases

## Customization Guide

### Adding New ETL Steps

To add custom data transformations to the ETL pipeline:

1. **Create New Transformer Class**:
```python
# In source/assets/etl_scripts/etl_glue_job.py

class CustomDataTransformer(Transformer):
    def __init__(self, custom_parameter: str) -> None:
        super().__init__()
        self.custom_parameter = custom_parameter
    
    def _transform(self, df: DataFrame) -> [DataFrame, List[str]]:
        # Your custom transformation logic
        df = df.withColumn("new_feature", 
                          col("existing_column") * 2)
        
        new_features = ["new_feature"]
        return [df, new_features]
```

2. **Integrate in ETL Pipeline**:
```python
# Add after existing transformers
custom_transformer = CustomDataTransformer("parameter_value")
df, custom_features = custom_transformer.transform(df)

# Update feature lists
TRAINING_COLUMNS = (default_numeric_features + 
                   engineered_numeric_features + 
                   custom_features + 
                   default_categorical_features)
```

3. **Update Model Configuration**:
```python
# In ml_training_stepfunction.py, update feature dimension
model_parameters = ModelParameters(
    feature_dimension="5",  # Updated from 4 to 5
    num_samples_per_tree="256",
    num_trees="100"
)
```

### Changing the ML Model

To replace Random Cut Forest with a custom model:

1. **Create Custom Training Script**:
```python
# Create new file: source/assets/training_scripts/custom_model.py
import joblib
from sklearn.ensemble import IsolationForest

def train_model(training_data_path, model_output_path):
    # Load training data
    data = pd.read_csv(training_data_path)
    
    # Train custom model
    model = IsolationForest(contamination=0.1)
    model.fit(data)
    
    # Save model
    joblib.dump(model, f"{model_output_path}/model.pkl")
```

2. **Update Training Job Configuration**:
```python
# In ml_training_stepfunction.py
training_job = aws_stepfunctions_tasks.SageMakerCreateTrainingJob(
    self,
    "train-model",
    # Replace with custom training image
    algorithm_specification=aws_stepfunctions_tasks.AlgorithmSpecification(
        training_image=aws_stepfunctions_tasks.DockerImage.from_registry(
            "your-account.dkr.ecr.region.amazonaws.com/custom-model:latest"
        ),
        training_input_mode=aws_stepfunctions_tasks.InputMode.FILE,
    ),
    # Update hyperparameters for your model
    hyperparameters={
        "contamination": "0.1",
        "n_estimators": "100",
    },
    # ... rest of configuration
)
```

3. **Update Inference Code**:
```python
# In source/lambda/realtime_inference/function/main.py
# Replace SageMaker endpoint call with custom inference logic
def invoke_custom_model(features, model_path):
    model = joblib.load(model_path)
    anomaly_score = model.decision_function([features])[0]
    return abs(anomaly_score)  # Convert to positive score
```

### Customizing Real-time Inference

To modify the real-time API behavior:

1. **Add New Input Fields**:
```python
# In source/lambda/realtime_inference/function/main.py
# Update input validation
required_fields = [
    "vehicle_id", "tire_id", "pressure", "temperature", 
    "delta_pressure", "delta_temp", "new_field"
]

new_field = body.get("new_field")
if None in [vehicle_id, tire_id, pressure, temperature, 
           delta_pressure, delta_temp, new_field]:
    # Handle validation error
```

2. **Modify Feature Normalization**:
```python
def normalize_features(pressure, temperature, delta_pressure, 
                      delta_temp, new_field, stats):
    features = {
        "pressure": pressure,
        "temperature": temperature,
        "delta_pressure": delta_pressure,
        "delta_temp": delta_temp,
        "new_field": new_field,  # Add new field
    }
    
    normalized = []
    for feature_name in ["pressure", "temperature", "delta_pressure", 
                        "delta_temp", "new_field"]:
        # Normalization logic remains the same
```

3. **Update API Gateway Configuration**:
```python
# In ml_realtime_inference.py
# Modify rate limits
usage_plan = aws_apigateway.UsagePlan(
    self,
    "realtime-inference-usage-plan",
    throttle=aws_apigateway.ThrottleSettings(
        rate_limit=200,  # Increased from 100
        burst_limit=400,  # Increased from 200
    ),
    quota=aws_apigateway.QuotaSettings(
        limit=50000,  # Increased from 10000
        period=aws_apigateway.Period.DAY,
    ),
)
```

You can also replace the model with another AWS model by skipping step 1 and following
step 2 and 3 above. You can get more information of other AWS models on [AWS SageMaker Documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/algos.html)

### Customizing Alert Processing

To modify alert generation and processing:

1. **Custom Alert Criteria**:
```python
# In source/lambda/transform_predictions_to_alerts/function/main.py
def should_create_alert(anomaly_score, threshold, vehicle_data):
    # Custom logic for alert creation
    base_condition = anomaly_score > threshold
    
    # Add custom conditions
    high_risk_vehicle = vehicle_data.get("risk_category") == "high"
    critical_tire = vehicle_data.get("tire_id") in ["FL", "FR"]
    
    return base_condition and (high_risk_vehicle or critical_tire)
```

2. **Custom Alert Enrichment**:
```python
def enrich_alert_data(alert_data, vehicle_id, tire_id):
    # Add custom metadata
    alert_data.update({
        "severity": calculate_severity(alert_data["anomaly_score"]),
        "recommended_action": get_recommended_action(tire_id),
        "maintenance_history": get_maintenance_history(vehicle_id),
    })
    return alert_data
```

3. **Adding notifications**:

Modify the code in `alerts_processor` lambda and add the notification logic.

## Deployment Instructions

### Deployment Prerequisites

#### Clone the Repository

If you have not done so, first clone the repository, and then `cd` into the created directory. If you have
already cloned the repository, ensure you still `cd` into the solution's directory.

> **WARNING:** If you do not `cd` into the solution's directory before installing tools,
> the correct versions may not be installed.

#### Required Tools

To deploy Tire Predictive Maintenance, a variety of tools are required. These deploy instructions will install the
following to your machine:

- [Pyenv](https://github.com/pyenv/pyenv)
- [Python](https://www.python.org/)
- [Pip](https://pypi.org/project/pip/)
- [Poetry](https://python-poetry.org/docs/)
- [AWS CLI](https://docs.aws.amazon.com/cli/)
- [AWS CDK Toolkit](https://docs.aws.amazon.com/cdk/v2/guide/cli.html)

#### Required Tool Versions

Certain tools also require specific versions. See the table below for the appropriate versions. Following the
provided install instructions will install the correct versions.

For tools not listed here, stable versions should work appropriately.

| Dependency | Version  |
|------------|----------|
| [Python](https://www.python.org)                                              | 3.12.*     |

##### Verify Required Tool Installations

Run the following command to verify the proper installation of all of the tools listed above. If
any errors are displayed, attempt to reinstall that tool.

```bash
make verify-required-tools
```

#### Install Solution Dependencies

Now that you have the correct tools, you can install the dependencies used by the solution using `make install`.
After installing, activate the environment which contains the dependencies.

```bash
make install
```

#### Setup Environment Variables

To deploy the solution, a variety of environment variables are required. These environment variables will be used to
provide the values to your deployment. To generate the file which will store these environment variables and
provide their values, run the following command:

```bash
make create-rc-file
source .predrc
```

> **IMPORTANT:** The `source .mmtrc` command is essential for getting the configuration settings set in your terminal.

### Deploy

Refer to the [architecture diagrams](#architecture-overview) for a detailed walk-through of what is deployed.

#### Prerequisites

Ensure you've followed the steps in the previous [deployment prerequisites](#deployment-prerequisites) section.

- Prerequisite tools installed. Refer to the [required tools](#required-tools) sections for details.
- Solution dependencies installed. Refer to the [install solution dependencies](#install-solution-dependencies)
  section for details.
- Environment variables set. Refer to the [setup environment variables](#setup-environment-variables) section for details.

#### Build the Solution

The build target builds required assets (e.g. packaged lambdas) and creates the AWS CloudFormation templates for the solution.
Assets are then bundled in the deployment/global-s3-assets and deployment/regional-s3-assets directories.

```bash
make build
```

#### Deploy on AWS

The deploy target deploys the solution.

```bash
make deploy
```

## Operational Procedures

### Daily Operations

1. **Monitor ETL Jobs**:
   - Check Glue job completion status
   - Verify data quality metrics
   - Review processing logs for errors

2. **Check ML Pipeline Health**:
   - Verify training job completion (weekly)
   - Monitor endpoint health and latency
   - Check inference accuracy metrics

3. **Review Alerts**:
   - Check DynamoDB for new alerts
   - Process any items in dead letter queue
   - Verify alert processing latency

### Weekly Operations

1. **Model Retraining**:
   - Review model performance metrics
   - Trigger manual retraining if needed
   - Validate new model performance

2. **Data Quality Assessment**:
   - Analyze data completeness and accuracy
   - Review normalization statistics trends
   - Check for data drift indicators

### Monthly Operations

1. **Cost Optimization**:
   - Review AWS costs by service
   - Optimize instance types and storage
   - Clean up old data and models

2. **Security Review**:
   - Rotate API keys
   - Review IAM permissions
   - Update security patches

### Troubleshooting Common Issues

**ETL Job Failures**:
```bash
# Check Glue job logs
aws logs describe-log-groups --log-group-name-prefix "/aws-glue"

# Verify S3 permissions
aws s3 ls s3://your-source-bucket/

# Check SSM parameter access
aws ssm get-parameter --name "/tire-maintenance/normalization-stats"
```

**Training Job Failures**:
```bash
# Check SageMaker training job status
aws sagemaker describe-training-job --training-job-name your-job-name

# Review Step Functions execution
aws stepfunctions describe-execution --execution-arn your-execution-arn
```

**API Gateway Issues**:
```bash
# Test API endpoint
curl -X POST https://your-api-id.execute-api.region.amazonaws.com/dev/predict \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: your-api-key" \
  -d '{"vehicle_id":"TEST","tire_id":"FL","pressure":32.5,"temperature":75.0,"delta_pressure":-0.5,"delta_temp":2.0}'

# Check Lambda logs
aws logs tail /aws/lambda/realtime-inference-lambda --follow
```

## Monitoring and Alerting

The system includes comprehensive monitoring through:

- **CloudWatch Metrics**: Custom metrics for all components
- **CloudWatch Logs**: Detailed logging for debugging
- **X-Ray Tracing**: Performance analysis and bottleneck identification
- **DynamoDB Monitoring**: Alert processing and storage metrics
- **API Gateway Monitoring**: Request rates, latency, and error rates

Key metrics to monitor:
- ETL job success rate and duration
- Model training completion and accuracy
- API response times and error rates
- Alert processing latency
- Data quality scores

This architecture provides a robust, scalable, and maintainable solution for tire predictive maintenance that can be easily customized for different use cases and requirements.