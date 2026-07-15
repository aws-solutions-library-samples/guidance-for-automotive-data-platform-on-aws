-- ============================================================================
-- charging_station_utilization.sql
--
-- Purpose : Network-level charging utilization aggregates for the trailing
--           90 days. Surfaces:
--             - sessions, kWh delivered, revenue, abort rate per network
--             - load factor (delivered_kWh / theoretical_capacity_kWh)
--             - DC-fast plug-in patterns
--             - geographic spread (by US state) for public networks
--           Useful for charging-network operations (capacity planning,
--           SLA reporting, billing reconciliation) and for product analytics
--           comparing networks at the cohort level.
--
-- Joins   : charging_sessions × charging_stations  (the dimension catalog
--                                                   under `adp_staging_dimensions`)
--           × ota_campaign_events (for "did a recent OTA correlate with
--                                  station-side abort spikes?" — kept LEFT
--                                  JOIN, optional)
--
-- Engine  : Athena Engine V3, Trino dialect.
--
-- Stage   : Glue databases follow `adp_{stage}_<product>`. Replace `staging`
--           → `prod` verbatim for production.
--
-- Iceberg : Uses Iceberg `$snapshots` to surface data freshness per the
--           pattern in `docs/cvx-integration-contract.md` §6.1. Hidden
--           partition pruning on `session_date` keeps the 90-day scan
--           bounded — Iceberg partition stats let Athena skip parquet files
--           outside the window without a partition-column WHERE clause
--           (per `data-contracts.md` → "Iceberg partition conventions").
--
-- Params  : Replace
--             - :as_of_date      (e.g. DATE '2026-05-29')
--             - :window_days     (e.g. 90)
--           with literals at execution time. The query runs as-written if
--           you leave the example values in place.
--
-- Notes   :
--   - `charging_stations` is a DIMENSION catalog (not Iceberg) — it lives in
--     the `adp_staging_dimensions` Glue database (see deployed lake stack).
--     No `$snapshots` reference for it.
--   - Stations with `latitude`/`longitude` NULL are home/destination synthetic
--     and are excluded from the geographic rollup (per spec.md "Schemas for
--     the three new EV-Operations products" — privacy carve-out).
-- ============================================================================

WITH
-- Iceberg snapshot pins for the two Iceberg tables we read.
chg_latest_snap AS (
    SELECT MAX(committed_at) AS committed_at,
           COUNT(*)          AS snapshot_count
    FROM   adp_staging_charging_sessions."charging_sessions$snapshots"
),
ota_latest_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_ota_campaigns."ota_campaign_events$snapshots"
),
window_dates AS (
    SELECT DATE '2026-05-29'                    AS hi,            -- :as_of_date
           DATE '2026-05-29' - INTERVAL '90' DAY AS lo            -- :window_days
),

-- Per-station base rollup. Iceberg hidden-partition prune on `session_date`.
station_rollup AS (
    SELECT cs.station_id,
           COUNT(*)                                          AS sessions,
           COUNT(DISTINCT cs.vin)                            AS unique_vins,
           SUM(cs.kwh_delivered)                             AS total_kwh,
           SUM(COALESCE(cs.cost_usd, DECIMAL '0.0'))         AS total_revenue_usd,
           SUM(cs.duration_seconds)                          AS total_session_seconds,
           SUM(CASE WHEN cs.interrupted THEN 1 ELSE 0 END)   AS aborted_sessions,
           AVG(cs.kwh_delivered)                             AS avg_kwh_per_session,
           AVG(cs.duration_seconds)                          AS avg_duration_seconds,
           AVG(cs.peak_power_kw)                             AS avg_peak_power_kw,
           AVG(cs.start_soc_pct)                             AS avg_start_soc_pct,
           AVG(cs.end_soc_pct)                               AS avg_end_soc_pct,
           SUM(CASE WHEN cs.interrupt_reason = 'station_fault' THEN 1 ELSE 0 END)
                                                              AS faults_station,
           SUM(CASE WHEN cs.interrupt_reason = 'vehicle_fault' THEN 1 ELSE 0 END)
                                                              AS faults_vehicle,
           SUM(CASE WHEN cs.interrupt_reason = 'network_drop' THEN 1 ELSE 0 END)
                                                              AS faults_network
    FROM   adp_staging_charging_sessions.charging_sessions cs
    JOIN   window_dates w ON cs.session_date BETWEEN w.lo AND w.hi
    GROUP BY cs.station_id
),

-- Optional: per-station counts of recent OTA installs that touched VINs which
-- subsequently charged at this station. Used to detect post-OTA abort spikes.
-- LEFT JOINed at the network rollup so it never blocks the main result.
ota_station_signal AS (
    SELECT cs.station_id,
           COUNT(DISTINCT e.vin)                                  AS post_ota_install_vins,
           SUM(CASE WHEN e.final_status = 'install_failed' THEN 1 ELSE 0 END)
                                                                  AS post_ota_install_failures
    FROM   adp_staging_charging_sessions.charging_sessions cs
    JOIN   window_dates w ON cs.session_date BETWEEN w.lo AND w.hi
    JOIN   adp_staging_ota_campaigns.ota_campaign_events e
           ON  e.vin = cs.vin
           AND e.install_completed_time IS NOT NULL
           AND CAST(e.install_completed_time AS DATE)
                  BETWEEN cs.session_date - INTERVAL '7' DAY AND cs.session_date
    GROUP BY cs.station_id
),

-- Enrich with the station catalog (network operator, location, capacity).
station_facts AS (
    SELECT s.station_id,
           s.network_provider,
           s.network_code,
           s.station_type,
           s.max_power_kw,
           s.stall_count,
           s.latitude,
           s.longitude,
           s.city,
           s.state,
           s.country,
           s.opened_date
    FROM   adp_staging_dimensions.charging_stations s
),

-- Wide per-station joined view. INNER JOIN on station_id is the
-- referential-integrity contract from `data-contracts.md` →
-- "Identifier formats" → `station_id` regex.
station_full AS (
    SELECT sr.*,
           sf.network_provider,
           sf.network_code,
           sf.station_type,
           sf.max_power_kw,
           sf.stall_count,
           sf.latitude,
           sf.longitude,
           sf.city,
           sf.state,
           sf.country,
           sf.opened_date,
           COALESCE(oss.post_ota_install_vins, 0)         AS post_ota_install_vins,
           COALESCE(oss.post_ota_install_failures, 0)     AS post_ota_install_failures
    FROM   station_rollup sr
    JOIN   station_facts sf ON sf.station_id = sr.station_id
    LEFT JOIN ota_station_signal oss ON oss.station_id = sr.station_id
)

-- Network-level aggregates.
SELECT
    sf.network_provider,
    sf.network_code,
    sf.station_type,

    -- Cardinality and activity
    COUNT(*)                                          AS stations_with_traffic,
    SUM(sf.stall_count)                               AS total_stalls,
    SUM(sf.sessions)                                  AS sessions_total,
    SUM(sf.unique_vins)                               AS unique_vins_sum,
    SUM(sf.total_kwh)                                 AS kwh_delivered_total,
    SUM(sf.total_revenue_usd)                         AS revenue_total_usd,

    -- Reliability
    SUM(sf.aborted_sessions)                          AS aborts_total,
    100.0 * SUM(sf.aborted_sessions)
        / NULLIF(SUM(sf.sessions), 0)                 AS abort_rate_pct,
    SUM(sf.faults_station)                            AS station_fault_count,
    SUM(sf.faults_vehicle)                            AS vehicle_fault_count,
    SUM(sf.faults_network)                            AS network_drop_count,

    -- Per-session averages — careful weighting (mean of station means is OK
    -- here because each station gets its own row with COUNT-weighted means,
    -- but we want the network-level mean weighted by sessions).
    SUM(sf.total_kwh)
        / NULLIF(SUM(sf.sessions), 0)                 AS avg_kwh_per_session,
    SUM(sf.total_session_seconds)
        / NULLIF(SUM(sf.sessions), 0)                 AS avg_duration_seconds,

    -- Load factor: delivered kWh / theoretical capacity over the window.
    -- Theoretical capacity = sum_of(stall_count * max_power_kw) * 24h * window_days.
    -- Result is in [0, 1]; production DC-fast networks land in 0.05–0.20.
    SUM(sf.total_kwh) / NULLIF(SUM(
        CAST(sf.stall_count AS DOUBLE)
        * sf.max_power_kw
        * 24.0
        * CAST(date_diff('day',
                         (SELECT lo FROM window_dates),
                         (SELECT hi FROM window_dates)) AS DOUBLE)
    ), 0.0)                                            AS load_factor,

    -- Geographic spread — public networks only (home/destination have NULL
    -- city/state per the spec privacy carve-out).
    COUNT(DISTINCT sf.state) FILTER (WHERE sf.state IS NOT NULL)
                                                       AS distinct_us_states,
    array_distinct(filter(array_agg(sf.state), x -> x IS NOT NULL))
                                                       AS state_list,

    -- Post-OTA correlation surface — does a recent install correlate with
    -- station-side aborts? Network-aggregated signal.
    SUM(sf.post_ota_install_vins)                     AS post_ota_install_vins_sum,
    SUM(sf.post_ota_install_failures)                 AS post_ota_install_failures_sum,

    -- Iceberg snapshot pins for lineage (see
    -- `docs/cvx-integration-contract.md` §6.1).
    (SELECT committed_at FROM chg_latest_snap)         AS charging_snapshot_committed_at,
    (SELECT committed_at FROM ota_latest_snap)         AS ota_snapshot_committed_at,
    (SELECT snapshot_count FROM chg_latest_snap)       AS charging_snapshot_history_depth,

    -- Window echo for the consumer
    (SELECT lo FROM window_dates)                      AS window_lo,
    (SELECT hi FROM window_dates)                      AS window_hi
FROM   station_full sf
GROUP BY sf.network_provider,
         sf.network_code,
         sf.station_type
ORDER BY revenue_total_usd DESC NULLS LAST,
         kwh_delivered_total DESC NULLS LAST;
