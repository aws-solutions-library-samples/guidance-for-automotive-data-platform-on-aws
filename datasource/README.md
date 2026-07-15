> ## DEPRECATED in v0.2 — see `platform-foundation/source/data-products/`
>
> This directory is no longer the canonical location for synthetic data
> generation. Its patterns have been superseded by the platform-foundation
> data-product generators under `platform-foundation/`. See:
>
> - [`README.md`](../README.md) — top-level repository overview
> - [`docs/MIGRATION-FROM-V0.1.0.md`](../docs/MIGRATION-FROM-V0.1.0.md) — migration guide
> - [`platform-foundation/source/data-products/`](../platform-foundation/source/data-products/) — current data-product generators (replaces this directory's synthetic-data generation patterns)
>
> v0.2 drops the standalone `generate_data.py` / per-source generator
> scripts in favor of a unified deterministic-seed generator pipeline
> (`make seed STAGE=...`) that emits Iceberg-ready parquet directly. See
> the migration guide for the full dropped-features list.
>
> The original v0.1.0 README content for this directory follows below
> for historical reference.

---

# Original v0.1.0 README content begins here

# Automotive Synthetic Data Sources

This module generates realistic synthetic data for automotive customer lifecycle, vehicle operations, and business intelligence use cases.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Generate small dataset
python generate_data.py --profile small --output s3://your-bucket/raw/

# Generate with specific sources
python generate_data.py --sources customer_demographics,sales_history --count 1000
```

## Directory Structure

```
datasource/
├── README.md                    # This file
├── IMPLEMENTATION_PLAN.md       # Phased implementation plan
├── requirements.txt             # Python dependencies
├── generate_data.py            # Main data generation script
├── config/
│   ├── generation_config.yaml  # Generation parameters
│   └── data_profiles.yaml      # Small/medium/large profiles
├── generators/
│   ├── __init__.py
│   ├── base_generator.py       # Base class for generators
│   ├── customer_demographics.py
│   ├── sales_history.py
│   ├── support_tickets.py
│   ├── contact_center.py
│   ├── survey_data.py
│   ├── marketing_interactions.py
│   ├── finance_lease.py
│   └── insurance_claims.py
├── schemas/
│   ├── customer_schema.json
│   ├── sales_schema.json
│   ├── support_schema.json
│   └── ...
├── utils/
│   ├── __init__.py
│   ├── s3_writer.py
│   ├── dynamodb_writer.py
│   └── data_faker.py
└── tests/
    └── test_generators.py
```

## Data Sources

### Phase 1 (Available)
- ✅ Customer Demographics
- ✅ Sales History
- ✅ Vehicle Inventory

### Phase 2 (In Progress)
- 🔄 Support Tickets
- 🔄 Contact Center Data
- 🔄 Survey Data
- 🔄 Marketing Interactions

### Phase 3 (Planned)
- ⏳ Finance/Lease Data
- ⏳ Insurance Claims
- ⏳ Parts Inventory

## Configuration

Edit `config/generation_config.yaml` to customize:
- Data volumes
- Date ranges
- Distribution patterns
- Output formats
- AWS resources

## Integration

### With Existing Tables
The generators respect existing schemas from:
- `/connected-mobility-guidance-on-aws/deployment/stacks/storage_stack.py`
- FleetWise signal catalog
- Event catalog schemas

### Output Formats
- **S3**: Parquet (partitioned by date)
- **DynamoDB**: Direct writes for operational data
- **Kinesis**: Streaming for real-time use cases

## Examples

See `examples/` directory for:
- Sample queries
- Data exploration notebooks
- Integration patterns
