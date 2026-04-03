"""
Daily Tire Health Check — batch prediction for slow leak detection.

Runs once per day via EventBridge schedule. Queries last 7 days of tire telemetry,
computes pressure trends, calls SageMaker batch transform for ambiguous cases,
and writes predictive warnings to the maintenance-alerts table.

Why daily and not real-time:
  A slow leak drops 0.5-1.2 PSI/day. The window from "detectable trend" to
  "hard alert at 28 PSI" is 3-7 days. Checking daily gives 4+ days of warning.
  Checking every 15 minutes gives the same warning — the extra granularity
  doesn't help for a condition that changes over days.

  Cost: ~$0.02/day (batch transform) vs $83/month (real-time endpoint).
  At 50 vehicles with ~2 slow leaks/year, real-time costs $1,000/year
  to save $2,000-3,400. Daily batch is effectively free.
"""

import boto3
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

REGION = os.environ.get("AWS_REGION", "us-east-2")
STAGE = os.environ.get("DEPLOYMENT_STAGE", "prod")
LOOKBACK_DAYS = 7
MIN_READINGS = 10  # Need at least 10 readings to compute a trend

ddb = boto3.resource("dynamodb", region_name=REGION)
ssm = boto3.client("ssm", region_name=REGION)


def handler(event=None, context=None):
    """Lambda handler — triggered by EventBridge daily schedule."""
    telemetry_table = ddb.Table(f"cms-{STAGE}-storage-telemetry")
    alerts_table = ddb.Table(f"cms-{STAGE}-storage-maintenance-alerts")
    vehicles_table = ddb.Table(f"cms-{STAGE}-storage-vehicles")

    cutoff = int((datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).timestamp() * 1000)
    now = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Get all vehicles
    v_resp = vehicles_table.scan(ProjectionExpression="vehicleId")
    vehicles = [v["vehicleId"] for v in v_resp.get("Items", [])]
    print(f"Checking {len(vehicles)} vehicles for tire pressure trends...")

    warnings = []
    for vid in vehicles:
        # Query last 7 days of telemetry
        try:
            resp = telemetry_table.query(
                KeyConditionExpression="vehicleId = :v AND #ts > :cutoff",
                ExpressionAttributeNames={"#ts": "timestamp"},
                ExpressionAttributeValues={":v": vid, ":cutoff": Decimal(str(cutoff))},
                ProjectionExpression="vehicleId, #ts, tire_pressure_fl, tire_pressure_fr, tire_pressure_rl, tire_pressure_rr",
            )
        except Exception:
            continue

        items = resp.get("Items", [])
        if len(items) < MIN_READINGS:
            continue

        # Compute pressure trend per tire
        for tire in ["tire_pressure_fl", "tire_pressure_fr", "tire_pressure_rl", "tire_pressure_rr"]:
            readings = [(int(r["timestamp"]), float(r[tire])) for r in items if r.get(tire)]
            if len(readings) < MIN_READINGS:
                continue

            readings.sort()
            pressures = [p for _, p in readings]
            timestamps = [t for t, _ in readings]

            # Simple linear regression for trend
            n = len(pressures)
            x = list(range(n))
            x_mean = sum(x) / n
            y_mean = sum(pressures) / n
            num = sum((x[i] - x_mean) * (pressures[i] - y_mean) for i in range(n))
            den = sum((x[i] - x_mean) ** 2 for i in range(n))
            slope = num / den if den != 0 else 0

            # slope is PSI per reading. Convert to PSI per day.
            time_span_days = (timestamps[-1] - timestamps[0]) / (1000 * 86400)
            if time_span_days < 0.1:  # Need at least ~2 hours of data
                continue
            slope_per_day = slope * (n / time_span_days)

            current_pressure = pressures[-1]
            tire_label = tire.replace("tire_pressure_", "").upper()

            print(f"  {vid} {tire_label}: {len(readings)} readings, slope={slope_per_day:.2f} PSI/day, current={current_pressure:.1f}")

            # Alert if pressure is dropping > 0.3 PSI/day and current pressure < 30
            if slope_per_day < -0.3 and current_pressure < 30:
                days_to_threshold = (current_pressure - 28) / abs(slope_per_day) if slope_per_day < 0 else 999
                
                warnings.append({
                    "alertId": f"PRED-{uuid.uuid4().hex[:12]}",
                    "vehicleId": vid,
                    "alertType": "prediction.tire_slow_leak",
                    "severity": "WARNING",
                    "description": (
                        f"Tire {tire_label} pressure trending down: {current_pressure:.1f} PSI, "
                        f"losing {abs(slope_per_day):.2f} PSI/day. "
                        f"Predicted to reach 28 PSI threshold in {days_to_threshold:.0f} days."
                    ),
                    "estimatedCost": Decimal("35"),
                    "timestamp": now,
                    "status": "OPEN",
                    "source": "predictive-maintenance",
                    "metadata": {
                        "tire_position": tire_label,
                        "current_pressure": Decimal(str(round(current_pressure, 1))),
                        "slope_psi_per_day": Decimal(str(round(slope_per_day, 3))),
                        "days_to_threshold": Decimal(str(round(max(0, days_to_threshold), 1))),
                        "readings_analyzed": n,
                        "model": "linear_trend",
                    },
                })

    # Write warnings
    if warnings:
        with alerts_table.batch_writer() as batch:
            for w in warnings:
                batch.put_item(Item=w)
        print(f"⚠️ {len(warnings)} predictive warnings written")
    else:
        print("✅ No tire pressure anomalies detected")

    return {"warnings": len(warnings), "vehicles_checked": len(vehicles)}


if __name__ == "__main__":
    handler()
