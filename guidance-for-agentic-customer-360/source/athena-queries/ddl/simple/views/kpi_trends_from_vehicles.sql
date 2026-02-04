-- View: kpi_trends_from_vehicles (QuickSight expects this name)
CREATE OR REPLACE VIEW cx_analytics.kpi_trends_from_vehicles AS
SELECT
  CAST(snapshot_month AS DATE) as snapshot_month,
  CAST(month_date AS DATE) as month_date,
  month_label,
  total_customers,
  monthly_sales,
  total_vehicles,
  CAST(median_health_score AS DECIMAL(10,2)) as median_health_score,
  CAST(total_clv AS BIGINT) as total_clv,
  CAST(revenue_at_risk AS DECIMAL(10,2)) as revenue_at_risk,
  CAST(avg_nps_score AS DECIMAL(10,2)) as avg_nps_score,
  CAST(nps_score AS DECIMAL(10,2)) as nps_score,
  at_risk_customers,
  CAST(pct_at_risk_customers * 100 AS DECIMAL(10,2)) as pct_at_risk_customers,
  CAST(revenue_growth_rate * 100 AS DECIMAL(10,2)) as revenue_growth_rate,
  CAST(avg_revenue_per_customer AS DECIMAL(10,2)) as avg_revenue_per_customer,
  open_cases,
  cases_created,
  CAST(retention_rate * 100 AS DECIMAL(10,2)) as retention_rate,
  CAST(customers_retained AS DECIMAL(10,2)) as customers_retained,
  CAST(retention_change * 100 AS DECIMAL(10,2)) as retention_change,
  subscriptions_sold
FROM cx_analytics.kpi_trends;
