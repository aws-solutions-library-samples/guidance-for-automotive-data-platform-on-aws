# Integrating with Connected Mobility Guidance

This guide explains how to feed live tire pressure telemetry from the CMS pipeline into the predictive maintenance system for real-time and batch anomaly detection.

## Integration Architecture

```
CMS Pipeline (connected-mobility-guidance-on-aws)
    │
    Signal Catalog (DynamoDB)
    │  tire_fl, tire_fr, tire_rl, tire_rr (PSI)
    │  engineTemp (°F), speed (mph)
    │
    EventDrivenTelemetryProcessor (Flink)
    │
    ├── Redis (latest vehicle state)
    │     vehicle:{id}:signals → tire_fl=35.2, tire_fr=34.8, ...
    │
    ├── cms-telemetry-preprocessed (Kafka)
    │     canonical JSON with tire pressure per message
    │
    └── S3 Iceberg sink
          partitioned by fleetId + day
                    │
                    ▼
    ┌───────────────────────────────────────────────┐
    │  Predictive Maintenance Integration           │
    │  (this repo)                                  │
    │                                               │
    │  Option A: Batch (hourly/daily)               │
    │    Root ETL Glue Job reads S3 sink            │
    │    → extract tire signals per vehicle          │
    │    → compute pressure deltas + leak rates      │
    │    → SageMaker batch transform (RCF model)     │
    │    → alerts to DynamoDB + SNS                  │
    │                                               │
    │  Option B: Real-time                          │
    │    Lambda consumes from Kafka topic            │
    │    → extract tire signals                      │
    │    → call SageMaker endpoint (RCF inference)   │
    │    → alert if anomaly score > threshold        │
    └───────────────────────────────────────────────┘
```

## Signal Catalog Mapping

The CMS signal catalog defines tire pressure signals in canonical units (PSI). The predictive maintenance system expects these specific fields:

| CMS Signal (`json_field`) | CMS Unit | PM Field | PM Expected | Notes |
|---------------------------|----------|----------|-------------|-------|
| `tire_fl` | PSI | `tire_pressure` + `tire_id=FL` | PSI | Front left |
| `tire_fr` | PSI | `tire_pressure` + `tire_id=FR` | PSI | Front right |
| `tire_rl` | PSI | `tire_pressure` + `tire_id=RL` | PSI | Rear left |
| `tire_rr` | PSI | `tire_pressure` + `tire_id=RR` | PSI | Rear right |
| `engineTemp` | °F | `ambient_temp` | °F | Temperature affects tire pressure |
| `speed` | mph | `vehicle_speed` | mph | Speed correlates with pressure changes |
| `timestamp` | epoch ms | `timestamp` | epoch ms | Measurement time |
| `vehicleId` | string | `vehicle_id` | string | Vehicle identifier |

### Unit Conversions

CMS normalizes all tire pressure to PSI regardless of source. If the predictive maintenance model was trained on different units, apply conversions:

- PSI → kPa: `× 6.89476`
- PSI → bar: `× 0.0689476`

No conversion is needed if both systems use PSI (the default).

### OEM Signal Availability

Not all OEM sources provide tire pressure at the same frequency or precision:

| Source | Tire Pressure | Frequency | Precision |
|--------|:------------:|-----------|-----------|
| Simulator/Direct | ✅ | 1-3 seconds | 0.1 PSI |
| FleetWise Edge (CAN) | ✅ | 1-5 seconds | 0.1 PSI |
| OEM Cloud (REST polling) | ✅ | 5 minutes | 1 PSI |
| OEM Cloud (streaming) | ✅ | 1-60 seconds | varies |

The batch approach works well for all sources. The real-time approach is most effective with FleetWise Edge and simulator data due to higher frequency.

## Option A: Batch Integration (Recommended)

### How It Works

1. CMS Flink pipeline writes normalized telemetry to S3 (Iceberg sink, partitioned by fleetId + day)
2. The Root ETL Glue job reads new tire pressure data from S3
3. The job pivots the flat CMS format into the per-tire format the PM model expects
4. SageMaker batch transform runs the Random Cut Forest model
5. Anomalies generate alerts in DynamoDB and SNS notifications

### Transform: CMS Format → PM Format

CMS writes one record per vehicle per timestamp with all signals flat:

```json
{
  "vehicleId": "VEH-001",
  "timestamp": 1710764400000,
  "tire_fl": 35.2,
  "tire_fr": 34.8,
  "tire_rl": 33.1,
  "tire_rr": 33.5,
  "engineTemp": 195.0,
  "speed": 65.2
}
```

The PM system expects one record per tire:

```json
{"vehicle_id": "VEH-001", "tire_id": "FL", "tire_pressure": 35.2, "timestamp": 1710764400000, "ambient_temp": 195.0, "vehicle_speed": 65.2}
{"vehicle_id": "VEH-001", "tire_id": "FR", "tire_pressure": 34.8, "timestamp": 1710764400000, "ambient_temp": 195.0, "vehicle_speed": 65.2}
{"vehicle_id": "VEH-001", "tire_id": "RL", "tire_pressure": 33.1, "timestamp": 1710764400000, "ambient_temp": 195.0, "vehicle_speed": 65.2}
{"vehicle_id": "VEH-001", "tire_id": "RR", "tire_pressure": 33.5, "timestamp": 1710764400000, "ambient_temp": 195.0, "vehicle_speed": 65.2}
```

### Configuration

Set the CMS S3 source in the Root ETL Glue job arguments:

```bash
# In the Glue job default arguments or via Makefile
--cms_source_bucket=cms-${DEPLOYMENT_STAGE}-datalake-${ACCOUNT_ID}
--cms_source_prefix=telemetry/
```

## Option B: Real-Time Integration

### How It Works

1. A Lambda function is triggered by MSK (Kafka) from `cms-telemetry-preprocessed`
2. For each message, it extracts tire pressure signals
3. It calls the SageMaker real-time inference endpoint
4. If the anomaly score exceeds the threshold, it writes an alert

### Configuration

Add the MSK trigger to the real-time inference Lambda:

```bash
aws lambda create-event-source-mapping \
  --function-name ${PM_INFERENCE_LAMBDA} \
  --event-source-arn ${MSK_CLUSTER_ARN} \
  --topics cms-telemetry-preprocessed \
  --starting-position LATEST \
  --batch-size 100
```

### Input Adapter

The real-time Lambda needs a small adapter to convert CMS canonical format to the PM inference format. Add this to the input processing:

```python
def adapt_cms_to_pm(cms_record):
    """Convert CMS canonical telemetry to PM per-tire records."""
    base = {
        'vehicle_id': cms_record.get('vehicleId'),
        'timestamp': cms_record.get('timestamp'),
        'ambient_temp': cms_record.get('engineTemp'),
        'vehicle_speed': cms_record.get('speed'),
    }
    tire_map = {
        'FL': 'tire_fl', 'FR': 'tire_fr',
        'RL': 'tire_rl', 'RR': 'tire_rr',
    }
    records = []
    for tire_id, field in tire_map.items():
        pressure = cms_record.get(field)
        if pressure is not None:
            records.append({**base, 'tire_id': tire_id, 'tire_pressure': pressure})
    return records
```

## Feeding Alerts Back to CMS

When the PM system detects an anomaly, it can write the alert back to the CMS maintenance alerts table so fleet operators see it in the Fleet Manager UI:

```python
import boto3

dynamodb = boto3.resource('dynamodb')
cms_alerts_table = dynamodb.Table(f'cms-{stage}-storage-maintenance-alerts')

def push_alert_to_cms(alert):
    cms_alerts_table.put_item(Item={
        'alertId': alert['alert_id'],
        'vehicleId': alert['vehicle_id'],
        'alertType': 'TIRE_PRESSURE_ANOMALY',
        'severity': 'high' if alert['anomaly_score'] > 0.9 else 'medium',
        'message': f"Tire {alert['tire_id']} pressure anomaly detected (score: {alert['anomaly_score']:.2f})",
        'timestamp': alert['timestamp'],
        'metadata': {
            'tire_id': alert['tire_id'],
            'pressure': str(alert['tire_pressure']),
            'anomaly_score': str(alert['anomaly_score']),
            'model': 'random_cut_forest',
        },
        'status': 'active',
    })
```

This makes PM alerts appear alongside other maintenance alerts in the CMS Fleet Manager dashboard, safety alerts page, and vehicle detail view — no CMS code changes required.

## Prerequisites

- Connected Mobility Guidance deployed with Flink pipeline running (Phases 1-5)
- Predictive Maintenance stack deployed (`make deploy` in this repo)
- For batch: CMS S3 Iceberg sink writing telemetry data
- For real-time: MSK cluster accessible from the PM Lambda (VPC networking)

## Verifying the Integration

```bash
# Check that CMS is writing tire pressure data to S3
aws s3 ls s3://cms-${STAGE}-datalake-${ACCOUNT}/telemetry/ --region ${REGION}

# Check PM alerts table for new anomalies
aws dynamodb scan \
  --table-name ${PM_ALERTS_TABLE} \
  --filter-expression "alertType = :t" \
  --expression-attribute-values '{":t":{"S":"TIRE_PRESSURE_ANOMALY"}}' \
  --select COUNT --region ${REGION}

# Check CMS maintenance alerts for PM-generated alerts
aws dynamodb scan \
  --table-name cms-${STAGE}-storage-maintenance-alerts \
  --filter-expression "alertType = :t" \
  --expression-attribute-values '{":t":{"S":"TIRE_PRESSURE_ANOMALY"}}' \
  --select COUNT --region ${REGION}
```
