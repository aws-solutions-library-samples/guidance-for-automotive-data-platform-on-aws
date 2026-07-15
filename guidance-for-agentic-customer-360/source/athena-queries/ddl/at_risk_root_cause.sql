-- View: at_risk_root_cause
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.at_risk_root_cause AS
SELECT
  customer_id
, health_score
, health_segment
, total_revenue
, avg_satisfaction_score
, total_cases
, open_cases
, total_service_appointments
, (CASE WHEN ((primary_root_cause = 'General Dissatisfaction') AND (contributing_factor = 'Open Cases')) THEN 'Unresolved Support Cases' WHEN ((primary_root_cause = 'General Dissatisfaction') AND (contributing_factor = 'Low Engagement')) THEN 'Poor Customer Experience' WHEN ((primary_root_cause = 'General Dissatisfaction') AND (contributing_factor = 'High Case Volume')) THEN 'Recurring Product Issues' WHEN (primary_root_cause = 'General Dissatisfaction') THEN 'Service Quality Issues' ELSE primary_root_cause END) primary_root_cause
, contributing_factor
, severity
, days_at_risk
, revenue_at_risk
FROM
  cx_analytics.at_risk_root_cause_cleaned;
