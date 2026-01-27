-- View: clv_analysis
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.clv_analysis AS
SELECT
  customer_id
, (total_revenue * 3.5E0) actual_clv
, total_revenue annual_value
, (total_revenue * 4.2E0) predicted_clv_3yr
, health_score
, health_segment
, total_revenue
, (CASE WHEN (total_revenue >= 10000) THEN 'B2B Fleet' WHEN (total_revenue >= 4000) THEN 'B2C Premium' WHEN (total_revenue >= 2000) THEN 'B2C Standard' ELSE 'B2C Entry' END) customer_type
, (CASE WHEN ((total_revenue >= 10000) AND (health_score >= 70)) THEN 'Strategic Account - Expand' WHEN ((total_revenue >= 10000) AND (health_score < 70)) THEN 'Strategic Account - At Risk' WHEN ((total_revenue >= 4000) AND (health_score >= 70)) THEN 'Brand Ambassador' WHEN ((total_revenue >= 4000) AND (health_score < 70)) THEN 'Premium - Needs Attention' WHEN ((total_revenue >= 2000) AND (health_score >= 60)) THEN 'Loyal Customer' WHEN ((total_revenue >= 2000) AND (health_score < 60)) THEN 'Retention Focus' WHEN ((total_revenue < 2000) AND (health_score >= 60)) THEN 'Growth Opportunity' ELSE 'Win-Back or Churn' END) strategic_segment
, (CASE WHEN (total_revenue >= 10000) THEN 'Enterprise' WHEN (total_revenue >= 4000) THEN 'Premium' WHEN (total_revenue >= 2000) THEN 'Standard' ELSE 'Entry' END) value_tier
FROM
  cx_analytics.customer_health_clean;
