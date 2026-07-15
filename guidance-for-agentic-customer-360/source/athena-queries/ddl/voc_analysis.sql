-- View: voc_analysis
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.voc_analysis AS
SELECT
  customer_id
, (avg_satisfaction_score * 20) nps_score
, (CASE WHEN (avg_satisfaction_score >= 4.5E0) THEN 'Promoter' WHEN (avg_satisfaction_score >= 3.5E0) THEN 'Passive' ELSE 'Detractor' END) nps_category
, total_cases feedback_count
, open_cases unresolved_issues
, (CASE WHEN (open_cases > 2) THEN 'Service Quality' WHEN (total_cases > 5) THEN 'Response Time' WHEN ((avg_satisfaction_score < 3) AND (total_service_appointments >= 4)) THEN 'Vehicle Reliability' WHEN ((avg_satisfaction_score < 3) AND (total_service_appointments < 2)) THEN 'Onboarding Issues' WHEN (total_service_appointments >= 5) THEN 'Maintenance Frequency' WHEN ((total_cases >= 3) AND (open_cases <= 1)) THEN 'Resolved Issues' ELSE 'Product Experience' END) primary_concern
, (CASE WHEN (avg_satisfaction_score >= 4) THEN 'Positive' WHEN (avg_satisfaction_score >= 3) THEN 'Neutral' ELSE 'Negative' END) sentiment
, health_score
, health_segment
, total_revenue
FROM
  cx_analytics.customer_health_clean;
