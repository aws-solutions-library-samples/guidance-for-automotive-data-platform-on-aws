# Reference Data

Canonical automotive reference data managed by the Automotive Data Platform.
These are industry-standard definitions that don't change per-fleet or per-deployment.

## Contents

### signal-catalog/
- `signal_catalog_seed.json` — 262 VSS-aligned CAN signals (engine, ADAS, body, cabin, chassis, EV, GPS, fleet)
- `seed_signal_catalog.py` — Script to seed a CMS DynamoDB signal catalog table

### event-catalog/
- `seed_event_catalog.py` — Safety + maintenance event definitions with trigger thresholds

### nhtsa-poller/
- `nhtsa_recall_poller.py` — Fetches real NHTSA recall data and matches against fleet vehicles

## Usage

These scripts can seed data into any CMS deployment:

```bash
# From the ADP repo:
cd reference-data/signal-catalog
AWS_REGION=us-east-1 DEPLOYMENT_STAGE=dev python3 seed_signal_catalog.py

cd ../event-catalog
AWS_REGION=us-east-1 DEPLOYMENT_STAGE=dev python3 seed_event_catalog.py

cd ../nhtsa-poller
AWS_REGION=us-east-1 DEPLOYMENT_STAGE=dev python3 nhtsa_recall_poller.py
```

CMS retains copies of these scripts for backward compatibility, but ADP
is the canonical source. Updates should be made here first.
