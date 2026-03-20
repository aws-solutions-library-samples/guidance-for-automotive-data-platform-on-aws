"""
CMS Telemetry Adapter for Predictive Maintenance

Transforms CMS canonical telemetry (flat, one record per vehicle)
into the per-tire format expected by the PM ETL and inference pipelines.

Usage:
  - Import adapt_cms_to_pm() in the Root ETL Glue job or real-time Lambda
  - Pass CMS canonical JSON records
  - Returns list of per-tire records ready for PM processing
"""


# CMS signal catalog field → PM tire_id mapping
TIRE_FIELD_MAP = {
    'tire_fl': 'FL',
    'tire_fr': 'FR',
    'tire_rl': 'RL',
    'tire_rr': 'RR',
}


def adapt_cms_to_pm(cms_record: dict) -> list[dict]:
    """Convert a CMS canonical telemetry record to PM per-tire records.

    Args:
        cms_record: CMS canonical JSON with flat tire fields (tire_fl, tire_fr, etc.)

    Returns:
        List of per-tire dicts with vehicle_id, tire_id, tire_pressure, timestamp,
        ambient_temp, vehicle_speed.
    """
    base = {
        'vehicle_id': cms_record.get('vehicleId'),
        'timestamp': cms_record.get('timestamp'),
        'ambient_temp': cms_record.get('engineTemp'),
        'vehicle_speed': cms_record.get('speed'),
    }

    records = []
    for cms_field, tire_id in TIRE_FIELD_MAP.items():
        pressure = cms_record.get(cms_field)
        if pressure is not None:
            records.append({
                **base,
                'tire_id': tire_id,
                'tire_pressure': float(pressure),
            })
    return records


def adapt_cms_batch(cms_records: list[dict]) -> list[dict]:
    """Batch convert CMS records to PM format."""
    result = []
    for record in cms_records:
        result.extend(adapt_cms_to_pm(record))
    return result


def push_alert_to_cms(alert: dict, cms_table_name: str, stage: str = 'dev'):
    """Write a PM alert back to the CMS maintenance alerts table.

    Args:
        alert: PM alert dict with vehicle_id, tire_id, anomaly_score, tire_pressure, timestamp
        cms_table_name: CMS maintenance alerts DynamoDB table name
        stage: Deployment stage
    """
    import boto3
    import uuid

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(cms_table_name)

    table.put_item(Item={
        'alertId': f"PM-{uuid.uuid4().hex[:12]}",
        'vehicleId': alert['vehicle_id'],
        'alertType': 'TIRE_PRESSURE_ANOMALY',
        'severity': 'high' if float(alert.get('anomaly_score', 0)) > 0.9 else 'medium',
        'message': (
            f"Tire {alert['tire_id']} pressure anomaly detected "
            f"(score: {float(alert.get('anomaly_score', 0)):.2f}, "
            f"pressure: {alert.get('tire_pressure')} PSI)"
        ),
        'timestamp': int(alert.get('timestamp', 0)),
        'metadata': {
            'tire_id': alert['tire_id'],
            'pressure': str(alert.get('tire_pressure', '')),
            'anomaly_score': str(alert.get('anomaly_score', '')),
            'model': 'random_cut_forest',
            'source': 'predictive-maintenance',
        },
        'status': 'active',
    })
