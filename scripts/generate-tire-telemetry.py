#!/usr/bin/env python3
"""
Generate synthetic tire telemetry data for testing.
Creates 90 days of realistic tire pressure, temperature, and wear data.
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
import boto3

def generate_tire_telemetry(days=90, vehicles=10):
    """Generate synthetic tire telemetry data."""
    data = []
    start_date = datetime.now() - timedelta(days=days)
    
    for vehicle_id in range(1, vehicles + 1):
        vin = f"5NP85LG49W2ULPJS{vehicle_id}"
        
        for day in range(days):
            current_date = start_date + timedelta(days=day)
            
            # Generate 24 readings per day (hourly)
            for hour in range(24):
                timestamp = current_date + timedelta(hours=hour)
                
                # Simulate tire degradation over time
                wear_factor = day / days
                
                reading = {
                    "vin": vin,
                    "timestamp": int(timestamp.timestamp() * 1000),
                    "tire_data": {
                        "front_left": {
                            "pressure_psi": round(32 - (wear_factor * 2) + random.uniform(-1, 1), 2),
                            "temperature_f": round(75 + random.uniform(-5, 15), 2),
                            "tread_depth_mm": round(8 - (wear_factor * 2), 2)
                        },
                        "front_right": {
                            "pressure_psi": round(32 - (wear_factor * 2) + random.uniform(-1, 1), 2),
                            "temperature_f": round(75 + random.uniform(-5, 15), 2),
                            "tread_depth_mm": round(8 - (wear_factor * 2), 2)
                        },
                        "rear_left": {
                            "pressure_psi": round(32 - (wear_factor * 2.5) + random.uniform(-1, 1), 2),
                            "temperature_f": round(75 + random.uniform(-5, 15), 2),
                            "tread_depth_mm": round(8 - (wear_factor * 2.5), 2)
                        },
                        "rear_right": {
                            "pressure_psi": round(32 - (wear_factor * 2.5) + random.uniform(-1, 1), 2),
                            "temperature_f": round(75 + random.uniform(-5, 15), 2),
                            "tread_depth_mm": round(8 - (wear_factor * 2.5), 2)
                        }
                    },
                    "vehicle_metrics": {
                        "speed_mph": random.randint(0, 75),
                        "odometer_miles": 10000 + (day * 50),
                        "ambient_temp_f": round(70 + random.uniform(-10, 20), 2)
                    }
                }
                data.append(reading)
    
    return data

def upload_to_s3(data, bucket_name, prefix="raw-telemetry"):
    """Upload data to S3 in partitioned structure."""
    s3 = boto3.client('s3')
    
    # Group by timestamp for partitioning
    for record in data:
        ts = datetime.fromtimestamp(record['timestamp'] / 1000)
        partition = f"{prefix}/year={ts.year}/month={ts.month:02d}/day={ts.day:02d}/hour={ts.hour:02d}"
        key = f"{partition}/{record['vin']}-{record['timestamp']}.json"
        
        s3.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=json.dumps(record),
            ContentType='application/json'
        )
    
    print(f"✓ Uploaded {len(data)} records to s3://{bucket_name}/{prefix}/")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: generate-tire-telemetry.py <bucket-name> [days] [vehicles]")
        sys.exit(1)
    
    bucket = sys.argv[1]
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    vehicles = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    
    print(f"Generating {days} days of telemetry for {vehicles} vehicles...")
    data = generate_tire_telemetry(days, vehicles)
    
    print(f"Uploading to S3...")
    upload_to_s3(data, bucket)
    
    print(f"✓ Complete! Generated {len(data)} records")
