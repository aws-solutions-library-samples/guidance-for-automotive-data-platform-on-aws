# Tech Research: PM Modernize + Reposition as Platform-Foundation Consumer

**Spec**: `.kiro/specs/2026-07-15-adp-pm-modernize-reposition/spec.md` — Phase 3 grounding survey.
**Generated**: 2026-07-15 (research-only; no implementation).
**Author note**: Every factual claim below cites the exact source file + line where it was verified.

---

## Area 1 — PM Today: What `TirePredictiveMaintenanceStack` Builds

### 1.1 Stack entry point

`guidance-for-predictive-maintenance/source/infrastructure/lib/stacks/tire_predictive_maintenance_stack.py`

The stack instantiates five top-level constructs (lines 62–108):

| Construct class | Logical ID | What it provisions |
|---|---|---|
| `EncryptedS3Construct` | `encrypted-asset-bucket` | KMS-encrypted S3 bucket for Glue scripts + Lambda assets |
| `AlertsSystemConstruct` | `alerts-system-construct` | SNS topic + Lambda (`alerts-transformer`) + SSM param for anomaly threshold |
| `ETLConstruct` | `root-etl-stack` | 3 S3 data buckets (raw / training / inference) + Glue ETL job + normalization stats SSM param |
| `PredictionModelConstruct` | `prediction-model-construct` | Encrypted S3 bucket for ML predictions (`prediction_bucket`) |
| `MLPipelineConstruct` | `ml-based-slow-leak-detection-construct` | ML ETL Lambda, training Step Function, inference Step Function |
| `CMSIntegrationConstruct` | `cms-integration` | Daily tire-check Lambda, blowout-risk Lambda, SageMaker resources wired to CMS |

Source: `tire_predictive_maintenance_stack.py` lines 1–108 (full file).

### 1.2 Cron schedule

All schedules are defined at lines 33–38 of `tire_predictive_maintenance_stack.py`:

| Variable | Value | Meaning |
|---|---|---|
| `query_cron_string` | `cron(0 * * * ? *)` | Hourly query Lambda (data fetch from raw bucket) |
| `etl_cron_string` | `cron(30 * ? * * *)` | Hourly ETL Glue job run |
| `ml_etl_cron_string` | `cron(0 2 ? * * *)` | Daily 02:00 UTC ML ETL (prepares inference data) |
| `ml_training_cron_string` | `cron(0 3 ? * FRI *)` | Weekly Friday 03:00 UTC SageMaker retraining |
| `ml_inference_cron_string` | `cron(30 2 * * ? *)` | Daily 02:30 UTC batch inference Step Function |

### 1.3 ETL data buckets (data flow)

Source: `source/infrastructure/lib/constructs/etl_constructs/etl_data_buckets.py` (full file).

Three CDK-provisioned encrypted S3 buckets with no explicit names (CDK-generated):

- `raw_data_bucket` — input: raw tire telemetry arrives here
- `training_data_bucket` — output of Glue ETL job; feeds SageMaker training
- `inference_data_bucket` — output of ML ETL Lambda; feeds SageMaker batch transform

### 1.4 Glue ETL job

Source: `source/infrastructure/lib/constructs/etl_constructs/etl_glue_jobs.py` lines 85–106.

```
--source-s3-bucket-uri   s3://<raw_data_bucket>
--training-s3-bucket-uri s3://<training_data_bucket>
--inference-s3-bucket-uri s3://<inference_data_bucket>
--normalization-stats-parameter  <SSM param name>
```

- Glue version 5.0, `G.8X` × 10 workers, 60-minute timeout.
- Script loaded from `source/assets/etl_scripts/etl_glue_job.py` (deployed to `asset_bucket/etl-scripts/`).
- EventBridge schedule is commented-out (lines 136–178 of `etl_glue_jobs.py`); the job is triggered manually or via Step Function.

### 1.5 ML training — SageMaker Random Cut Forest

Source: `source/infrastructure/lib/constructs/ml_constructs/ml_training_stepfunction.py` lines 29–34.

```python
TRAINING_IMAGE_ACCOUNT = "382416733822"
TRAINING_IMAGE_REGION  = "us-east-1"
TRAINING_IMAGE_URL     = f"{TRAINING_IMAGE_ACCOUNT}.dkr.ecr.{TRAINING_IMAGE_REGION}.amazonaws.com/randomcutforest:1"
```

- Algorithm: **Amazon SageMaker Random Cut Forest (RCF)** — unsupervised anomaly detection.
- `ModelParameters`: `feature_dimension=10`, `num_samples_per_tree=256`, `num_trees=100` (lines 37–40).
- `ModelTrainingConfig`: `instance_type=m5.12xlarge`, `instance_volume_size_in_gib=400`, `max_training_time_in_seconds=3600` (lines 29–35).
- Step Function: Train → Create Model → Create Endpoint (from `ml_training_stepfunction.py`).

### 1.6 ML inference — Step Function

Source: `source/infrastructure/lib/constructs/ml_constructs/ml_inference_stepfunction.py`.

Two Lambdas:
- `start-batch-transform-lambda` — reads model name from SSM, launches SageMaker Batch Transform job reading from `inference_data_bucket`
- `inference-job-status-lambda` — polls job status

Results land in `prediction_bucket` (provisioned by `PredictionModelConstruct`).

### 1.7 CRITICAL — Where PM gets its input data TODAY

**PM does NOT read from the platform-foundation lake. It is self-contained.**

Evidence chain:

1. `ETLConstruct` reads from `etl_data_buckets.raw_data_bucket` — a CDK-provisioned bucket with no S3 path pointing to the foundation lake (`etl_glue_jobs.py` line 85: `--source-s3-bucket-uri s3://<raw_data_bucket_name>`).
2. The raw data bucket is populated **externally** — no Lambda or Step Function in the stack writes to it. The only documented data path is the **synthetic data generator**: `guidance-for-predictive-maintenance/scripts/generate_training_data.py`.
3. A second (earlier) ad-hoc script exists at `platform-foundation/scripts/generate-tire-telemetry.py` — it uploads JSON records directly to a named S3 bucket via boto3, formatted as nested dicts (different schema from the PM generator).

**No S3 path in any PM construct references `adp-{stage}-foundation-lake-*` or any DataZone subscription.** PM currently trains and infers on self-generated synthetic data.

### 1.8 Tire-relevant data fields consumed/produced by PM (synthetic schema)

Source: `scripts/generate_training_data.py` lines 1–52 (module docstring + `records.append()` block at lines 153–175).

**Input fields (per tire reading — long format, one row per tire per timestamp):**

| Field | Type | Description |
|---|---|---|
| `vehicle_id` | str | Vehicle identifier (`VEH-NNNN`) |
| `tire_id` | str | Position: `FL`, `FR`, `RL`, `RR` |
| `timestamp` | str | ISO 8601 UTC |
| `pressure` | float | PSI (range ~5–42 PSI; base 31–33 + temp adjustment) |
| `temperature` | float | Celsius (ambient + speed × 0.15 + noise) |
| `tread_depth` | float | mm (starts 7–9 mm, decays ~0.008 mm/day) |
| `speed` | float | km/h (0–80) |
| `ambient_temp` | float | Celsius (city + seasonal sinusoid + noise) |
| `latitude` | float | GPS latitude (city centroid + Gaussian jitter) |
| `longitude` | float | GPS longitude |
| `label` | str | `normal` / `slow_leak` / `puncture` / `valve_failure` / `overinflation` |

**Derived features added post-generation** (lines 178–180):

| Field | Derivation |
|---|---|
| `delta_pressure` | Per-`(vehicle_id, tire_id)` first-difference of `pressure` |
| `delta_temp` | Per-`(vehicle_id, tire_id)` first-difference of `temperature` |

**Anomaly injection rates** (lines 44–47):

| Anomaly | Rate (per vehicle-tire) |
|---|---|
| `slow_leak` | 8% — gradual pressure loss, 0.3–1.2 PSI/day |
| `puncture` | 4% — sudden drop then flat |
| `valve_failure` | 3% — intermittent, 40% of days lose 2–6 PSI |
| `overinflation` | 2% — +5–10 PSI |

**Output scale**: 50 vehicles × 4 tires × 180 days × 48 readings/day = ~17.3M records, partitioned monthly as `tire_telemetry_{YYYY-MM}.parquet` plus `tire_telemetry_full.parquet`.

**Note**: The `platform-foundation/scripts/generate-tire-telemetry.py` (older ad-hoc script) uses a **different schema** — nested JSON with `tire_data.{front_left,front_right,rear_left,rear_right}.{pressure_psi,temperature_f,tread_depth_mm}` plus `vehicle_metrics.{speed_mph,odometer_miles,ambient_temp_f}`. It uploads hourly JSON to S3 and is **not** connected to the PM CDK stack. Source: `platform-foundation/scripts/generate-tire-telemetry.py` lines 15–52.

---

## Area 2 — Platform-Foundation Data Products: Schemas and Physical Locations

### 2.1 Catalog overview (all 9 products)

Source: `platform-foundation/stacks/foundation_stack.py` lines 57–68 (`DATA_PRODUCT_DATABASES` list).

| # | Technical name | Glue database (`staging`) | Storage format | Partition key(s) |
|---|---|---|---|---|
| 1 | `vehicle_telemetry_aggregated` | `adp_staging_vehicle_telemetry_aggregated` | Iceberg | `event_date, bucket(16, vin)` |
| 2 | `vehicle_identity` | `adp_staging_vehicle_identity` | Iceberg | `model_year` |
| 3 | `charging_sessions` | `adp_staging_charging_sessions` | Iceberg | `session_date, bucket(16, vin)` |
| 4 | `energy_usage` | `adp_staging_energy_usage` | Iceberg | `usage_date` |
| 5 | `ota_campaigns` | `adp_staging_ota_campaigns` | Iceberg | `campaign_id` (header) + `dispatch_date` (events) |
| 6 | `customer_360` | `adp_staging_customer_360` | Iceberg | `snapshot_date` |
| 7 | `customer_interactions` | `adp_staging_customer_interactions` | Iceberg | `interaction_date, bucket(16, customer_id)` |
| 8 | `service_records` | `adp_staging_service_records` | Iceberg | `service_month` |
| 9 | `vehicle_knowledge_base` | n/a (S3 + Bedrock KB) | `documents` | n/a |

Lake bucket name pattern (source: `foundation_stack.py` line 73):
```
adp-{stage}-foundation-lake-{account}-{region}
```

Curated data S3 prefix (source: `platform-foundation/Makefile` line `SEED_OUTPUT_ROOT ?= curated`):
```
s3://adp-{stage}-foundation-lake-{account}-{region}/curated/{product_name}/{table_name}/
```

Dimensions S3 prefix:
```
s3://adp-{stage}-foundation-lake-{account}-{region}/dimensions/{dimension_name}/data.parquet
```

Knowledge Base S3 prefix (source: `docs/cvx-integration-contract.md` line under §3.9):
```
s3://adp-{stage}-foundation-lake-{account}-{region}/knowledge/vehicle_knowledge_base/
```

### 2.2 `vehicle_telemetry_aggregated` schema

Source: `platform-foundation/source/data-products/vehicle_telemetry_aggregated/schema.yaml` (full file).

- **Primary key**: `[vin, event_time]`
- **Partition keys**: `[event_date]`; **bucketing**: `vin` × 16 buckets
- **Generator**: `source/data-products/vehicle_telemetry_aggregated/generator.py` — PySpark, 10M rows / 90-day rolling window

**All 27 columns:**

| Column | Type | Nullable | Description / VSS ref |
|---|---|---|---|
| `vin` | string | false | FK → `vins` dimension; 17-char ISO-3779 |
| `event_date` | date | false | UTC calendar day (partition key) |
| `event_time` | timestamp | false | Source-truth UTC microsecond |
| `ingest_time` | timestamp | false | Loader write time UTC |
| `speed_kmh` | double | true | VSS Vehicle.Speed avg (km/h), range 0–300 |
| `avg_speed_kmh` | double | true | VSS Vehicle.AverageSpeed (km/h) |
| `total_miles_driven` | double | true | VSS Vehicle.TraveledDistance (miles, US dev) |
| `start_soc_pct` | double | true | State-of-Charge at window start (%) |
| `end_soc_pct` | double | true | State-of-Charge at window end (%) |
| `state_of_health_pct` | double | true | VSS .StateOfHealth (%) |
| `battery_pack_temp_avg_c` | double | true | VSS .Temperature.Average (°C) range −40–80 |
| `ambient_temp_avg_c` | double | true | VSS Vehicle.AmbientAirTemperature (°C) range −50–60 |
| `cabin_temp_c` | double | true | VSS Cabin.HVAC.AmbientAirTemperature (°C) |
| `motor_rpm` | double | true | VSS .ElectricMotor.Speed (rpm) |
| `motor_torque_nm` | double | true | VSS .ElectricMotor.Torque (Nm; negative under regen) |
| `motor_power_kw` | double | true | VSS .ElectricMotor.Power (kW) |
| `motor_temp_c` | double | true | VSS .ElectricMotor.Temperature (°C) |
| `range_estimate_start_mi` | double | true | VSS .Range at window start (miles) |
| `range_estimate_end_mi` | double | true | VSS .Range at window end (miles) |
| `is_charging` | boolean | false | VSS .IsCharging |
| `avg_power_kw` | double | true | VSS .ChargeRate average (kW) |
| `latitude` | double | true | PII — GPS latitude (°), NULL on ~60% of rows |
| `longitude` | double | true | PII — GPS longitude (°), NULL on ~60% of rows |
| `heading_deg` | double | true | VSS .Heading (°) |
| `drive_type` | string | true | `awd` / `fwd` / `rwd` |
| `powertrain_type` | string | true | `electric` / `hybrid` / `erev` |
| `vss_version` | string | false | VSS catalog version (emits `"6.0"`) |

**Tire-relevant columns in `vehicle_telemetry_aggregated`**: `speed_kmh`, `ambient_temp_avg_c`, `total_miles_driven`, `vin`, `event_date`, `event_time`. **No direct tire pressure/tread columns** — this product is EV powertrain telemetry only.

### 2.3 `service_records` schema

Source: `platform-foundation/source/data-products/service_records/schema.yaml` (full file).

- **Primary key**: `[service_id]`
- **Partition key**: `[service_month]` (monthly grain)
- **Generator**: `source/data-products/service_records/generator.py` — pandas, 10M rows over 10 years

**Tire-relevant columns:**

| Column | Type | Description |
|---|---|---|
| `service_id` | string | PK |
| `service_date` | date | Service event date |
| `service_month` | date | First-of-month (partition key) |
| `vin` | string | FK → `vins` |
| `customer_id` | string | FK → `customers` (nullable) |
| `dealer_id` | string | FK → `dealers` |
| `service_type` | string | Enum — **`tire_service`** is the relevant value for PM |
| `complaint_text` | string | PII drift-target free-text — could include tire complaints |
| `dtc_codes` | array\<string\> | DTC codes at intake (e.g. `['P0AA6']`) |
| `parts_used` | array\<string\> | Part numbers replaced — tire part numbers join `parts` dimension |
| `labor_hours` | double | Total labor billed |
| `total_cost_usd` | decimal(12,2) | Invoice total (null if warranty) |
| `warranty_covered` | boolean | Warranty coverage flag |
| `outcome` | string | `resolved` / `parts_pending` / `follow_up_required` / `lemon_law_buyback` |
| `event_time` | timestamp | Source-truth event time (= service_date 00:00 UTC) |

**Service type enum**: `scheduled_maintenance`, `warranty_repair`, `safety_recall`, `software_recall`, `body_repair`, **`tire_service`**, `charging_system`, `battery_replacement`, `hv_battery_diagnostic`, `software_update`. Source: `service_records/schema.yaml` lines 37–49.

**Generator distribution** (source: `service_records/generator.py` lines 20–22): `service_type_probs` assigns `tire_service` = 10% of 10M rows = ~1M tire service records over 10 years.

### 2.4 `vehicle_knowledge_base` schema

Source: `platform-foundation/source/data-products/vehicle_knowledge_base/schema.yaml` (full file) — `storage_format: documents`.

**Schema fields** (document chunks, not Iceberg):

| Field | Description |
|---|---|
| `chunk_id` | UUIDv5 |
| `source_doc_id` | Source document identifier |
| `source_category` | Enum: `dtc_guide`, `tsb_recall`, `owner_manual`, `parts_catalog`, `service_network`, `service_policy`, `charging_narrative`, `ota_rollout_summary` |
| `title` | Document title |
| `chunk_index` | Position in source doc |
| `chunk_text` | Raw text chunk |
| `chunk_size_tokens` | Token count |
| `chunk_overlap_tokens` | Overlap token count |
| `embedding_model` | Default `amazon.titan-embed-text-v2:0` |
| `s3_uri` | S3 URI of the chunk file |
| `language` | Language code |
| `indexed_at` | Timestamp |

Physical location: `s3://adp-{stage}-foundation-lake-{account}-{region}/knowledge/vehicle_knowledge_base/`
Source: `docs/cvx-integration-contract.md` section 3.9.

After the 2026-06-22 VKB content-fill spec (`2026-06-22-adp-vkb-content-fill`): 57 documents total, 6 DTC guides covering P0420, P0300, C0035, U0100, P0171, B0001 — all powertrain/charging DTCs, no tire DTCs. Source: `CHANGELOG.md` entry 2026-06-22.

### 2.5 Other products: DataZone asset names

Source: `docs/cvx-integration-contract.md` §1.1 (catalog table).

All 9 DataZone listing names match their technical names exactly (e.g., `vehicle_telemetry_aggregated` listing = `vehicle_telemetry_aggregated`). The domain name pattern is `adp-{stage}-foundation-domain`. Domain ID is exported as CFN export `adp-{stage}-foundation-datazone-domain-id`.

---

## Area 3 — Consumer Pattern: How a Downstream Consumer Reads a Governed Data Product

### 3.1 The cross-account CVX consumer pattern (canonical reference)

Source: `docs/cvx-integration-contract.md` (full doc); `platform-foundation/stacks/governance_stack.py` lines 18–27 (docstring); `platform-foundation/app.py` lines 95–116 (`_resolve_cvx_kb_principals`).

The governance stack accepts an optional `cvx_account_id` parameter (sourced from CDK context `cvxAccountId` OR env var `ADP_KB_CVX_ACCOUNT_ID`). When supplied at deploy time, it bootstraps a Lake Formation cross-account share granting `SELECT + DESCRIBE` on all `adp_{stage}_*` databases to the CVX account root principal via database-wildcard LF v4 shares.

Source: `governance_stack.py` docstring lines 20–27:
> "when `cvx_account_id` is supplied … bootstraps LF management and grants SELECT+DESCRIBE on all in-scope `adp_{stage}_*` databases to the CVX account root principal via database-wildcard shares (LF v4)"

**Cross-account CVX consumer read path:**

```
CVX role  →  DataZone subscription request (create + accept)
          →  Lake Formation grant (auto-issued by DataZone after approval)
          →  Athena query against Glue catalog adp_staging_<product>.<table>
          →  LF issues short-lived credentials via lakeformation:GetDataAccess
          →  S3 GetObject against lake bucket (KMS decrypt with lake CMK)
```

Source: `docs/cvx-integration-contract.md` §2 note: "Hard-binding `s3:GetObject` on the lake bucket is an anti-pattern — it bypasses LF row/column filters."

### 3.2 Required IAM actions on the consumer principal

Source: `docs/cvx-integration-contract.md` §2.1 (IAM JSON block).

```json
{
  "datazone:ListDomains", "datazone:GetDomain", "datazone:ListProjects",
  "datazone:GetProject", "datazone:SearchListings", "datazone:GetListing",
  "datazone:CreateSubscriptionRequest", "datazone:GetSubscriptionRequest",
  "datazone:ListSubscriptionRequests", "datazone:ListSubscriptionGrants",
  "datazone:GetSubscriptionGrant"
}
```
Resource: `arn:aws:datazone:us-east-1:<adp-account>:domain/<domain-id>`

```json
{
  "glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables",
  "glue:GetPartitions",
  "athena:StartQueryExecution", "athena:GetQueryExecution",
  "athena:GetQueryResults", "athena:StopQueryExecution",
  "athena:ListWorkGroups", "athena:GetWorkGroup"
}
```
Resource: `*`

```json
{ "lakeformation:GetDataAccess" }
{ "kms:Decrypt", "kms:DescribeKey" }   -- lake CMK: alias/adp-{stage}-foundation-lake
{ "s3:PutObject", "s3:GetObject", "s3:ListBucket" }  -- consumer's Athena results bucket
```

### 3.3 Subscription flow (canonical CLI)

Source: `docs/cvx-integration-contract.md` §3 (boilerplate block), and `platform-foundation/scripts/smoke-test-subscription.sh` (canonical reference implementation per auto-subscribe-cvx.sh line 34).

```bash
DOMAIN_ID=$(aws cloudformation list-exports --region us-east-1 \
  --query "Exports[?Name=='adp-${STAGE}-foundation-datazone-domain-id'].Value | [0]" \
  --output text)

ASSET_ID=$(aws datazone search-listings \
  --domain-identifier "$DOMAIN_ID" --search-text "vehicle_telemetry_aggregated" \
  --region us-east-1 --query 'items[0].assetListing.entityId' --output text)

REQ_ID=$(aws datazone create-subscription-request \
  --domain-identifier "$DOMAIN_ID" \
  --request-reason "PM consumer: vehicle_telemetry_aggregated" \
  --subscribed-listings "{\"identifier\":\"$ASSET_ID\"}" \
  --subscribed-principals "{\"project\":{\"identifier\":\"$CONSUMER_PROJECT_ID\"}}" \
  --region us-east-1 --query 'id' --output text)

aws datazone accept-subscription-request \
  --domain-identifier "$DOMAIN_ID" --identifier "$REQ_ID" --region us-east-1
```

CVX auto-subscribes to 5 products via `platform-foundation/scripts/auto-subscribe-cvx.sh` (products listed at lines 57–63): `vehicle_telemetry_aggregated`, `customer_360`, `charging_sessions`, `energy_usage`, `vehicle_knowledge_base`.

### 3.4 Same-account PM consumer read path

**PM is in the same account as the platform-foundation** (both deploy to the same AWS account). For a same-account consumer, the LF grant path is simpler — no cross-account LF resource share needed.

Canonical same-account read path:

```
PM Glue ETL job role / PM Lambda role
  →  DataZone consumer project (created in adp-{stage}-foundation-domain)
  →  DataZone subscription to listing (search-listings → create → accept)
  →  Lake Formation grant (auto-issued): SELECT + DESCRIBE on Glue database+table
  →  Glue/Athena query: SELECT * FROM adp_staging_service_records.service_records
                          WHERE service_type = 'tire_service'
                            AND service_month >= DATE '...'
  →  LF GetDataAccess → temporary S3 credentials
  →  Read from s3://adp-staging-foundation-lake-{account}-us-east-1/curated/service_records/
```

The `DataProductsStack` IAM role pattern (same-account Spark-ETL role) is the precedent:
Source: `platform-foundation/stacks/data_products_stack.py` lines 1–50 (docstring): role name pattern `adp-{stage}-foundation-spark-etl-role-{region}`, grants S3 read/write on lake bucket curated prefixes + Glue catalog databases.

A PM ETL role would follow the same CDK pattern, scoped to `adp_{stage}_service_records` and `adp_{stage}_vehicle_telemetry_aggregated` databases.

### 3.5 PII column handling

Source: `docs/cvx-integration-contract.md` §2.3.

LF column tags propagate from `pii: true` flags in schema YAMLs. The governance stack tags PII columns with `adp-classification: PII`. Non-PII consumers see PII columns masked. For PM's ML use case: `service_records.complaint_text` and `service_records.customer_id` are PII; the ML pipeline should request non-PII access (masking complaint_text is acceptable for training).

Relevant `vehicle_telemetry_aggregated` PII columns: `latitude`, `longitude` (NULL on ~60% of rows by design). Source: `vehicle_telemetry_aggregated/schema.yaml` lines 63–70.

### 3.6 Athena workgroup convention

Source: `docs/cvx-integration-contract.md` §2.2.

Consumers SHOULD bind to a dedicated workgroup (`pm-staging-analytics`, `pm-prod-analytics`) for cost attribution. Workgroup owns its Athena results S3 location (a PM-side bucket, not the lake bucket).

### 3.7 Canonical Athena query for tire-service records

Source: `docs/cvx-integration-contract.md` §3.8 (service_records sample query pattern).

```sql
-- Tire service records for a VIN over trailing 12 months
SELECT sr.vin,
       sr.service_date,
       sr.service_type,
       dtc_code,
       sr.parts_used,
       sr.labor_hours,
       sr.outcome
FROM   adp_staging_service_records.service_records sr
CROSS JOIN UNNEST(dtc_codes) AS t(dtc_code)
WHERE  service_month >= DATE '2025-07-01'        -- fires Iceberg partition prune
  AND  service_type  = 'tire_service'
  AND  service_date  >= DATE '2025-07-15'
ORDER BY sr.service_date DESC;
```

```sql
-- Vehicle telemetry for a VIN, driving segments only (not charging)
SELECT vin, event_date, event_time, speed_kmh, ambient_temp_avg_c, total_miles_driven
FROM   adp_staging_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated
WHERE  event_date BETWEEN DATE '2026-06-15' AND DATE '2026-07-15'
  AND  is_charging = false
ORDER BY event_time;
```

---

## Area 4 — Seed Generator Extension Points

### 4.1 `make seed` pipeline

Source: `platform-foundation/Makefile` lines 200–305 (seed orchestration section).

The master `seed` target runs **9 product generators in strict dependency order**. Each step is a Makefile target that depends on the prior:

```
seed-dimensions        (generate_all.py — 7 dimensions)
  └→ seed-vehicle-identity      [1/9] pandas
       └→ seed-customer-360         [2/9] pandas
            └→ seed-charging-sessions    [3/9] pandas
                 └→ seed-ota-campaigns       [4/9] pandas (2 tables)
                      └→ seed-customer-interactions  [5/9] pandas
                           └→ seed-service-records       [6/9] pandas
                                └→ seed-vehicle-telemetry-aggregated  [7/9] PySpark
                                     └→ seed-energy-usage              [8/9] PySpark
                                          └→ seed-vehicle-knowledge-base  [9/9] text/markdown
                                               └→ seed-integrity (pytest FK + drift tests)
                                                    └→ seed (master, prints complete)
```

**Emit order rule**: dimensions FIRST (all 7), then products in the dependency chain shown above. Products that use FK values from an earlier product must come AFTER it in the chain. Source: `Makefile` comment block lines 200–218.

**Invocation**:
```bash
make seed STAGE=staging          # full run, deterministic seed=42
make seed-dimensions STAGE=staging   # just dimensions
make seed-service-records STAGE=staging  # [6/9] + all predecessors
```

**Environment variables** controlling scale (source: `Makefile` lines 27–32):
```makefile
PYSPARK_LOCAL_ROWS       ?= 100000    # PySpark local sample (100K rows)
PYSPARK_LOCAL_DAYS_TEL   ?= 7         # vehicle_telemetry_aggregated: 7-day window locally
PYSPARK_LOCAL_DAYS_NRG   ?= 30        # energy_usage: 30-day window locally
PYSPARK_LOCAL_PARTITIONS ?= 4
```
Full Glue scale: 10M rows / 90 days for `vehicle_telemetry_aggregated`; deferred per `decisions.md`.

### 4.2 Base class: `ProductGenerator`

Source: `platform-foundation/source/lib/product_generator.py` (full file — 24KB).

All 7 pandas-based product generators extend `ProductGenerator`. The PySpark generators (`vehicle_telemetry_aggregated`, `energy_usage`) do NOT extend it (they are standalone scripts), but they follow the same output conventions.

**Key `ProductGenerator` methods:**

| Method | Purpose |
|---|---|
| `generate_table(table, seed, scale, dimensions)` | Abstract — subclass implements; returns pandas DataFrame |
| `write_partitioned_parquet(df, table, output_root)` | Writes DataFrame as partitioned parquet to `output_root/{product}/{table}/` |
| `write_manifest(...)` | Writes `manifest.json` with seed, row count, edge-case rates, SHA-256 |
| `upload_to_s3(local_dir, s3_prefix)` | Uploads local tree to S3 when `--output-root s3://...` |
| `register_iceberg_table(table, location)` | Builds Athena DDL from `schema_loader.Table.iceberg_ddl()` and submits to Athena |

**Edge-case injection** (source: `product_generator.py` lines 35–60, `EDGE_CASE_RATES`):

| Code | Rate | Behavior |
|---|---|---|
| `missing_required` | 0.75% | NaN on `edge_case_eligible` columns |
| `late_arrival` | 0.50% | `ingest_time` + 1–3 days |
| `schema_drift` | 0.35% | `DRIFT-` prefix on string cells |
| `bad_pii` | 0.20% | Applied to `pii_drift_target` columns |
| `orphan_fk` | 0.00% | Counter-example — never injected |
| `outlier_value` | 0.40% | 5–10× above column `range` upper bound |

### 4.3 Schema YAML convention

Source: `platform-foundation/source/lib/schema_loader.py` (full file); any product's `schema.yaml`.

Every product has a `schema.yaml` at `source/data-products/{product_name}/schema.yaml`. Top-level fields:

```yaml
name: <product_name>        # matches directory name
kind: product               # or "dimension"
domain: automotive          # or service / ev_operations / customer / knowledge
display_name: "..."
version: 1.0.0
deterministic_seed: 42
tables:
  - name: <table_name>
    storage_format: iceberg   # or "documents" for vehicle_knowledge_base
    primary_key: [col1, col2]
    partition_keys: [colN]
    bucketing:
      <col>: 16
    columns:
      - name: <col>
        type: string          # allowed: string, int, bigint, double, decimal, boolean, timestamp, date, array<string>, array<int>
        nullable: false
        pii: false
        edge_case_eligible: true  # marks columns eligible for missing_required + outlier injection
        description: "..."
        pattern: "^regex$"    # for ID columns
        range: [min, max]
        enum_values: [...]
    foreign_keys:
      - column: vin
        references_table: vins  # must be in _VALID_DIMENSION_REFS
        references_column: vin
```

Source: `schema_loader.py` — `ALLOWED_COLUMN_TYPES` set (lines ~40–51); `_VALID_DIMENSION_REFS` is the allowed set for `references_table`.

### 4.4 Referential integrity tests

Source: `platform-foundation/tests/test_referential_integrity.py` (full file).

After all 9 products are generated, `make seed-integrity` runs two pytest suites:
- `tests/test_referential_integrity.py` — FK closure: every FK value in curated parquet must appear in the referenced dimension's PK column; zero orphans required.
- `tests/test_data_contracts.py` — drift detection.

**Key test**: `test_every_fk_targets_known_dimension` (lines 62–72) — static check that every `foreign_key.references_table` in every product's schema is in `_VALID_DIMENSION_REFS`. **Adding a new product requires adding its schema's FK targets to `_VALID_DIMENSION_REFS` in `schema_loader.py`.**

FK-closure test pattern (lines 80–120 of `test_referential_integrity.py`): for each product × FK column, reads both parquet files, computes `set(product_col) - set(dimension_pk_col)`, asserts empty.

### 4.5 Dimensions catalog

Source: `platform-foundation/dimensions/` directory; `platform-foundation/source/dimensions/generate_all.py`.

7 dimensions, generated first:

| Dimension | Primary key | Relevant FK targets |
|---|---|---|
| `vins` | `vin` | Used by all 8 Iceberg products |
| `customers` | `customer_id` | Used by `charging_sessions`, `customer_360`, `customer_interactions`, `service_records` |
| `dealers` | `dealer_id` | Used by `service_records` |
| `parts` | `part_number` | Used by `service_records.parts_used` |
| `suppliers` | `supplier_id` | Used by `vehicle_identity` |
| `charging_stations` | `station_id` | Used by `charging_sessions` |
| `time_calendar` | `date_key` | Reference table |

### 4.6 HOW TO ADD a new `tire_health` data product

The following describes the exact files to touch and conventions to follow. **This is documentation of the mechanism only — no implementation is done here.**

#### Step 1: Create the schema YAML
**File to create**: `platform-foundation/source/data-products/tire_health/schema.yaml`

Follow the schema YAML convention in §4.3. For a `tire_health` product with tire telemetry time-series + failure labels, the schema would declare:

- `name: tire_health`, `kind: product`, `domain: automotive`
- A single Iceberg table `tire_health`
- FK: `vin → vins.vin` (required — must be in `_VALID_DIMENSION_REFS`)
- Partition key: `event_date` (daily grain, like `vehicle_telemetry_aggregated`)
- Columns should include: `vin`, `tire_id` (`FL`/`FR`/`RL`/`RR`), `event_date`, `event_time`, `pressure_psi` (double), `temperature_c` (double), `tread_depth_mm` (double), `speed_kmh` (double, FK-compatible with `vehicle_telemetry_aggregated.speed_kmh`), `ambient_temp_c` (double), `label` (string enum — `normal`/`slow_leak`/`puncture`/`valve_failure`/`overinflation`), `delta_pressure` (double, derived), `wear_rate_mm_per_day` (double, derived)

#### Step 2: Create the generator
**File to create**: `platform-foundation/source/data-products/tire_health/generator.py`

For a **pandas** product (recommended for v1 tire_health — same tier as `service_records`):
- Extend `ProductGenerator` (import from `source/lib/product_generator.py`)
- Set `product_name = "tire_health"` class attribute
- Implement `generate_table(table, seed, scale, dimensions)` — receives `dimensions["vins"]` DataFrame, generates per-VIN per-tire per-timestamp rows
- Call `self.apply_edge_cases(df, table)` to inject the standard edge-case taxonomy
- FK contract: every `vin` value must be drawn from `dimensions["vins"]["vin"].to_numpy()`; `orphan_fk` rate must be 0.0%

For a **PySpark** product (if >1M rows required):
- Follow `vehicle_telemetry_aggregated/generator.py` structure — standalone script, deferred-import PySpark, `--vins-source`, `--output-root`, `--rows`, `--days`, `--partitions`, `--seed` CLI args
- Local mode falls back to plain parquet (no Iceberg classpath)

#### Step 3: Register the Glue database
**File to touch**: `platform-foundation/stacks/foundation_stack.py`

Add a new entry to `DATA_PRODUCT_DATABASES` list (currently lines 57–68):
```python
("tire_health", "Per-VIN per-tire telemetry with anomaly labels (rolling window)"),
```
This causes CDK to create `adp_{stage}_tire_health` Glue database at deploy time.

#### Step 4: Wire the Makefile
**File to touch**: `platform-foundation/Makefile`

Add a new target after `seed-service-records` (position [7/9] shifts to [8/9], etc.) OR insert it after step [6] (service_records — the most sensible dependency since `tire_health` needs `service_records` for join labels):

```makefile
seed-tire-health: _require-stage seed-service-records ## [7/9] Generate tire_health (pandas)
	@echo "$(GREEN)[7/9] tire_health (pandas, seed=$(SEED)) ...$(NC)"
	@$(PY) source/data-products/tire_health/generator.py \
		--seed $(SEED) --dim-root $(SEED_DIM_ROOT) --output-root $(SEED_OUTPUT_ROOT)
```

Update the chain: change `seed-vehicle-telemetry-aggregated` to depend on `seed-tire-health` instead of `seed-service-records`. Update step numbers for the PySpark products (→ [8/9], [9/9]) and VKB (→ [10/10]).

#### Step 5: Update `_VALID_DIMENSION_REFS` in `schema_loader.py`
**File to touch**: `platform-foundation/source/lib/schema_loader.py`

The referential integrity test at `test_referential_integrity.py` line 64 checks that every `foreign_key.references_table` is in `schema_loader._VALID_DIMENSION_REFS`. If `tire_health.vin` references `vins`, this is already in the set. No change needed if only referencing existing dimensions.

#### Step 6: Add referential integrity assertions
**File to touch**: `platform-foundation/tests/test_referential_integrity.py`

The existing generic test loop (`test_vin_fk_closure_per_product`, etc.) should automatically pick up the new product once the schema YAML declares `foreign_keys`. The `product_names` fixture in `conftest.py` enumerates all product directories — adding `tire_health/schema.yaml` is sufficient.

Source: `tests/conftest.py` (fixture `product_names` enumerates `source/data-products/` subdirectories).

#### Step 7: Register the DataZone data product listing
**File to touch**: `platform-foundation/stacks/datazone_projects_stack.py` (or `datazone_stack.py`)

Follow the existing pattern of creating a DataZone project + publishing the listing for the new product. Source: `platform-foundation/stacks/datazone_projects_stack.py` (full file).

#### Step 8 (optional): Extend `auto-subscribe-cvx.sh`
**File to touch**: `platform-foundation/scripts/auto-subscribe-cvx.sh`

If PM should be a DataZone subscriber (same-account), mirror the CVX subscription pattern. The PM consumer project would subscribe to `tire_health` + `vehicle_telemetry_aggregated` + `service_records`.

### 4.7 Join contract: `tire_health` ↔ `vehicle_telemetry_aggregated` ↔ `service_records`

For ML training, the join keys are:

| Join | Key columns | Notes |
|---|---|---|
| `tire_health` ↔ `vehicle_telemetry_aggregated` | `vin`, `event_date` | Date-grain join; VTA has no per-tire granularity |
| `tire_health` ↔ `service_records` | `vin`, `service_date` ≈ `tire_health.event_date` | Temporal join; filter `service_type = 'tire_service'` |
| `service_records.parts_used` ↔ `parts` dimension | `part_number` | Parts dimension for tire part identification |

The join between `tire_health` (hourly/30-min telemetry) and `service_records` (event-level) is a many-to-one temporal join: for each tire telemetry row, look back N days to find the most recent `tire_service` event for that VIN. This is a standard window-function or range-join pattern in Athena/Spark.

---

## Open Questions for the Architect

These are ambiguous design choices surfaced by the research that require architect decisions before Phase 3 implementation can proceed. They are questions only — no answers are proposed here.

1. **`tire_health` schema grain**: Should `tire_health` be per-tire per-timestamp (long format, matching PM's synthetic generator at ~17M rows/6 months) or per-VIN per-day aggregate (matching `vehicle_telemetry_aggregated`'s grain)? The former is the natural ML training format; the latter is more consistent with the existing product conventions and reduces seed cost. The ML pipeline expects per-tire time-series — if `tire_health` aggregates to daily, PM must un-aggregate or use a separate Glue ETL step to re-expand.

2. **Supervised vs unsupervised labels**: The current PM model uses **Random Cut Forest (unsupervised anomaly detection)** — it does not use labels. The synthetic generator (`scripts/generate_training_data.py`) DOES emit ground-truth labels (`slow_leak`, `puncture`, etc.). Should Phase 3 switch to a supervised model (e.g., XGBoost, Random Forest classifier) using the labels? If yes, the SageMaker training image URL and `ModelParameters` in `ml_training_stepfunction.py` lines 29–40 must change. If no, the `label` column in `tire_health` is for evaluation only and should be marked `nullable: true` with a note.

3. **`tire_health` product placement — new product vs extension of `vehicle_telemetry_aggregated`**: Should tire telemetry live as a **new 10th data product** (`tire_health`) or as additional columns appended to `vehicle_telemetry_aggregated`? VTA has no per-tire granularity today; adding `tire_id` would change VTA's primary key (`[vin, event_time]` → `[vin, tire_id, event_time]`) and break existing CVX consumers. A separate product is safer.

4. **`service_records.tire_service` coverage**: The existing `service_records` generator assigns `tire_service` = 10% of 10M rows (~1M records). These are synthetic with no tire-specific DTC codes (current `DTC_CODES` list in `service_records/generator.py` lines 14–21 contains powertrain codes only, no tire DTCs like `C0040`/`C0044`). Should the generator be extended to emit tire-specific DTCs and `parts_used` tire part numbers for `service_type = 'tire_service'` rows? Or will PM use the existing records as-is?

5. **Pandas vs PySpark tier for `tire_health`**: The per-tire per-timestamp schema at ~17M rows/6 months exceeds the pandas "full" tier precedent (service_records is 10M/10 years). Should `tire_health` be a **PySpark** product (following `vehicle_telemetry_aggregated`)? PySpark local mode works at `PYSPARK_LOCAL_ROWS=100000` but requires PySpark 3.5+ installed. Given the known `pyspark-py314-pickle-incompat` P3 issue (`issues/2026-06-01-pyspark-py314-pickle-incompat/`), what Python version will the seed pipeline target for `tire_health`?

6. **PM consumer DataZone project vs direct lake read**: Should PM create a **DataZone consumer project** (full subscription flow) or — since PM is in the same account as the foundation — take a simpler same-account path (direct Glue catalog + LF grant without DataZone subscription)? CVX uses full DataZone because it's a different account. PM could use direct LF grants for simplicity, but DataZone adds lineage tracking and access governance. This is a governance decision.

7. **ML read path for training**: SageMaker training jobs read from S3. The current PM training pipeline reads from `training_data_bucket` (a CDK-provisioned private bucket). After Phase 3, should the Glue ETL job read from the foundation lake (via LF credentials) and write transformed features to `training_data_bucket`? Or should SageMaker be granted direct Athena access to read from the lake Iceberg tables? The former (Glue → S3 → SageMaker) is the existing pattern and lower-risk; the latter requires SageMaker execution role to hold `lakeformation:GetDataAccess`.

---

*End of tech research. All claims are cited to source files above.*
