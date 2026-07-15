# Tire Prediction API Usage Guide

## Overview

The Tire Prediction API provides real-time anomaly detection for tire sensor data. It uses machine learning to predict potential tire issues based on pressure and temperature readings.

## API Endpoint

The API is deployed via AWS API Gateway with the following structure:
- **Base URL**: Retrieved from SSM Parameter `/tire-prediction/api-url`
- **Endpoint**: `POST /predict`
- **Authentication**: API Key required (stored in SSM Parameter `/tire-prediction/api-key-id`)

## Authentication

The API uses API Key authentication. Include the API key in the request headers:

```
X-Api-Key: your-api-key-here
```

## Request Format

### Endpoint
```
POST {api_url}/predict
```

### Headers
```
Content-Type: application/json
X-Api-Key: {your-api-key}
```

### Request Body
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

### Field Descriptions
- `vehicle_id` (string): Unique identifier for the vehicle
- `tire_id` (string): Tire position identifier (FL=Front Left, FR=Front Right, RL=Rear Left, RR=Rear Right)
- `pressure` (number): Current tire pressure reading
- `temperature` (number): Current tire temperature reading
- `delta_pressure` (number): Change in pressure from previous reading
- `delta_temp` (number): Change in temperature from previous reading

## Response Format

### Success Response (200 OK)
```json
{
  "anomaly_score": 0.7542,
  "prediction": true,
  "vehicle_id": "VEHICLE_001",
  "tire_id": "FL"
}
```

### Field Descriptions
- `anomaly_score` (number): Numerical score indicating anomaly likelihood (0.0 to 1.0)
- `prediction` (boolean): `true` if anomaly detected, `false` if normal
- `vehicle_id` (string): Echo of input vehicle ID
- `tire_id` (string): Echo of input tire ID

### Error Responses

#### 400 Bad Request - Missing Fields
```json
{
  "error": "Missing required fields: vehicle_id, tire_id, pressure, temperature, delta_pressure, delta_temp"
}
```

#### 400 Bad Request - Invalid JSON
```json
{
  "error": "Invalid JSON in request body"
}
```

#### 403 Forbidden - Invalid API Key
```json
{
  "message": "Forbidden"
}
```

#### 503 Service Unavailable - Model Not Ready
```json
{
  "error": "Service Unavailable",
  "message": "Anomaly threshold not yet available. Please run batch inference first to establish baseline."
}
```

## Rate Limits

- **Rate Limit**: 100 requests per second
- **Burst Limit**: 200 requests
- **Daily Quota**: 10,000 requests per day

## Example Usage

### Python with requests
```python
import requests
import json

# API configuration
api_url = "https://your-api-id.execute-api.region.amazonaws.com/prod/"
api_key = "your-api-key"

# Request data
data = {
    "vehicle_id": "VEHICLE_001",
    "tire_id": "FL",
    "pressure": 32.5,
    "temperature": 75.0,
    "delta_pressure": -0.5,
    "delta_temp": 2.0
}

# Make request
response = requests.post(
    f"{api_url}predict",
    json=data,
    headers={
        "Content-Type": "application/json",
        "X-Api-Key": api_key
    }
)

if response.status_code == 200:
    result = response.json()
    print(f"Anomaly Score: {result['anomaly_score']}")
    print(f"Prediction: {result['prediction']}")
else:
    print(f"Error: {response.status_code} - {response.text}")
```

### curl
```bash
curl -X POST \
  https://your-api-id.execute-api.region.amazonaws.com/prod/predict \
  -H 'Content-Type: application/json' \
  -H 'X-Api-Key: your-api-key' \
  -d '{
    "vehicle_id": "VEHICLE_001",
    "tire_id": "FL",
    "pressure": 32.5,
    "temperature": 75.0,
    "delta_pressure": -0.5,
    "delta_temp": 2.0
  }'
```

## Getting API Credentials

The API URL and key are stored in AWS Systems Manager Parameter Store:

1. **API URL**: `/tire-prediction/api-url`
2. **API Key ID**: `/tire-prediction/api-key-id`

Use the AWS CLI or SDK to retrieve these values:

```bash
# Get API URL
aws ssm get-parameter --name "/tire-prediction/api-url" --query "Parameter.Value" --output text

# Get API Key ID
aws ssm get-parameter --name "/tire-prediction/api-key-id" --query "Parameter.Value" --output text

# Get actual API Key value (requires the key ID from above)
aws apigateway get-api-key --api-key YOUR_KEY_ID --include-value --query "value" --output text
```

## Testing

Use the provided `test_api_example.py` script to test the API:

```bash
python test_api_example.py
```

This script will:
1. Retrieve API credentials from AWS
2. Make a test prediction request
3. Display the results

## CORS Support

The API includes CORS headers to support web browser requests:
- `Access-Control-Allow-Origin: *`
- `Access-Control-Allow-Methods: POST, OPTIONS`
- `Access-Control-Allow-Headers: Content-Type, X-Api-Key, Authorization`

## Monitoring

The API includes:
- CloudWatch metrics for request count, latency, and errors
- CloudWatch logs for detailed request/response logging
- X-Ray tracing for performance analysis

Monitor the API through the AWS Console under API Gateway and CloudWatch services.