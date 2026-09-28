-- Normalized trips across all sources
-- Fleet operators see unified trip data regardless of vehicle source
SELECT
    t.tripId,
    t.vehicleId,
    t.fleetId,
    t.driverId,
    t.source,
    from_unixtime(t.startTime / 1000) AS start_time,
    from_unixtime(t.endTime / 1000) AS end_time,
    t.durationMinutes,
    t.distanceMiles,
    t.avgSpeedMph,
    t.maxSpeedMph,
    t.fuelUsedPercent,
    t.startLat, t.startLng,
    t.endLat, t.endLng
FROM cms_normalized_trips t
WHERE t.fleetId = '${FLEET_ID}'
  AND t.startTime >= (to_unixtime(current_timestamp - interval '7' day) * 1000)
ORDER BY t.startTime DESC;
