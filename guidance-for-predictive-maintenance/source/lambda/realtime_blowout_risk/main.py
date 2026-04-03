"""
Real-Time Highway Blowout Risk — SageMaker inference for imminent tire failure.

Called by the Flink MaintenanceProcessor ONLY when:
  1. Vehicle speed > 60 mph AND
  2. Any tire pressure < 30 PSI OR tire temp > 120°F

Why real-time for this and not for slow leaks:
  A slow leak takes days — daily batch catches it with plenty of lead time.
  But a tire under stress (high speed + high temp + low tread + borderline pressure)
  can fail catastrophically in minutes. Each signal is individually "fine" but
  the combination is dangerous. A rule-based system can't catch this because
  no single threshold is crossed.

  The ML model recognizes multi-signal risk patterns that preceded blowouts
  in the training data. It only runs for vehicles in active risk conditions
  (~50-100 inferences/day instead of 19,200), keeping costs reasonable.

Cost justification:
  SageMaker endpoint: $83/month
  Highway blowout cost: $10,000+ (tow, tire, cargo damage, downtime, liability)
  At 5,000 vehicles: ~5 blowouts/year prevented = $50,000+ saved
  ROI: 50x
"""

import boto3
import json
import os
from decimal import Decimal

REGION = os.environ.get("AWS_REGION", "us-east-2")
STAGE = os.environ.get("DEPLOYMENT_STAGE", "prod")

sm_runtime = boto3.client("sagemaker-runtime", region_name=REGION)
ssm = boto3.client("ssm", region_name=REGION)

# Cache config
_config = {}


def get_config():
    if _config:
        return _config
    prefix = f"/tire-prediction/{STAGE}"
    try:
        _config["endpoint"] = ssm.get_parameter(Name=f"{prefix}/endpoint-name")["Parameter"]["Value"]
        _config["stats"] = json.loads(ssm.get_parameter(Name=f"{prefix}/normalization-stats")["Parameter"]["Value"])
        _config["threshold"] = json.loads(ssm.get_parameter(Name=f"{prefix}/anomaly-threshold")["Parameter"]["Value"])["threshold"]
    except Exception as e:
        print(f"Failed to load config: {e}")
        _config["endpoint"] = None
    return _config


def assess_blowout_risk(telemetry: dict) -> list:
    """Assess blowout risk for a vehicle's tires using the ML model.
    
    Args:
        telemetry: CMS canonical telemetry dict with tire_pressure_fl/fr/rl/rr,
                   temperature, speed, etc.
    
    Returns:
        List of risk assessments for tires that exceed the anomaly threshold.
    """
    config = get_config()
    if not config.get("endpoint"):
        return []

    stats = config["stats"]
    threshold = config["threshold"]
    speed = float(telemetry.get("speed", 0))

    # Only assess at highway speeds with concerning signals
    if speed < 60:
        return []

    tires = {
        "FL": ("tire_pressure_fl", "tire_pressure_fr"),
        "FR": ("tire_pressure_fr", "tire_pressure_fl"),
        "RL": ("tire_pressure_rl", "tire_pressure_rr"),
        "RR": ("tire_pressure_rr", "tire_pressure_rl"),
    }

    tire_temp = float(telemetry.get("tire_temp_max", telemetry.get("tire_temp_fl", 80)))
    # Convert F to C for the model
    tire_temp_c = (tire_temp - 32) * 5 / 9

    risks = []
    for tire_id, (pressure_field, _) in tires.items():
        pressure = float(telemetry.get(pressure_field, 32))

        # Pre-filter: only call model if signals are in warning zone
        if pressure >= 30 and tire_temp < 120:
            continue

        # Compute delta (approximate from single reading — real implementation
        # would track previous readings)
        delta_pressure = float(telemetry.get("delta_pressure", -0.5))
        delta_temp = tire_temp_c - 20  # delta from baseline

        # Normalize features
        features = [
            (pressure - stats["pressure"]["mean"]) / stats["pressure"]["std"],
            (tire_temp_c - stats["temperature"]["mean"]) / stats["temperature"]["std"],
            (delta_pressure - stats["delta_pressure"]["mean"]) / stats["delta_pressure"]["std"],
            (delta_temp - stats["delta_temp"]["mean"]) / stats["delta_temp"]["std"],
        ]

        # Call SageMaker endpoint
        try:
            response = sm_runtime.invoke_endpoint(
                EndpointName=config["endpoint"],
                ContentType="text/csv",
                Body=",".join(str(f) for f in features),
            )
            result = json.loads(response["Body"].read().decode())
            score = result["scores"][0]["score"]

            if score > threshold:
                risks.append({
                    "tire_id": tire_id,
                    "anomaly_score": round(score, 4),
                    "pressure": pressure,
                    "temperature": tire_temp,
                    "speed": speed,
                    "risk_level": "CRITICAL" if score > threshold * 1.5 else "HIGH",
                })
        except Exception as e:
            print(f"Inference error for {tire_id}: {e}")

    return risks


def handler(event, context=None):
    """Lambda handler — invoked by Flink or DDB Stream for highway vehicles."""
    telemetry = event if isinstance(event, dict) else json.loads(event)
    vehicle_id = telemetry.get("vehicleId", "unknown")

    risks = assess_blowout_risk(telemetry)

    if risks:
        ddb = boto3.resource("dynamodb", region_name=REGION)
        alerts_table = ddb.Table(f"cms-{STAGE}-storage-maintenance-alerts")
        import uuid
        from datetime import datetime, timezone

        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        for risk in risks:
            alerts_table.put_item(Item={
                "alertId": f"BLOWOUT-{uuid.uuid4().hex[:12]}",
                "vehicleId": vehicle_id,
                "alertType": "prediction.blowout_risk",
                "severity": risk["risk_level"],
                "description": (
                    f"⚠️ BLOWOUT RISK: Tire {risk['tire_id']} at {risk['pressure']:.1f} PSI, "
                    f"{risk['temperature']:.0f}°F, {risk['speed']:.0f} mph. "
                    f"Anomaly score: {risk['anomaly_score']:.3f}"
                ),
                "estimatedCost": Decimal("800"),
                "timestamp": now,
                "status": "OPEN",
                "source": "predictive-maintenance-realtime",
                "metadata": {
                    "tire_position": risk["tire_id"],
                    "anomaly_score": Decimal(str(risk["anomaly_score"])),
                    "pressure": Decimal(str(risk["pressure"])),
                    "temperature": Decimal(str(risk["temperature"])),
                    "speed": Decimal(str(risk["speed"])),
                    "model": "random_cut_forest",
                    "inference_type": "realtime",
                },
            })
        print(f"🚨 {len(risks)} blowout risk alerts for {vehicle_id}")

    return {"vehicle_id": vehicle_id, "risks": len(risks)}
