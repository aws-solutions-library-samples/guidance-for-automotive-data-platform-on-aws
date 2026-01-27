-- Customer Health Scores View for QuickSight
CREATE OR REPLACE VIEW customer_health_scores AS
SELECT 
    customer_id,
    user_id,
    total_revenue,
    avg_satisfaction_score,
    total_cases,
    open_cases,
    total_vehicles,
    total_service_spend,
    total_service_appointments,
    opportunity_count,
    health_score,
    health_segment,
    customer_count,
    is_at_risk,
    at_risk_revenue,
    satisfaction_bucket
FROM customer_health;
