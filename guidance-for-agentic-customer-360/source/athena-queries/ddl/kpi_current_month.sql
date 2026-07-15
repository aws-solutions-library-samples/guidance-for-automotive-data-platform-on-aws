-- View: kpi_current_month
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.kpi_current_month AS
SELECT
  snapshot_month
, month_label
, total_customers
, median_health_score
, total_clv
, revenue_at_risk
, avg_nps_score
, at_risk_customers
, revenue_growth_rate
, avg_revenue_per_customer
FROM
  kpi_trends_from_vehicles
WHERE (snapshot_month = (SELECT MAX(snapshot_month)
FROM
  kpi_trends_from_vehicles
));
