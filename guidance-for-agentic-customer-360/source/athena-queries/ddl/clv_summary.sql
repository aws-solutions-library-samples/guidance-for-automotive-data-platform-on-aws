-- View: clv_summary
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.clv_summary AS
SELECT
  value_tier
, COUNT(*) customer_count
, ROUND(AVG(actual_clv), 2) avg_clv
, ROUND(SUM(actual_clv), 2) total_clv
, ROUND(AVG(predicted_clv_3yr), 2) avg_predicted_clv
, ROUND(AVG(annual_value), 2) avg_annual_value
FROM
  clv_analysis
GROUP BY value_tier;
