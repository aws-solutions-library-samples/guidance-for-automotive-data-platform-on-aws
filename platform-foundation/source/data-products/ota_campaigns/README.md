# OTA Campaigns (`ota_campaigns`)

> **Domain**: EV-Operations &nbsp;·&nbsp; **Storage**: Iceberg
> (two tables) &nbsp;·&nbsp; **Display name**: `OTA Campaigns`
> &nbsp;·&nbsp; **Net-new in v1**

Software OTA campaign metadata (header) plus per-VIN dispatch /
download / install events. **A single product publishing two Iceberg
tables.** Producer is [`generator.py`](generator.py) (pandas tier);
column formats follow
[`docs/data-contracts.md`](../../../../docs/data-contracts.md).

> Distinct from CMS FleetWise data-collection campaigns —
> `ota_campaigns` is software OTA dispatch, not telematics fleet
> data-collection.

## Schema — `ota_campaigns` (header)

| Column | Type | Nullable | Description |
|---|---|---|---|
| `campaign_id` | string | no | Unique campaign identifier (PK + **partition key**) |
| `campaign_name` | string | no | Human-readable name (e.g. `Battery Management v3.4`) |
| `release_version` | string | no | Software version delivered (semver) |
| `target_make` | string | no | Target manufacturer |
| `target_model` | string | yes | Null = all models for make |
| `target_model_year_min` / `_max` | int | yes | Inclusive year range |
| `target_software_version_min` | string | yes | Minimum prior version eligible (semver) |
| `package_size_mb` | int | no | OTA package size (1–8000 MB) |
| `category` | string | no | enum: `safety_recall` / `feature_add` / `bug_fix` / `security_patch` / `performance` |
| `severity` | string | no | enum: `critical` / `high` / `medium` / `low` |
| `dispatch_start_date` | date | no | First date dispatch becomes active |
| `dispatch_end_date` | date | yes | Null = open-ended |
| `phased_rollout_pct` | array&lt;int&gt; | yes | Phased cohort percentages (e.g. `[5, 25, 50, 100]`) |
| `status` | string | no | enum: `planned` / `active` / `paused` / `completed` / `cancelled` |

## Schema — `ota_campaign_events` (per-VIN dispatch table)

| Column | Type | Nullable | Description |
|---|---|---|---|
| `campaign_id` | string | no | FK → `ota_campaigns.campaign_id` (PK part) |
| `vin` | string | no | FK → [`vins`](#lineage); regex per [data-contracts](../../../../docs/data-contracts.md#identifier-formats) (PK part) |
| `dispatch_date` | date | no | UTC calendar day. **Partition key** |
| `dispatch_time` | timestamp | no | When the campaign was dispatched to this VIN |
| `download_started_time` / `_completed_time` | timestamp | yes | Download timeline |
| `install_started_time` / `_completed_time` | timestamp | yes | Install timeline |
| `final_status` | string | no | enum: `not_yet_dispatched` / `dispatched` / `downloading` / `download_failed` / `installing` / `install_failed` / `installed` / `rolled_back` / `declined_by_user` |
| `failure_reason` | string | yes | Free-text reason on failure paths |
| `previous_software_version` / `new_software_version` | string | yes | Semver bookends |
| `event_time` | timestamp | no | Latest status-change time |
| `ingest_time` | timestamp | no | Loader write timestamp |

## Partition keys

- **Header (`ota_campaigns`)**: `campaign_id` — small table (~100 rows
  at scale 1.0); partitioning by PK keeps every row in its own
  metadata leaf for fast lookup.
- **Events (`ota_campaign_events`)**: `dispatch_date` — daily grain;
  ~30M rows / 100 campaigns at scale 1.0. Iceberg hidden-partition
  prune fires on `dispatch_date` predicates.
- **Pruning (events)**: filter on `dispatch_date` (partition) AND
  optionally on `dispatch_time` for sub-day windowing — see
  [data-contracts → Iceberg partition conventions](../../../../docs/data-contracts.md#iceberg-partition-conventions).

## Sample queries

Adoption curve for the most recent `safety_recall` campaign (time-to-
install percentiles):

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

Failure-rate per category (fleet-wide, trailing 90 days):

```sql
SELECT c.category,
       c.severity,
       COUNT(*)                                                       AS dispatched,
       SUM(CASE WHEN e.final_status = 'install_failed'  THEN 1 ELSE 0 END) AS install_failures,
       SUM(CASE WHEN e.final_status = 'download_failed' THEN 1 ELSE 0 END) AS download_failures,
       SUM(CASE WHEN e.final_status = 'rolled_back'     THEN 1 ELSE 0 END) AS rollbacks
FROM   adp_staging_ota_campaigns.ota_campaign_events e
JOIN   adp_staging_ota_campaigns.ota_campaigns       c ON c.campaign_id = e.campaign_id
WHERE  e.dispatch_date >= DATE '2026-02-28'
GROUP BY c.category, c.severity
ORDER BY install_failures DESC;
```

Pre / post efficiency-delta join (`vin_x_ota_x_energy.sql`) lives in
[`platform-foundation/source/athena-queries/`](../../athena-queries/);
adoption-decay variant in
[`docs/cvx-integration-contract.md` § 4.2](../../../../docs/cvx-integration-contract.md).

## Lineage

- **Inputs**:
  - `vins` dimension (5M, sampled with replacement for events).
  - In-process header table (deterministic seed; 100 campaigns at
    scale 1.0) cached on the generator object so events FK to
    deterministic `campaign_id` strings.
- **Producer**: [`generator.py`](generator.py) (pandas, both tables
  in declaration order; multi-table flag set on schema-loader). Runs
  from the master `make seed STAGE=...` target.
- **Consumers (cross-links via shared dimensions / FKs)**:
  - [`vehicle_identity`](../vehicle_identity/README.md) — same `vins`;
    `target_make` / `target_model` filter against
    `vehicle_identity.make` / `model`.
  - [`energy_usage`](../energy_usage/README.md) — same `vins`; the
    post-OTA efficiency drift narrative (§ Realistic narratives there)
    joins `ota_campaign_events.install_completed_time` to per-VIN
    energy windows.
  - [`vehicle_telemetry_aggregated`](../vehicle_telemetry_aggregated/README.md)
    — same `vins`; per-VIN `current_software_version` rolls forward
    after `install_completed_time`.
  - [`service_records`](../service_records/README.md) — `linked_campaign_id`
    in `service_records` references `ota_campaigns.campaign_id` for
    `service_type = 'software_recall'` rows (structural FK, not
    enforced at the schema layer).
  - [`customer_interactions`](../customer_interactions/README.md) —
    `channel = 'ota_update_notification'` rows correlate with dispatch
    activity in this product.
- **Lineage trace**: `SELECT * FROM
  adp_staging_ota_campaigns."ota_campaigns$snapshots"
  ORDER BY committed_at DESC LIMIT 5` (and `_events$snapshots`). See
  [`cvx-integration-contract.md` § 6](../../../../docs/cvx-integration-contract.md).

## Realistic narratives

Distribution choices in [`generator.py`](generator.py) follow real
EV-fleet OTA telemetry — fast adoption tail, modest failure rate,
small rollback fraction. Flat distributions were rejected because
they produce un-shippable distribution-profile reports.

- **Header — category mix**: `safety_recall` 10%, `feature_add` 30%,
  `bug_fix` 30%, `security_patch` 20%, `performance` 10`. Categories
  carry differentiated severity mixes:
  - `safety_recall`: 40% critical / 40% high (urgency dominates)
  - `feature_add`: 50% low (low operational risk)
  - `security_patch`: 30% critical / 50% high
- **Header — phased-rollout curves**: 4 realistic patterns sampled:
  `[5, 25, 50, 100]` (canonical 4-phase), `[10, 50, 100]` (3-phase
  fast), `[1, 10, 50, 100]` (canary-first), `[100]` (instant; rare,
  reserved for `safety_recall`).
- **Events — adoption mix**: a single Uniform(0, 1) draw per row
  branches into:
  - 84.5% `installed` (target: 60% within 7 days, 85% within 30 days
    per spec PRD)
  - 5% `dispatched` (never started — phone off, VIN out of WAN range)
  - 4% `download_failed` (network drop mid-download)
  - 3% `install_failed` (storage full, version mismatch, install error)
  - 3% `declined_by_user` (driver postpones the install)
  - 0.5% `rolled_back` (post-install regression detected, OTA reverts)
- **Events — dispatch time spread**: Beta(0.7, 2.0) within each
  campaign's `dispatch_start_date → dispatch_end_date` window —
  early-skewed, matching real-world phased rollouts where most
  vehicles get the OTA in the first ~3–5 days.
- **Events — per-event timing**: download → install timestamps
  derived from `dispatch_time` with incremental random hours / minutes;
  download lasts minutes, install lasts ~30 min on average for a
  ~500 MB package. Timing fields are NULL on
  `dispatched`/`download_failed` paths beyond the corresponding stage.
- **Failure-reason mix**: when `final_status` indicates failure,
  `failure_reason` populates from a weighted enum of realistic OTA
  failure modes (signal loss, low storage, version mismatch, install
  abort, thermal limit, post-install boot failure).

## Data-quality summary

- **Row count**: 100 campaigns + ~30M events at scale 1.0
  (`scale_n × 0.001 → ~27K events` at smoke).
- **Edge-case injection** (1–3% per-product band per the six-code
  taxonomy in [`docs/tech.md`](../../../../docs/tech.md)):
  - `missing_required` 0.75% on `failure_reason` and other
    edge_case_eligible columns
  - `late_arrival` 0.50% (`ingest_time = event_time + 2 days`)
  - `schema_drift` 0.35% (`DRIFT-` prefix on enum columns)
  - `bad_pii` 0.20% on `pii_drift_target` columns (zero on the
    header table; events table has no PII columns either, so this
    is effectively a structural zero — the schema YAML carries no
    `pii_drift_target` flag)
  - `outlier_value` 0.40% on Int32 `package_size_mb` (header) only
  - `orphan_fk` 0.00% (counter-example)
- **FK closure**: `campaign_id` 100% (deterministic in-process
  header → events join); `vin` 100%. Verified by
  `tests/test_referential_integrity.py::test_zero_orphan_campaign_ids_in_events`
  + `test_zero_orphan_vins`.
- **Adoption-curve assertion** (60% installed within 7 days, 85%
  within 30 days): encoded into the generator's adoption-outcome
  branches; validated against curated parquet by the master `seed`
  task's integrity test (gated by `@pytest.mark.needs_curated`).
- **Profiling**: `quality-reports/ota_campaigns/profile.{json,md}`
  generated by [`scripts/profile-data.py`](../../../scripts/profile-data.py)
  — emits one row per Iceberg table on the CloudWatch dashboard
  `adp-{stage}-foundation-data-quality` (the multi-table OTA case
  is handled explicitly).

## Contract

**Provenance**: `single-vintage`

This product produces one partition per seed run and overwrites the previous partition on re-generation. The lake publishes each generation's output additively to the curated directory. For operator details on publishing behavior and single-vintage handling (including the optional `` `--allow-purge` `` flag for multi-partition cleanup), see [`docs/DEPLOYMENT.md` § "Publishing single-vintage products"](../../../../docs/DEPLOYMENT.md).

## See also

- Schema-of-record: [`schema.yaml`](schema.yaml) (multi-table)
- Producer: [`generator.py`](generator.py)
- Sibling EV-Ops products:
  [`charging_sessions`](../charging_sessions/README.md) ·
  [`energy_usage`](../energy_usage/README.md)
- Integration contract: [`docs/cvx-integration-contract.md` § 3.5](../../../../docs/cvx-integration-contract.md)
- Column formats: [`docs/data-contracts.md`](../../../../docs/data-contracts.md)
