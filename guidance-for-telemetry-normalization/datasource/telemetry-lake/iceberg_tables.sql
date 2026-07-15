-- Iceberg table for normalized fleet telemetry
-- Partitioned by fleetId + day for tenant isolation and query performance
-- All sources (simulator, fleetwise, oem) converge to this schema

CREATE TABLE cms_normalized_telemetry (
    vehicleId       STRING      COMMENT 'CMS internal vehicle ID',
    fleetId         STRING      COMMENT 'Fleet ID for tenant isolation',
    timestamp_ms    BIGINT      COMMENT 'Epoch milliseconds',
    source          STRING      COMMENT 'simulator | fleetwise | oem',
    oem             STRING      COMMENT 'ford | tesla | null',
    speed           DOUBLE      COMMENT 'mph',
    odometer        DOUBLE      COMMENT 'miles',
    lat             DOUBLE      COMMENT 'GPS latitude',
    lng             DOUBLE      COMMENT 'GPS longitude',
    heading         DOUBLE      COMMENT 'Degrees (0=North)',
    ignitionOn      BOOLEAN     COMMENT 'Engine/motor running',
    engineRPM       DOUBLE      COMMENT 'RPM (ICE only)',
    engineTemp      DOUBLE      COMMENT 'Fahrenheit',
    fuelLevel       DOUBLE      COMMENT 'Percent (SOC for EVs)',
    batteryVoltage  DOUBLE      COMMENT '12V battery voltage',
    tire_fl         DOUBLE      COMMENT 'PSI front-left',
    tire_fr         DOUBLE      COMMENT 'PSI front-right',
    tire_rl         DOUBLE      COMMENT 'PSI rear-left',
    tire_rr         DOUBLE      COMMENT 'PSI rear-right',
    tripId          STRING      COMMENT 'Active trip ID',
    driverId        STRING      COMMENT 'Assigned driver ID'
)
PARTITIONED BY (fleetId, days(from_unixtime(timestamp_ms / 1000)))
LOCATION 's3://${DATALAKE_BUCKET}/telemetry/normalized/'
TBLPROPERTIES (
    'table_type' = 'ICEBERG',
    'format' = 'parquet',
    'write_compression' = 'zstd'
);

-- Trip summary view — aggregates telemetry into per-trip metrics
CREATE TABLE cms_normalized_trips (
    tripId          STRING,
    vehicleId       STRING,
    fleetId         STRING,
    driverId        STRING,
    startTime       BIGINT      COMMENT 'Epoch ms',
    endTime         BIGINT      COMMENT 'Epoch ms',
    durationMinutes DOUBLE,
    distanceMiles   DOUBLE,
    avgSpeedMph     DOUBLE,
    maxSpeedMph     DOUBLE,
    fuelUsedPercent DOUBLE,
    startLat        DOUBLE,
    startLng        DOUBLE,
    endLat          DOUBLE,
    endLng          DOUBLE,
    source          STRING
)
PARTITIONED BY (fleetId, days(from_unixtime(startTime / 1000)))
LOCATION 's3://${DATALAKE_BUCKET}/telemetry/trips/'
TBLPROPERTIES (
    'table_type' = 'ICEBERG',
    'format' = 'parquet',
    'write_compression' = 'zstd'
);
