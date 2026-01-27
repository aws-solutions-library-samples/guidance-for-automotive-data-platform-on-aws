-- View: revenue_leakage
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.revenue_leakage AS
SELECT
  health_segment
, ROUND(AVG(total_revenue), 2) avg_revenue_per_customer
, COUNT(*) customer_count
, SUM(total_revenue) total_revenue
, AVG(health_score) avg_health
FROM
  customer_health
GROUP BY health_segment;
