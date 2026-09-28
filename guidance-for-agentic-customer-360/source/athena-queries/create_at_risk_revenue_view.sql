-- At-Risk Revenue View for QuickSight
CREATE OR REPLACE VIEW at_risk_revenue_view AS
SELECT 
    CAST(month_date AS DATE) as month_date,
    month_label,
    customer_type,
    at_risk_customers,
    vehicle_sales_at_risk,
    service_revenue_at_risk,
    subscription_revenue_at_risk,
    financing_revenue_at_risk,
    warranty_revenue_at_risk,
    total_revenue_at_risk
FROM at_risk_revenue;
