-- View: churn_risk
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.churn_risk AS
SELECT
  health_segment
, COUNT(*) customers
, SUM(total_revenue) revenue_at_risk
, (CASE WHEN (health_segment = 'Critical') THEN 4.5E-1 WHEN (health_segment = 'At-Risk') THEN 3E-1 WHEN (health_segment = 'Needs Attention') THEN 2E-1 WHEN (health_segment = 'Stable') THEN 1E-1 ELSE 5E-2 END) churn_probability
, (SUM(total_revenue) * (CASE WHEN (health_segment = 'Critical') THEN 4.5E-1 WHEN (health_segment = 'At-Risk') THEN 3E-1 WHEN (health_segment = 'Needs Attention') THEN 2E-1 WHEN (health_segment = 'Stable') THEN 1E-1 ELSE 5E-2 END)) expected_revenue_loss
FROM
  customer_health
GROUP BY health_segment;
