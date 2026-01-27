-- KPI Trends View for QuickSight
CREATE OR REPLACE VIEW kpi_trends AS
SELECT 
    CAST(snapshot_month AS DATE) as snapshot_month,
    CAST(month_date AS DATE) as month_date,
    month_label,
    total_customers,
    monthly_sales,
    total_vehicles,
    median_health_score,
    total_clv,
    revenue_at_risk,
    avg_nps_score,
    nps_score,
    at_risk_customers,
    pct_at_risk_customers,
    revenue_growth_rate,
    avg_revenue_per_customer,
    open_cases,
    cases_created,
    retention_rate,
    customers_retained,
    retention_change,
    subscriptions_sold
FROM monthly_kpis;
