-- ============================================================================
-- vin_x_ota_x_energy.sql
--
-- Purpose : "Did the last OTA improve efficiency?" — for a target OTA campaign,
--           compare per-VIN average efficiency (kWh/100mi) for the 14 days
--           BEFORE the install completed vs the 14 days AFTER. Aggregates the
--           delta by powertrain_type × battery_chemistry from
--           `vehicle_identity` so improvements are visible at the cohort
--           level, not just one VIN at a time.
--
-- Joins   : ota_campaigns × ota_campaign_events × energy_usage ×
--           vehicle_identity
--
-- Engine  : Athena Engine V3, Trino dialect.
--
-- Stage   : Glue databases follow `adp_{stage}_<product>`. Replace `staging`
--           → `prod` verbatim for production.
--
-- Iceberg : Uses Iceberg `$snapshots` to pin freshness and `$history` to
--           reason about which snapshots were committed before/after the
--           campaign install date — useful when the OTA dispatch and the
--           energy_usage write happen in different `make seed` runs and the
--           consumer needs to confirm both products were on the same data
--           generation. Pattern from `docs/cvx-integration-contract.md` §6.
--
-- Params  : Replace
--             - :campaign_name (e.g. 'Battery Management v3.4')
--           with a literal at execution time. The query runs as-written if
--           you leave the example value in place.
--
-- Notes on time arithmetic (per `data-contracts.md` → "Time and date
-- conventions"):
--   - `install_completed_time` is UTC microsecond-precision timestamp;
--     casting to DATE keeps the windowing on calendar-day grain.
--   - `usage_date` is UTC calendar day. The pre/post window is half-open on
--     the install date itself to avoid double-counting partial-day data.
-- ============================================================================

WITH
-- Iceberg metadata pin — surface the latest commit per product alongside the
-- result so the consumer can confirm both sides were generated from the same
-- `make seed` run (Iceberg-snapshot-syntax pattern from
-- `docs/cvx-integration-contract.md` §6.1).
ota_latest_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_ota_campaigns."ota_campaign_events$snapshots"
),
eu_latest_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_energy_usage."energy_usage$snapshots"
),
vi_latest_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_vehicle_identity."vehicle_identity$snapshots"
),
target_camp AS (
    SELECT campaign_id,
           campaign_name,
           release_version,
           category,
           severity,
           dispatch_start_date,
           dispatch_end_date
    FROM   adp_staging_ota_campaigns.ota_campaigns
    WHERE  campaign_name = 'Battery Management v3.4'   -- :campaign_name
    LIMIT  1
),
-- Cohort: every VIN that successfully installed the campaign. Per
-- `data-contracts.md` → "Identifier formats", `vin` matches
-- `^[A-HJ-NPR-Z0-9]{17}$`; the FK to `vehicle_identity` is 1:1.
installed AS (
    SELECT e.vin,
           CAST(e.install_completed_time AS DATE) AS install_date,
           e.install_completed_time
    FROM   adp_staging_ota_campaigns.ota_campaign_events e
    JOIN   target_camp t ON t.campaign_id = e.campaign_id
    WHERE  e.final_status = 'installed'
      AND  e.install_completed_time IS NOT NULL
),
-- 14-day pre-install efficiency. Iceberg hidden-partition prune on
-- `usage_date` keeps the scan bounded.
pre AS (
    SELECT i.vin,
           i.install_date,
           AVG(eu.efficiency_kwh_per_100mi) AS pre_eff,
           AVG(eu.ambient_temp_avg_c)       AS pre_avg_ambient_c,
           SUM(eu.total_kwh_consumed)       AS pre_kwh_consumed,
           SUM(eu.total_miles_driven)       AS pre_miles
    FROM   installed i
    JOIN   adp_staging_energy_usage.energy_usage eu
           ON  eu.vin = i.vin
           AND eu.usage_date BETWEEN i.install_date - INTERVAL '14' DAY
                                AND i.install_date - INTERVAL '1'  DAY
    GROUP BY i.vin, i.install_date
),
-- 14-day post-install efficiency.
post AS (
    SELECT i.vin,
           i.install_date,
           AVG(eu.efficiency_kwh_per_100mi) AS post_eff,
           AVG(eu.ambient_temp_avg_c)       AS post_avg_ambient_c,
           SUM(eu.total_kwh_consumed)       AS post_kwh_consumed,
           SUM(eu.total_miles_driven)       AS post_miles
    FROM   installed i
    JOIN   adp_staging_energy_usage.energy_usage eu
           ON  eu.vin = i.vin
           AND eu.usage_date BETWEEN i.install_date + INTERVAL '1'  DAY
                                AND i.install_date + INTERVAL '14' DAY
    GROUP BY i.vin, i.install_date
),
-- Cohort enrichment from the vehicle identity graph. INNER JOIN here is
-- intentional — every VIN in installed/pre/post must exist in
-- `vehicle_identity` (1:1 FK contract per spec.md "Data product catalog").
cohort AS (
    SELECT pre.vin,
           pre.install_date,
           pre.pre_eff,
           post.post_eff,
           pre.pre_avg_ambient_c,
           post.post_avg_ambient_c,
           pre.pre_kwh_consumed,
           post.post_kwh_consumed,
           pre.pre_miles,
           post.post_miles,
           vi.powertrain_type,
           vi.battery_chemistry,
           vi.battery_pack_kwh,
           vi.max_charging_rate_kw,
           vi.connector_type
    FROM   pre
    JOIN   post
           ON pre.vin = post.vin
          AND pre.install_date = post.install_date
    JOIN   adp_staging_vehicle_identity.vehicle_identity vi
           ON vi.vin = pre.vin
)
-- Cohort rollup. Lower kWh/100mi == better; sort ascending pct_change to
-- surface the most-improved cohorts first.
SELECT
    tc.campaign_name,
    tc.release_version,
    tc.category                                  AS campaign_category,
    tc.severity                                  AS campaign_severity,

    co.powertrain_type,
    co.battery_chemistry,

    COUNT(DISTINCT co.vin)                       AS vins_in_cohort,
    AVG(co.pre_eff)                              AS avg_pre_eff_kwh_per_100mi,
    AVG(co.post_eff)                             AS avg_post_eff_kwh_per_100mi,
    AVG(co.post_eff) - AVG(co.pre_eff)           AS delta_eff,
    100.0 * (AVG(co.post_eff) - AVG(co.pre_eff)) /
        NULLIF(AVG(co.pre_eff), 0.0)             AS pct_change,

    -- Ambient-temperature delta — a confound when reading efficiency deltas.
    -- If the post-window was meaningfully colder, the OTA may have improved
    -- efficiency more than the raw pct_change suggests. Per
    -- `data-contracts.md` → "VSS vocabulary subset", `ambient_temp_avg_c` is
    -- in Celsius.
    AVG(co.post_avg_ambient_c) - AVG(co.pre_avg_ambient_c) AS delta_ambient_c,

    -- Activity context: how much of the cohort actually drove during each
    -- window? Sparse miles in either window weakens the comparison.
    AVG(co.pre_miles)                            AS avg_pre_miles,
    AVG(co.post_miles)                           AS avg_post_miles,

    -- Iceberg metadata pin (see `docs/cvx-integration-contract.md` §6.1).
    (SELECT committed_at FROM ota_latest_snap)   AS ota_snapshot_committed_at,
    (SELECT committed_at FROM eu_latest_snap)    AS energy_snapshot_committed_at,
    (SELECT committed_at FROM vi_latest_snap)    AS identity_snapshot_committed_at
FROM   cohort co
CROSS JOIN target_camp tc
GROUP BY tc.campaign_name,
         tc.release_version,
         tc.category,
         tc.severity,
         co.powertrain_type,
         co.battery_chemistry
HAVING COUNT(DISTINCT co.vin) >= 5  -- suppress tiny cohorts; tune for prod
ORDER BY pct_change ASC NULLS LAST;  -- most-improved (lower kWh/100mi) first
