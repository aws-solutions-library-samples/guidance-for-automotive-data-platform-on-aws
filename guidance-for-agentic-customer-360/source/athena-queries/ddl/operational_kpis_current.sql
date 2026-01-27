-- View: operational_kpis_current
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.operational_kpis_current AS
SELECT *
FROM
  operational_kpis
WHERE (month_date >= DATE_ADD('month', -1, (SELECT MAX(month_date)
FROM
  operational_kpis
)));
