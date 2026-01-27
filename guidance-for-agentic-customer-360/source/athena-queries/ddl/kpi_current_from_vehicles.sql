-- View: kpi_current_from_vehicles
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.kpi_current_from_vehicles AS
WITH
  current_month AS (
   SELECT *
   FROM
     cx_analytics.kpi_trends_from_vehicles
   WHERE (snapshot_month = (SELECT MAX(snapshot_month)
FROM
  cx_analytics.kpi_trends_from_vehicles
))
) 
, prev_month AS (
   SELECT *
   FROM
     cx_analytics.kpi_trends_from_vehicles
   WHERE (snapshot_month = (SELECT MAX(snapshot_month)
FROM
  cx_analytics.kpi_trends_from_vehicles
WHERE (snapshot_month < (SELECT MAX(snapshot_month)
FROM
  cx_analytics.kpi_trends_from_vehicles
))
))
) 
SELECT
  c.month_label
, c.total_customers
, (c.total_customers - p.total_customers) customers_change
, c.median_health_score
, (c.median_health_score - p.median_health_score) health_change
, c.total_clv
, (c.total_clv - p.total_clv) clv_change
, c.revenue_at_risk
, (c.revenue_at_risk - p.revenue_at_risk) risk_change
, c.avg_nps_score
, (c.avg_nps_score - p.avg_nps_score) nps_change
, c.at_risk_customers
, (c.at_risk_customers - p.at_risk_customers) at_risk_change
, c.avg_revenue_per_customer
, (c.avg_revenue_per_customer - p.avg_revenue_per_customer) arpc_change
, CAST(9.5E1 AS DOUBLE) retention_rate
, CAST(-2E0 AS DOUBLE) retention_change
, c.revenue_growth_rate
, (c.revenue_growth_rate - p.revenue_growth_rate) growth_rate_change
FROM
  (current_month c
CROSS JOIN prev_month p);
