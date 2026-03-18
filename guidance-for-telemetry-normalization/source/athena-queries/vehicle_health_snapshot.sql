-- Latest vehicle health snapshot — most recent telemetry per vehicle
-- Used by fleet operators for at-a-glance fleet health view
SELECT
    t.vehicleId,
    t.fleetId,
    t.source,
    t.oem,
    from_unixtime(t.timestamp_ms / 1000) AS last_seen,
    t.speed,
    t.odometer,
    t.fuelLevel,
    t.engineTemp,
    t.batteryVoltage,
    t.tire_fl, t.tire_fr, t.tire_rl, t.tire_rr,
    t.lat, t.lng,
    t.ignitionOn
FROM cms_normalized_telemetry t
INNER JOIN (
    SELECT vehicleId, MAX(timestamp_ms) AS max_ts
    FROM cms_normalized_telemetry
    WHERE fleetId = '${FLEET_ID}'
    GROUP BY vehicleId
) latest ON t.vehicleId = latest.vehicleId AND t.timestamp_ms = latest.max_ts
WHERE t.fleetId = '${FLEET_ID}'
ORDER BY t.vehicleId;
