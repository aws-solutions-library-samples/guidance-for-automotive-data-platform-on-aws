-- View: recovery_opportunities
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.recovery_opportunities AS
SELECT
  health_segment
, COUNT(*) customers
, SUM(total_revenue) revenue_impact
, (CASE WHEN (health_segment = 'At-Risk') THEN 7 WHEN (health_segment = 'Needs Attention') THEN 8 WHEN (health_segment = 'Critical') THEN 4 WHEN (health_segment = 'Stable') THEN 6 ELSE 3 END) ease_to_improve
, AVG(health_score) current_health
, (CASE WHEN (health_segment = 'At-Risk') THEN 65 WHEN (health_segment = 'Needs Attention') THEN 70 WHEN (health_segment = 'Critical') THEN 55 WHEN (health_segment = 'Stable') THEN 75 ELSE 80 END) target_health
FROM
  customer_health
GROUP BY health_segment;
