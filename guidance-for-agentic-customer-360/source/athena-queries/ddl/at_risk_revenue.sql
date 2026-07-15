-- View: at_risk_revenue
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.at_risk_revenue AS
WITH
  nps_detractors AS (
   SELECT
     customer_id
   , DATE_TRUNC('month', survey_date) survey_month
   FROM
     cx_analytics.nps_surveys
   WHERE (survey_date >= DATE_ADD('month', -6, current_date))
   GROUP BY customer_id, DATE_TRUNC('month', survey_date)
   HAVING (MAX(nps_score) <= 6)
) 
, vehicles_at_risk AS (
   SELECT
     n.survey_month
   , v.user_id
   , v.vehicle_id
   , v.customer_type
   , ((43000 + (MONTH(v.purchase_date) * 200)) + ((YEAR(v.purchase_date) - 2021) * 500)) vehicle_revenue
   FROM
     (cx_analytics.vehicles_with_customer_type v
   INNER JOIN nps_detractors n ON (v.user_id = n.customer_id))
   WHERE (v.purchase_date >= DATE_ADD('year', -1, current_date))
) 
, service_rev AS (
   SELECT
     vehicle_id
   , SUM(revenue) annual_revenue
   FROM
     cx_analytics.service_revenue
   WHERE (YEAR(service_date) = YEAR(current_date))
   GROUP BY vehicle_id
) 
, subscription_rev AS (
   SELECT
     vehicle_id
   , SUM(monthly_revenue) annual_revenue
   FROM
     cx_analytics.subscription_revenue
   WHERE (YEAR(billing_date) = YEAR(current_date))
   GROUP BY vehicle_id
) 
, financing_rev AS (
   SELECT
     vehicle_id
   , SUM(interest_revenue) annual_revenue
   FROM
     cx_analytics.financing_revenue
   WHERE (YEAR(payment_date) = YEAR(current_date))
   GROUP BY vehicle_id
) 
, warranty_rev AS (
   SELECT
     vehicle_id
   , SUM(warranty_revenue) annual_revenue
   FROM
     cx_analytics.warranty_revenue
   WHERE (YEAR(sale_date) = YEAR(current_date))
   GROUP BY vehicle_id
) 
SELECT
  v.survey_month month_date
, DATE_FORMAT(v.survey_month, '%b %Y') month_label
, v.customer_type
, COUNT(DISTINCT v.user_id) at_risk_customers
, SUM(v.vehicle_revenue) vehicle_sales_at_risk
, SUM(COALESCE(s.annual_revenue, 0)) service_revenue_at_risk
, SUM(COALESCE(sub.annual_revenue, 0)) subscription_revenue_at_risk
, SUM(COALESCE(f.annual_revenue, 0)) financing_revenue_at_risk
, SUM(COALESCE(w.annual_revenue, 0)) warranty_revenue_at_risk
, SUM(((((v.vehicle_revenue + COALESCE(s.annual_revenue, 0)) + COALESCE(sub.annual_revenue, 0)) + COALESCE(f.annual_revenue, 0)) + COALESCE(w.annual_revenue, 0))) total_revenue_at_risk
FROM
  ((((vehicles_at_risk v
LEFT JOIN service_rev s ON (v.vehicle_id = s.vehicle_id))
LEFT JOIN subscription_rev sub ON (v.vehicle_id = sub.vehicle_id))
LEFT JOIN financing_rev f ON (v.vehicle_id = f.vehicle_id))
LEFT JOIN warranty_rev w ON (v.vehicle_id = w.vehicle_id))
GROUP BY v.survey_month, v.customer_type;
