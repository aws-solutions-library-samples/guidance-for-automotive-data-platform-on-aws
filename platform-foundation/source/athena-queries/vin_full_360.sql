-- ============================================================================
-- vin_full_360.sql
--
-- Purpose : "Everything we know about a VIN, in one query." — single triage /
--           escalation lookup that joins every product where the VIN is a
--           navigable identifier. Useful for grounding a Bedrock agent with
--           up-to-the-minute context, for service-team triage, or for fleet
--           ops investigating an outlier vehicle.
--
-- Joins   : The 8 Iceberg products that key on or reference VIN —
--             1. vehicle_identity              (1:1 with VIN)
--             2. customer_360                  (via primary_vin)
--             3. customer_interactions         (via vin, nullable on row)
--             4. service_records               (via vin)
--             5. charging_sessions             (via vin)
--             6. energy_usage                  (via vin)
--             7. ota_campaigns                 (via campaign_id ← ota_campaign_events.campaign_id)
--             8. ota_campaign_events           (via vin)
--
--           The 9th product is `vehicle_knowledge_base` — Bedrock-KB-ready
--           document chunks (storage_format `documents`, NOT Iceberg). KB
--           retrieval happens out-of-band via the Bedrock Agent Runtime API
--           (`bedrock-agent-runtime:Retrieve`) — see
--           `docs/cvx-integration-contract.md` §5 for the seed and retrieval
--           pattern. The S3 manifest is the closest SQL surface; if the
--           foundation has registered it as an Athena external table (Group 5
--           "Bedrock KB seeding extensions"), it appears as
--           `adp_staging_vehicle_knowledge_base.vehicle_knowledge_base_manifest`.
--           This query does NOT inline that table to keep the result row
--           shape stable; uncomment the `kb_facts` CTE and the corresponding
--           SELECT block if/when the Group 5 manifest table lands.
--
-- Engine  : Athena Engine V3, Trino dialect.
--
-- Stage   : Glue databases follow `adp_{stage}_<product>`. Replace `staging`
--           → `prod` verbatim for production.
--
-- Iceberg : Demonstrates Iceberg-snapshot-syntax in two ways:
--             (a) Per-product `$snapshots` reads to surface
--                 `last_committed_at` so the consumer knows which generator
--                 run produced the row (lineage; see
--                 `docs/cvx-integration-contract.md` §6.1).
--             (b) Optional `FOR TIMESTAMP AS OF` time-travel — uncomment the
--                 `AS OF TIMESTAMP TIMESTAMP '...'` clauses to query a
--                 specific snapshot of the data (Athena Engine V3 supports
--                 Iceberg time travel).
--
-- Params  : Replace
--             - :vin              (e.g. '1FA00000000033EK4')
--             - :short_window_lo  (e.g. DATE '2026-04-29' — 30-day rollups)
--             - :long_window_lo   (e.g. DATE '2025-05-29' — 12-month rollups)
--             - :long_window_ts   (e.g. TIMESTAMP '2026-05-15 00:00:00' —
--                                   recent telemetry boundary)
--           with literals at execution time. The query runs as-written if
--           you leave the example values in place.
-- ============================================================================

WITH
target AS (SELECT '1FA00000000033EK4' AS vin),    -- :vin (example synthetic)

-- ------------------------------------------------------------------
-- Snapshot pins (Iceberg metadata) — surfaced in the SELECT for lineage.
-- Pattern from `docs/cvx-integration-contract.md` §6.1.
-- ------------------------------------------------------------------
vi_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_vehicle_identity."vehicle_identity$snapshots"
),
c360_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_customer_360."customer_360$snapshots"
),
ci_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_customer_interactions."customer_interactions$snapshots"
),
sr_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_service_records."service_records$snapshots"
),
cs_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_charging_sessions."charging_sessions$snapshots"
),
eu_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_energy_usage."energy_usage$snapshots"
),
oc_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_ota_campaigns."ota_campaigns$snapshots"
),
oce_snap AS (
    SELECT MAX(committed_at) AS committed_at
    FROM   adp_staging_ota_campaigns."ota_campaign_events$snapshots"
),

-- ------------------------------------------------------------------
-- 1. vehicle_identity — 1:1 with VIN, the canonical "what is this vehicle?"
-- ------------------------------------------------------------------
identity AS (
    SELECT vi.vin,
           vi.make,
           vi.model,
           vi.trim,
           vi.model_year,
           vi.body_style,
           vi.drive_type,
           vi.powertrain_type,
           vi.battery_chemistry,
           vi.battery_pack_kwh,
           vi.battery_net_kwh,
           vi.motor_count,
           vi.max_charging_rate_kw,
           vi.connector_type,
           vi.range_epa_mi,
           vi.assembly_plant,
           vi.manufacture_date,
           vi.build_software_version,
           vi.current_software_version,
           vi.vss_version
    FROM   adp_staging_vehicle_identity.vehicle_identity vi
    JOIN   target t ON vi.vin = t.vin
),

-- ------------------------------------------------------------------
-- 2. customer_360 — owner facts at the latest snapshot_date partition.
-- ------------------------------------------------------------------
c360_latest_partition AS (
    SELECT MAX(snapshot_date) AS d
    FROM   adp_staging_customer_360.customer_360
),
owner AS (
    SELECT c.customer_id,
           c.full_name,
           c.email,
           c.phone,
           c.customer_segment,
           c.lifetime_value_usd,
           c.health_score,
           c.churn_probability,
           c.nps_score,
           c.total_charging_sessions_30d,
           c.total_kwh_consumed_30d,
           c.opted_in_marketing,
           c.created_at                 AS customer_created_at,
           c.snapshot_date              AS owner_snapshot_date
    FROM   adp_staging_customer_360.customer_360 c
    JOIN   c360_latest_partition lp ON c.snapshot_date = lp.d
    JOIN   target t ON c.primary_vin = t.vin
),

-- ------------------------------------------------------------------
-- 3. customer_interactions — recent 30-day contact history for the VIN's
--    owner (or for the VIN directly when the row carries `vin`).
-- ------------------------------------------------------------------
recent_interactions AS (
    SELECT COUNT(*)                                              AS interactions_30d,
           SUM(CASE WHEN ci.outcome = 'escalated' THEN 1 ELSE 0 END)
                                                                 AS escalations_30d,
           SUM(CASE WHEN ci.channel IN ('mobile_app_charging_issue',
                                        'ota_update_notification') THEN 1 ELSE 0 END)
                                                                 AS ev_themed_30d,
           AVG(ci.sentiment_score)                               AS avg_sentiment_30d,
           AVG(CAST(ci.csat_score AS DOUBLE))                    AS avg_csat_30d,
           MAX(ci.interaction_date)                              AS last_interaction_date
    FROM   adp_staging_customer_interactions.customer_interactions ci
    JOIN   target t ON ci.vin = t.vin
    WHERE  ci.interaction_date >= DATE '2026-04-29'   -- :short_window_lo
),

-- ------------------------------------------------------------------
-- 4. service_records — last 12 months of service visits for the VIN.
-- ------------------------------------------------------------------
recent_service AS (
    SELECT COUNT(*)                                              AS service_visits_12mo,
           SUM(CASE WHEN sr.service_type IN ('charging_system',
                                             'battery_replacement',
                                             'hv_battery_diagnostic')
                    THEN 1 ELSE 0 END)                           AS battery_charging_visits_12mo,
           SUM(CASE WHEN sr.service_type = 'safety_recall' THEN 1 ELSE 0 END)
                                                                 AS safety_recalls_12mo,
           SUM(CASE WHEN sr.linked_campaign_id IS NOT NULL THEN 1 ELSE 0 END)
                                                                 AS campaign_linked_visits_12mo,
           SUM(COALESCE(sr.total_cost_usd, DECIMAL '0.0'))       AS total_service_cost_usd,
           MAX(sr.service_date)                                  AS last_service_date
    FROM   adp_staging_service_records.service_records sr
    JOIN   target t ON sr.vin = t.vin
    WHERE  sr.service_date >= DATE '2025-05-29'   -- :long_window_lo
),

-- ------------------------------------------------------------------
-- 5. charging_sessions — 30-day rollup with network mix.
-- ------------------------------------------------------------------
recent_charging AS (
    SELECT COUNT(*)                                                AS sessions_30d,
           SUM(cs.kwh_delivered)                                   AS kwh_delivered_30d,
           SUM(COALESCE(cs.cost_usd, DECIMAL '0.0'))               AS spend_30d,
           SUM(CASE WHEN cs.station_type = 'public_dc_fast' THEN 1 ELSE 0 END)
                                                                   AS dc_fast_sessions_30d,
           SUM(CASE WHEN cs.interrupted THEN 1 ELSE 0 END)         AS aborted_sessions_30d,
           AVG(cs.peak_power_kw)                                   AS avg_peak_power_kw_30d,
           MAX(cs.session_date)                                    AS last_session_date
    FROM   adp_staging_charging_sessions.charging_sessions cs
    JOIN   target t ON cs.vin = t.vin
    WHERE  cs.session_date >= DATE '2026-04-29'   -- :short_window_lo
),

-- ------------------------------------------------------------------
-- 6. energy_usage — 30-day per-VIN-per-day rollup aggregated.
-- ------------------------------------------------------------------
recent_energy AS (
    SELECT MAX(eu.usage_date)                                     AS last_usage_date,
           SUM(eu.total_kwh_consumed)                             AS kwh_consumed_30d,
           SUM(eu.total_kwh_charged)                              AS kwh_charged_30d,
           SUM(eu.total_miles_driven)                             AS miles_30d,
           AVG(eu.efficiency_kwh_per_100mi)                       AS avg_eff_kwh_per_100mi,
           AVG(eu.state_of_health_pct)                            AS avg_soh_pct,
           MIN(eu.state_of_health_pct)                            AS min_soh_pct,
           AVG(eu.battery_pack_temp_avg_c)                        AS avg_pack_temp_c,
           AVG(eu.ambient_temp_avg_c)                             AS avg_ambient_c
    FROM   adp_staging_energy_usage.energy_usage eu
    JOIN   target t ON eu.vin = t.vin
    WHERE  eu.usage_date >= DATE '2026-04-29'   -- :short_window_lo
),

-- ------------------------------------------------------------------
-- 7+8. ota_campaigns + ota_campaign_events — lifetime OTA activity for the
-- VIN, joined against the campaign header for human-readable names.
-- ------------------------------------------------------------------
recent_ota AS (
    SELECT MAX(e.install_completed_time)                          AS last_install_at,
           COUNT(*)                                               AS ota_events_lifetime,
           SUM(CASE WHEN e.final_status = 'installed'      THEN 1 ELSE 0 END)
                                                                  AS ota_installed_lifetime,
           SUM(CASE WHEN e.final_status = 'install_failed' THEN 1 ELSE 0 END)
                                                                  AS ota_install_failures_lifetime,
           SUM(CASE WHEN e.final_status = 'rolled_back'    THEN 1 ELSE 0 END)
                                                                  AS ota_rollbacks_lifetime,
           SUM(CASE WHEN e.final_status = 'declined_by_user' THEN 1 ELSE 0 END)
                                                                  AS ota_declined_lifetime,
           SUM(CASE WHEN c.severity IN ('critical', 'high')
                       AND e.final_status NOT IN ('installed', 'rolled_back')
                    THEN 1 ELSE 0 END)                            AS ota_outstanding_critical_or_high
    FROM   adp_staging_ota_campaigns.ota_campaign_events e
    JOIN   target t ON e.vin = t.vin
    LEFT JOIN adp_staging_ota_campaigns.ota_campaigns c
           ON c.campaign_id = e.campaign_id
)

-- ------------------------------------------------------------------
-- Final projection — denormalized "everything about a VIN" row.
-- ------------------------------------------------------------------
SELECT
    -- 1. Vehicle identity
    i.vin,
    i.make, i.model, i.trim, i.model_year,
    i.body_style, i.drive_type, i.powertrain_type,
    i.battery_chemistry, i.battery_pack_kwh, i.battery_net_kwh,
    i.motor_count, i.max_charging_rate_kw, i.connector_type,
    i.range_epa_mi, i.assembly_plant, i.manufacture_date,
    i.build_software_version, i.current_software_version, i.vss_version,

    -- 2. Owner
    o.customer_id, o.full_name, o.customer_segment,
    o.lifetime_value_usd, o.health_score, o.churn_probability,
    o.nps_score, o.opted_in_marketing,
    o.owner_snapshot_date,

    -- 3. Recent interactions
    ri.interactions_30d, ri.escalations_30d, ri.ev_themed_30d,
    ri.avg_sentiment_30d, ri.avg_csat_30d, ri.last_interaction_date,

    -- 4. Recent service
    rs.service_visits_12mo, rs.battery_charging_visits_12mo,
    rs.safety_recalls_12mo, rs.campaign_linked_visits_12mo,
    rs.total_service_cost_usd, rs.last_service_date,

    -- 5. Recent charging
    rc.sessions_30d, rc.kwh_delivered_30d, rc.spend_30d,
    rc.dc_fast_sessions_30d, rc.aborted_sessions_30d,
    rc.avg_peak_power_kw_30d, rc.last_session_date,

    -- 6. Recent energy
    re.last_usage_date, re.kwh_consumed_30d, re.kwh_charged_30d,
    re.miles_30d, re.avg_eff_kwh_per_100mi,
    re.avg_soh_pct, re.min_soh_pct,
    re.avg_pack_temp_c, re.avg_ambient_c,

    -- 7+8. Recent OTA
    ro.last_install_at, ro.ota_events_lifetime,
    ro.ota_installed_lifetime, ro.ota_install_failures_lifetime,
    ro.ota_rollbacks_lifetime, ro.ota_declined_lifetime,
    ro.ota_outstanding_critical_or_high,

    -- Lineage / freshness — Iceberg snapshot pins (one per joined product).
    -- See `docs/cvx-integration-contract.md` §6.1 for the pattern.
    (SELECT committed_at FROM vi_snap)   AS vehicle_identity_snapshot_at,
    (SELECT committed_at FROM c360_snap) AS customer_360_snapshot_at,
    (SELECT committed_at FROM ci_snap)   AS customer_interactions_snapshot_at,
    (SELECT committed_at FROM sr_snap)   AS service_records_snapshot_at,
    (SELECT committed_at FROM cs_snap)   AS charging_sessions_snapshot_at,
    (SELECT committed_at FROM eu_snap)   AS energy_usage_snapshot_at,
    (SELECT committed_at FROM oc_snap)   AS ota_campaigns_snapshot_at,
    (SELECT committed_at FROM oce_snap)  AS ota_campaign_events_snapshot_at,

    -- vehicle_knowledge_base lookup is OUT OF BAND. Use the Bedrock Agent
    -- Runtime `Retrieve` API filtered by `source_category` — see
    -- `docs/cvx-integration-contract.md` §5.3. Surface this as a dummy
    -- column for downstream callers that template the result row.
    'use bedrock-agent-runtime:Retrieve, see cvx-integration-contract §5.3'
                                            AS vehicle_knowledge_base_lookup_hint
FROM   identity i
LEFT JOIN owner               o  ON true
LEFT JOIN recent_interactions ri ON true
LEFT JOIN recent_service      rs ON true
LEFT JOIN recent_charging     rc ON true
LEFT JOIN recent_energy       re ON true
LEFT JOIN recent_ota          ro ON true;

-- ============================================================================
-- Optional time-travel variant (Iceberg `FOR TIMESTAMP AS OF`)
-- ----------------------------------------------------------------------------
-- To pin every Iceberg read to a specific historical snapshot (e.g. for a
-- reproducible audit query), substitute each table reference with the
-- AS-OF form. Athena Engine V3 supports both timestamp- and snapshot-id-
-- based time travel for Iceberg. Example for `vehicle_identity`:
--
--   FROM adp_staging_vehicle_identity.vehicle_identity
--        FOR TIMESTAMP AS OF TIMESTAMP '2026-05-29 12:00:00'
--
-- Or by snapshot id (resolve via the `$snapshots` metadata table):
--
--   FROM adp_staging_vehicle_identity.vehicle_identity
--        FOR VERSION AS OF 1234567890123456789
--
-- See `docs/cvx-integration-contract.md` §6 for the full lineage pattern
-- (Iceberg metadata tables: $snapshots, $history, $files, $partitions,
-- $manifests).
-- ============================================================================
