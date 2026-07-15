# Data Contracts — ADP Foundation

**Pinned VSS version**: v6.0 (released 2026-01-16). See
`docs/tech.md` "VSS (Vehicle Signal Specification) — v6.0" for
tooling and unit-conversion notes.

This document is the authoritative cross-repo contract between ADP
and CMS. Both repos converge through the conventions declared here.
Neither repo imports from the other; neither runtime-depends on the
other; this document is the convergence point.

CMS may cross-link this document from its own `docs/`. CMS does not
need to copy it. If ADP needs to break the contract (e.g., change
VIN format), the change requires a coordinated announcement — not a
coordinated deploy.

## VSS vocabulary subset

The following 40 signals constitute the minimum vocabulary ADP
publishes in `vehicle_telemetry_aggregated` and `energy_usage`. CMS
publishes a different (and overlapping) subset via its FleetWise
campaigns; the **CMS-equivalent** column below is informational only
— it is not a contract on CMS, and the CMS integration is not
required for either repo to ship.

| # | VSS path | ADP column | Unit | Range | CMS-reported equivalent (informational) |
|---|---|---|---|---|---|
| 1  | `Vehicle.Speed`                                                  | `speed_kmh`              | km/h        | 0–300       | `Vehicle.Speed` |
| 2  | `Vehicle.TraveledDistance`                                       | `total_miles_driven`     | mi (US dev) | 0–1e6       | `Vehicle.TraveledDistance` (km) |
| 3  | `Vehicle.AverageSpeed`                                           | `avg_speed_kmh`          | km/h        | 0–300       | n/a |
| 4  | `Vehicle.Powertrain.TractionBattery.StateOfCharge.Current`       | `start_soc_pct`          | percent     | 0–100       | `…StateOfCharge.Current` |
| 5  | `Vehicle.Powertrain.TractionBattery.StateOfCharge.Current`       | `end_soc_pct`            | percent     | 0–100       | `…StateOfCharge.Current` (snapshot) |
| 6  | `Vehicle.Powertrain.TractionBattery.StateOfCharge.Current`       | `min_soc_pct`            | percent     | 0–100       | n/a |
| 7  | `Vehicle.Powertrain.TractionBattery.StateOfCharge.Current`       | `max_soc_pct`            | percent     | 0–100       | n/a |
| 8  | `Vehicle.Powertrain.TractionBattery.StateOfCharge.Current`       | `avg_soc_pct`            | percent     | 0–100       | n/a |
| 9  | `Vehicle.Powertrain.TractionBattery.StateOfHealth`               | `state_of_health_pct`    | percent     | 0–100       | `…StateOfHealth` |
| 10 | `Vehicle.Powertrain.TractionBattery.GrossCapacity`               | `battery_pack_kwh`       | kWh         | 0–250       | `…GrossCapacity` |
| 11 | `Vehicle.Powertrain.TractionBattery.NominalVoltage`              | `battery_nominal_voltage_v` | V        | 0–1000      | `…NominalVoltage` |
| 12 | `Vehicle.Powertrain.TractionBattery.Temperature.Average`         | `battery_pack_temp_avg_c` | Celsius    | -40–80      | `…Temperature.Average` |
| 13 | `Vehicle.Powertrain.TractionBattery.Range`                       | `range_estimate_end_mi`  | mi (US dev) | 0–800       | `…Range` (km) |
| 14 | `Vehicle.Powertrain.TractionBattery.Range`                       | `range_estimate_start_mi` | mi (US dev) | 0–800      | `…Range` (km) |
| 15 | `Vehicle.Powertrain.TractionBattery.Charging.IsCharging`         | `is_charging`            | bool        | true/false  | `…IsCharging` |
| 16 | `Vehicle.Powertrain.TractionBattery.Charging.ChargeRate`         | `avg_power_kw`           | kW          | 0–400       | `…ChargeRate` |
| 17 | `Vehicle.Powertrain.TractionBattery.Charging.PowerLossDuringCharge` | `peak_power_kw`        | kW          | 0–400       | n/a |
| 18 | `Vehicle.Powertrain.TractionBattery.Charging.MaximumChargingCurrent.DC` | `max_charging_rate_kw` | kW       | 0–400       | n/a |
| 19 | `Vehicle.Powertrain.TractionBattery.Charging.ChargePortFlap.IsOpen` | `charge_port_open`     | bool        | true/false  | `…ChargePortFlap.IsOpen` |
| 20 | `Vehicle.Powertrain.TractionBattery.Charging.ChargeLimit`        | `charge_limit_pct`       | percent     | 0–100       | `…ChargeLimit` |
| 21 | `Vehicle.Powertrain.ElectricMotor.Speed`                         | `motor_rpm`              | rpm         | 0–25000     | `…ElectricMotor.Speed` |
| 22 | `Vehicle.Powertrain.ElectricMotor.Torque`                        | `motor_torque_nm`        | Nm          | -1000–1500  | `…ElectricMotor.Torque` |
| 23 | `Vehicle.Powertrain.ElectricMotor.Power`                         | `motor_power_kw`         | kW          | -400–600    | `…ElectricMotor.Power` |
| 24 | `Vehicle.Powertrain.ElectricMotor.Temperature`                   | `motor_temp_c`           | Celsius     | -40–200     | `…ElectricMotor.Temperature` |
| 25 | `Vehicle.Powertrain.ElectricMotor.TimeInUse`                     | `motor_time_in_use_s`    | s           | 0–1e9       | `…TimeInUse` |
| 26 | `Vehicle.Powertrain.Transmission.DriveType`                      | `drive_type`             | enum        | `awd`/`fwd`/`rwd` | `…DriveType` |
| 27 | `Vehicle.Powertrain.Type`                                        | `powertrain_type`        | enum        | `electric`/`hybrid`/`erev` | `…Powertrain.Type` |
| 28 | `Vehicle.CurrentLocation.Latitude`                               | `latitude`               | degrees     | -90–90      | `…Latitude` |
| 29 | `Vehicle.CurrentLocation.Longitude`                              | `longitude`              | degrees     | -180–180    | `…Longitude` |
| 30 | `Vehicle.CurrentLocation.Altitude`                               | `altitude_m`             | m           | -500–9000   | `…Altitude` |
| 31 | `Vehicle.CurrentLocation.Heading`                                | `heading_deg`            | degrees     | 0–360       | `…Heading` |
| 32 | `Vehicle.AmbientAirTemperature`                                  | `ambient_temp_avg_c`     | Celsius     | -50–60      | `…AmbientAirTemperature` |
| 33 | `Vehicle.Cabin.HVAC.AmbientAirTemperature`                       | `cabin_temp_c`           | Celsius     | -10–60      | `…AmbientAirTemperature` |
| 34 | `Vehicle.Powertrain.TractionBattery.NetCapacity`                 | `battery_net_kwh`        | kWh         | 0–250       | `…NetCapacity` |
| 35 | `Vehicle.Chassis.Brake.PedalPosition`                            | `brake_pedal_pct`        | percent     | 0–100       | `…BrakePedalPosition` |
| 36 | `Vehicle.Chassis.Accelerator.PedalPosition`                      | `accelerator_pedal_pct`  | percent     | 0–100       | `…AcceleratorPedalPosition` |
| 37 | `Vehicle.OBD.RegenerativeBraking.kWh`  *(legacy, ADP overlay)*   | `regen_kwh_recovered`    | kWh         | 0–1e6       | n/a (CMS uses motor power negative samples) |
| 38 | `Vehicle.Powertrain.TractionBattery.Charging.ChargingType`       | `connector_type`         | enum        | `J1772`/`CCS1`/`NACS`/`CHAdeMO` | `…ChargingType` |
| 39 | `Vehicle.Powertrain.FuelSystem.RelativeLevel`                    | n/a (EV-only, retained for EREV) | percent | 0–100 | `…RelativeLevel` |
| 40 | `Vehicle.VersionVSS`                                             | `vss_version`            | string      | `6.0`       | `…VersionVSS` |

**Notes**:
- Columns marked **`mi (US dev)`** are explicit US-market narrative
  deviations from VSS (which uses km). The `_mi` suffix flags the
  deviation. See `docs/tech.md` "VSS unit conventions" for the full
  unit table.
- Row 37 references `Vehicle.OBD.RegenerativeBraking.kWh`. The OBD
  branch was removed in VSS v6.0 — this is an ADP overlay signal.
  Keep the column for the EV narrative; rename to a non-OBD VSS path
  in v2 if the catalog gets a regen-aware standard signal.
- Row 39 (`Vehicle.Powertrain.FuelSystem.RelativeLevel`) is retained
  for the EREV (Extended Range EV) signal definitions added in VSS
  v6.0 — most ADP synthetic VINs are pure-BEV and emit `NULL` here.
- Row 40 (`Vehicle.VersionVSS`) lets downstream consumers verify
  which VSS version produced the row; ADP v1 emits `"6.0"`.

## Identifier formats

All IDs are stored as `string` columns. The regex patterns below are
the contract — both ADP and CMS adhere to them. Drift-detection tests
in `platform-foundation/tests/test_data_contracts.py::TestKeyFormats`
sample 10K rows per product and assert every value matches.

| Identifier | Format | Length | Python regex |
|---|---|---|---|
| `vin`           | ISO 3779: 17 alphanumeric chars, no `I`, `O`, `Q`. Acme Motors WMI prefix `1FA`. | 17 | `^[A-HJ-NPR-Z0-9]{17}$` |
| `customer_id`   | `CUST-` prefix + 8 hex chars (UUIDv5 short form) | 13 | `^CUST-[0-9A-F]{8}$` |
| `dealer_id`     | `DLR-` prefix + 5-digit zero-padded number | 9 | `^DLR-[0-9]{5}$` |
| `supplier_id`   | `SUP-` prefix + 4-digit zero-padded number | 8 | `^SUP-[0-9]{4}$` |
| `part_number`   | 8 alphanumeric chars, dash, 4 alphanumeric chars | 13 | `^[A-Z0-9]{8}-[A-Z0-9]{4}$` |
| `station_id`    | `STN-` prefix + network code (2–4 chars) + dash + 8-digit zero-padded sequence | 16–18 | `^STN-(TS\|EA\|EVGO\|CP\|HOME\|DEST)-[0-9]{8}$` |

**Notes**:
- `vin`: Acme Motors is a fictional EV manufacturer. The WMI prefix
  `1FA` is intentionally illustrative — it would be assigned by SAE
  in a real-world production scenario. Do not use real OEM WMIs in
  ADP synthetic data.
- `customer_id` is a UUIDv5 short form (deterministic from a seed +
  ordinal index). Re-running the dimension generator with the same
  seed produces byte-identical customer IDs — see
  `tasks.md` Group 2 dimension generator constraints.
- `station_id` network codes correspond to the synthetic station
  catalog: `TS` = Tesla Supercharger, `EA` = Electrify America,
  `EVGO` = EVgo, `CP` = ChargePoint, `HOME` = synthetic home
  charger, `DEST` = synthetic destination L2.

## Time and date conventions

- All `timestamp` columns store **microsecond precision, UTC, no
  timezone column**. The pyarrow type is
  `pa.timestamp('us', tz='UTC')`; the Iceberg type is `timestamp`.
- All `date` columns store **UTC calendar day** as Iceberg `date`
  (pyarrow `pa.date32()`). Partition keys named `<event>_date`
  (e.g., `session_date`, `event_date`, `usage_date`,
  `dispatch_date`) are date-typed.
- **`event_time`** is the source-truth event time — when the event
  actually happened (e.g., charging session start, OTA dispatch
  emission, telemetry sample collection).
- **`ingest_time`** is when the generator / loader wrote the row to
  the lake. Always ≥ `event_time`. The two columns together model
  late-arrival edge cases.
- **`late arrival` definition**: a row is "late" if
  `(ingest_time - event_time) > 1 day`. The edge-case taxonomy in
  `docs/tech.md` injects this case at 0.3–0.7% per product.
- **Time zone of display** is downstream's choice — ADP stores UTC
  always. Do not store local time.

## Iceberg partition conventions

ADP uses Apache Iceberg on Glue (Athena Engine V3 read path,
Glue 4.0 / Spark 3.3 write path for the PySpark tier; pandas + pyarrow
+ PyIceberg 0.7 for the pandas tier).

### Daily-grain fact tables
Partition by `<event>_date` of type `date` (Iceberg `day(<ts>)`
hidden transform preferred when supported).

| Table | Partition |
|---|---|
| `vehicle_telemetry_aggregated` | `day(event_time), bucket(16, vin)` |
| `charging_sessions`            | `day(start_time), bucket(16, vin)` |
| `energy_usage`                 | `day(usage_date)` |
| `customer_interactions`        | `day(interaction_date)` |
| `ota_campaign_events`          | `day(dispatch_date)` |

### Long-tail tables (monthly grain)
Partition by `month(<event_date>)`.

| Table | Partition |
|---|---|
| `service_records`              | `month(service_date)` |

### Snapshot tables
Partition by snapshot day.

| Table | Partition |
|---|---|
| `customer_360`                 | `snapshot_date` |

### Identifier / dimension tables
Partition by a low-cardinality identity column.

| Table | Partition |
|---|---|
| `ota_campaigns`                | `campaign_id` |
| `vehicle_identity`             | `model_year` |

### Bucketing rules
- Bucket on high-cardinality FK columns when the table is large
  (>50M rows).
- Default bucket count: **16** for VIN-keyed fact tables.
- Bucketing is set via Athena DDL `CREATE TABLE … PARTITIONED BY
  (..., bucket(N, col))` or Spark DataFrame `bucketBy`. Glue API
  alone does not support setting bucketing; see `docs/tech.md`
  "AWS Glue — Iceberg `create_table`" pitfalls.

### Hidden partitioning preference
Prefer Iceberg's hidden transforms (`day()`, `month()`, `year()`,
`bucket()`, `truncate()`) over explicit partition columns. The
`<event>_date` columns above are stored physically as date partition
keys for Athena Engine V3 compatibility, but downstream queries
should use `WHERE event_time BETWEEN '…' AND '…'` and let Iceberg
prune via the hidden transform.

## Explicit non-dependencies

Restating spec Constraints #11–#13 here so this doc is the
single source of truth on the boundary:

1. **No imports from CMS in ADP code.** `automotive-data-platform-on-aws/`
   does not `import` or `require` any module from
   `connected-mobility-guidance-on-aws/`. Verified by grep + the
   standalone-deploy harness in `tasks.md` Group 6.
2. **No imports from ADP in CMS code.** Same property in reverse.
   CMS deploys with zero references to ADP, asserted by deploying
   CMS in a clean account post-merge per the spec verification
   matrix.
3. **No runtime data flow CMS↔ADP except via the explicit, opt-in,
   off-by-default ingest module.** The optional CMS→ADP module is
   gated by `cdk deploy -c enable_cms_ingest=true`; default deploys
   create zero ingest resources. There is no ADP→CMS runtime flow,
   ever.
4. **No shared package / library / type definitions in v1.**
   `automotive-data-contracts` (a hypothetical shared schema package)
   is a backlog candidate post-v1. v1 ships convention-based
   convergence — this document is the convention.
5. **No deploy ordering.** ADP deploys standalone; CMS deploys
   standalone. If both are deployed, neither requires the other
   first. The opt-in ingest module assumes CMS is already deployed
   in the same account, but failing to deploy CMS first does not
   block ADP — the ingest construct is gated off by default.
6. **Drift handling**: when ADP needs to break the contract (e.g.,
   change VIN format, change a VSS column name), the change requires
   a coordinated **announcement** (PR comment cross-linked between
   the two repos), not a coordinated **deploy**. The drift-detection
   tests in `platform-foundation/tests/test_data_contracts.py` will
   fire on the ADP side first and gate the ADP merge until the
   contract is updated.

## Drift-detection test design

Three pytest test classes in
`platform-foundation/tests/test_data_contracts.py`. All three are
runnable post-Group-3 (when generators have written data); pre-Group-3
they're red (missing `curated/<product>/` fixtures), which is
expected per the test-skeleton phase per `~/.kiro/steering/testing.md`.

### `TestKeyFormats`
For each generated product, sample 10K rows. For each ID column on
the row (`vin`, `customer_id`, `dealer_id`, `supplier_id`,
`part_number`, `station_id`), assert the value matches the regex
declared in this document's "Identifier formats" section. Fail on
any non-matching row.

### `TestVSSColumnPresence`
For `vehicle_telemetry_aggregated` and `energy_usage`, assert every
column listed in this document's "VSS vocabulary subset" table is
present in the generated parquet schema. The test reads the VSS
table from this markdown file via a parser fixture (so updates to
the table flow into the test automatically).

### `TestPartitionConventions`
For each Iceberg table, assert the `partition_spec` from Glue
matches the convention declared in this document's "Iceberg
partition conventions" section.

Verify command:
```
pytest platform-foundation/tests/test_data_contracts.py -v
```
Test runs in CI on every commit; fails fast on drift.
