-- View: revenue_stream_growth
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.revenue_stream_growth AS
WITH
  current_month AS (
   SELECT
     revenue_stream
   , revenue
   FROM
     cx_analytics.revenue_breakdown_current
) 
, previous_month AS (
   SELECT
     'Vehicle Sales' revenue_stream
   , SUM(((CASE WHEN (customer_type = 'Commercial') THEN 3E-1 ELSE 7E-1 END) * ((43000 + (MONTH(purchase_date) * 200)) + ((YEAR(purchase_date) - 2021) * 500)))) revenue
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
ORDER BY revenue_change DESC
LIMIT 1;
