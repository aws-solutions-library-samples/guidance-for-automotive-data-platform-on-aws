-- View: journey_summary
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.journey_summary AS
SELECT
  journey_stage
, COUNT(*) customer_count
, ROUND(AVG(health_score), 2) avg_health
, ROUND(AVG(touchpoints), 2) avg_touchpoints
, ROUND(SUM(total_revenue), 2) total_revenue
, ROUND(AVG(avg_satisfaction_score), 2) avg_satisfaction
FROM
  customer_journey
GROUP BY journey_stage;
