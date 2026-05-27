-- Fleet utilization report — daily metrics per fleet
-- Used by fleet operators in CMS UI analytics dashboard
SELECT
    fleetId,
    date(from_unixtime(timestamp_ms / 1000)) AS report_date,
    COUNT(DISTINCT vehicleId) AS active_vehicles,
    COUNT(DISTINCT tripId) AS total_trips,
    ROUND(SUM(speed * 0.0001388), 1) AS estimated_miles,  -- speed samples × interval
    ROUND(AVG(speed), 1) AS avg_speed_mph,
    ROUND(AVG(fuelLevel), 1) AS avg_fuel_level_pct,
    COUNT(*) AS telemetry_points
FROM cms_normalized_telemetry
WHERE timestamp_ms >= (to_unixtime(current_timestamp - interval '30' day) * 1000)
GROUP BY fleetId, date(from_unixtime(timestamp_ms / 1000))
ORDER BY fleetId, report_date DESC;
