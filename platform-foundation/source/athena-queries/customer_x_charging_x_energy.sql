-- ============================================================================
-- customer_x_charging_x_energy.sql
--
-- Purpose : "Why is this customer's charging cost high?" — diagnose anomalous
--           30-day charging spend by attributing it to network mix (home L2 vs
--           public DC fast) and surfacing per-VIN efficiency over the same
--           window. Worse-than-fleet efficiency typically correlates with
--           cold-weather range loss (see `data-contracts.md` → "VSS vocabulary
--           subset" row 32 → `ambient_temp_avg_c`).
--
-- Joins   : customer_360 × charging_sessions × energy_usage × charging_stations
--
-- Engine  : Athena Engine V3, Trino dialect.
--
-- Stage   : Glue databases follow `adp_{stage}_<product>` (see
--           `docs/cvx-integration-contract.md` §1.1). Literals below use the
--           `staging` stage; replace `staging` → `prod` verbatim for production.
--
-- Iceberg : Uses Iceberg `$snapshots` metadata table to pin the query to the
--           latest committed snapshot of each Iceberg table for read-isolation
--           and to surface data-freshness alongside the result. This is the
--           Iceberg-snapshot-syntax pattern documented in
--           `docs/cvx-integration-contract.md` §6.
--
-- Params  : Replace
--             - :customer_id (e.g. 'CUST-3F2504E0' — see `data-contracts.md` →
--               "Identifier formats" for the regex `^CUST-[0-9A-F]{8}$`)
--             - :as_of_date  (e.g. DATE '2026-05-29')
--           with literals at execution time. The query runs as-written if you
--           leave the example values in place.
--
-- Edge cases:
--   - `customer_id` may be NULL on `charging_sessions` for guest charges
--     (per spec.md "Schemas for the three new EV-Operations products"); the
--     LEFT JOIN preserves the customer row when no charging history exists.
--   - `cost_usd` is NULL for free home charging; we treat NULL as 0.0 in the
--     aggregate using COALESCE.
-- ============================================================================

WITH
-- Pin the query to the latest snapshot of each Iceberg table (Iceberg metadata
-- pattern from `docs/cvx-integration-contract.md` §6.1). The CTEs are scalar
-- subqueries — Athena evaluates them once at planning time.
c360_latest_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_customer_360."customer_360$snapshots"
),
chg_latest_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_charging_sessions."charging_sessions$snapshots"
),
eu_latest_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_energy_usage."energy_usage$snapshots"
),
window_dates AS (
    SELECT DATE '2026-05-29'                    AS hi,
           DATE '2026-05-29' - INTERVAL '30' DAY AS lo
),
-- Latest snapshot date for the customer_360 SCD-style snapshot table. The
-- partition column `snapshot_date` doubles as the SCD effective-date.
c360_latest_partition AS (
    SELECT MAX(snapshot_date) AS d
    FROM   adp_staging_customer_360.customer_360
),
target_cust AS (
    SELECT c.customer_id,
           c.full_name,
           c.primary_vin,
           c.lifetime_value_usd,
           c.customer_segment,
           c.total_charging_sessions_30d,
           c.total_kwh_consumed_30d
    FROM   adp_staging_customer_360.customer_360 c
    JOIN   c360_latest_partition lp ON c.snapshot_date = lp.d
    WHERE  c.customer_id = 'CUST-3F2504E0'    -- :customer_id
),
-- Per-network charging breakdown for the customer in the 30-day window.
-- Iceberg hidden-partition prune on `session_date` keeps scan bytes bounded.
chg_by_network AS (
    SELECT cs.customer_id,
           cs.station_type,
           COALESCE(cs.network_provider, 'unknown')   AS network_provider,
           COUNT(*)                                   AS sessions,
           SUM(cs.kwh_delivered)                      AS kwh,
           SUM(COALESCE(cs.cost_usd, DECIMAL '0.0'))  AS spend_usd,
           AVG(cs.peak_power_kw)                      AS avg_peak_power_kw,
           SUM(CASE WHEN cs.interrupted THEN 1 ELSE 0 END) AS aborted_sessions
    FROM   adp_staging_charging_sessions.charging_sessions cs
    JOIN   window_dates w ON cs.session_date BETWEEN w.lo AND w.hi
    WHERE  cs.customer_id = 'CUST-3F2504E0'   -- :customer_id
    GROUP BY cs.customer_id, cs.station_type, COALESCE(cs.network_provider, 'unknown')
),
-- Per-VIN efficiency over the same window. Energy usage rolls up per-day, so
-- AVG over `usage_date` is the natural aggregate.
eu_summary AS (
    SELECT eu.vin,
           AVG(eu.efficiency_kwh_per_100mi)  AS avg_eff_kwh_per_100mi,
           AVG(eu.ambient_temp_avg_c)        AS avg_ambient_c,
           AVG(eu.battery_pack_temp_avg_c)   AS avg_pack_temp_c,
           AVG(eu.state_of_health_pct)       AS avg_soh_pct,
           SUM(eu.total_kwh_consumed)        AS kwh_consumed,
           SUM(eu.total_kwh_charged)         AS kwh_charged_eu,
           SUM(eu.total_miles_driven)        AS miles
    FROM   adp_staging_energy_usage.energy_usage eu
    JOIN   window_dates w ON eu.usage_date BETWEEN w.lo AND w.hi
    WHERE  eu.vin = (SELECT primary_vin FROM target_cust)
    GROUP BY eu.vin
)
SELECT
    -- Customer attribution
    tc.customer_id,
    tc.full_name,
    tc.customer_segment,
    tc.lifetime_value_usd,
    tc.primary_vin,

    -- Per-network spend rollup
    chg.station_type,
    chg.network_provider,
    chg.sessions,
    chg.kwh                                 AS chg_kwh_delivered,
    chg.spend_usd                           AS chg_spend_usd,
    chg.aborted_sessions,
    chg.avg_peak_power_kw,

    -- Efficiency context (kWh/100mi — lower is better)
    eu.avg_eff_kwh_per_100mi,
    eu.avg_ambient_c,
    eu.avg_pack_temp_c,
    eu.avg_soh_pct,
    eu.miles                                AS miles_driven,

    -- Reconciliation: charging-side total vs energy-usage-side total. A large
    -- delta points to public-network sessions that didn't make it into the
    -- per-VIN energy_usage rollup (session billed to a different VIN, or
    -- ingest-skew per `data-contracts.md` → "Time and date conventions").
    chg.kwh - eu.kwh_charged_eu             AS reconcile_chg_kwh_minus_eu_kwh,

    -- Lineage / freshness — surfaces the snapshot pinned for this query.
    -- Pattern from `docs/cvx-integration-contract.md` §6.1.
    (SELECT committed_at FROM c360_latest_snap) AS c360_snapshot_committed_at,
    (SELECT committed_at FROM chg_latest_snap)  AS charging_snapshot_committed_at,
    (SELECT committed_at FROM eu_latest_snap)   AS energy_snapshot_committed_at
FROM   target_cust tc
LEFT JOIN chg_by_network chg ON tc.customer_id = chg.customer_id
LEFT JOIN eu_summary     eu  ON tc.primary_vin  = eu.vin
ORDER BY chg.spend_usd DESC NULLS LAST;
