#!/usr/bin/env python3
"""Generate synthetic dealer/service center network data."""

import argparse
import json
import random
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "datasource" / "service-network"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CENTERS = [
    # (name, city, state, lat, lon, type, brands_serviced)
    ("Rush Truck Center — Dallas", "Dallas", "TX", 32.802, -96.862, "fleet-service", ["Chevrolet", "Ford", "RAM"]),
    ("Penske Truck Leasing — Chicago", "Chicago", "IL", 41.843, -87.654, "fleet-service", ["Ford", "RAM", "Chevrolet"]),
    ("Ryder Maintenance — Atlanta", "Atlanta", "GA", 33.812, -84.432, "fleet-service", ["Ford", "RAM", "Toyota"]),
    ("Freightliner of Austin", "Austin", "TX", 30.372, -97.687, "fleet-service", ["Chevrolet", "Ford", "RAM"]),
    ("TravelCenters of America — Phoenix", "Phoenix", "AZ", 33.432, -112.098, "fleet-service", ["Ford", "RAM", "Chevrolet"]),
    ("Hendrick Chevrolet — Charlotte", "Charlotte", "NC", 35.194, -80.832, "dealer", ["Chevrolet"]),
    ("AutoNation Ford — Denver", "Denver", "CO", 39.714, -104.942, "dealer", ["Ford"]),
    ("Larry H. Miller Toyota — Salt Lake City", "Salt Lake City", "UT", 40.712, -111.872, "dealer", ["Toyota"]),
    ("Galpin Ford — Los Angeles", "Los Angeles", "CA", 34.232, -118.472, "dealer", ["Ford"]),
    ("Jim Ellis Chevrolet — Atlanta", "Atlanta", "GA", 33.892, -84.312, "dealer", ["Chevrolet"]),
    ("Longo Toyota — Los Angeles", "Los Angeles", "CA", 34.082, -117.932, "dealer", ["Toyota"]),
    ("Park Place Dealerships — Dallas", "Dallas", "TX", 32.912, -96.782, "dealer", ["Chevrolet", "Toyota"]),
    ("Sewell Automotive — Dallas", "Dallas", "TX", 32.852, -96.772, "dealer", ["Chevrolet", "Ford"]),
    ("Firestone Complete Auto Care — Miami", "Miami", "FL", 25.782, -80.212, "independent", ["Chevrolet", "Ford", "RAM", "Toyota"]),
    ("Midas — Houston", "Houston", "TX", 29.762, -95.372, "independent", ["Chevrolet", "Ford", "RAM", "Toyota"]),
    ("Jiffy Lube — Seattle", "Seattle", "WA", 47.612, -122.332, "quick-service", ["Chevrolet", "Ford", "RAM", "Toyota"]),
    ("Valvoline Instant Oil Change — Boston", "Boston", "MA", 42.362, -71.062, "quick-service", ["Chevrolet", "Ford", "RAM", "Toyota"]),
    ("Pep Boys — Philadelphia", "Philadelphia", "PA", 39.952, -75.162, "independent", ["Chevrolet", "Ford", "RAM", "Toyota"]),
    ("Caliber Collision — Denver", "Denver", "CO", 39.742, -104.982, "body-shop", ["Chevrolet", "Ford", "RAM", "Toyota"]),
    ("Service King — Phoenix", "Phoenix", "AZ", 33.482, -112.072, "body-shop", ["Chevrolet", "Ford", "RAM", "Toyota"]),
]

CAPABILITIES = {
    "fleet-service": ["oil-change", "brakes", "tires", "transmission", "engine", "electrical", "hvac", "suspension", "diagnostics", "fleet-maintenance-program"],
    "dealer": ["oil-change", "brakes", "tires", "transmission", "engine", "electrical", "hvac", "suspension", "diagnostics", "warranty-repair", "recall-service", "body-work"],
    "independent": ["oil-change", "brakes", "tires", "electrical", "hvac", "suspension", "diagnostics"],
    "quick-service": ["oil-change", "tires", "filters", "wipers", "battery"],
    "body-shop": ["body-work", "paint", "glass", "dent-repair", "frame-straightening"],
}

HOURS = {
    "fleet-service": {"weekday": "6:00 AM - 10:00 PM", "saturday": "7:00 AM - 5:00 PM", "sunday": "Closed"},
    "dealer": {"weekday": "7:00 AM - 7:00 PM", "saturday": "8:00 AM - 5:00 PM", "sunday": "Closed"},
    "independent": {"weekday": "7:30 AM - 6:00 PM", "saturday": "8:00 AM - 4:00 PM", "sunday": "Closed"},
    "quick-service": {"weekday": "7:00 AM - 7:00 PM", "saturday": "8:00 AM - 6:00 PM", "sunday": "9:00 AM - 5:00 PM"},
    "body-shop": {"weekday": "8:00 AM - 5:30 PM", "saturday": "By appointment", "sunday": "Closed"},
}


def generate_records() -> list[dict]:
    records = []
    for i, (name, city, state, lat, lon, center_type, brands) in enumerate(CENTERS):
        records.append({
            "centerId": f"SC-{i+1:04d}",
            "name": name,
            "type": center_type,
            "address": f"{random.randint(100,9999)} {random.choice(['Main St', 'Industrial Blvd', 'Commerce Dr', 'Auto Park Way', 'Service Rd'])}",
            "city": city,
            "state": state,
            "zipCode": f"{random.randint(10000,99999)}",
            "latitude": lat + random.uniform(-0.01, 0.01),
            "longitude": lon + random.uniform(-0.01, 0.01),
            "phone": f"({random.randint(200,999)}) {random.randint(200,999)}-{random.randint(1000,9999)}",
            "brandsServiced": brands,
            "capabilities": CAPABILITIES[center_type],
            "hours": HOURS[center_type],
            "rating": round(random.uniform(3.8, 4.9), 1),
            "reviewCount": random.randint(50, 800),
            "averageWaitDays": random.randint(0, 5) if center_type != "quick-service" else 0,
            "fleetDiscount": center_type in ("fleet-service", "dealer"),
            "mobileServiceAvailable": center_type == "fleet-service",
            "loanerVehicles": center_type == "dealer",
            "certifications": _certifications(center_type),
        })
    return records


def _certifications(center_type: str) -> list[str]:
    base = ["ASE Certified"]
    if center_type == "dealer":
        base += ["OEM Factory Trained", "Warranty Authorized"]
    if center_type == "fleet-service":
        base += ["Fleet Maintenance Certified", "DOT Inspection Authorized"]
    if center_type == "body-shop":
        base += ["I-CAR Gold", "OEM Certified Collision"]
    return base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-ddb", action="store_true")
    parser.add_argument("--stage", default="dev")
    args = parser.parse_args()

    records = generate_records()
    out_file = OUT_DIR / "service_network.json"
    out_file.write_text(json.dumps(records, indent=2))
    print(f"✅ Generated {len(records)} service center records → {out_file}")

    if args.seed_ddb:
        import boto3
        from decimal import Decimal
        table_name = f"adp-{args.stage}-service-network"
        ddb = boto3.resource("dynamodb").Table(table_name)
        with ddb.batch_writer() as batch:
            for r in records:
                # Convert floats to Decimal for DynamoDB
                r["latitude"] = Decimal(str(r["latitude"]))
                r["longitude"] = Decimal(str(r["longitude"]))
                r["rating"] = Decimal(str(r["rating"]))
                batch.put_item(Item=r)
        print(f"✅ Seeded {len(records)} records to {table_name}")


if __name__ == "__main__":
    main()
