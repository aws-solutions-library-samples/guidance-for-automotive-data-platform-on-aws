-- View: churn_prediction
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.churn_prediction AS
SELECT
  customer_id
, health_score
, health_segment
, total_revenue
, (CASE WHEN (health_score < 25) THEN 'Critical Risk' WHEN (health_score < 30) THEN 'High Risk' WHEN (health_score < 35) THEN 'Medium Risk' ELSE 'Low Risk' END) churn_risk
, (CASE WHEN (health_score < 25) THEN 7E-1 WHEN (health_score < 30) THEN 4.5E-1 WHEN (health_score < 35) THEN 2E-1 ELSE 5E-2 END) churn_probability
, (CASE WHEN (health_score < 35) THEN 1 ELSE 0 END) churn_indicator
, (total_revenue * (CASE WHEN (health_score < 25) THEN 7E-1 WHEN (health_score < 30) THEN 4.5E-1 WHEN (health_score < 35) THEN 2E-1 ELSE 5E-2 END)) expected_loss
FROM
  cx_analytics.customer_health_clean
WHERE (health_score < 35);
