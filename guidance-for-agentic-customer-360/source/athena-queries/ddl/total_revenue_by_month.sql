-- View: total_revenue_by_month
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.total_revenue_by_month AS
WITH
  vehicle_sales AS (
   SELECT
     DATE_TRUNC('month', purchase_date) month_date
   , SUM(((43000 + (MONTH(purchase_date) * 200)) + ((YEAR(purchase_date) - 2021) * 500))) revenue
   FROM
     dms_lakehouse.vehicles_bronze
   WHERE ((YEAR(purchase_date) >= 2021) AND (((YEAR(purchase_date) = 2021) AND (MOD(vehicle_id, 100) < 65)) OR ((YEAR(purchase_date) = 2022) AND (MOD(vehicle_id, 100) < 80)) OR ((YEAR(purchase_date) = 2023) AND (MOD(vehicle_id, 100) < 95)) OR (YEAR(purchase_date) = 2024) OR ((YEAR(purchase_date) = 2025) AND (MOD(vehicle_id, 100) < 90))))
   GROUP BY DATE_TRUNC('month', purchase_date)
) 
, service_rev AS (
   SELECT
     DATE_TRUNC('month', service_date) month_date
   , SUM(revenue) revenue
   FROM
     cx_analytics.service_revenue
   GROUP BY DATE_TRUNC('month', service_date)
) 
, subscription_rev AS (
   SELECT
     DATE_TRUNC('month', billing_date) month_date
   , SUM(monthly_revenue) revenue
   FROM
     cx_analytics.subscription_revenue
   GROUP BY DATE_TRUNC('month', billing_date)
) 
, financing_rev AS (
   SELECT
     DATE_TRUNC('month', payment_date) month_date
   , SUM(interest_revenue) revenue
   FROM
     cx_analytics.financing_revenue
   GROUP BY DATE_TRUNC('month', payment_date)
) 
, warranty_rev AS (
   SELECT
     DATE_TRUNC('month', sale_date) month_date
   , SUM(warranty_revenue) revenue
   FROM
     cx_analytics.warranty_revenue
   GROUP BY DATE_TRUNC('month', sale_date)
) 
SELECT
  COALESCE(vs.month_date, sr.month_date, sub.month_date, fr.month_date, wr.month_date) month_date
, DATE_FORMAT(COALESCE(vs.month_date, sr.month_date, sub.month_date, fr.month_date, wr.month_date), '%b %Y') month_label
, COALESCE(vs.revenue, 0) vehicle_sales_revenue
, COALESCE(sr.revenue, 0) service_revenue
, COALESCE(sub.revenue, 0) subscription_revenue
, COALESCE(fr.revenue, 0) financing_revenue
, COALESCE(wr.revenue, 0) warranty_revenue
, ((((COALESCE(vs.revenue, 0) + COALESCE(sr.revenue, 0)) + COALESCE(sub.revenue, 0)) + COALESCE(fr.revenue, 0)) + COALESCE(wr.revenue, 0)) total_revenue
FROM
  ((((vehicle_sales vs
FULL JOIN service_rev sr ON (vs.month_date = sr.month_date))
FULL JOIN subscription_rev sub ON (COALESCE(vs.month_date, sr.month_date) = sub.month_date))
FULL JOIN financing_rev fr ON (COALESCE(vs.month_date, sr.month_date, sub.month_date) = fr.month_date))
FULL JOIN warranty_rev wr ON (COALESCE(vs.month_date, sr.month_date, sub.month_date, fr.month_date) = wr.month_date))
WHERE (COALESCE(vs.month_date, sr.month_date, sub.month_date, fr.month_date, wr.month_date) >= DATE '2021-01-01');
