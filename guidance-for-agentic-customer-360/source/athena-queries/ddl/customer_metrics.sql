-- View: customer_metrics
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.customer_metrics AS
SELECT
  COUNT(DISTINCT customer_id) total_customers
, SUM(total_revenue) total_revenue
, AVG(health_score) avg_health_score
, SUM((CASE WHEN (health_segment IN ('At-Risk', 'Needs Attention', 'Critical')) THEN total_revenue ELSE 0 END)) at_risk_revenue
, COUNT((CASE WHEN (health_segment IN ('At-Risk', 'Needs Attention', 'Critical')) THEN 1 END)) at_risk_customers
FROM
  cx_analytics.customer_health;
