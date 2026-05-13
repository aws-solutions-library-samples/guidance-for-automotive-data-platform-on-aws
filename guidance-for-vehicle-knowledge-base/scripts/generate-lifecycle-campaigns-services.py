#!/usr/bin/env python3
"""Generate vehicle lifecycle, campaign/offers, and connected services data."""

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "datasource"

MAKES_MODELS = [
    ("Chevrolet", "Equinox"), ("Ford", "Transit"), ("RAM", "ProMaster"),
    ("Toyota", "RAV4"), ("Ford", "Escape"),
]
YEARS = [2020, 2021, 2022, 2023, 2024]
STATES = ["TX", "CA", "IL", "GA", "FL", "NY", "WA", "CO", "AZ", "NC"]
INSURERS = ["State Farm", "GEICO", "Progressive", "Allstate", "Liberty Mutual", "USAA"]


def generate_lifecycle(count=500):
    out_dir = BASE_DIR / "vehicle-lifecycle"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for i in range(count):
        make, model = random.choice(MAKES_MODELS)
        year = random.choice(YEARS)
        purchase_date = datetime(year, random.randint(1, 12), random.randint(1, 28))
        warranty_end = purchase_date + timedelta(days=365 * 3)
        powertrain_end = purchase_date + timedelta(days=365 * 5)

        records.append({
            "vin": f"VLC{i:014d}",
            "make": make, "model": model, "year": year,
            "purchaseDate": purchase_date.strftime("%Y-%m-%d"),
            "purchaseType": random.choice(["new", "certified-preowned", "fleet-order"]),
            "msrp": random.randint(28000, 55000),
            "purchasePrice": random.randint(25000, 50000),
            "warrantyStart": purchase_date.strftime("%Y-%m-%d"),
            "warrantyEnd": warranty_end.strftime("%Y-%m-%d"),
            "powertrainWarrantyEnd": powertrain_end.strftime("%Y-%m-%d"),
            "registrationState": random.choice(STATES),
            "registrationExpiry": (datetime.now() + timedelta(days=random.randint(30, 365))).strftime("%Y-%m-%d"),
            "insuranceProvider": random.choice(INSURERS),
            "insurancePolicyNumber": f"POL-{random.randint(100000, 999999)}",
            "leaseTermMonths": random.choice([None, 24, 36, 48]),
            "currentValue": random.randint(12000, 42000),
            "depreciationRate": round(random.uniform(0.12, 0.22), 2),
        })

    (out_dir / "vehicle_lifecycle.json").write_text(json.dumps(records, indent=2))
    print(f"✅ Generated {len(records)} lifecycle records")
    return records


def generate_campaigns(count=50):
    out_dir = BASE_DIR / "campaigns-offers"
    out_dir.mkdir(parents=True, exist_ok=True)
    campaign_types = [
        ("service-discount", "15% off brake service", 15),
        ("loyalty-reward", "$50 service credit at 50k miles", 50),
        ("recall-incentive", "Free loaner during recall repair", 0),
        ("seasonal", "Winter tire package — $100 off", 100),
        ("referral", "$75 credit for fleet referral", 75),
        ("trade-in", "Enhanced trade-in value +$1,500", 1500),
        ("subscription-upgrade", "1 month free Premium connected services", 0),
        ("maintenance-bundle", "Prepaid 3-service package — save 20%", 20),
    ]
    records = []
    for i in range(count):
        ctype, desc, value = random.choice(campaign_types)
        eligible_makes = random.sample([m for m, _ in MAKES_MODELS], random.randint(1, 4))
        start = datetime.now() - timedelta(days=random.randint(0, 60))
        end = start + timedelta(days=random.randint(30, 180))

        records.append({
            "campaignId": f"CMP-{i+1:04d}",
            "type": ctype,
            "title": desc,
            "discountValue": value,
            "discountUnit": "percent" if value <= 25 else "dollars",
            "eligibleMakes": eligible_makes,
            "eligibleYears": random.sample(YEARS, random.randint(2, 5)),
            "startDate": start.strftime("%Y-%m-%d"),
            "endDate": end.strftime("%Y-%m-%d"),
            "active": end > datetime.now(),
            "redemptionChannel": random.choice(["app", "dealer", "online", "any"]),
            "maxRedemptions": random.choice([None, 100, 500, 1000]),
        })

    (out_dir / "campaigns_offers.json").write_text(json.dumps(records, indent=2))
    print(f"✅ Generated {len(records)} campaign/offer records")
    return records


def generate_connected_services(count=500):
    out_dir = BASE_DIR / "connected-services"
    out_dir.mkdir(parents=True, exist_ok=True)
    plans = [
        ("basic", ["remote-lock", "vehicle-status", "maintenance-alerts"], 15),
        ("standard", ["remote-lock", "vehicle-status", "maintenance-alerts", "remote-start", "trip-history"], 25),
        ("premium", ["remote-lock", "vehicle-status", "maintenance-alerts", "remote-start", "trip-history", "wifi-hotspot", "ota-updates", "roadside-assist", "stolen-vehicle-tracking"], 40),
    ]
    records = []
    for i in range(count):
        plan_name, features, price = random.choice(plans)
        activation = datetime.now() - timedelta(days=random.randint(30, 900))
        renewal = activation + timedelta(days=365)

        records.append({
            "vin": f"VCS{i:014d}",
            "planTier": plan_name,
            "monthlyPrice": price,
            "features": features,
            "activationDate": activation.strftime("%Y-%m-%d"),
            "renewalDate": renewal.strftime("%Y-%m-%d"),
            "autoRenew": random.random() > 0.2,
            "status": "active" if renewal > datetime.now() else "expired",
            "trialEndsDate": None if random.random() > 0.3 else (activation + timedelta(days=90)).strftime("%Y-%m-%d"),
            "otaUpdatesAvailable": random.randint(0, 3),
            "lastOtaUpdate": (datetime.now() - timedelta(days=random.randint(1, 90))).strftime("%Y-%m-%d"),
        })

    (out_dir / "connected_services.json").write_text(json.dumps(records, indent=2))
    print(f"✅ Generated {len(records)} connected services records")
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-ddb", action="store_true")
    parser.add_argument("--stage", default="dev")
    args = parser.parse_args()

    generate_lifecycle()
    generate_campaigns()
    generate_connected_services()

    if args.seed_ddb:
        print("DynamoDB seeding not yet implemented for these tables — use upload-data + Makefile")


if __name__ == "__main__":
    main()
