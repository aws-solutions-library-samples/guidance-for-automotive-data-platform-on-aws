#!/usr/bin/env python3
"""Generate synthetic parts catalog with pricing and vehicle compatibility."""

import argparse
import json
import random
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "datasource" / "parts-catalog"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Parts organized by repair category
PARTS_DB = [
    # (category, partNumber, description, priceRange, compatibleMakes, supplier)
    # Brakes
    ("brakes", "BRK-FP-001", "Front Brake Pad Set (Ceramic)", (45, 189), ["Chevrolet", "Ford", "Toyota"], "ACDelco"),
    ("brakes", "BRK-FP-002", "Front Brake Pad Set (Semi-Metallic)", (35, 95), ["Chevrolet", "Ford", "RAM", "Toyota"], "Wagner"),
    ("brakes", "BRK-RP-001", "Rear Brake Pad Set (Ceramic)", (40, 165), ["Chevrolet", "Ford", "Toyota"], "ACDelco"),
    ("brakes", "BRK-RT-001", "Front Brake Rotor", (55, 145), ["Chevrolet", "Ford", "Toyota"], "ACDelco"),
    ("brakes", "BRK-RT-002", "Rear Brake Rotor", (48, 125), ["Chevrolet", "Ford", "Toyota"], "Brembo"),
    ("brakes", "BRK-FL-001", "Brake Fluid DOT 4 (1L)", (8, 18), ["Chevrolet", "Ford", "RAM", "Toyota"], "Valvoline"),
    ("brakes", "BRK-CL-001", "Brake Caliper (Reman)", (85, 250), ["Chevrolet", "Ford", "RAM", "Toyota"], "Cardone"),
    ("brakes", "BRK-HW-001", "Brake Hardware Kit", (15, 35), ["Chevrolet", "Ford", "RAM", "Toyota"], "Dorman"),
    # Engine
    ("engine", "ENG-OIL-001", "Full Synthetic 5W-30 (5qt)", (28, 45), ["Chevrolet", "Ford", "RAM"], "Mobil 1"),
    ("engine", "ENG-OIL-002", "Full Synthetic 0W-20 (5qt)", (30, 48), ["Toyota", "Ford"], "Mobil 1"),
    ("engine", "ENG-FLT-001", "Oil Filter", (8, 22), ["Chevrolet", "Ford", "RAM", "Toyota"], "Fram"),
    ("engine", "ENG-FLT-002", "Oil Filter (Extended Life)", (12, 28), ["Chevrolet", "Ford", "RAM", "Toyota"], "Mobil 1"),
    ("engine", "ENG-AIR-001", "Engine Air Filter", (15, 45), ["Chevrolet", "Ford", "RAM", "Toyota"], "K&N"),
    ("engine", "ENG-SPK-001", "Spark Plug (Iridium)", (8, 18), ["Chevrolet", "Ford", "RAM", "Toyota"], "NGK"),
    ("engine", "ENG-SPK-002", "Spark Plug (Double Platinum)", (12, 24), ["Chevrolet", "Ford", "RAM"], "Bosch"),
    ("engine", "ENG-CLT-001", "Coolant 50/50 (1 gal)", (12, 25), ["Chevrolet", "Ford", "RAM", "Toyota"], "Prestone"),
    ("engine", "ENG-BLT-001", "Serpentine Belt", (25, 65), ["Chevrolet", "Ford", "RAM", "Toyota"], "Gates"),
    ("engine", "ENG-WP-001", "Water Pump", (85, 280), ["Chevrolet", "Ford", "RAM", "Toyota"], "GMB"),
    ("engine", "ENG-ALT-001", "Alternator (Reman)", (180, 450), ["Chevrolet", "Ford", "RAM", "Toyota"], "Denso"),
    ("engine", "ENG-STR-001", "Starter Motor (Reman)", (150, 380), ["Chevrolet", "Ford", "RAM", "Toyota"], "Denso"),
    ("engine", "ENG-THS-001", "Thermostat", (18, 55), ["Chevrolet", "Ford", "RAM", "Toyota"], "Stant"),
    ("engine", "ENG-FP-001", "Fuel Pump Assembly", (250, 650), ["Chevrolet", "Ford", "RAM", "Toyota"], "Delphi"),
    # Electrical
    ("electrical", "ELC-BAT-001", "Battery (Group 48, 700 CCA)", (120, 220), ["Chevrolet", "Ford", "RAM", "Toyota"], "Interstate"),
    ("electrical", "ELC-BAT-002", "Battery (Group 35, 640 CCA)", (110, 195), ["Toyota", "Ford"], "Optima"),
    ("electrical", "ELC-O2-001", "O2 Sensor (Upstream)", (45, 180), ["Chevrolet", "Ford", "RAM", "Toyota"], "Denso"),
    ("electrical", "ELC-O2-002", "O2 Sensor (Downstream)", (40, 150), ["Chevrolet", "Ford", "RAM", "Toyota"], "Bosch"),
    ("electrical", "ELC-MAF-001", "Mass Air Flow Sensor", (85, 280), ["Chevrolet", "Ford", "RAM", "Toyota"], "Denso"),
    ("electrical", "ELC-ABS-001", "ABS Wheel Speed Sensor", (35, 120), ["Chevrolet", "Ford", "RAM", "Toyota"], "Dorman"),
    # Suspension
    ("suspension", "SUS-STR-001", "Front Strut Assembly (Complete)", (150, 380), ["Chevrolet", "Ford", "Toyota"], "Monroe"),
    ("suspension", "SUS-SHK-001", "Rear Shock Absorber", (55, 150), ["Chevrolet", "Ford", "RAM", "Toyota"], "Bilstein"),
    ("suspension", "SUS-BRG-001", "Wheel Bearing & Hub Assembly (Front)", (85, 250), ["Chevrolet", "Ford", "RAM", "Toyota"], "Timken"),
    ("suspension", "SUS-TRD-001", "Tie Rod End (Outer)", (25, 75), ["Chevrolet", "Ford", "RAM", "Toyota"], "Moog"),
    ("suspension", "SUS-BJ-001", "Ball Joint (Lower)", (35, 120), ["Chevrolet", "Ford", "RAM", "Toyota"], "Moog"),
    # Transmission
    ("transmission", "TRN-FLD-001", "ATF Dexron VI (1qt)", (8, 15), ["Chevrolet", "RAM"], "Valvoline"),
    ("transmission", "TRN-FLD-002", "ATF Mercon LV (1qt)", (9, 16), ["Ford"], "Motorcraft"),
    ("transmission", "TRN-FLT-001", "Transmission Filter Kit", (25, 85), ["Chevrolet", "Ford", "RAM"], "Wix"),
    # Tires
    ("tires", "TIR-AS-001", "All-Season 225/65R17", (120, 195), ["Chevrolet", "Toyota", "Ford"], "Michelin"),
    ("tires", "TIR-AS-002", "All-Season 235/65R16C (LT)", (145, 240), ["Ford", "RAM"], "Michelin"),
    ("tires", "TIR-AT-001", "All-Terrain 225/65R17", (155, 230), ["Chevrolet", "Toyota"], "BFGoodrich"),
    # HVAC
    ("hvac", "HVC-CAB-001", "Cabin Air Filter", (12, 30), ["Chevrolet", "Ford", "RAM", "Toyota"], "Fram"),
    ("hvac", "HVC-CMP-001", "A/C Compressor (Reman)", (280, 650), ["Chevrolet", "Ford", "RAM", "Toyota"], "Denso"),
    # Exhaust/Emissions
    ("emissions", "EMI-CAT-001", "Catalytic Converter (Direct Fit)", (450, 1800), ["Chevrolet", "Ford", "RAM", "Toyota"], "MagnaFlow"),
    ("emissions", "EMI-EGR-001", "EGR Valve", (85, 280), ["Chevrolet", "Ford", "RAM"], "Dorman"),
]

MODELS_BY_MAKE = {
    "Chevrolet": ["Equinox"],
    "Ford": ["Transit", "Escape"],
    "RAM": ["ProMaster"],
    "Toyota": ["RAV4"],
}


def generate_records() -> list[dict]:
    records = []
    for cat, part_num, desc, (price_low, price_high), makes, supplier in PARTS_DB:
        # Generate per-vehicle compatibility
        compatible = []
        for make in makes:
            for model in MODELS_BY_MAKE.get(make, []):
                compatible.append({"make": make, "model": model})

        tier1_price = round(random.uniform(price_high * 0.85, price_high), 2)
        tier2_price = round(tier1_price * random.uniform(0.7, 0.8), 2)
        tier3_price = round(tier1_price * random.uniform(0.5, 0.65), 2)

        records.append({
            "partNumber": part_num,
            "category": cat,
            "description": desc,
            "pricing": {
                "tier1_oem": tier1_price,
                "tier2_equivalent": tier2_price,
                "tier3_fleet": tier3_price,
                "currency": "USD",
            },
            "supplier": supplier,
            "compatibleVehicles": compatible,
            "inStock": random.random() > 0.15,
            "leadTimeDays": 0 if random.random() > 0.15 else random.randint(1, 5),
            "warrantyMonths": 24 if "Reman" not in desc else 12,
        })
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-ddb", action="store_true")
    parser.add_argument("--stage", default="dev")
    args = parser.parse_args()

    records = generate_records()
    out_file = OUT_DIR / "parts_catalog.json"
    out_file.write_text(json.dumps(records, indent=2))
    print(f"✅ Generated {len(records)} parts records → {out_file}")

    if args.seed_ddb:
        import boto3
        from decimal import Decimal
        table_name = f"adp-{args.stage}-parts-catalog"
        ddb = boto3.resource("dynamodb").Table(table_name)
        with ddb.batch_writer() as batch:
            for r in records:
                r["pricing"] = json.loads(json.dumps(r["pricing"]), parse_float=Decimal)
                batch.put_item(Item=r)
        print(f"✅ Seeded {len(records)} records to {table_name}")


if __name__ == "__main__":
    main()
