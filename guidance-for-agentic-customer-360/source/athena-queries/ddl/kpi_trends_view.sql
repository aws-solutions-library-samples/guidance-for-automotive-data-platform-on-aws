-- View: kpi_trends_view
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.kpi_trends_view AS
SELECT
  DATE_FORMAT(snapshot_month, '%Y-%m') month_label
, snapshot_month
, total_customers
, median_health_score
, total_clv
, revenue_at_risk
, avg_nps_score
, at_risk_customers
, revenue_growth_rate
, avg_revenue_per_customer
FROM
  cx_analytics.kpi_trends_with_arpc
ORDER BY snapshot_month ASC;
