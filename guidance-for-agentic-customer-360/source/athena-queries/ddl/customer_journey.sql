-- View: customer_journey
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.customer_journey AS
SELECT
  customer_id
, (CASE WHEN (total_service_appointments = 0) THEN 'Awareness' WHEN (total_service_appointments = 1) THEN 'Acquisition' WHEN (total_service_appointments <= 3) THEN 'Onboarding' WHEN (health_score >= 70) THEN 'Loyalty' WHEN (health_score < 50) THEN 'At-Risk' ELSE 'Active' END) journey_stage
, CAST(FLOOR((RAND() * 1000)) AS INTEGER) days_since_purchase
, health_score
, health_segment
, total_revenue
FROM
  cx_analytics.customer_health_clean;
