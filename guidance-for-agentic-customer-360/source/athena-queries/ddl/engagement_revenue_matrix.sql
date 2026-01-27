-- View: engagement_revenue_matrix
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.engagement_revenue_matrix AS
SELECT
  (CASE WHEN (total_vehicles = 0) THEN 'No Vehicles' WHEN (total_vehicles = 1) THEN '1 Vehicle' ELSE '2+ Vehicles' END) vehicle_segment
, (CASE WHEN (total_service_appointments = 0) THEN 'None' WHEN (total_service_appointments BETWEEN 1 AND 5) THEN 'Low (1-5)' WHEN (total_service_appointments BETWEEN 6 AND 10) THEN 'Medium (6-10)' ELSE 'High (10+)' END) service_segment
, COUNT(*) customer_count
, ROUND(AVG(total_revenue), 2) avg_revenue
, ROUND(AVG(health_score), 2) avg_health
FROM
  customer_health
GROUP BY (CASE WHEN (total_vehicles = 0) THEN 'No Vehicles' WHEN (total_vehicles = 1) THEN '1 Vehicle' ELSE '2+ Vehicles' END), (CASE WHEN (total_service_appointments = 0) THEN 'None' WHEN (total_service_appointments BETWEEN 1 AND 5) THEN 'Low (1-5)' WHEN (total_service_appointments BETWEEN 6 AND 10) THEN 'Medium (6-10)' ELSE 'High (10+)' END);
