#!/usr/bin/env python3
"""
Generate synthetic Vehicle Identity Graph — VIN decode reference data.

Produces ~500 VIN records for the fleet makes/models used by CMS:
Chevrolet Equinox, Ford Transit, RAM ProMaster, Toyota RAV4, Ford Escape.

Each record maps a VIN to its decoded identity: make, model, year, trim,
engine, transmission, body style, fuel type, curb weight, tow capacity,
maintenance group, and recall eligibility.

Output: JSON file ready to seed DynamoDB (adp-{stage}-vehicle-identity)

Usage:
    python3 scripts/generate-vehicle-identity.py
    python3 scripts/generate-vehicle-identity.py --seed-ddb --stage dev
"""

import argparse
import json
import random
import string
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "datasource" / "vehicle-identity"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── Vehicle Definitions ─────────────────────────────────────────────────────

VEHICLES = [
    {
        "make": "Chevrolet", "model": "Equinox", "years": [2020, 2021, 2022, 2023, 2024],
        "trims": ["LS", "LT", "RS", "Premier"],
        "engines": [
            {"code": "1.5T", "desc": "1.5L Turbo I4", "hp": 175, "fuel": "gasoline"},
        ],
        "transmissions": ["CVT"],
        "bodyStyle": "SUV", "drivetrains": ["FWD", "AWD"],
        "curbWeight": (3274, 3514), "towCapacity": (1500, 1500),
        "maintenanceGroup": "GM-LDT-1.5T",
        "wmi": "2GN",  # World Manufacturer Identifier
    },
    {
        "make": "Ford", "model": "Transit", "years": [2020, 2021, 2022, 2023, 2024],
        "trims": ["Base", "XL", "XLT"],
        "engines": [
            {"code": "2.0T", "desc": "2.0L EcoBoost I4", "hp": 250, "fuel": "gasoline"},
            {"code": "3.5V6", "desc": "3.5L V6", "hp": 275, "fuel": "gasoline"},
        ],
        "transmissions": ["10-Speed Auto"],
        "bodyStyle": "Van", "drivetrains": ["RWD", "AWD"],
        "curbWeight": (4650, 5900), "towCapacity": (4600, 7500),
        "maintenanceGroup": "FORD-CV-2.0T",
        "wmi": "1FT",
    },
    {
        "make": "RAM", "model": "ProMaster", "years": [2020, 2021, 2022, 2023],
        "trims": ["1500", "2500", "3500"],
        "engines": [
            {"code": "3.6V6", "desc": "3.6L Pentastar V6", "hp": 280, "fuel": "gasoline"},
        ],
        "transmissions": ["9-Speed Auto"],
        "bodyStyle": "Van", "drivetrains": ["FWD"],
        "curbWeight": (4685, 5600), "towCapacity": (5100, 6800),
        "maintenanceGroup": "FCA-CV-3.6",
        "wmi": "3C6",
    },
    {
        "make": "Toyota", "model": "RAV4", "years": [2020, 2021, 2022, 2023, 2024],
        "trims": ["LE", "XLE", "XLE Premium", "Adventure", "TRD Off-Road"],
        "engines": [
            {"code": "2.5I4", "desc": "2.5L I4", "hp": 203, "fuel": "gasoline"},
            {"code": "2.5HYB", "desc": "2.5L Hybrid", "hp": 219, "fuel": "hybrid"},
        ],
        "transmissions": ["8-Speed Auto", "eCVT"],
        "bodyStyle": "SUV", "drivetrains": ["FWD", "AWD"],
        "curbWeight": (3615, 4235), "towCapacity": (1750, 3500),
        "maintenanceGroup": "TOYOTA-LDT-2.5",
        "wmi": "2T3",
    },
    {
        "make": "Ford", "model": "Escape", "years": [2020, 2021, 2022, 2023],
        "trims": ["S", "SE", "SEL", "Titanium"],
        "engines": [
            {"code": "1.5T", "desc": "1.5L EcoBoost I3", "hp": 181, "fuel": "gasoline"},
            {"code": "2.5HYB", "desc": "2.5L Hybrid", "hp": 200, "fuel": "hybrid"},
        ],
        "transmissions": ["8-Speed Auto", "eCVT"],
        "bodyStyle": "SUV", "drivetrains": ["FWD", "AWD"],
        "curbWeight": (3298, 3800), "towCapacity": (1500, 2000),
        "maintenanceGroup": "FORD-LDT-1.5T",
        "wmi": "1FM",
    },
]

COLORS = ["White", "Black", "Silver", "Gray", "Blue", "Red", "Green", "Brown"]

# Recall eligibility by make/model/year
RECALL_MAP = {
    ("Chevrolet", "Equinox", 2021): ["24V-456"],
    ("Chevrolet", "Equinox", 2022): ["24V-456", "24V-567"],
    ("Chevrolet", "Equinox", 2023): ["24V-567"],
    ("Ford", "Transit", 2022): ["24V-234"],
    ("Ford", "Transit", 2023): ["24V-234"],
    ("RAM", "ProMaster", 2023): ["24V-678"],
    ("RAM", "ProMaster", 2024): ["24V-678"],
    ("Ford", "Escape", 2020): ["23V-891"],
    ("Ford", "Escape", 2021): ["23V-891"],
    ("Ford", "Escape", 2022): ["23V-891"],
    ("Toyota", "RAV4", 2022): ["24V-112"],
    ("Toyota", "RAV4", 2023): ["24V-112"],
    ("Toyota", "RAV4", 2024): ["24V-112"],
}


def generate_vin(wmi: str, year: int, seq: int) -> str:
    """Generate a plausible 17-char VIN."""
    year_code = chr(ord('A') + (year - 2010)) if year < 2020 else chr(ord('L') + (year - 2020))
    vds = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    plant = random.choice("ABCDEFGHJKLMNPRSTUVWXYZ")
    serial = f"{seq:06d}"
    vin = f"{wmi}{vds}{year_code}{plant}{serial}"
    # Replace check digit position (9th char) with calculated placeholder
    return vin[:8] + "X" + vin[9:]


def generate_records(count_per_model: int = 100) -> list[dict]:
    records = []
    for vdef in VEHICLES:
        for i in range(count_per_model):
            year = random.choice(vdef["years"])
            trim = random.choice(vdef["trims"])
            engine = random.choice(vdef["engines"])
            trans = random.choice(vdef["transmissions"])
            if engine["fuel"] == "hybrid" and "eCVT" in vdef["transmissions"]:
                trans = "eCVT"
            drivetrain = random.choice(vdef["drivetrains"])
            vin = generate_vin(vdef["wmi"], year, i + 1)

            recalls = RECALL_MAP.get((vdef["make"], vdef["model"], year), [])

            records.append({
                "vin": vin,
                "make": vdef["make"],
                "model": vdef["model"],
                "year": year,
                "trim": trim,
                "engine": engine["desc"],
                "engineCode": engine["code"],
                "horsepower": engine["hp"],
                "fuelType": engine["fuel"],
                "transmission": trans,
                "drivetrain": drivetrain,
                "bodyStyle": vdef["bodyStyle"],
                "exteriorColor": random.choice(COLORS),
                "curbWeight": random.randint(*vdef["curbWeight"]),
                "towCapacity": random.randint(*vdef["towCapacity"]),
                "maintenanceGroup": vdef["maintenanceGroup"],
                "recallEligibility": recalls,
            })
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100, help="Records per model")
    parser.add_argument("--seed-ddb", action="store_true", help="Seed DynamoDB directly")
    parser.add_argument("--stage", default="dev")
    args = parser.parse_args()

    records = generate_records(args.count)
    out_file = OUT_DIR / "vehicle_identity.json"
    out_file.write_text(json.dumps(records, indent=2))
    print(f"✅ Generated {len(records)} vehicle identity records → {out_file}")

    if args.seed_ddb:
        import boto3
        table_name = f"adp-{args.stage}-vehicle-identity"
        ddb = boto3.resource("dynamodb").Table(table_name)
        with ddb.batch_writer() as batch:
            for r in records:
                batch.put_item(Item=r)
        print(f"✅ Seeded {len(records)} records to {table_name}")


if __name__ == "__main__":
    main()
