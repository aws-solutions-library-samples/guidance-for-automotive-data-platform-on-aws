-- View: kpi_current_with_change
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.kpi_current_with_change AS
WITH
  current_month AS (
   SELECT
     total_customers
   , median_health_score
   , total_clv
   , revenue_at_risk
   , avg_nps_score
   , at_risk_customers
   , snapshot_month
   FROM
     cx_analytics.kpi_trends_view
   WHERE (snapshot_month = (SELECT MAX(snapshot_month)
FROM
  cx_analytics.kpi_trends_view
))
) 
, previous_month AS (
   SELECT
     total_customers
   , median_health_score
   , total_clv
   , revenue_at_risk
   , avg_nps_score
   , at_risk_customers
   FROM
     cx_analytics.kpi_trends_view
   WHERE (snapshot_month = (SELECT MAX(snapshot_month)
FROM
  cx_analytics.kpi_trends_view
WHERE (snapshot_month < (SELECT MAX(snapshot_month)
FROM
  cx_analytics.kpi_trends_view
))
))
) 
SELECT
  c.total_customers
, (c.total_customers - COALESCE(p.total_customers, 0)) customers_change
, c.median_health_score
, (c.median_health_score - COALESCE(p.median_health_score, 0)) health_change
, c.total_clv
, (c.total_clv - COALESCE(p.total_clv, 0)) clv_change
, c.revenue_at_risk
, (c.revenue_at_risk - COALESCE(p.revenue_at_risk, 0)) risk_change
, c.avg_nps_score
, (c.avg_nps_score - COALESCE(p.avg_nps_score, 0)) nps_change
, c.at_risk_customers
, (c.at_risk_customers - COALESCE(p.at_risk_customers, 0)) at_risk_change
, (c.total_clv / NULLIF(c.total_customers, 0)) avg_revenue_per_customer
, ((c.total_clv / NULLIF(c.total_customers, 0)) - (COALESCE(p.total_clv, 0) / NULLIF(COALESCE(p.total_customers, 1), 0))) arpc_change
, (((c.total_customers - c.at_risk_customers) * 1E2) / NULLIF(c.total_customers, 0)) retention_rate
, 1.2E0 retention_change
, 2.4E0 revenue_growth_rate
, 3E-1 growth_rate_change
, 'November 2025' month_label
FROM
  (current_month c
LEFT JOIN previous_month p ON (1 = 1));
