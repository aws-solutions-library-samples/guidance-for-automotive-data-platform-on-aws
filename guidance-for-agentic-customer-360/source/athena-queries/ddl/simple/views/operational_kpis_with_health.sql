-- View: operational_kpis_with_health (QuickSight expects this name)
CREATE OR REPLACE VIEW cx_analytics.operational_kpis_with_health AS
SELECT
  CAST(month_date AS DATE) as month_date,
  month_label,
  CAST(first_contact_resolution_rate AS DECIMAL(10,2)) as first_contact_resolution_rate,
  CAST(avg_case_resolution_days AS DECIMAL(10,2)) as avg_case_resolution_days,
  CAST(service_wait_days AS DECIMAL(10,2)) as service_wait_days,
  CAST(warranty_claim_rate AS DECIMAL(10,2)) as warranty_claim_rate,
  CAST(repeat_service_rate AS DECIMAL(10,2)) as repeat_service_rate,
  churn_risk_customers,
  CAST(churn_risk_revenue AS INTEGER) as churn_risk_revenue,
  CAST((first_contact_resolution_rate + (100 - avg_case_resolution_days) + (100 - service_wait_days * 10)) / 3 AS DECIMAL(10,2)) as operational_health_score
FROM cx_analytics.operational_kpis;
