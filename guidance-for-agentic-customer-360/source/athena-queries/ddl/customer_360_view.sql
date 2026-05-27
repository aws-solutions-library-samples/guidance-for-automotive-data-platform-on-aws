-- View: customer_360_view
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.customer_360_view AS
SELECT
  ch.customer_id
, ch.health_score
, ch.health_segment
, ch.total_revenue clv
, ch.avg_satisfaction_score
, ch.total_cases
, ch.open_cases
, ch.total_vehicles
, ch.total_service_spend
, ch.total_service_appointments
, COUNT(DISTINCT (CASE WHEN (ci.topic IN ('battery_degradation', 'charging_issues')) THEN ci.interaction_id END)) battery_related_cases
, MAX(ci.interaction_date) last_interaction_date
, AVG(ci.sentiment_score) avg_sentiment
, MIN(v.purchase_date) first_purchase_date
, MAX(v.purchase_date) last_purchase_date
FROM
  ((customer_health ch
LEFT JOIN dms_lakehouse.vehicles_bronze v ON (ch.customer_id = v.user_id))
LEFT JOIN customer_interactions ci ON (ch.customer_id = ci.customer_id))
GROUP BY ch.customer_id, ch.health_score, ch.health_segment, ch.total_revenue, ch.avg_satisfaction_score, ch.total_cases, ch.open_cases, ch.total_vehicles, ch.total_service_spend, ch.total_service_appointments;
