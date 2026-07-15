-- View: support_cases_detail
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.support_cases_detail AS
SELECT
  ci.customer_id
, ci.interaction_id case_id
, ci.interaction_date case_date
, DATE_TRUNC('month', ci.interaction_date) month_date
, ci.topic case_category
, (CASE WHEN (ci.topic = 'battery_degradation') THEN (CASE WHEN (RAND() < 3E-1) THEN 'Customer reports battery range decreased from 300 miles to 220 miles. Battery health check needed.' WHEN (RAND() < 6E-1) THEN 'Significant battery degradation observed. Range anxiety reported. Charge time increased.' ELSE 'Battery performance below expected. Customer experiencing reduced range and longer charge times.' END) WHEN (ci.topic = 'charging_issues') THEN (CASE WHEN (RAND() < 3E-1) THEN 'Vehicle not charging properly. Charge time exceeds normal duration. Battery may be affected.' WHEN (RAND() < 6E-1) THEN 'Charging speed significantly reduced. Customer reports extended charge time at home and public stations.' ELSE 'Intermittent charging problems. Battery not reaching full capacity. Range impacted.' END) ELSE ci.notes END) case_notes
, ci.resolution_status
, ci.sentiment_score
, ci.channel
FROM
  customer_interactions ci
WHERE ((ci.interaction_type = 'support_case') AND (ci.interaction_date >= DATE '2025-01-01'));
