-- Operational KPIs View for QuickSight
CREATE OR REPLACE VIEW operational_kpis AS
SELECT 
    CAST(month_date AS DATE) as month_date,
    month_label,
    first_contact_resolution_rate,
    avg_case_resolution_days,
    service_wait_days,
    warranty_claim_rate,
    repeat_service_rate,
    churn_risk_customers,
    churn_risk_revenue,
    operational_health_score
FROM operational_kpis;
