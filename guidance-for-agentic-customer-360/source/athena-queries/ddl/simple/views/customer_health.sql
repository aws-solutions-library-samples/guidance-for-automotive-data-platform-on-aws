-- View: customer_health (QuickSight expects this name)
CREATE OR REPLACE VIEW cx_analytics.customer_health AS
SELECT
  customer_id,
  customer_id as user_id,
  clv as total_revenue,
  satisfaction_score as avg_satisfaction_score,
  CAST(total_cases AS DOUBLE) as total_cases,
  CAST(open_cases AS DOUBLE) as open_cases,
  CAST(1 AS DOUBLE) as total_vehicles,
  total_service_spend,
  CAST(total_service_appointments AS DOUBLE) as total_service_appointments,
  CAST(0 AS DOUBLE) as opportunity_count,
  health_score,
  health_segment
FROM cx_analytics.customer_health_scores;
