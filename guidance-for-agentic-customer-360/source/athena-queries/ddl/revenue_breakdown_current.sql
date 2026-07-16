-- View: revenue_breakdown_current
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.revenue_breakdown_current AS
WITH
  latest_month AS (
   SELECT MAX(month_date) max_date
   FROM
     cx_analytics.total_revenue_by_month
) 
, commercial_vehicle_sales AS (
   SELECT SUM(((43000 + (MONTH(purchase_date) * 200)) + ((YEAR(purchase_date) - 2021) * 500))) revenue
   FROM
     cx_analytics.vehicles_with_customer_type
   WHERE ((DATE_TRUNC('month', purchase_date) = (SELECT max_date
FROM
  latest_month
)) AND (customer_type = 'Commercial') AND (((YEAR(purchase_date) = 2021) AND (MOD(vehicle_id, 100) < 65)) OR ((YEAR(purchase_date) = 2022) AND (MOD(vehicle_id, 100) < 80)) OR ((YEAR(purchase_date) = 2023) AND (MOD(vehicle_id, 100) < 95)) OR (YEAR(purchase_date) = 2024) OR ((YEAR(purchase_date) = 2025) AND (MOD(vehicle_id, 100) < 90))))
) 
, individual_vehicle_sales AS (
   SELECT SUM(((43000 + (MONTH(purchase_date) * 200)) + ((YEAR(purchase_date) - 2021) * 500))) revenue
   FROM
     cx_analytics.vehicles_with_customer_type
   WHERE ((DATE_TRUNC('month', purchase_date) = (SELECT max_date
FROM
  latest_month
)) AND (customer_type = 'Individual') AND (((YEAR(purchase_date) = 2021) AND (MOD(vehicle_id, 100) < 65)) OR ((YEAR(purchase_date) = 2022) AND (MOD(vehicle_id, 100) < 80)) OR ((YEAR(purchase_date) = 2023) AND (MOD(vehicle_id, 100) < 95)) OR (YEAR(purchase_date) = 2024) OR ((YEAR(purchase_date) = 2025) AND (MOD(vehicle_id, 100) < 90))))
) 
, current_revenue AS (
   SELECT
     service_revenue
   , subscription_revenue
   , financing_revenue
   , warranty_revenue
   FROM
     cx_analytics.total_revenue_by_month
   WHERE (month_date = (SELECT max_date
FROM
  latest_month
))
) 
SELECT
  'Commercial Sales' revenue_stream
, (SELECT revenue
FROM
  commercial_vehicle_sales
) revenue

UNION ALL SELECT
  'Individual Sales'
, (SELECT revenue
FROM
  individual_vehicle_sales
)

UNION ALL SELECT
  'Service & Parts'
, service_revenue
FROM
  current_revenue
UNION ALL SELECT
  'Financing'
, financing_revenue
FROM
  current_revenue
UNION ALL SELECT
  'Subscriptions'
, subscription_revenue
FROM
  current_revenue
UNION ALL SELECT
  'Warranty'
, warranty_revenue
FROM
  current_revenue;
