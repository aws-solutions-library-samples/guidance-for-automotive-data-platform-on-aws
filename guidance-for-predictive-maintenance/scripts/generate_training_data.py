#!/usr/bin/env python3
"""
Generate realistic tire telemetry training dataset for the predictive maintenance model.

Produces 6 months of per-tire telemetry for 50 vehicles with:
- Normal driving patterns (seasonal temp variation, altitude, load)
- Injected anomalies:
  - Slow leaks (gradual pressure loss over days)
  - Nail punctures (sudden pressure drop)
  - Valve stem failures (intermittent pressure loss)
  - Seasonal pressure changes (cold weather drops)
  - Overinflation events
  - Tread wear correlation with pressure

Output: Parquet files partitioned by year/month, ready for SageMaker training.
Each record is one tire reading (long format, not wide).

Schema:
  vehicle_id    str     Vehicle identifier
  tire_id       str     FL, FR, RL, RR
  timestamp     str     ISO 8601
  pressure      float   PSI
  temperature   float   Celsius
  tread_depth   float   mm
  speed         float   km/h
  ambient_temp  float   Celsius
  latitude      float   GPS lat
  longitude     float   GPS lng
  label         str     normal | slow_leak | puncture | valve_failure | overinflation
"""

import os
import random
import math
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

NUM_VEHICLES = 50
DAYS = 180  # 6 months
READINGS_PER_DAY = 48  # every 30 min when driving (~12 hours/day)
TIRE_POSITIONS = ["FL", "FR", "RL", "RR"]

# Realistic fleet cities with lat/lng and avg temps by month (°C)
CITIES = {
    "Dallas":   {"lat": 32.78, "lng": -96.80, "temps": [7, 10, 15, 20, 25, 30, 33, 33, 28, 21, 13, 8]},
    "Atlanta":  {"lat": 33.75, "lng": -84.39, "temps": [6, 8, 13, 18, 23, 27, 29, 28, 25, 18, 12, 7]},
    "Chicago":  {"lat": 41.88, "lng": -87.63, "temps": [-3, -1, 5, 11, 17, 23, 25, 24, 20, 13, 5, -1]},
    "Phoenix":  {"lat": 33.45, "lng": -112.07, "temps": [13, 15, 18, 23, 28, 34, 37, 36, 33, 26, 18, 13]},
    "Seattle":  {"lat": 47.61, "lng": -122.33, "temps": [5, 6, 8, 11, 14, 17, 20, 20, 17, 12, 7, 4]},
}

# Anomaly injection rates
SLOW_LEAK_PROB = 0.08       # 8% of vehicle-tires get a slow leak
PUNCTURE_PROB = 0.04        # 4% get a puncture
VALVE_FAILURE_PROB = 0.03   # 3% get valve failure
OVERINFLATION_PROB = 0.02   # 2% get overinflated


def ambient_temp_for_day(city: dict, day_of_year: int) -> float:
    """Get realistic ambient temperature for a city on a given day."""
    month = (day_of_year // 30) % 12
    base = city["temps"][month]
    # Daily variation
    return base + random.gauss(0, 3)


def pressure_from_temp(base_pressure: float, ambient_c: float, ref_temp_c: float = 20.0) -> float:
    """Adjust tire pressure for temperature (Gay-Lussac's law approximation).
    ~1 PSI per 10°F (5.5°C) change."""
    delta_c = ambient_c - ref_temp_c
    return base_pressure + (delta_c / 5.5)


def generate_vehicle_data(vehicle_idx: int) -> list[dict]:
    """Generate 6 months of tire telemetry for one vehicle."""
    city_name = list(CITIES.keys())[vehicle_idx % len(CITIES)]
    city = CITIES[city_name]
    vehicle_id = f"VEH-{vehicle_idx + 1:04d}"
    
    records = []
    start_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
    
    # Per-tire state
    tire_state = {}
    for pos in TIRE_POSITIONS:
        base_pressure = random.uniform(31.0, 33.0)  # Manufacturer spec
        tread = random.uniform(7.0, 9.0)  # New tire tread depth mm
        tire_state[pos] = {
            "base_pressure": base_pressure,
            "tread": tread,
            "anomaly": "normal",
            "anomaly_start_day": None,
            "leak_rate": 0.0,  # PSI per day
        }
    
    # Inject anomalies
    for pos in TIRE_POSITIONS:
        r = random.random()
        if r < SLOW_LEAK_PROB:
            tire_state[pos]["anomaly"] = "slow_leak"
            tire_state[pos]["anomaly_start_day"] = random.randint(30, 150)
            tire_state[pos]["leak_rate"] = random.uniform(0.3, 1.2)  # PSI/day
        elif r < SLOW_LEAK_PROB + PUNCTURE_PROB:
            tire_state[pos]["anomaly"] = "puncture"
            tire_state[pos]["anomaly_start_day"] = random.randint(20, 170)
        elif r < SLOW_LEAK_PROB + PUNCTURE_PROB + VALVE_FAILURE_PROB:
            tire_state[pos]["anomaly"] = "valve_failure"
            tire_state[pos]["anomaly_start_day"] = random.randint(40, 160)
        elif r < SLOW_LEAK_PROB + PUNCTURE_PROB + VALVE_FAILURE_PROB + OVERINFLATION_PROB:
            tire_state[pos]["anomaly"] = "overinflation"
            tire_state[pos]["anomaly_start_day"] = random.randint(10, 170)
    
    for day in range(DAYS):
        current_date = start_date + timedelta(days=day)
        day_of_year = current_date.timetuple().tm_yday
        ambient_c = ambient_temp_for_day(city, day_of_year)
        
        # Simulate driving hours (6am - 6pm with gaps)
        driving_hours = sorted(random.sample(range(6, 18), k=random.randint(8, 12)))
        
        for hour in driving_hours:
            for minute_offset in [0, 30]:
                ts = current_date + timedelta(hours=hour, minutes=minute_offset)
                speed = random.uniform(15, 80) if random.random() > 0.1 else 0  # 10% stopped
                
                # Tire temp rises with speed and ambient
                tire_temp_c = ambient_c + (speed * 0.15) + random.gauss(0, 2)
                
                for pos in TIRE_POSITIONS:
                    state = tire_state[pos]
                    label = "normal"
                    
                    # Base pressure adjusted for temperature
                    pressure = pressure_from_temp(state["base_pressure"], ambient_c)
                    
                    # Natural tread wear (~0.01mm per day of driving)
                    state["tread"] = max(1.0, state["tread"] - 0.008)
                    
                    # Apply anomalies
                    if state["anomaly"] != "normal" and day >= (state["anomaly_start_day"] or 999):
                        days_since_anomaly = day - state["anomaly_start_day"]
                        
                        if state["anomaly"] == "slow_leak":
                            pressure -= state["leak_rate"] * days_since_anomaly
                            label = "slow_leak"
                            
                        elif state["anomaly"] == "puncture":
                            if days_since_anomaly == 0:
                                # Sudden drop
                                pressure -= random.uniform(8, 15)
                            elif days_since_anomaly < 3:
                                # Rapid continued loss
                                pressure -= 5 + (days_since_anomaly * 3)
                            else:
                                # Flat
                                pressure = random.uniform(5, 12)
                            label = "puncture"
                            
                        elif state["anomaly"] == "valve_failure":
                            # Intermittent — loses pressure some days, recovers others
                            if random.random() < 0.4:
                                pressure -= random.uniform(2, 6)
                                label = "valve_failure"
                                
                        elif state["anomaly"] == "overinflation":
                            pressure += random.uniform(5, 10)
                            label = "overinflation"
                    
                    # Add sensor noise
                    pressure += random.gauss(0, 0.3)
                    pressure = max(5.0, pressure)  # Can't go below 5 PSI
                    
                    # Rear tires slightly different load
                    if pos in ("RL", "RR"):
                        pressure -= random.uniform(0, 0.5)
                    
                    records.append({
                        "vehicle_id": vehicle_id,
                        "tire_id": pos,
                        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S+00:00"),
                        "pressure": round(pressure, 2),
                        "temperature": round(tire_temp_c, 2),
                        "tread_depth": round(state["tread"], 2),
                        "speed": round(speed, 1),
                        "ambient_temp": round(ambient_c, 2),
                        "latitude": round(city["lat"] + random.gauss(0, 0.02), 6),
                        "longitude": round(city["lng"] + random.gauss(0, 0.02), 6),
                        "label": label,
                    })
    
    return records


def main():
    output_dir = Path(__file__).parent.parent / "data" / "training"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating {DAYS} days of tire telemetry for {NUM_VEHICLES} vehicles...")
    print(f"Output: {output_dir}")
    
    all_records = []
    for i in range(NUM_VEHICLES):
        records = generate_vehicle_data(i)
        all_records.extend(records)
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{NUM_VEHICLES} vehicles ({len(all_records):,} records)")
    
    df = pd.DataFrame(all_records)
    
    # Add derived features the model needs
    df = df.sort_values(["vehicle_id", "tire_id", "timestamp"])
    df["delta_pressure"] = df.groupby(["vehicle_id", "tire_id"])["pressure"].diff().fillna(0)
    df["delta_temp"] = df.groupby(["vehicle_id", "tire_id"])["temperature"].diff().fillna(0)
    
    # Stats
    print(f"\nDataset: {len(df):,} records")
    print(f"Vehicles: {df['vehicle_id'].nunique()}")
    print(f"Date range: {df['timestamp'].min()} → {df['timestamp'].max()}")
    print(f"\nLabel distribution:")
    print(df["label"].value_counts().to_string())
    print(f"\nPressure stats:")
    print(f"  Normal:     {df[df['label']=='normal']['pressure'].describe()[['mean','std','min','max']].to_dict()}")
    print(f"  Slow leak:  {df[df['label']=='slow_leak']['pressure'].describe()[['mean','std','min','max']].to_dict()}")
    
    # Save as Parquet (partitioned by month for efficient training)
    df["month"] = pd.to_datetime(df["timestamp"]).dt.to_period("M").astype(str)
    
    for month, month_df in df.groupby("month"):
        path = output_dir / f"tire_telemetry_{month}.parquet"
        month_df.drop(columns=["month"]).to_parquet(path, index=False)
        print(f"  Wrote {path.name}: {len(month_df):,} records")
    
    # Also save a single file for quick loading
    full_path = output_dir / "tire_telemetry_full.parquet"
    df.drop(columns=["month"]).to_parquet(full_path, index=False)
    print(f"\n  Full dataset: {full_path} ({full_path.stat().st_size / 1024 / 1024:.1f} MB)")
    
    # Save anomaly summary
    anomaly_summary = df[df["label"] != "normal"].groupby(["vehicle_id", "tire_id", "label"]).agg(
        start=("timestamp", "min"),
        end=("timestamp", "max"),
        min_pressure=("pressure", "min"),
        records=("pressure", "count"),
    ).reset_index()
    summary_path = output_dir / "anomaly_summary.csv"
    anomaly_summary.to_csv(summary_path, index=False)
    print(f"  Anomaly summary: {summary_path} ({len(anomaly_summary)} anomalies)")


if __name__ == "__main__":
    main()
