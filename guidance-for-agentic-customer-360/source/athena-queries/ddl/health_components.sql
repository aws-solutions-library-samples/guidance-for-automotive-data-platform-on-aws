-- View: health_components
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.health_components AS
SELECT
  'Satisfaction Score' component
, '50% (with surveys)' weight
, ROUND(AVG((CASE WHEN (avg_satisfaction_score > 0) THEN avg_satisfaction_score ELSE null END)), 1) avg_score
, COUNT((CASE WHEN (avg_satisfaction_score > 0) THEN 1 END)) customers_with_data
FROM
  cx_analytics.customer_health
UNION ALL SELECT
  'Support Health' component
, '30% (with surveys), 60% (without)' weight
, ROUND(AVG((CASE WHEN ((open_cases = 0) AND (total_cases <= 5)) THEN 8E0 WHEN (open_cases = 0) THEN 5E0 ELSE 3E0 END)), 1) avg_score
, COUNT(*) customers_with_data
FROM
  cx_analytics.customer_health
UNION ALL SELECT
  'Vehicle Engagement' component
, '15% (with surveys), 30% (without)' weight
, ROUND(AVG((CASE WHEN (total_vehicles >= 2) THEN 9E0 WHEN (total_vehicles = 1) THEN 7E0 ELSE 4E0 END)), 1) avg_score
, COUNT(*) customers_with_data
FROM
  cx_analytics.customer_health
UNION ALL SELECT
  'Service Activity' component
, '5% (with surveys), 10% (without)' weight
, ROUND(AVG((CASE WHEN (total_service_appointments > 10) THEN 8E0 WHEN (total_service_appointments > 5) THEN 6E0 WHEN (total_service_appointments > 0) THEN 5E0 ELSE 3E0 END)), 1) avg_score
, COUNT(*) customers_with_data
FROM
  cx_analytics.customer_health;
