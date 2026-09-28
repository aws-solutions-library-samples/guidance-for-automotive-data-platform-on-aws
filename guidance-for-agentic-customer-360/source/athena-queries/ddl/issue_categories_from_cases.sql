-- View: issue_categories_from_cases
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.issue_categories_from_cases AS
SELECT
  DATE_TRUNC('month', interaction_date) month_date
, DATE_FORMAT(DATE_TRUNC('month', interaction_date), '%b %Y') month_label
, SUM((CASE WHEN (topic IN ('battery_degradation', 'charging_issues')) THEN 1 ELSE 0 END)) battery_cases
, SUM((CASE WHEN (topic = 'software_problems') THEN 1 ELSE 0 END)) software_cases
, COUNT(*) total_cases
FROM
  customer_interactions
WHERE ((interaction_type = 'support_case') AND (interaction_date >= DATE '2025-01-01'))
GROUP BY DATE_TRUNC('month', interaction_date);
