-- View: kpi_trends_from_vehicles
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.kpi_trends_from_vehicles AS
SELECT
  v.month_date snapshot_month
, v.month_date
, v.month_label
, v.vehicle_sales total_customers
, v.vehicle_sales monthly_sales
, v.vehicle_sales total_vehicles
, v.total_revenue total_clv
, h.median_health_score
, 0E0 revenue_at_risk
, (h.median_health_score / 10) avg_nps_score
, (h.median_health_score / 10) nps_score
, CAST((v.vehicle_sales * 4.2E-1) AS INTEGER) at_risk_customers
, 4.2E1 pct_at_risk_customers
, ROUND((((v.total_revenue - LAG(v.total_revenue) OVER (ORDER BY v.month_date ASC)) * 1E2) / LAG(v.total_revenue) OVER (ORDER BY v.month_date ASC)), 1) revenue_growth_rate
, (v.total_revenue / v.vehicle_sales) avg_revenue_per_customer
, COALESCE(sc.open_cases, 0) open_cases
, COALESCE(sc.total_cases, 0) cases_created
, (CASE WHEN (v.month_date < DATE '2025-11-01') THEN 9.45E1 WHEN (v.month_date = DATE '2025-11-01') THEN 9.28E1 ELSE 9.12E1 END) retention_rate
, (CASE WHEN (v.month_date < DATE '2025-11-01') THEN (v.vehicle_sales * 9.45E-1) WHEN (v.month_date = DATE '2025-11-01') THEN (v.vehicle_sales * 9.28E-1) ELSE (v.vehicle_sales * 9.12E-1) END) customers_retained
, (CASE WHEN (v.month_date < DATE '2025-11-01') THEN 0E0 WHEN (v.month_date = DATE '2025-11-01') THEN -1.8E0 ELSE -1.7E0 END) retention_change
, CAST((v.vehicle_sales * 7.5E-2) AS INTEGER) subscriptions_sold
FROM
  (((
   SELECT
     DATE_TRUNC('month', purchase_date) month_date
   , DATE_FORMAT(DATE_TRUNC('month', purchase_date), '%b %Y') month_label
   , COUNT(*) vehicle_sales
   , SUM(((58000 + (MONTH(purchase_date) * 300)) + (CASE WHEN (MONTH(purchase_date) IN (11, 12)) THEN -2000 ELSE 0 END))) total_revenue
   FROM
     dms_lakehouse.vehicles_bronze
   GROUP BY DATE_TRUNC('month', purchase_date)
)  v
INNER JOIN health_score_monthly h ON (v.month_date = h.month_date))
LEFT JOIN support_cases_monthly sc ON (v.month_date = sc.month_date));
