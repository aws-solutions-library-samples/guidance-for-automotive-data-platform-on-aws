-- View: operational_kpis_with_health
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.operational_kpis_with_health AS
SELECT
  *
, (100 - (((100 - first_contact_resolution_rate) + (avg_case_resolution_days * 5)) + (warranty_claim_rate * 3))) operational_health_score
FROM
  operational_kpis;
