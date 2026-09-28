# CVX Integration Contract — ADP Foundation v1

This document is the integration contract between the **ADP Foundation**
(this repo, `automotive-data-platform-on-aws`) and downstream
channel-layer consumers, with **CVX**
(`guidance-for-connected-vehicle-experience-on-aws`) as the
canonical example. It tells a CVX architect how to subscribe to
ADP-published data products, query them from Athena, seed a Bedrock
Knowledge Base from `vehicle_knowledge_base`, and trace lineage —
without re-defining any data contracts (which live in
[`docs/data-contracts.md`](data-contracts.md)).

> **Authority of references**: Every column-name, regex, partition,
> or unit reference in this document points back to
> [`docs/data-contracts.md`](data-contracts.md). If this doc and
> `data-contracts.md` disagree, `data-contracts.md` is correct and
> this doc is wrong — file an issue.

> **Placeholder notation in commands and ARNs below**: any
> `<account>` token is a **user-substitution** — replace it with
> your 12-digit AWS account ID before running the command (e.g.
> `aws sts get-caller-identity --query Account --output text`).
> Region is pinned to `us-east-1` as a literal throughout
> (single-region by design); there is no `<region>` placeholder.
> Stage tokens (`{stage}`) are filled by your deploy environment
> per the Makefile contract — see
> [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) "Stage gate".

---

## 1. Scope and stage convention

ADP publishes **9 data products** through DataZone V2. Eight are
Iceberg-on-Glue tables; one (`vehicle_knowledge_base`) is a set of
Bedrock-KB-ready document chunks (storage format `documents`, see
schema YAML).

The deployed foundation supports two stages — `staging` and `prod`
(see `docs/DEPLOYMENT.md` "Stage rollout (2026-05-29 onwards)").
**Glue databases follow the pattern `adp_{stage}_<product>` and
DataZone domain names follow `adp-{stage}-foundation-domain`.** The
literal examples below use `staging`; replace `staging` with `prod`
verbatim for production.

### 1.1 Catalog overview

| # | Domain | Technical name | DataZone listing name | Glue database | Iceberg table(s) | Partition (per `data-contracts.md` → "Iceberg partition conventions") |
|---|---|---|---|---|---|---|
| 1 | Automotive   | `vehicle_telemetry_aggregated` | `vehicle_telemetry_aggregated` | `adp_staging_vehicle_telemetry_aggregated` | `vehicle_telemetry_aggregated`                       | `event_date, bucket(16, vin)` |
| 2 | Automotive   | `vehicle_identity`             | `vehicle_identity`             | `adp_staging_vehicle_identity`             | `vehicle_identity`                                   | `model_year` |
| 3 | EV Operations| `charging_sessions`            | `charging_sessions`            | `adp_staging_charging_sessions`            | `charging_sessions`                                  | `session_date, bucket(16, vin)` |
| 4 | EV Operations| `energy_usage`                 | `energy_usage`                 | `adp_staging_energy_usage`                 | `energy_usage`                                       | `usage_date` |
| 5 | EV Operations| `ota_campaigns`                | `ota_campaigns`                | `adp_staging_ota_campaigns`                | `ota_campaigns` (header) **+** `ota_campaign_events` | `campaign_id` (header); `dispatch_date` (events) |
| 6 | Customer     | `customer_360`                 | `customer_360`                 | `adp_staging_customer_360`                 | `customer_360`                                       | `snapshot_date` |
| 7 | Customer     | `customer_interactions`        | `customer_interactions`        | `adp_staging_customer_interactions`        | `customer_interactions`                              | `interaction_date, bucket(16, customer_id)` |
| 8 | Service      | `service_records`              | `service_records`              | `adp_staging_service_records`              | `service_records`                                    | `service_month` |
| 9 | Knowledge    | `vehicle_knowledge_base`       | `vehicle_knowledge_base`       | n/a (S3 + Bedrock KB)                      | n/a (document chunks)                                | n/a |

> Partition columns above are **literal Iceberg partition column
> names** as declared in each product's
> `platform-foundation/source/data-products/<product>/schema.yaml`
> `partition_keys` (and `bucketing` where applicable). Iceberg's
> hidden-partition prune fires when the query's `WHERE` clause
> predicates on the literal partition column (e.g., `event_date`,
> `session_date`, `service_month`). Predicates on source-truth
> timestamps (`event_time`, `start_time`, `service_date`) document
> analyst intent and enable sub-day filtering, but they do NOT prune
> partitions — pair them with a partition-column predicate at the
> outer query.

> Note: `ota_campaigns` is one DataZone product but materializes as
> **two** Iceberg tables in one Glue database — the header
> (`ota_campaigns`) and the per-VIN dispatch events
> (`ota_campaign_events`). Subscribe to the listing once; both tables
> become queryable.

### 1.2 Identifier and unit contract (recap)

All IDs match the regex pattern in
[`docs/data-contracts.md` → "Identifier formats"](data-contracts.md#identifier-formats):
`vin` 17-char ISO-3779, `customer_id` `^CUST-[0-9A-F]{8}$`,
`dealer_id` `^DLR-[0-9]{5}$`, `supplier_id` `^SUP-[0-9]{4}$`,
`part_number` `^[A-Z0-9]{8}-[A-Z0-9]{4}$`, `station_id`
`^STN-(TS|EA|EVGO|CP|HOME|DEST)-[0-9]{8}$`. All `timestamp` columns
are UTC microsecond, all `date` columns are UTC calendar day (see
[`docs/data-contracts.md` → "Time and date conventions"](data-contracts.md#time-and-date-conventions)).
Distance columns ending in `_mi` are an explicit US-narrative
deviation from VSS km — flagged by the suffix
(see [`docs/data-contracts.md` → "VSS vocabulary subset"](data-contracts.md#vss-vocabulary-subset),
notes after the table).

---

## 2. Auth & IAM requirements (consumer side)

CVX is a **DataZone subscriber**. The CVX deploy creates an IAM role
(or roles) for its data-consumer project and that role is added as a
Project Member in the ADP DataZone consumer project. After CVX
creates and accepts a subscription request to a listing, Lake
Formation grants flow automatically; CVX never edits LF grants
directly.

### 2.1 Required IAM actions on the CVX-side principal

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DataZoneCatalogRead",
      "Effect": "Allow",
      "Action": [
        "datazone:ListDomains",
        "datazone:GetDomain",
        "datazone:ListProjects",
        "datazone:GetProject",
        "datazone:SearchListings",
        "datazone:GetListing",
        "datazone:CreateSubscriptionRequest",
        "datazone:GetSubscriptionRequest",
        "datazone:ListSubscriptionRequests",
        "datazone:ListSubscriptionGrants",
        "datazone:GetSubscriptionGrant"
      ],
      "Resource": "arn:aws:datazone:us-east-1:<adp-account>:domain/<domain-id>"
    },
    {
      "Sid": "GlueAndAthenaRead",
      "Effect": "Allow",
      "Action": [
        "glue:GetDatabase",
        "glue:GetDatabases",
        "glue:GetTable",
        "glue:GetTables",
        "glue:GetPartitions",
        "athena:StartQueryExecution",
        "athena:GetQueryExecution",
        "athena:GetQueryResults",
        "athena:StopQueryExecution",
        "athena:ListWorkGroups",
        "athena:GetWorkGroup"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LakeFormationDataAccess",
      "Effect": "Allow",
      "Action": ["lakeformation:GetDataAccess"],
      "Resource": "*"
    },
    {
      "Sid": "AthenaResultS3",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::<cvx-athena-results-bucket>",
        "arn:aws:s3:::<cvx-athena-results-bucket>/*"
      ]
    },
    {
      "Sid": "LakeKMSDecryptForLFGrantedReads",
      "Effect": "Allow",
      "Action": ["kms:Decrypt", "kms:DescribeKey"],
      "Resource": "arn:aws:kms:us-east-1:<adp-account>:key/<lake-kms-key-id>"
    }
  ]
}
```

**Notes**:
- `s3:GetObject` against the lake bucket `adp-{stage}-foundation-lake-<account>-us-east-1`
  is **not** granted directly to CVX. Lake Formation issues
  short-lived credentials via `lakeformation:GetDataAccess` after the
  DataZone subscription is approved. Hard-binding `s3:GetObject` on
  the lake bucket is an anti-pattern — it bypasses LF row/column
  filters.
- The KMS alias for the lake bucket is `alias/adp-{stage}-foundation-lake`
  (see `docs/DEPLOYMENT.md` "Naming summary").
- For Bedrock KB retrieval (section 5), additionally grant
  `bedrock:Retrieve` and `bedrock:RetrieveAndGenerate` against the
  KB ARN. The KB owns its own embeddings-model invocation role;
  CVX never invokes the embedding model directly.

### 2.2 Per-stage Athena workgroup

CVX SHOULD bind queries to a dedicated workgroup
(`cvx-staging-analytics`, `cvx-prod-analytics`) so that Athena cost
shows up tagged to CVX rather than ADP. The workgroup owns its
result-output S3 location; the role above grants `s3:PutObject`
against that CVX-side bucket.

### 2.3 PII column tagging

Lake Formation column tags propagate from `pii: true` flags on
schema YAMLs (see `data-contracts.md` does not list these
column-by-column — they are declared in each product's
`platform-foundation/source/data-products/<product>/schema.yaml`).
The governance stack tags PII columns with
`adp-classification: PII`. CVX subscribers receive **column-level
filtering** via the LF grant — non-PII consumers see PII columns
masked. To request unmasked access, CVX must subscribe with a
project tagged for PII access (out of scope for v1; default CVX
deploy is non-PII).

---

## 3. Subscription instructions — per product

The standard subscription flow is the same for all 9 products:
**`search-listings` → `create-subscription-request` →
`accept-subscription-request` (or wait for owner approval) →
query**. For an end-to-end smoke against the deployed foundation
see `platform-foundation/scripts/smoke-test-subscription.sh` —
which is the canonical reference implementation.

```bash
# Stage convention: replace 'staging' with 'prod' for prod.
export STAGE=staging
export REGION=us-east-1
DOMAIN_ID=$(aws cloudformation list-exports --region "$REGION" \
  --query "Exports[?Name=='adp-${STAGE}-foundation-datazone-domain-id'].Value | [0]" \
  --output text)
CONSUMER_PROJECT_ID=$(aws cloudformation list-exports --region "$REGION" \
  --query "Exports[?Name=='adp-${STAGE}-foundation-datazone-project-data-consumer-test-id'].Value | [0]" \
  --output text)

PRODUCT="vehicle_telemetry_aggregated"   # change per product
ASSET_ID=$(aws datazone search-listings \
  --domain-identifier "$DOMAIN_ID" --search-text "$PRODUCT" \
  --region "$REGION" \
  --query 'items[0].assetListing.entityId' --output text)
REQ_ID=$(aws datazone create-subscription-request \
  --domain-identifier "$DOMAIN_ID" \
  --request-reason "CVX consumer: $PRODUCT" \
  --subscribed-listings "{\"identifier\":\"$ASSET_ID\"}" \
  --subscribed-principals "{\"project\":{\"identifier\":\"$CONSUMER_PROJECT_ID\"}}" \
  --region "$REGION" --query 'id' --output text)
aws datazone accept-subscription-request \
  --domain-identifier "$DOMAIN_ID" --identifier "$REQ_ID" --region "$REGION"
```

Each of the 9 products below shows: the listing name, the Glue
database/table the LF grant materializes, partition keys (with a
data-contracts pointer), and one canonical Athena query.

### 3.1 `vehicle_telemetry_aggregated` (Vehicle Telemetry — Aggregated)

- **Listing**: `vehicle_telemetry_aggregated`
- **Glue**: `adp_staging_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated`
- **Partition / bucketing**: `event_date, bucket(16, vin)`
  (literal column per the schema YAML; see
  [`data-contracts.md` → "Iceberg partition conventions"](data-contracts.md#iceberg-partition-conventions),
  daily-grain fact tables row 1).
- **Key columns** (refer to `data-contracts.md` → "VSS vocabulary
  subset", rows 1–40 of the table for unit + range): `vin` (row
  identifier — see "Identifier formats: vin"), `event_date`
  (partition column), `event_time` (UTC microsecond source-of-truth
  timestamp), `speed_kmh` (row 1), `total_miles_driven` (row 2),
  `start_soc_pct`/`end_soc_pct` (rows 4/5), `state_of_health_pct`
  (row 9), `battery_pack_temp_avg_c` (row 12),
  `range_estimate_*_mi` (rows 13/14), `latitude`/`longitude` (rows
  28/29 — PII), `vss_version` (row 40 — emits `"6.0"`).

Sample query — top-10 hottest battery-pack VINs over the last 7 days
of telemetry, filtered to drive segments only (`is_charging =
false`). The `event_date` predicate is what fires Iceberg hidden-
partition pruning; the `event_time` predicate keeps sub-day
filtering precise.

```sql
SELECT vin,
       AVG(battery_pack_temp_avg_c) AS avg_pack_temp_c,
       MAX(battery_pack_temp_avg_c) AS peak_pack_temp_c,
       COUNT(*)                     AS samples
FROM   adp_staging_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated
WHERE  event_date BETWEEN DATE '2026-05-22' AND DATE '2026-05-29'
  AND  event_time BETWEEN TIMESTAMP '2026-05-22 00:00:00' AND TIMESTAMP '2026-05-29 00:00:00'
  AND  is_charging = false
  AND  battery_pack_temp_avg_c IS NOT NULL
GROUP BY vin
ORDER BY peak_pack_temp_c DESC
LIMIT 10;
```

### 3.2 `vehicle_identity` (Vehicle Identity Graph)

- **Listing**: `vehicle_identity`
- **Glue**: `adp_staging_vehicle_identity.vehicle_identity`
- **Partition**: `model_year`
  (see `data-contracts.md` → "Identifier / dimension tables",
  `vehicle_identity` row).
- **Key columns** (per the schema YAML): `vin` (PK, 1:1 to dimension
  `vins` — see "Identifier formats: vin"), `model_year`, `make`,
  `model`, `trim`, `body_style`, `drive_type` (VSS row 26),
  `powertrain_type` (VSS row 27), `battery_chemistry`,
  `battery_pack_kwh` (VSS row 10), `battery_net_kwh` (VSS row 34),
  `motor_count`, `max_charging_rate_kw` (VSS row 18),
  `connector_type` (VSS row 38), `range_epa_mi` (US-narrative
  deviation, see `_mi` suffix note), `manufacture_date`,
  `current_software_version`, `vss_version`.

Sample query — fleet composition by powertrain × battery-chemistry,
limited to model years 2024 and newer:

```sql
SELECT powertrain_type,
       battery_chemistry,
       COUNT(*)                      AS vins,
       AVG(battery_pack_kwh)         AS avg_pack_kwh,
       AVG(range_epa_mi)             AS avg_range_mi
FROM   adp_staging_vehicle_identity.vehicle_identity
WHERE  model_year >= 2024
GROUP BY powertrain_type, battery_chemistry
ORDER BY vins DESC;
```

### 3.3 `charging_sessions` (Charging Sessions)

- **Listing**: `charging_sessions`
- **Glue**: `adp_staging_charging_sessions.charging_sessions`
- **Partition / bucketing**: `session_date, bucket(16, vin)`
  (literal column per the schema YAML; see
  `data-contracts.md` → "Iceberg partition conventions",
  `charging_sessions` row).
- **Key columns**: `session_id` (PK, UUIDv5),
  `vin` (FK → `vins`), `customer_id` (FK → `customers`, nullable
  for guest charge — see "Identifier formats: customer_id"),
  `session_date` (partition column, derived as
  `CAST(start_time AS DATE)`), `start_time`/`end_time`,
  `station_id` (FK → `charging_stations`, see "Identifier formats:
  station_id"), `station_type` (`home_l1|home_l2|public_dc_fast|destination_l2`),
  `network_provider`, `connector_type` (VSS row 38),
  `start_soc_pct`/`end_soc_pct`, `kwh_delivered`, `peak_power_kw`,
  `cost_usd` (decimal(10,4)), `cost_per_kwh_usd` (decimal(10,6)),
  `latitude`/`longitude` (PII; null for home — privacy),
  `interrupted`, `interrupt_reason`.

Sample query — charging-network share of public DC-fast energy
delivered in May 2026. The `session_date` predicate is what fires
Iceberg hidden-partition pruning; the `start_time` predicate keeps
sub-day filtering precise.

```sql
SELECT network_provider,
       COUNT(*)                                 AS sessions,
       SUM(kwh_delivered)                       AS total_kwh,
       AVG(peak_power_kw)                       AS avg_peak_kw,
       SUM(cost_usd)                            AS total_revenue_usd
FROM   adp_staging_charging_sessions.charging_sessions
WHERE  session_date BETWEEN DATE '2026-05-01' AND DATE '2026-06-01'
  AND  start_time BETWEEN TIMESTAMP '2026-05-01 00:00:00' AND TIMESTAMP '2026-06-01 00:00:00'
  AND  station_type = 'public_dc_fast'
GROUP BY network_provider
ORDER BY total_kwh DESC;
```

### 3.4 `energy_usage` (Energy Usage)

- **Listing**: `energy_usage`
- **Glue**: `adp_staging_energy_usage.energy_usage`
- **Partition**: `usage_date`
  (literal column per the schema YAML; see
  `data-contracts.md` → "Iceberg partition conventions",
  `energy_usage` row).
- **Grain**: 1 row per `(vin, usage_date)` (PK).
- **Key columns** — every column maps to a VSS row (see
  `data-contracts.md` → "VSS vocabulary subset"): `vin`,
  `usage_date`, `start_soc_pct`/`end_soc_pct`/`min_soc_pct`/`max_soc_pct`/`avg_soc_pct`
  (rows 4–8), `total_kwh_consumed`, `total_kwh_charged`
  (must reconcile to `charging_sessions.kwh_delivered`,
  see spec Constraint #5), `regen_kwh_recovered` (row 37 —
  ADP overlay), `total_miles_driven` (row 2; US `_mi` deviation),
  `efficiency_kwh_per_100mi` (derived), `range_estimate_*_mi`
  (rows 13/14), `battery_pack_temp_avg_c` (row 12),
  `ambient_temp_avg_c` (row 32), `state_of_health_pct` (row 9),
  `battery_age_days`.

Sample query — fleet-average efficiency by week, last 90 days, with
seasonal-temperature side-output:

```sql
SELECT DATE_TRUNC('week', usage_date)              AS week,
       COUNT(DISTINCT vin)                         AS active_vins,
       AVG(efficiency_kwh_per_100mi)               AS avg_eff_kwh_per_100mi,
       AVG(ambient_temp_avg_c)                     AS avg_ambient_c,
       SUM(total_kwh_consumed)                     AS total_kwh_consumed,
       SUM(total_miles_driven)                     AS total_miles_driven
FROM   adp_staging_energy_usage.energy_usage
WHERE  usage_date BETWEEN DATE '2026-02-28' AND DATE '2026-05-29'
GROUP BY DATE_TRUNC('week', usage_date)
ORDER BY week;
```

### 3.5 `ota_campaigns` (OTA Campaigns — header + events)

- **Listing**: `ota_campaigns` (single subscription unlocks **both**
  tables).
- **Glue**: `adp_staging_ota_campaigns.ota_campaigns` and
  `adp_staging_ota_campaigns.ota_campaign_events`.
- **Partition**: header `campaign_id`; events `dispatch_date`
  (literal columns per the schema YAML; see
  `data-contracts.md` → "Iceberg partition conventions",
  `ota_campaigns` and `ota_campaign_events` rows).
- **Key columns** — header: `campaign_id` (PK), `campaign_name`,
  `release_version` (semver), `target_make`, `target_model`,
  `target_model_year_min`/`_max`, `package_size_mb`, `category`
  (`safety_recall|feature_add|bug_fix|security_patch|performance`),
  `severity` (`critical|high|medium|low`), `dispatch_start_date`,
  `dispatch_end_date`, `phased_rollout_pct` (`array<int>`), `status`.
  Events: `campaign_id` (FK → header), `vin` (FK → `vins`),
  `dispatch_date`, `dispatch_time`, `download_started_time`,
  `download_completed_time`, `install_started_time`,
  `install_completed_time`, `final_status`
  (`installed|install_failed|download_failed|rolled_back|declined_by_user|...`),
  `previous_software_version`, `new_software_version`.

Sample query — adoption curve for the most recent `safety_recall`
campaign (time-to-install percentiles):

```sql
WITH last_recall AS (
  SELECT campaign_id, campaign_name, dispatch_start_date
  FROM   adp_staging_ota_campaigns.ota_campaigns
  WHERE  category = 'safety_recall'
  ORDER BY dispatch_start_date DESC
  LIMIT  1
)
SELECT lr.campaign_name,
       e.final_status,
       COUNT(*)                                                     AS vins,
       APPROX_PERCENTILE(
         DATE_DIFF('hour', e.dispatch_time, e.install_completed_time), 0.50
       )                                                            AS p50_hours_to_install,
       APPROX_PERCENTILE(
         DATE_DIFF('hour', e.dispatch_time, e.install_completed_time), 0.95
       )                                                            AS p95_hours_to_install
FROM   adp_staging_ota_campaigns.ota_campaign_events e
JOIN   last_recall lr ON lr.campaign_id = e.campaign_id
WHERE  e.dispatch_date >= lr.dispatch_start_date
GROUP BY lr.campaign_name, e.final_status
ORDER BY vins DESC;
```

### 3.6 `customer_360` (Customer 360)

- **Listing**: `customer_360`
- **Glue**: `adp_staging_customer_360.customer_360`
- **Partition**: `snapshot_date`
  (see `data-contracts.md` → "Iceberg partition conventions",
  snapshot tables row).
- **Key columns** — `customer_id` (PK, see "Identifier formats:
  customer_id"), `snapshot_date`, `full_name`/`email`/`phone`
  (PII + drift-target — see schema YAML for `pii_drift_target: true`
  flag), `lifetime_value_usd` (decimal(12,2)), `vehicles_owned_count`,
  `primary_vin` (FK → `vins`, see "Identifier formats: vin"),
  `customer_segment` (`enthusiast|family|fleet|commercial|prospect`),
  `health_score` (0–100), `churn_probability` (0–1),
  `total_charging_sessions_30d`, `total_kwh_consumed_30d`,
  `opted_in_marketing`.

Sample query — churn-risk top-100 EV-startup customers (most-recent
snapshot only, high-LTV bucket):

```sql
WITH latest_snapshot AS (
  SELECT MAX(snapshot_date) AS d FROM adp_staging_customer_360.customer_360
)
SELECT c.customer_id,
       c.customer_segment,
       c.lifetime_value_usd,
       c.health_score,
       c.churn_probability,
       c.total_charging_sessions_30d,
       c.total_kwh_consumed_30d
FROM   adp_staging_customer_360.customer_360 c
JOIN   latest_snapshot ls ON c.snapshot_date = ls.d
WHERE  c.lifetime_value_usd >= 50000
  AND  c.churn_probability  >= 0.40
ORDER BY c.churn_probability DESC, c.lifetime_value_usd DESC
LIMIT 100;
```

### 3.7 `customer_interactions` (Customer Interactions)

- **Listing**: `customer_interactions`
- **Glue**: `adp_staging_customer_interactions.customer_interactions`
- **Partition / bucketing**: `interaction_date, bucket(16, customer_id)`
  (literal column per the schema YAML; see
  `data-contracts.md` → "Iceberg partition conventions",
  `customer_interactions` row).
- **Key columns** — `interaction_id` (PK, UUIDv5),
  `customer_id` (FK → `customers`, see "Identifier formats:
  customer_id"), `interaction_date`, `interaction_time`,
  `channel` (`dealer|service_center|website|mobile_app|call_center|mobile_app_charging_issue|ota_update_notification|chatbot|email`),
  `interaction_type`, `outcome`, `duration_seconds`,
  `vin` (nullable, FK → `vins`),
  `dealer_id` (nullable, FK → `dealers`, see "Identifier formats:
  dealer_id"), `agent_id`, `sentiment_score` (-1..1),
  `subject`/`notes` (PII drift-target free-text),
  `csat_score` (1–5).

Sample query — channel-mix of charging-related contacts in May 2026
and their resolution rates:

```sql
SELECT channel,
       COUNT(*)                                            AS contacts,
       SUM(CASE WHEN outcome = 'resolved'  THEN 1 ELSE 0 END) AS resolved,
       SUM(CASE WHEN outcome = 'escalated' THEN 1 ELSE 0 END) AS escalated,
       AVG(sentiment_score)                                AS avg_sentiment,
       AVG(csat_score)                                     AS avg_csat
FROM   adp_staging_customer_interactions.customer_interactions
WHERE  interaction_date BETWEEN DATE '2026-05-01' AND DATE '2026-05-29'
  AND  channel IN ('mobile_app_charging_issue', 'call_center', 'service_center')
GROUP BY channel
ORDER BY contacts DESC;
```

### 3.8 `service_records` (Service Records)

- **Listing**: `service_records`
- **Glue**: `adp_staging_service_records.service_records`
- **Partition**: `service_month` — long-tail monthly grain
  (literal column per the schema YAML, derived as
  `DATE_TRUNC('month', service_date)`; see
  `data-contracts.md` → "Iceberg partition conventions",
  long-tail tables row).
- **Key columns** — `service_id` (PK), `service_date`,
  `service_month` (partition), `vin` (FK → `vins`),
  `customer_id` (nullable, FK → `customers`),
  `dealer_id` (FK → `dealers`),
  `service_type` (`scheduled_maintenance|warranty_repair|safety_recall|software_recall|body_repair|tire_service|charging_system|battery_replacement|hv_battery_diagnostic|software_update`),
  `complaint_text` (PII drift-target),
  `dtc_codes` (`array<string>`), `parts_used` (`array<string>` of
  `part_number` — see "Identifier formats: part_number"),
  `labor_hours`, `total_cost_usd` (decimal(12,2)),
  `warranty_covered`, `outcome`, `csat_score`,
  `linked_interaction_id`, `linked_campaign_id`.

Sample query — top DTC codes seen on `charging_system` services in
the trailing 12 months. The `service_month` predicate is what fires
Iceberg hidden-partition pruning; the `service_date` predicate keeps
intra-month filtering precise.

```sql
SELECT dtc_code,
       COUNT(*)                  AS service_visits,
       AVG(labor_hours)          AS avg_labor_hours,
       AVG(total_cost_usd)       AS avg_cost_usd
FROM   adp_staging_service_records.service_records
CROSS JOIN UNNEST(dtc_codes) AS t(dtc_code)
WHERE  service_month >= DATE '2025-05-01'
  AND  service_type  = 'charging_system'
  AND  service_date >= DATE '2025-05-29'
GROUP BY dtc_code
ORDER BY service_visits DESC
LIMIT 20;
```

### 3.9 `vehicle_knowledge_base` (Vehicle Knowledge Base — Bedrock KB)

- **Listing**: `vehicle_knowledge_base`
- **Storage**: NOT Iceberg. Document chunks materialized to
  `s3://adp-staging-foundation-lake-<account>-us-east-1/knowledge/vehicle_knowledge_base/`
  with a `manifest.json` describing every chunk.
- **Schema fields** (per `vehicle_knowledge_base/schema.yaml`,
  `storage_format: documents`): `chunk_id` (UUIDv5),
  `source_doc_id`, `source_category`
  (`dtc_guide|tsb_recall|owner_manual|parts_catalog|service_network|service_policy|charging_narrative|ota_rollout_summary`),
  `title`, `chunk_index`, `chunk_text`, `chunk_size_tokens`,
  `chunk_overlap_tokens`, `embedding_model` (default
  `amazon.titan-embed-text-v2:0`), `s3_uri`, `language`,
  `indexed_at`.
- **Subscribe pattern**: subscribe to the listing exactly the same
  way (section 3 boilerplate). LF grants give the consumer
  `s3:GetObject` against the `knowledge/vehicle_knowledge_base/`
  prefix; CVX then either (a) reads the manifest and embeds itself,
  or (b) points a Bedrock KB at the same prefix as a data source —
  see section 5.

For chunk introspection (rare; usually CVX retrieves through the KB)
you can register the manifest as an Athena table on top of the JSON:

```sql
-- Optional: surface the chunk manifest for inspection (not required for retrieval).
SELECT source_category,
       COUNT(*)                       AS chunks,
       APPROX_PERCENTILE(chunk_size_tokens, 0.50) AS p50_tokens,
       MAX(indexed_at)                AS most_recent_indexed_at
FROM   adp_staging_vehicle_knowledge_base.vehicle_knowledge_base_manifest
GROUP BY source_category
ORDER BY chunks DESC;
```

> The `vehicle_knowledge_base_manifest` table is registered by the
> Group 5 / Bedrock-KB-seeding-extensions task; pre-Group-5 the
> manifest is on S3 at `knowledge/vehicle_knowledge_base/manifest.json`
> and CVX reads it directly via `aws s3 cp`.

---

## 4. Cross-product join examples

These four queries answer realistic EV-startup questions by joining
across products. Every column reference cites
`docs/data-contracts.md` either explicitly above or by virtue of
being one of the canonical FK/identifier columns
(`vin`, `customer_id`, `dealer_id`, `station_id`, `campaign_id` —
see [`data-contracts.md` → "Identifier formats"](data-contracts.md#identifier-formats)).

### 4.1 `customer × charging × energy` — "Why is this customer's charging cost high?"

Joins `customer_360` × `charging_sessions` × `energy_usage` to
diagnose a high-LTV customer whose charging spend looks anomalous.
The query attributes their 30-day charging cost to network mix
(home L2 vs public DC fast) and surfaces their efficiency
(kWh/100mi) for the same window — efficiency that's worse than
fleet average usually correlates with cold-weather range loss
(seasonality), see `data-contracts.md` → "VSS vocabulary subset"
row 32 (`ambient_temp_avg_c`).

```sql
WITH window_dates AS (
  SELECT DATE '2026-05-29' - INTERVAL '30' DAY AS lo,
         DATE '2026-05-29'                    AS hi
),
target_cust AS (
  SELECT c.customer_id, c.primary_vin, c.lifetime_value_usd,
         c.total_charging_sessions_30d, c.total_kwh_consumed_30d
  FROM   adp_staging_customer_360.customer_360 c
  JOIN   (SELECT MAX(snapshot_date) AS d FROM adp_staging_customer_360.customer_360) ls
         ON c.snapshot_date = ls.d
  WHERE  c.customer_id = 'CUST-3F2504E0'    -- example
),
chg AS (
  SELECT cs.customer_id,
         cs.station_type,
         COUNT(*)               AS sessions,
         SUM(cs.kwh_delivered)  AS kwh,
         SUM(cs.cost_usd)       AS spend_usd
  FROM   adp_staging_charging_sessions.charging_sessions cs
  JOIN   window_dates w ON cs.session_date BETWEEN w.lo AND w.hi
  WHERE  cs.customer_id = 'CUST-3F2504E0'
  GROUP BY cs.customer_id, cs.station_type
),
eu AS (
  SELECT eu.vin,
         AVG(eu.efficiency_kwh_per_100mi) AS avg_eff,
         AVG(eu.ambient_temp_avg_c)       AS avg_ambient_c,
         SUM(eu.total_kwh_consumed)       AS kwh_consumed,
         SUM(eu.total_miles_driven)       AS miles
  FROM   adp_staging_energy_usage.energy_usage eu
  JOIN   window_dates w ON eu.usage_date BETWEEN w.lo AND w.hi
  WHERE  eu.vin = (SELECT primary_vin FROM target_cust)
  GROUP BY eu.vin
)
SELECT tc.customer_id,
       tc.lifetime_value_usd,
       tc.total_kwh_consumed_30d,
       chg.station_type,
       chg.sessions,
       chg.kwh                  AS chg_kwh,
       chg.spend_usd            AS chg_spend_usd,
       eu.avg_eff               AS efficiency_kwh_per_100mi,
       eu.avg_ambient_c         AS avg_ambient_c
FROM   target_cust tc
LEFT JOIN chg ON tc.customer_id = chg.customer_id
LEFT JOIN eu  ON tc.primary_vin  = eu.vin
ORDER BY chg_spend_usd DESC NULLS LAST;
```

### 4.2 `VIN × OTA × energy` — "Did the last OTA improve efficiency?"

Joins `ota_campaign_events` × `energy_usage` × `vehicle_identity`
to compare fleet efficiency for the 14 days before vs the 14 days
after a campaign installed for each VIN. Per
`docs/data-contracts.md` → "Time and date conventions",
`install_completed_time` is UTC-microsecond, so the windowing
arithmetic is straightforward.

```sql
WITH target_camp AS (
  SELECT campaign_id, campaign_name, dispatch_start_date
  FROM   adp_staging_ota_campaigns.ota_campaigns
  WHERE  campaign_name = 'Battery Management v3.4'  -- example
  LIMIT  1
),
installed AS (
  SELECT e.vin,
         CAST(e.install_completed_time AS DATE) AS install_date
  FROM   adp_staging_ota_campaigns.ota_campaign_events e
  JOIN   target_camp t ON t.campaign_id = e.campaign_id
  WHERE  e.dispatch_date >= t.dispatch_start_date          -- partition prune on events
    AND  e.final_status = 'installed'
    AND  e.install_completed_time IS NOT NULL
),
pre AS (
  SELECT i.vin,
         AVG(eu.efficiency_kwh_per_100mi) AS pre_eff
  FROM   installed i
  JOIN   adp_staging_energy_usage.energy_usage eu
         ON  eu.vin = i.vin
         AND eu.usage_date BETWEEN i.install_date - INTERVAL '14' DAY
                              AND i.install_date - INTERVAL '1'  DAY
  GROUP BY i.vin
),
post AS (
  SELECT i.vin,
         AVG(eu.efficiency_kwh_per_100mi) AS post_eff
  FROM   installed i
  JOIN   adp_staging_energy_usage.energy_usage eu
         ON  eu.vin = i.vin
         AND eu.usage_date BETWEEN i.install_date + INTERVAL '1'  DAY
                              AND i.install_date + INTERVAL '14' DAY
  GROUP BY i.vin
)
SELECT vi.powertrain_type,
       vi.battery_chemistry,
       COUNT(DISTINCT pre.vin)                                  AS vins,
       AVG(pre.pre_eff)                                         AS avg_pre_eff,
       AVG(post.post_eff)                                       AS avg_post_eff,
       AVG(post.post_eff) - AVG(pre.pre_eff)                    AS delta_eff,
       100.0 * (AVG(post.post_eff) - AVG(pre.pre_eff)) / AVG(pre.pre_eff)
                                                                AS pct_change
FROM   pre
JOIN   post                              ON pre.vin = post.vin
JOIN   adp_staging_vehicle_identity.vehicle_identity vi ON vi.vin = pre.vin
GROUP BY vi.powertrain_type, vi.battery_chemistry
ORDER BY pct_change ASC;  -- most-improved first (lower kWh/100mi == better)
```

### 4.3 `customer × service × charging` — "Did this customer have charging-issue service visits?"

Joins `customer_360` × `service_records` × `charging_sessions` to
test the hypothesis that a customer who reports recurrent charging
trouble through the call center also has elevated rates of
charging-system service visits AND aborted public DC-fast sessions.
`charging_system` is one of the schema-level enum values for
`service_type`; `interrupted = true` is the abort signal on
`charging_sessions`.

```sql
WITH latest AS (
  SELECT MAX(snapshot_date) AS d FROM adp_staging_customer_360.customer_360
),
top_charging_complainers AS (
  SELECT c.customer_id, c.full_name, c.primary_vin
  FROM   adp_staging_customer_360.customer_360 c
  JOIN   latest ls ON c.snapshot_date = ls.d
  JOIN   adp_staging_customer_interactions.customer_interactions ci
         ON  ci.customer_id = c.customer_id
         AND ci.channel IN ('mobile_app_charging_issue', 'call_center')
         AND ci.interaction_date >= DATE '2026-02-28'
  GROUP BY c.customer_id, c.full_name, c.primary_vin
  HAVING COUNT(*) >= 3            -- customers with ≥3 charging-themed contacts in 90d
),
svc AS (
  SELECT t.customer_id,
         COUNT(*) AS charging_system_visits,
         SUM(CASE WHEN s.linked_campaign_id IS NOT NULL THEN 1 ELSE 0 END)
                  AS visits_linked_to_recall
  FROM   top_charging_complainers t
  JOIN   adp_staging_service_records.service_records s
         ON  s.customer_id = t.customer_id
         AND s.service_month >= DATE '2026-02-01'   -- partition prune
         AND s.service_type IN ('charging_system', 'hv_battery_diagnostic')
         AND s.service_date >= DATE '2026-02-28'
  GROUP BY t.customer_id
),
chg AS (
  SELECT t.customer_id,
         COUNT(*)                                              AS sessions,
         SUM(CASE WHEN cs.interrupted THEN 1 ELSE 0 END)       AS aborted,
         AVG(cs.kwh_delivered)                                 AS avg_kwh
  FROM   top_charging_complainers t
  JOIN   adp_staging_charging_sessions.charging_sessions cs
         ON  cs.customer_id = t.customer_id
         AND cs.session_date >= DATE '2026-02-28'
  GROUP BY t.customer_id
)
SELECT t.customer_id,
       t.full_name,
       t.primary_vin,
       COALESCE(svc.charging_system_visits, 0)        AS charging_system_visits,
       COALESCE(svc.visits_linked_to_recall, 0)       AS visits_linked_to_recall,
       chg.sessions,
       chg.aborted,
       100.0 * chg.aborted / NULLIF(chg.sessions, 0)  AS abort_rate_pct
FROM   top_charging_complainers t
LEFT JOIN svc ON svc.customer_id = t.customer_id
LEFT JOIN chg ON chg.customer_id = t.customer_id
ORDER BY abort_rate_pct DESC NULLS LAST, charging_system_visits DESC;
```

### 4.4 `vin_full_360` — Everything we know about a VIN, in one query

Joins all 8 Iceberg products on a single VIN. Useful for triage,
escalation, or grounding a Bedrock agent with up-to-the-minute
context. Every join column is one of the canonical identifiers from
[`data-contracts.md` → "Identifier formats"](data-contracts.md#identifier-formats).

```sql
WITH target AS (SELECT 'MRDN0008000000013' AS vin),  -- example synthetic VIN
identity AS (
  SELECT vi.* FROM adp_staging_vehicle_identity.vehicle_identity vi
  JOIN target t ON vi.vin = t.vin
),
recent_telem AS (
  SELECT MAX(event_time)              AS last_event_time,
         AVG(state_of_health_pct)     AS avg_soh_pct,
         AVG(battery_pack_temp_avg_c) AS avg_pack_temp_c
  FROM   adp_staging_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated v
  JOIN   target t ON v.vin = t.vin
  WHERE  v.event_date >= DATE '2026-05-15'                 -- partition prune
    AND  v.event_time >= TIMESTAMP '2026-05-15 00:00:00'
),
recent_energy AS (
  SELECT MAX(usage_date)               AS last_usage_date,
         SUM(total_kwh_consumed)       AS kwh_consumed_30d,
         AVG(efficiency_kwh_per_100mi) AS avg_eff_kwh_per_100mi
  FROM   adp_staging_energy_usage.energy_usage eu
  JOIN   target t ON eu.vin = t.vin
  WHERE  eu.usage_date >= DATE '2026-04-29'
),
recent_charging AS (
  SELECT COUNT(*)             AS sessions_30d,
         SUM(kwh_delivered)   AS kwh_delivered_30d,
         SUM(cost_usd)        AS spend_30d
  FROM   adp_staging_charging_sessions.charging_sessions cs
  JOIN   target t ON cs.vin = t.vin
  WHERE  cs.session_date >= DATE '2026-04-29'
),
recent_service AS (
  SELECT MAX(service_date) AS last_service_date,
         COUNT(*)          AS service_visits_12mo
  FROM   adp_staging_service_records.service_records sr
  JOIN   target t ON sr.vin = t.vin
  WHERE  sr.service_month >= DATE '2025-05-01'             -- partition prune
    AND  sr.service_date  >= DATE '2025-05-29'
),
recent_ota AS (
  SELECT MAX(install_completed_time) AS last_install,
         COUNT(*)                    AS ota_events_lifetime,
         SUM(CASE WHEN final_status = 'install_failed' THEN 1 ELSE 0 END) AS install_failures
  FROM   adp_staging_ota_campaigns.ota_campaign_events e
  JOIN   target t ON e.vin = t.vin
),
owner AS (
  SELECT c.customer_id, c.full_name, c.lifetime_value_usd, c.churn_probability
  FROM   adp_staging_customer_360.customer_360 c
  JOIN   target t ON c.primary_vin = t.vin
  JOIN   (SELECT MAX(snapshot_date) AS d FROM adp_staging_customer_360.customer_360) ls
         ON c.snapshot_date = ls.d
)
SELECT i.vin, i.make, i.model, i.model_year, i.powertrain_type, i.battery_chemistry,
       i.battery_pack_kwh, i.range_epa_mi, i.current_software_version,
       o.customer_id, o.full_name, o.lifetime_value_usd, o.churn_probability,
       rt.last_event_time, rt.avg_soh_pct, rt.avg_pack_temp_c,
       re.last_usage_date, re.kwh_consumed_30d, re.avg_eff_kwh_per_100mi,
       rc.sessions_30d, rc.kwh_delivered_30d, rc.spend_30d,
       rs.last_service_date, rs.service_visits_12mo,
       ro.last_install, ro.ota_events_lifetime, ro.install_failures
FROM   identity      i
LEFT JOIN owner          o  ON o.customer_id   IS NOT NULL
LEFT JOIN recent_telem   rt ON true
LEFT JOIN recent_energy  re ON true
LEFT JOIN recent_charging rc ON true
LEFT JOIN recent_service rs ON true
LEFT JOIN recent_ota     ro ON true;
```

---

## 5. Bedrock Knowledge Base seeding pattern (`vehicle_knowledge_base`)

CVX uses `vehicle_knowledge_base` as a Bedrock-KB grounding source.
The pattern below assumes CVX already has its own Bedrock KB (or
will create one) and points it at the ADP-published S3 prefix as a
data source.

### 5.1 Source-of-truth artifacts

The `vehicle_knowledge_base` generator
(`platform-foundation/source/data-products/vehicle_knowledge_base/generator.py`)
materializes:

```
s3://adp-staging-foundation-lake-<account>-us-east-1/knowledge/vehicle_knowledge_base/
├── manifest.json                      # one record per chunk; columns match schema YAML
└── sources/
    ├── dtc_guide/<doc>.md             # source_category = dtc_guide
    ├── tsb_recall/<doc>.md            #                  tsb_recall
    ├── owner_manual/<doc>.md          #                  owner_manual
    ├── parts_catalog/<doc>.md         #                  parts_catalog
    ├── service_network/<doc>.md       #                  service_network
    ├── service_policy/<doc>.md        #                  service_policy
    ├── charging_narrative/<doc>.md    #                  charging_narrative
    └── ota_rollout_summary/<doc>.md   #                  ota_rollout_summary
```

Schema fields per chunk (verbatim from
`vehicle_knowledge_base/schema.yaml`, `storage_format: documents`):
`chunk_id`, `source_doc_id`, `source_category` (8-value enum above),
`title`, `chunk_index`, `chunk_text`, `chunk_size_tokens`,
`chunk_overlap_tokens`, `embedding_model` (default
`amazon.titan-embed-text-v2:0` per
[`docs/tech.md` → "Bedrock Knowledge Base — ingestion"](tech.md#bedrock-knowledge-base--ingestion)),
`s3_uri`, `language` (`en`), `indexed_at` (UTC microsecond — see
[`data-contracts.md` → "Time and date conventions"](data-contracts.md#time-and-date-conventions)).

### 5.2 CVX-side seed pattern (boto3)

CVX creates a Bedrock KB whose S3 data source points at the ADP
prefix it subscribed to. The KB owns its own embedding model
invocation role; CVX never invokes the embedding model directly.

```python
import boto3, time, uuid

bra = boto3.client("bedrock-agent", region_name="us-east-1")

# 1) Create the data source, pointing at the ADP-published prefix.
ds = bra.create_data_source(
    knowledgeBaseId=cvx_kb_id,                 # CVX's pre-created KB
    name="adp-vehicle-knowledge-base",
    dataSourceConfiguration={
        "type": "S3",
        "s3Configuration": {
            "bucketArn": "arn:aws:s3:::adp-staging-foundation-lake-<adp-account>-us-east-1",
            "inclusionPrefixes": ["knowledge/vehicle_knowledge_base/sources/"],
        },
    },
    vectorIngestionConfiguration={
        # Match the chunk_size_tokens / chunk_overlap_tokens we emit so
        # the KB doesn't re-chunk our pre-chunked artifacts.
        "chunkingConfiguration": {
            "chunkingStrategy": "FIXED_SIZE",
            "fixedSizeChunkingConfiguration": {
                "maxTokens": 512,           # matches generator default
                "overlapPercentage": 10,    # ≈50 tokens of 512
            }
        }
    },
    clientToken=str(uuid.uuid4()),
)
ds_id = ds["dataSource"]["dataSourceId"]

# 2) Trigger ingestion (async, returns 202 immediately).
job = bra.start_ingestion_job(
    knowledgeBaseId=cvx_kb_id,
    dataSourceId=ds_id,
    description="ADP vehicle_knowledge_base v1 seed",
    clientToken=str(uuid.uuid4()),         # MUST be unique per re-ingest
)
job_id = job["ingestionJob"]["ingestionJobId"]

# 3) Poll for completion (per docs/tech.md "Bedrock Knowledge Base — ingestion").
while True:
    j = bra.get_ingestion_job(
        knowledgeBaseId=cvx_kb_id, dataSourceId=ds_id, ingestionJobId=job_id
    )["ingestionJob"]
    if j["status"] in ("COMPLETE", "FAILED"):
        break
    time.sleep(30)
assert j["status"] == "COMPLETE", j
```

**IAM** — the CVX KB's data-source role needs `s3:ListBucket` and
`s3:GetObject` on the ADP prefix; ADP grants these via the
DataZone subscription's LF grant (no direct bucket policy edit
required). Per `docs/tech.md` → "Bedrock Knowledge Base —
ingestion" the job will fail silently with `AccessDenied` in the
job summary if the role lacks list/get on the prefix — check the
job summary before declaring success.

### 5.3 Retrieval (CVX agent path)

```python
brar = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
resp = brar.retrieve(
    knowledgeBaseId=cvx_kb_id,
    retrievalQuery={"text": "Common charging issues with NACS connector at home L2"},
    retrievalConfiguration={
        "vectorSearchConfiguration": {
            "numberOfResults": 5,
            "filter": {
                "equals": {
                    "key": "source_category",
                    "value": "charging_narrative"
                }
            }
        }
    }
)
for hit in resp["retrievalResults"]:
    print(hit["score"], hit["location"]["s3Location"]["uri"])
```

Filtering on `source_category` lets CVX scope retrieval (e.g.,
`dtc_guide` for diagnostic flows, `service_network` for dealer
locator, `charging_narrative` for charging troubleshooting). The
filterable metadata is automatically lifted from the manifest by the
ingestion job — no custom metadata-extraction Lambda required.

### 5.4 Re-ingest cadence

Re-ingest after every ADP data drop. The generator updates
`indexed_at` on every emit; CVX can decide whether to re-ingest by
comparing `MAX(indexed_at)` from the manifest with the previous
ingestion-job timestamp. A daily cron is sufficient for v1 — KB
updates are not real-time-critical.

---

## 6. Lineage trace — Athena / Iceberg metadata

ADP writes Iceberg-on-Glue tables with full snapshot history. Every
write is a new snapshot; Athena Engine V3 exposes Iceberg metadata
tables (`$snapshots`, `$history`, `$files`, `$partitions`,
`$manifests`) for consumer-side lineage tracing without going
through DataZone's lineage UI. Use these when CVX needs to answer
"which generator run produced the row I'm looking at?"

### 6.1 Snapshot history of `energy_usage`

```sql
SELECT snapshot_id,
       parent_id,
       committed_at,
       operation,
       summary['added-records']    AS added_records,
       summary['deleted-records']  AS deleted_records,
       summary['total-records']    AS total_records
FROM   adp_staging_energy_usage."energy_usage$snapshots"
ORDER BY committed_at DESC
LIMIT 20;
```

`operation` takes values `append`, `overwrite`, `delete`, `replace`.
The dimension-then-fact pipeline (see spec → "Architecture topology")
appends per regenerate; an `overwrite` indicates a `make seed`
re-run.

### 6.2 Files contributing to a partition (lineage to S3 object)

```sql
SELECT file_path,
       file_format,
       record_count,
       file_size_in_bytes,
       partition,
       column_sizes
FROM   adp_staging_charging_sessions."charging_sessions$files"
WHERE  CAST(partition AS JSON) LIKE '%2026-05-01%'
ORDER BY file_path
LIMIT 50;
```

`file_path` is the S3 URI of the parquet file. CVX can fetch the
file directly (with LF-issued credentials) for byte-level
auditing or lineage replay.

### 6.3 Cross-product event-time lineage — "who wrote what, when?"

This pattern joins `$snapshots` for the products in a question
against the user-visible `event_time` / `ingest_time` contract
declared in
[`data-contracts.md` → "Time and date conventions"](data-contracts.md#time-and-date-conventions).
It answers "for VIN X, what's the most-recent snapshot in each
product I have visibility into, and how stale is each?"

```sql
WITH target AS (SELECT 'MRDN0008000000013' AS vin),
v_snap AS (
  SELECT 'vehicle_telemetry_aggregated' AS product, MAX(committed_at) AS last_committed_at
  FROM   adp_staging_vehicle_telemetry_aggregated."vehicle_telemetry_aggregated$snapshots"
),
e_snap AS (
  SELECT 'energy_usage' AS product, MAX(committed_at) AS last_committed_at
  FROM   adp_staging_energy_usage."energy_usage$snapshots"
),
c_snap AS (
  SELECT 'charging_sessions' AS product, MAX(committed_at) AS last_committed_at
  FROM   adp_staging_charging_sessions."charging_sessions$snapshots"
),
o_snap AS (
  SELECT 'ota_campaign_events' AS product, MAX(committed_at) AS last_committed_at
  FROM   adp_staging_ota_campaigns."ota_campaign_events$snapshots"
),
last_event_per_product AS (
  SELECT 'vehicle_telemetry_aggregated' AS product,
         MAX(event_time) AS max_event_time, MAX(ingest_time) AS max_ingest_time
  FROM   adp_staging_vehicle_telemetry_aggregated.vehicle_telemetry_aggregated v
  JOIN   target t ON v.vin = t.vin
  UNION ALL
  SELECT 'energy_usage',
         MAX(event_time), MAX(ingest_time)
  FROM   adp_staging_energy_usage.energy_usage eu
  JOIN   target t ON eu.vin = t.vin
  UNION ALL
  SELECT 'charging_sessions',
         MAX(event_time), MAX(ingest_time)
  FROM   adp_staging_charging_sessions.charging_sessions cs
  JOIN   target t ON cs.vin = t.vin
  UNION ALL
  SELECT 'ota_campaign_events',
         MAX(event_time), MAX(ingest_time)
  FROM   adp_staging_ota_campaigns.ota_campaign_events e
  JOIN   target t ON e.vin = t.vin
),
snaps AS (
  SELECT * FROM v_snap UNION ALL
  SELECT * FROM e_snap UNION ALL
  SELECT * FROM c_snap UNION ALL
  SELECT * FROM o_snap
)
SELECT le.product,
       le.max_event_time,
       le.max_ingest_time,
       s.last_committed_at,
       DATE_DIFF('hour', le.max_event_time,  CURRENT_TIMESTAMP) AS event_age_hours,
       DATE_DIFF('hour', le.max_ingest_time, CURRENT_TIMESTAMP) AS ingest_age_hours,
       DATE_DIFF('minute', le.max_ingest_time, le.max_event_time) AS ingest_minus_event_minutes
FROM   last_event_per_product le
JOIN   snaps s ON s.product = le.product
ORDER BY ingest_age_hours DESC;
```

The `ingest_minus_event_minutes` column corresponds to the
`(ingest_time - event_time)` definition in `data-contracts.md` and
flags `late_arrival` cases (>1 day) where a row's source-truth
event time is older than the ingest time would suggest.

### 6.4 DataZone lineage events (when the V2 lineage API is enabled)

DataZone V2 emits lineage events for every catalog-asset publish and
subscription grant. Consumers use the V2 lineage API (out of band of
SQL) to traverse asset → asset relationships:

```python
# Reads back to DataZone control plane; not Athena. Included here for
# completeness of the lineage story.
import boto3
dz = boto3.client("datazone", region_name="us-east-1")
# Resolve the listing for a target product, then walk lineage.
listing = dz.search_listings(
    domainIdentifier=domain_id, searchText="charging_sessions"
)["items"][0]["assetListing"]
# DataZone V2 lineage relationship types: HAS_TYPE, IS_INSTANCE_OF, ...
# Per the V2 API, lineage queries are scoped per asset.
```

For v1, ADP relies primarily on Iceberg metadata tables (`$snapshots`
etc.) plus the per-product `manifest.json` written by each generator
under `s3://.../curated/<product>/_manifest.json` — that manifest
records the deterministic seed, the dimension catalog version, and
the generator commit hash. Together they trace any row back to its
source generator run.

---

## 7. Verification

This document's verify command (per `tasks.md` Group 4 task "CVX
integration contract"):

```bash
grep -c '```sql' docs/cvx-integration-contract.md   # expect ≥ 12
```

Each sample SQL block above is meant to run unmodified against the
deployed staging foundation once Group 3 generators have produced
data; Group 6 task "Run all sample queries from the integration
contract" provides the script that exercises every block end-to-end.

### Cross-references

- [`docs/data-contracts.md`](data-contracts.md) — VSS subset,
  identifier formats, time/date conventions, partition conventions,
  drift-detection test design. **Authoritative for every column /
  identifier reference in this document.**
- [`docs/tech.md`](tech.md) — DataZone V2, Glue Iceberg
  `create_table`, Athena Engine V3 DDL, Lake Formation tag-based
  access control, Bedrock KB ingestion, Firehose dynamic partitioning,
  VSS v6.0. **Authoritative for SDK / API contracts referenced by
  this document.**
- [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) — stage rollout, naming
  summary, migration runbook. **Authoritative for the
  `adp-{stage}-foundation-*` and `adp_{stage}_<product>` naming
  used throughout this document.**
- `platform-foundation/source/data-products/<product>/schema.yaml`
  — per-product column declarations, PII tags, partition keys,
  foreign keys. **Authoritative for any column attribute not
  explicitly cited from `data-contracts.md`.**
- `platform-foundation/scripts/smoke-test-subscription.sh` —
  reference implementation of the subscribe-and-query flow used in
  section 3.


---

## Cross-account grants for CVX

Producer-side enabling work shipped 2026-06-09 via spec
`automotive-data-platform-on-aws/.kiro/specs/2026-06-09-adp-kb-cross-account-grants/`.

This section documents the parameter contract that CVX-on-foundation v1
deploys against. Phase A spike outputs (CDK class names, LF cross-account
version, KB ARN attribute paths, audit trail of grant decisions) live in
`.kiro/specs/2026-06-09-adp-kb-cross-account-grants/decisions.md`.

### What it grants

Two pipes open when ADP is deployed with cross-account on:

1. **Bedrock KB pipe** — CVX agents can call
   `bedrock-agent-runtime:Retrieve` and
   `bedrock-agent-runtime:RetrieveAndGenerate` against the ADP
   `adp-{stage}-vehicle-knowledge` KB. Retrieves DTC manuals, TSBs,
   owner manuals, service policies (the 4 data-source prefixes).
2. **Lake Formation table pipe** — CVX account principal gets
   `SELECT` + `DESCRIBE` (no `WITH GRANT OPTION`) on every table in
   each database holding an in-scope curated table. Per-database
   wildcard share (`name=ALL_TABLES`) — see "Wildcard semantics" below.

### Parameters

ADP CDK accepts two cross-account parameters via CDK context OR env var.
Both are optional; absence disables the cross-account pipes (single-account
default; behavior identical to pre-2026-06-09 deploys).

| Parameter | CDK context | Env var | Format | Effect when absent |
|---|---|---|---|---|
| CVX KB principals | `cvxKbPrincipals` | `ADP_KB_CVX_PRINCIPAL_ARNS` | comma-separated IAM role ARNs | KB resource policy not attached |
| CVX account ID | `cvxAccountId` | `ADP_KB_CVX_ACCOUNT_ID` | 12-digit AWS account ID | LF bootstrap + share not synthesized |

### Deploy with cross-account on

**Step 0 (manual prerequisite — one-time per account):** Lake Formation
settings are an account-singleton (one `DataLakeSettings` per
account-region). CDK does NOT manage them in this spec — `PutDataLakeSettings`
REPLACES the entire settings object (it does not append), and per-stack
CDK ownership would silently drop existing admins on deploy. Set them
out-of-band before first `cdk deploy` of either sub-project with
cross-account on:

```bash
# Read existing admins so we don't drop them.
EXISTING=$(aws lakeformation get-data-lake-settings --region us-east-1 \
  --query 'DataLakeSettings.DataLakeAdmins' --output json)

# Compose updated settings: existing admins + AllowExternalDataFiltering=true
# + CROSS_ACCOUNT_VERSION=4. Add new admins here if needed.
aws lakeformation put-data-lake-settings --region us-east-1 \
  --data-lake-settings "$(jq -n \
    --argjson admins "$EXISTING" \
    '{
       DataLakeAdmins: $admins,
       AllowExternalDataFiltering: true,
       Parameters: {"CROSS_ACCOUNT_VERSION": "4"}
     }')"
```

Verify: `aws lakeformation get-data-lake-settings --region us-east-1`
should show `AllowExternalDataFiltering: true` and
`Parameters.CROSS_ACCOUNT_VERSION: "4"`. Existing `DataLakeAdmins` are
preserved.

**Step 1 — deploy platform-foundation (includes the KB construct):**

```bash
cd platform-foundation
.venv/bin/cdk deploy \
  -c stage=staging \
  -c cvxAccountId=<cvx-account>
```

**Step 2 — deploy the vehicle-knowledge-base stack with the CVX principals:**

As of 2026-06-18 (spec `2026-06-16-adp-vehicle-knowledge-base`), the
Bedrock KB construct lives **inside `platform-foundation`** as the
per-stage stack `adp-{stage}-foundation-vehicle-knowledge-base` — the
standalone `guidance-for-vehicle-knowledge-base/` directory was deleted.
The KB resource policy attaches when `cvxKbPrincipals` is supplied:

```bash
cd platform-foundation
.venv/bin/cdk deploy adp-staging-foundation-vehicle-knowledge-base \
  -c stage=staging \
  -c adpKbDeployRoleArn=<deploy-role-arn> \
  -c cvxKbPrincipals=arn:aws:iam::<cvx-account>:role/cvx-staging-supervisor-role,arn:aws:iam::<cvx-account>:role/cvx-staging-driver-role
```

Both stacks live in the same CDK app, so a single `make deploy
STAGE=staging` (which includes `adp-staging-foundation-vehicle-knowledge-base`
in its `--exclusively` list) deploys everything; the explicit
single-stack form above is for re-applying the KB resource policy after a
CVX principal-ARN change without redeploying the rest of the foundation.

Order matters: the LF bootstrap + cross-account share (in the
`governance` stack, gated on `cvxAccountId`) must precede the KB resource
policy attach. Within a single `make deploy` run, the
`vehicle_kb.add_dependency(lake)` edge plus CFN's natural ordering
handle this; for split deploys, run the `governance`-bearing deploy
first.

### What synthesizes when cross-account is on

`platform-foundation` adds:
- 1× `AWS::LakeFormation::Resource` — registers
  `s3://adp-staging-foundation-lake-{account}-{region}` as an LF resource.
- (`AWS::LakeFormation::DataLakeSettings` is INTENTIONALLY NOT
  synthesized — it's a manual prerequisite per Step 0 above.)
- 6× `AWS::LakeFormation::PrincipalPermissions` — one per in-scope
  database (vehicle_identity, service_records, charging_sessions,
  customer_360, customer_interactions, ota_campaigns), wildcard table
  share to `arn:aws:iam::{cvxAccountId}:root` with
  `permissions=[SELECT, DESCRIBE]` and empty
  `permissions_with_grant_option`.
- CloudTrail trail extended with advanced event selector for
  `AWS::Bedrock::KnowledgeBase` resources scoped to ADP-account KB ARNs.

The `adp-{stage}-foundation-vehicle-knowledge-base` stack adds:
- 1× `AWS::Bedrock::ResourcePolicy` — attached to the
  `adp-{stage}-vehicle-knowledge` KB, allowing the listed CVX
  principals to invoke `Retrieve` and `RetrieveAndGenerate`.

### Wildcard semantics — what's actually shared

**Per-database wildcard, not per-table whitelist.** When CVX account
gets the share on `adp_staging_charging_sessions`, they can SELECT/DESCRIBE
**every** table in that database — not just the named one.

In ADP today, each in-scope database holds exactly one table (the
foundation-shipped naming convention is one-database-per-data-product),
so the practical effect is one-table-per-database. But future tables
added to the same database (e.g., a `charging_sessions_aggregated`
follow-on) would be implicitly shared without an explicit grant change.

Two consequences:

1. **PySpark-gated tables (`vehicle_telemetry_aggregated`, `energy_usage`)
   live in their own databases**, currently empty (no Glue tables
   registered until `PySpark via Glue` ships). They are NOT in the
   in-scope database list above; CVX does not see them today. When
   `PySpark via Glue` registers tables in those databases, governance
   choice is required: extend in-scope list (CVX gets read), or leave
   absent (CVX does not).
2. **CVX cannot re-share** to other accounts — `permissions_with_grant_option`
   is empty.

### Audit posture

CloudTrail data events on `AWS::Bedrock::KnowledgeBase` capture every
cross-account `Retrieve` / `RetrieveAndGenerate` call against the ADP
KB. Standard CloudTrail event delivery (S3 + CloudTrail Lake if
configured). LF data-event coverage is via existing data-lake-level
LF audit logs.

### What's NOT included in this contract

- **CVX-side wiring** — agent IAM role definitions, Bedrock client
  config, persona-grounding tool implementations. Owned by
  `CVX-on-foundation v1` PRD
  (`~/.kiro/portfolio/initiatives/2026-06-08-cvx-on-foundation-v1/prd.md`).
- **Cross-region grants** — ADP cross-account shares are scoped to
  `us-east-1`. CVX must consume from `us-east-1`.
- **Resource link creation** — CVX side must create LF resource links
  in their own catalog after accepting the AWS RAM share invitation.
  Not driven from ADP.
- **PySpark-gated tables** — see "Wildcard semantics" above.


---

## Cross-account grants for DMS

Producer-side enabling work shipped via spec
`automotive-data-platform-on-aws/.kiro/specs/2026-08-26-adp-dealer-domain/`
(Groups 2 + 6). This section mirrors the CVX contract above for the
DMS-accelerator consumer.

Additive to the CVX section: the same producer stacks host both pipes,
extended (not duplicated) to cover the DMS principal(s). The KB resource
policy is a single `Statement` with a combined `Principal.AWS` array
holding both CVX and DMS principals — one policy, two consumers.

### What it grants

Two pipes open when ADP is deployed with the DMS-side flags on:

1. **Bedrock KB pipe** — DMS agents can call
   `bedrock-agent-runtime:Retrieve` and
   `bedrock-agent-runtime:RetrieveAndGenerate` against the ADP
   `adp-{stage}-vehicle-knowledge` KB. This is the same KB the CVX
   consumer sees; DMS gets it via the same resource policy.
   Consumers filter by `source_category` at query time — DMS
   agents use `dealer_bulletin`, `warranty_policy`, and
   `parts_catalog` (the two new categories shipped by Group 4 plus
   the R2d-superseded corpus shipped by Group 5).
2. **Lake Formation table pipe** — DMS account principal gets
   `SELECT` + `DESCRIBE` (no `WITH GRANT OPTION`) on every table in
   `adp_{stage}_dealer_domain` and `adp_{stage}_parts_domain`.
   Per-database wildcard share (`table_wildcard={}`) — CVX's
   six databases are **not** included; DMS's two are **not**
   included on the CVX principal. The two consumers see disjoint
   database sets.

### Parameters

ADP CDK accepts two DMS-side cross-account parameters via CDK context
OR env var. Both are optional; absence disables the DMS-side pipes.
CVX-side parameters (documented above) remain independent — turning
on DMS does NOT change what CVX sees.

| Parameter | CDK context | Env var | Format | Effect when absent |
|---|---|---|---|---|
| DMS KB principals | `dmsKbPrincipals` | `ADP_KB_DMS_PRINCIPAL_ARNS` | comma-separated IAM role ARNs | KB resource policy statement not extended to DMS |
| DMS account ID | `dmsAccountId` | `ADP_KB_DMS_ACCOUNT_ID` | 12-digit AWS account ID | LF share on `dealer_domain` + `parts_domain` not synthesized |

### Deploy with DMS cross-account on

**Step 0 (manual prerequisite):** Same Lake Formation
`AllowExternalDataFiltering=true` + `CROSS_ACCOUNT_VERSION=4` account
setting as the CVX section above. If CVX was already turned on in this
account+region, Step 0 is already done — no re-application needed.

**Step 1 — deploy platform-foundation with DMS flags set:**

```bash
cd platform-foundation
ADP_KB_DMS_ACCOUNT_ID=<dms-account> \
ADP_KB_DMS_PRINCIPAL_ARNS=arn:aws:iam::<dms-account>:role/dms-staging-supervisor-role \
make deploy STAGE=staging
```

The Makefile's `deploy` target passes `-c stage=<stage>` only via
`CDK_CTX`; DMS opt-in parameters flow through `os.environ`, which the
`app.py` resolvers read (`_resolve_dms_kb_principals()` +
`app.node.try_get_context("dmsAccountId") or os.environ.get("ADP_KB_DMS_ACCOUNT_ID")`).
Setting them as env vars on the same line as `make deploy` is the
sanctioned invocation.

CVX and DMS can be on simultaneously — the resolvers are independent
and the resource policy combines both principal lists into one
statement. To deploy with both consumers on:

```bash
cd platform-foundation
ADP_KB_CVX_ACCOUNT_ID=<cvx-account> \
ADP_KB_CVX_PRINCIPAL_ARNS=arn:aws:iam::<cvx-account>:role/cvx-staging-supervisor-role \
ADP_KB_DMS_ACCOUNT_ID=<dms-account> \
ADP_KB_DMS_PRINCIPAL_ARNS=arn:aws:iam::<dms-account>:role/dms-staging-supervisor-role \
make deploy STAGE=staging
```

### What synthesizes when DMS cross-account is on

`platform-foundation` adds (when `dmsAccountId` is set):
- 2× `AWS::LakeFormation::PrincipalPermissions` — one per DMS-facing
  database (`dealer_domain`, `parts_domain`), wildcard table share to
  `arn:aws:iam::{dmsAccountId}:root` with
  `permissions=[SELECT, DESCRIBE]` and empty
  `permissions_with_grant_option`.

The `adp-{stage}-foundation-vehicle-knowledge-base` stack modifies
(when `dmsKbPrincipals` is set):
- 1× `AWS::Bedrock::ResourcePolicy` — the existing single-statement
  policy's `Principal.AWS` array is extended to include the DMS
  principal ARNs alongside any CVX principals. If **only** DMS is on
  (CVX flags absent), the policy is synthesized with DMS principals
  alone. If **both** are on, one policy holds both. If **neither** is
  on, no policy is synthesized.

The single-statement design (rather than two per-consumer statements)
keeps the policy under `AWS::Bedrock::CfnResourcePolicy`'s size limits
and matches the shape verified in Group 1 SDK research (`docs/tech.md`
§ "DMS accelerator: adp_dealer_domain + adp_parts_domain").

### Wildcard semantics — what's actually shared with DMS

**Per-database wildcard, DMS-scoped to two databases.** Every table in
`adp_{stage}_dealer_domain` and `adp_{stage}_parts_domain` is shared —
current and future. In v1 these databases hold:

- `adp_{stage}_dealer_domain`: seeded via DMS-side ETL (empty at ADP
  deploy time — DMS populates on its own deploy).
- `adp_{stage}_parts_domain`: `parts_catalog`, `parts_fitment`,
  `parts_interchange` — seeded via `make seed-parts` on the ADP side.

Two consequences mirror the CVX section:

1. **Databases outside these two are NOT shared with DMS.** The
   CVX-facing six databases (`vehicle_identity`, `service_records`,
   `charging_sessions`, `customer_360`, `customer_interactions`,
   `ota_campaigns`) remain CVX-only. If DMS agents need to join a
   parts row with a service history, they do it through the DMS-side
   `customer-master` handler that reads `customer_360` via its own
   principal — governed by DMS's spec `2026-09-01-dms-customer-master-adp`,
   not this contract.
2. **DMS cannot re-share** — `permissions_with_grant_option=[]`.

### Audit posture

CloudTrail data events on `AWS::Bedrock::KnowledgeBase` (configured
in `governance_stack.py`, extended in closed spec
`2026-06-09-adp-kb-cross-account-grants`) capture every cross-account
`Retrieve` / `RetrieveAndGenerate` against the ADP KB. The extension
is source-agnostic — DMS calls are captured under the same trail as
CVX calls, distinguishable by `userIdentity.accountId`.

Lake Formation data-event coverage is via the existing data-lake-level
LF audit logs; no additional configuration is required for the DMS
share.

### What's NOT included in this contract

- **DMS-side wiring** — DMS agent IAM role definitions, Bedrock client
  config, `parts_lookup` tool implementations. Owned by DMS spec
  `2026-08-26-dms-accelerator-v1` and follow-ons.
- **Cross-region grants** — same as CVX; DMS must consume from
  `us-east-1`.
- **Resource link creation** — DMS side must create LF resource links
  in their own catalog after accepting the AWS RAM share invitation.
- **Additional DMS-side agent grants** — this contract covers the two
  DMS-supervisor-facing pipes (LF share on `dealer_domain` +
  `parts_domain`, KB retrieval on the shared VKB). Other DMS agent
  personas deferred per DMS spec § Non-goals are out of scope.
