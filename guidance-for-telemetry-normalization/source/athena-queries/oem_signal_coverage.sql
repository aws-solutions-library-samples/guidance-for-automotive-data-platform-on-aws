-- Signal coverage by source — shows which signals each source provides
-- Helps fleet operators understand data gaps for OEM vehicles
SELECT
    source,
    oem,
    COUNT(DISTINCT vehicleId) AS vehicle_count,
    COUNT(*) AS total_records,
    ROUND(100.0 * COUNT(speed) / COUNT(*), 1) AS speed_pct,
    ROUND(100.0 * COUNT(odometer) / COUNT(*), 1) AS odometer_pct,
    ROUND(100.0 * COUNT(lat) / COUNT(*), 1) AS gps_pct,
    ROUND(100.0 * COUNT(engineRPM) / COUNT(*), 1) AS rpm_pct,
    ROUND(100.0 * COUNT(engineTemp) / COUNT(*), 1) AS engine_temp_pct,
    ROUND(100.0 * COUNT(fuelLevel) / COUNT(*), 1) AS fuel_level_pct,
    ROUND(100.0 * COUNT(tire_fl) / COUNT(*), 1) AS tire_pressure_pct
FROM cms_normalized_telemetry
WHERE timestamp_ms >= (to_unixtime(current_timestamp - interval '7' day) * 1000)
GROUP BY source, oem
ORDER BY source, oem;
