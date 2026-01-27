-- View: top_revenue_stream
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.top_revenue_stream AS
WITH
  current_month AS (
   SELECT
     (CASE WHEN (revenue_stream IN ('Commercial Sales', 'Individual Sales')) THEN 'Vehicle Sales' ELSE revenue_stream END) revenue_stream
   , SUM(revenue) revenue
   FROM
     cx_analytics.revenue_breakdown_current
   GROUP BY (CASE WHEN (revenue_stream IN ('Commercial Sales', 'Individual Sales')) THEN 'Vehicle Sales' ELSE revenue_stream END)
) 
, previous_month AS (
   SELECT
     'Vehicle Sales' revenue_stream
   , SUM(((43000 + (MONTH(purchase_date) * 200)) + ((YEAR(purchase_date) - 2021) * 500))) revenue
   FROM
     cx_analytics.vehicles_with_customer_type
   WHERE (DATE_TRUNC('month', purchase_date) = DATE_ADD('month', -1, DATE_TRUNC('month', current_date)))
UNION ALL    SELECT
     'Service & Parts'
   , SUM(revenue)
   FROM
     cx_analytics.service_revenue
   WHERE (DATE_TRUNC('month', service_date) = DATE_ADD('month', -1, DATE_TRUNC('month', current_date)))
UNION ALL    SELECT
     'Financing'
   , SUM(interest_revenue)
   FROM
     cx_analytics.financing_revenue
   WHERE (DATE_TRUNC('month', payment_date) = DATE_ADD('month', -1, DATE_TRUNC('month', current_date)))
UNION ALL    SELECT
     'Subscriptions'
   , SUM(monthly_revenue)
   FROM
     cx_analytics.subscription_revenue
   WHERE (DATE_TRUNC('month', billing_date) = DATE_ADD('month', -1, DATE_TRUNC('month', current_date)))
UNION ALL    SELECT
     'Warranty'
   , SUM(warranty_revenue)
   FROM
     cx_analytics.warranty_revenue
   WHERE (DATE_TRUNC('month', sale_date) = DATE_ADD('month', -1, DATE_TRUNC('month', current_date)))
) 
SELECT
  c.revenue_stream
, c.revenue current_revenue
, p.revenue previous_revenue
, (c.revenue - p.revenue) revenue_change
, (((c.revenue - p.revenue) * 1E2) / NULLIF(p.revenue, 0)) growth_rate
FROM
  (current_month c
LEFT JOIN previous_month p ON (c.revenue_stream = p.revenue_stream))
ORDER BY growth_rate DESC
LIMIT 1;
