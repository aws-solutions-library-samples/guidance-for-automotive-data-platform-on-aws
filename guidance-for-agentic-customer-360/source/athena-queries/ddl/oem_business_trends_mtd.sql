-- View: oem_business_trends_mtd
-- Database: cx_analytics
-- Type: Virtual View

CREATE OR REPLACE VIEW cx_analytics.oem_business_trends_mtd AS
SELECT
  o.month_date
, o.month_label
, 0 monthly_sales
, 0 total_vehicles
, 0 active_dealers
, 0 cases_created
, oc.open_cases
, COALESCE(h.median_health_score, 0E0) avg_health_score
, 0E0 avg_revenue_per_customer
, 0 at_risk_customers
, 0E0 avg_sales_per_dealer
FROM
  (((
   SELECT DISTINCT
     month_date
   , month_label
   FROM
     open_cases_monthly
)  o
LEFT JOIN open_cases_monthly oc ON (o.month_date = oc.month_date))
LEFT JOIN health_score_monthly h ON (o.month_date = h.month_date));
