#!/usr/bin/env python3
"""
Generate synthetic weather data for tire prediction.
Creates realistic weather patterns that affect tire wear.
"""
import json
import random
from datetime import datetime, timedelta
import boto3

# US regions with typical weather patterns
REGIONS = {
    'northeast': {'temp_range': (20, 85), 'precip_prob': 0.3, 'snow_months': [12, 1, 2, 3]},
    'southeast': {'temp_range': (45, 95), 'precip_prob': 0.4, 'snow_months': []},
    'midwest': {'temp_range': (10, 90), 'precip_prob': 0.3, 'snow_months': [11, 12, 1, 2, 3]},
    'southwest': {'temp_range': (40, 105), 'precip_prob': 0.1, 'snow_months': []},
    'west': {'temp_range': (35, 85), 'precip_prob': 0.2, 'snow_months': [12, 1, 2]},
}

ROAD_CONDITIONS = ['DRY', 'WET', 'ICY', 'SNOWY']

def generate_weather_data(days=90, locations=5):
    """Generate synthetic weather data."""
    data = []
    start_date = datetime.now() - timedelta(days=days)
    
    for location_id in range(1, locations + 1):
        region = random.choice(list(REGIONS.keys()))
        region_data = REGIONS[region]
        
        for day in range(days):
            current_date = start_date + timedelta(days=day)
            month = current_date.month
            
            # Temperature varies by season
            base_temp = region_data['temp_range'][0] + \
                       (region_data['temp_range'][1] - region_data['temp_range'][0]) * \
                       (0.5 + 0.5 * abs(6 - month) / 6)
            
            # Daily temperature variation
            temp_f = base_temp + random.uniform(-10, 10)
            
            # Precipitation
            has_precip = random.random() < region_data['precip_prob']
            precip_inches = random.uniform(0.1, 2.0) if has_precip else 0
            
            # Road condition based on weather
            if month in region_data['snow_months'] and temp_f < 32 and has_precip:
                road_condition = random.choice(['ICY', 'SNOWY'])
            elif has_precip:
                road_condition = 'WET'
            else:
                road_condition = 'DRY'
            
            # Wind affects tire wear
            wind_mph = random.uniform(0, 30)
            
            # Humidity
            humidity_pct = random.uniform(30, 90) if has_precip else random.uniform(20, 60)
            
            record = {
                'location_id': f'LOC-{location_id:03d}',
                'region': region,
                'date': current_date.strftime('%Y-%m-%d'),
                'timestamp': int(current_date.timestamp() * 1000),
                'temperature_f': round(temp_f, 1),
                'precipitation_inches': round(precip_inches, 2),
                'humidity_pct': round(humidity_pct, 1),
                'wind_mph': round(wind_mph, 1),
                'road_condition': road_condition,
                'uv_index': random.randint(0, 11) if 6 <= current_date.hour <= 18 else 0
            }
            
            data.append(record)
    
    return data

def upload_to_s3(data, bucket_name, prefix="weather-data"):
    """Upload weather data to S3 in partitioned structure."""
    s3 = boto3.client('s3')
    
    # Group by date for partitioning
    for record in data:
        date = datetime.strptime(record['date'], '%Y-%m-%d')
        partition = f"{prefix}/year={date.year}/month={date.month:02d}/day={date.day:02d}"
        key = f"{partition}/{record['location_id']}-{record['date']}.json"
        
        s3.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=json.dumps(record),
            ContentType='application/json'
        )
    
    print(f"✓ Uploaded {len(data)} weather records to s3://{bucket_name}/{prefix}/")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: generate-weather-data.py <bucket-name> [days] [locations]")
        sys.exit(1)
    
    bucket = sys.argv[1]
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    locations = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    
    print(f"Generating {days} days of weather data for {locations} locations...")
    data = generate_weather_data(days, locations)
    
    print(f"Uploading to S3...")
    upload_to_s3(data, bucket)
    
    print(f"✓ Complete! Generated {len(data)} weather records")
